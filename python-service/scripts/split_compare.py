"""分章规则对比：新的 text_loader.split_book 与旧版（另存的 text_loader.py）在同几本书上的差别。

    .venv/Scripts/python scripts/split_compare.py --files a.txt b.txt [--old <旧 text_loader.py>] [--show 20]
    .venv/Scripts/python scripts/split_compare.py --java http://localhost:8012 --file-ids 3 5   # 只比对 Java ChapterCounter 的章数

打印每本书新旧章数、新增 / 去掉的标题（各前 --show 个）、书头长度、警告。
--java：再从 Java /api/file/list 取 chapter_count（ChapterCounter），和 Python count_chapters 比对（两边规则必须一致）。
"""
import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import text_loader  # noqa: E402


def load_old(path: str):
    spec = importlib.util.spec_from_file_location("text_loader_old", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["text_loader_old"] = mod
    # 旧文件 import 了 `from . import config`：给一个空的包上下文
    mod.__package__ = "app"
    spec.loader.exec_module(mod)
    return mod


def read(path: Path) -> str:
    return text_loader.clean_text(text_loader.decode_text(path.read_bytes()))


def compare(path: Path, old, show: int) -> None:
    text = read(path)
    book = text_loader.split_book(text)
    new_titles = [c["title"] for c in book["chapters"]]
    print(f"\n=== {path.name}  {len(text):,} 字")
    print(f"新：{len(book['chapters'])} 章（其中章节 {book['headings']}，"
          f"开篇 {sum(c['kind'] == 'opening' for c in book['chapters'])}，"
          f"卷简介 {sum(c['kind'] == 'volume' for c in book['chapters'])}，"
          f"分段 {sum(c['kind'] == 'segment' for c in book['chapters'])}），书头 {len(book['preface'])} 字，"
          f"count_chapters = {text_loader.count_chapters(text)}")
    for w in book["warnings"]:
        print(f"  警告：{w}")
    if old:
        old_titles = [c["title"] for c in old.split_chapters(text)]
        print(f"旧：{len(old_titles)} 章")
        old_set, new_set = set(old_titles), set(new_titles)
        gone = [t for t in old_titles if t not in new_set]
        added = [t for t in new_titles if t not in old_set]
        if gone:
            print(f"  去掉 {len(gone)}：" + " | ".join(gone[:show]))
        if added:
            print(f"  新增 {len(added)}：" + " | ".join(added[:show]))
    print("  前几章：" + " | ".join(new_titles[:show]))


def java_check(base: str, ids: list[int]) -> None:
    import httpx

    rows = httpx.get(f"{base}/api/file/list", timeout=30, trust_env=False).json()["data"]
    by_id = {r["id"]: r for r in rows}
    for fid in ids:
        row = by_id.get(fid)
        if not row:
            print(f"文件 {fid} 不存在")
            continue
        data = httpx.get(f"{base}/api/file/preview/{fid}", timeout=120, trust_env=False).content
        py = text_loader.count_chapters(text_loader.to_plain_text(data, row["fileExt"]))
        ok = "一致" if py == row.get("chapterCount") else "不一致！"
        print(f"{fid} {row['fileName']}：Java {row.get('chapterCount')}，Python {py}  {ok}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", default=[])
    ap.add_argument("--old", help="旧版 text_loader.py 的路径（不给就只看新版）")
    ap.add_argument("--show", type=int, default=20)
    ap.add_argument("--java", help="Java 后端地址，如 http://localhost:8012")
    ap.add_argument("--file-ids", nargs="*", type=int, default=[])
    args = ap.parse_args()
    old = load_old(args.old) if args.old else None
    for f in args.files:
        compare(Path(f), old, args.show)
    if args.java and args.file_ids:
        java_check(args.java.rstrip("/"), args.file_ids)


if __name__ == "__main__":
    main()
