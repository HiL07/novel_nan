"""一次性迁移：把 MySQL 中需要保留的「系统配置」导入新的 SQLite 库（业务数据不迁移）。

只导入：ai_model_config（模型配置，含只存在于数据库中的 API Key）与 python_env（Python 环境配置）。
- 只读访问 MySQL（mysql 命令行，所有列以 HEX 读取，避免编码与转义问题），不修改、不删除任何源数据
- 目标 SQLite 不存在时按 backend/src/main/resources/sql/init.sql 建表；目标表已有数据时拒绝执行（--force 才覆盖这两张表）
- 保留原 id 并同步 sqlite_sequence，导入后逐行逐列做 SHA-256 比对
- 不在终端或任何文件中输出 API Key 明文，不生成备份文件

用法（项目根目录）：
  set MYSQL_PWD=...            （或 PowerShell: $env:MYSQL_PWD="..."；密码只经环境变量传给 mysql 命令行）
  py -3.10 scripts/migration/import_mysql_config.py [--mysql-bin "C:/Program Files/MySQL/MySQL Server 8.0/bin/mysql.exe"]
      [--host localhost] [--port 3306] [--user root] [--database test10000] [--sqlite data/nan_novel.db] [--force]
"""
import argparse
import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INIT_SQL = ROOT / "backend" / "src" / "main" / "resources" / "sql" / "init.sql"

TABLES = {
    "ai_model_config": ["id", "name", "base_url", "model", "api_key", "concurrency", "status", "verify_message",
                        "verified_time", "active", "create_time", "update_time"],
    "python_env": ["id", "env_type", "python_path", "conda_root", "conda_env", "python_version", "cuda_available",
                   "gpu_name", "torch_version", "status", "check_result", "active", "checked_time", "create_time"],
}
INT_COLS = {"id", "concurrency", "active", "cuda_available"}


def mysql_rows(args, table, cols):
    # 先 CAST 成文本再 HEX：整数列直接 HEX 会得到数值的十六进制而非数字字符；DATETIME 转为 'yyyy-MM-dd HH:mm:ss'
    sql = (f"SELECT {', '.join(f'HEX(CAST(`{c}` AS CHAR CHARACTER SET utf8mb4))' for c in cols)} "
           f"FROM `{args.database}`.`{table}` ORDER BY id")
    cmd = [args.mysql_bin, "--default-character-set=utf8mb4", "-h", args.host, "-P", str(args.port), "-u", args.user, "-N", "-B", "-e", sql]
    res = subprocess.run(cmd, capture_output=True, env=os.environ)
    if res.returncode != 0:
        sys.exit(f"读取 MySQL 失败（{table}）：{res.stderr.decode('utf-8', 'replace').strip()[:300]}")
    rows = []
    for line in res.stdout.decode("ascii").splitlines():
        vals = []
        for c, h in zip(cols, line.split("\t")):
            if h == "NULL":
                vals.append(None)
                continue
            text = bytes.fromhex(h).decode("utf-8")
            vals.append(int(text) if c in INT_COLS else text)
        rows.append(tuple(vals))
    return rows


def digest(row) -> str:
    return hashlib.sha256(repr(row).encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mysql-bin", default=r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=3306)
    ap.add_argument("--user", default="root")
    ap.add_argument("--database", default="test10000")
    ap.add_argument("--sqlite", default=str(ROOT / "data" / "nan_novel.db"))
    ap.add_argument("--force", action="store_true", help="目标表已有数据时先清空这两张表再导入")
    args = ap.parse_args()
    if not os.environ.get("MYSQL_PWD"):
        sys.exit("请先通过环境变量 MYSQL_PWD 提供 MySQL 密码（不会被打印）")

    target = Path(args.sqlite)
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target)
    con.executescript(INIT_SQL.read_text(encoding="utf-8"))  # IF NOT EXISTS：已存在的表不受影响

    report_ok = True
    for table, cols in TABLES.items():
        src = mysql_rows(args, table, cols)
        existing = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if existing and not args.force:
            sys.exit(f"目标库 {table} 已有 {existing} 行，为避免覆盖已停止（确认后加 --force）")
        with con:
            if existing:
                con.execute(f"DELETE FROM {table}")
            con.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", src)
            if src:
                con.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
                con.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table, max(r[0] for r in src)))
        dst = con.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY id").fetchall()
        same = [digest(a) == digest(tuple(b)) for a, b in zip(src, dst)]
        ok = len(src) == len(dst) and all(same)
        report_ok &= ok
        extra = ""
        if table == "ai_model_config":
            k = cols.index("api_key")
            keys_ok = sum(1 for a, b in zip(src, dst) if a[k] == b[k] and a[k])
            extra = f"，API Key 一致 {keys_ok}/{sum(1 for a in src if a[k])}（不显示明文）"
        print(f"{table}: MySQL {len(src)} 行 → SQLite {len(dst)} 行，逐行 SHA-256 一致 {sum(same)}/{len(src)}{extra} {'OK' if ok else 'MISMATCH'}")
    con.close()
    print("导入完成，验证通过" if report_ok else "验证未通过，请检查")
    return 0 if report_ok else 1


if __name__ == "__main__":
    sys.exit(main())
