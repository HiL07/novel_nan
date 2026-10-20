"""抓取断点：每抓完一章就追加落盘，进程关闭 / 断网 / 站点换域名后可从断点继续。

目录 ``data/crawl-cache/<resumeKey>/``（resumeKey 由 Java 生成：单本 ``c<任务id>``，整站 ``c<任务id>b<书籍id>``）：

- ``meta.json``：目录页地址、书名 / 作者 / 简介、**本次抓取范围内的章节清单** ``[{title, url}]``。
  续抓时直接用它，不再依赖目录页——目录页失效也能把剩下的章节抓完；换了域名可整体改写。
- ``chapters.jsonl``：一行一章 ``{"i": 序号(0 起), "ok": true, "text": "..."}``，逐行追加并 fsync；
  进程在写一半时被杀，最后一行是残缺 JSON，读取时跳过即可。失败的章节不记录，续抓时重试。

Java 取走全文存入文件管理后调用 release，断点随之删除；取消 / 失败时保留，供「继续抓取」使用。
"""
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from ..config import DATA_DIR

log = logging.getLogger("crawler")

CACHE_DIR = (DATA_DIR / "crawl-cache").resolve()
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _dir(key: str) -> Path:
    if not KEY_PATTERN.match(key or ""):
        raise ValueError("resumeKey 只能包含字母、数字、下划线和短横线")
    path = (CACHE_DIR / key).resolve()
    if path.parent != CACHE_DIR:
        raise ValueError("resumeKey 不合法")
    return path


def origin_of(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def rewrite_origin(url: str, old_origin: str, new_origin: str) -> str:
    """把 old_origin 下的地址换到 new_origin（站点换域名 / IP 后路径不变的常见情况），其他地址原样返回。"""
    if not url or origin_of(url).lower() != old_origin.lower():
        return url
    new = urlsplit(new_origin)
    p = urlsplit(url)
    return urlunsplit((new.scheme, new.netloc, p.path, p.query, p.fragment))


def load(key: str) -> Optional[dict]:
    """→ {"meta": {...}, "done": {i: text}}；没有断点返回 None。"""
    folder = _dir(key)
    meta_file = folder / "meta.json"
    if not meta_file.is_file():
        return None
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("断点 %s 的 meta.json 损坏，忽略：%s", key, e)
        return None
    done: dict[int, str] = {}
    lines = folder / "chapters.jsonl"
    if lines.is_file():
        with lines.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue  # 写到一半被打断的行
                if row.get("ok") and isinstance(row.get("i"), int):
                    done[row["i"]] = row.get("text") or ""
    return {"meta": meta, "done": done}


def save_meta(key: str, meta: dict) -> None:
    folder = _dir(key)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "meta.json.tmp"
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, folder / "meta.json")


class ChapterLog:
    """逐章追加写入（每章 fsync，断电 / 强杀最多丢正在写的那一章）。"""

    def __init__(self, key: str):
        folder = _dir(key)
        folder.mkdir(parents=True, exist_ok=True)
        self._fh = (folder / "chapters.jsonl").open("a", encoding="utf-8")

    def append(self, index: int, text: str) -> None:
        self._fh.write(json.dumps({"i": index, "ok": True, "text": text}, ensure_ascii=False) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def close(self) -> None:
        self._fh.close()


def remove(key: str) -> None:
    try:
        shutil.rmtree(_dir(key), ignore_errors=True)
    except ValueError:
        pass
