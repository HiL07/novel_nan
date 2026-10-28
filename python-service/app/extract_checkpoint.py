"""提取断点（素材提取 v2）：每读完一块 / 整理完一张卡就追加落盘，服务重启、取消、断网后可从断点继续。

目录 ``data/extract-cache/<resumeKey>/``（resumeKey 由 Java 生成：``e<任务id>``）：

- ``meta.json``：本次提取的指纹（文件 id、分块字数、读几遍、分类、块数）。指纹变了（换了参数）就清空重来，
  避免把不同切法的块结果拼在一起。
- ``<阶段>.jsonl``：一行一条 ``{"k": 键, "data": ...}``，逐行追加并 fsync；最后一行写到一半被打断时读取跳过。
  阶段：``pass1`` / ``pass2``（键 = 块序号）、``cards``（键 = 实体键）、``systems``、``arcs``（键 = 窗口序号）。

Java 保存结果成功后调用 delete，断点随之删除；失败 / 取消时保留，供「继续提取」使用。
"""
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

from .config import DATA_DIR

log = logging.getLogger(__name__)

CACHE_DIR = (DATA_DIR / "extract-cache").resolve()
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _dir(key: str) -> Path:
    if not KEY_PATTERN.match(key or ""):
        raise ValueError("resumeKey 只能包含字母、数字、下划线和短横线")
    path = (CACHE_DIR / key).resolve()
    if path.parent != CACHE_DIR:
        raise ValueError("resumeKey 不合法")
    return path


class Checkpoint:
    """一次提取的断点。key 为空时什么都不写（不续跑的调用，如评测脚本）。"""

    def __init__(self, key: str | None, fingerprint: dict):
        self.key = key or None
        self._rows: dict[str, dict[str, Any]] = {}
        self._files: dict[str, Any] = {}
        if not self.key:
            return
        folder = _dir(self.key)
        meta_file = folder / "meta.json"
        try:
            old = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.is_file() else None
        except (OSError, ValueError):
            old = None
        if old != fingerprint:
            if old is not None:
                log.info("提取断点 %s 的参数变了，清空重来", self.key)
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True, exist_ok=True)
            tmp = folder / "meta.json.tmp"
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(fingerprint, fh, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, meta_file)
            return
        for f in folder.glob("*.jsonl"):
            rows: dict[str, Any] = {}
            with f.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue  # 写到一半被打断的行
                    if isinstance(row, dict) and "k" in row:
                        rows[str(row["k"])] = row.get("data")
            self._rows[f.stem] = rows

    def done(self, stage: str) -> dict[str, Any]:
        """该阶段已完成的 {键: 数据}。"""
        return self._rows.setdefault(stage, {})

    def append(self, stage: str, k, data) -> None:
        self.done(stage)[str(k)] = data
        if not self.key:
            return
        fh = self._files.get(stage)
        if fh is None:
            fh = self._files[stage] = (_dir(self.key) / f"{stage}.jsonl").open("a", encoding="utf-8")
        fh.write(json.dumps({"k": str(k), "data": data}, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())

    def close(self) -> None:
        for fh in self._files.values():
            fh.close()
        self._files.clear()


def info(key: str) -> dict:
    """→ {exists, stages: {阶段: 条数}}（只数行，不解析内容）"""
    folder = _dir(key)
    if not (folder / "meta.json").is_file():
        return {"exists": False, "stages": {}}
    stages = {}
    for f in folder.glob("*.jsonl"):
        with f.open(encoding="utf-8", errors="replace") as fh:
            stages[f.stem] = sum(1 for _ in fh)
    return {"exists": True, "stages": stages}


def remove(key: str) -> None:
    shutil.rmtree(_dir(key), ignore_errors=True)
