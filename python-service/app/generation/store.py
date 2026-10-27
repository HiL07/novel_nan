"""工作区存储：共享数据目录下的 data/novels/<id>/（JSON 文件；默认 ${DATA_DIR}/novels，可用 NOVELS_DIR 单独覆盖）。

写入者：本模块（Python）；Java 按 data/README.md 的约定只读。所有写入均为「临时文件 → 原子替换」。

novels/<id>/
├── novel.json          工作区：标题、模型、上下文窗口、设定（编辑器配置 + 规范化设定）、生成参数、前情概要、token 统计
├── facts.json          故事账本：伏笔 / 角色状态 / 时间线（见 facts.py）
└── chapters/0001.json  章节：目标、规划、正文、摘要、本章事实、一致性检查、状态、每次模型调用的 token 明细

以后若改为数据库存储，只需替换本模块的函数实现，接口保持不变。
"""
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from ..config import DATA_DIR
from . import facts as facts_mod

NOVELS_DIR = Path(os.getenv("NOVELS_DIR") or DATA_DIR / "novels").resolve()
NOVELS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_PARAMS = {"segmentTokens": 768, "temperature": 0.7, "topP": 0.8, "topK": 20, "repetitionPenalty": 1.1,
                  "recentTokens": 900,
                  # 写作流程：先规划节拍 / 写完抽取故事事实（与摘要同一次调用）/ 写完检查一致性（None = 大模型开、本地关）
                  "planChapter": True, "extractFacts": True, "reviewChapter": None}
CONTEXT_WINDOWS = (8192, 32768)

_lock = threading.RLock()


class StoreError(ValueError):
    pass


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _dir(novel_id: str) -> Path:
    d = (NOVELS_DIR / novel_id).resolve()
    if d.parent != NOVELS_DIR or not novel_id.replace("-", "").isalnum():
        raise StoreError("非法的工作区 id")
    return d


# ---------------------------------------------------------------- 工作区

def create_novel(title: str, model: dict, context_window: int) -> dict:
    novel_id = f"novel-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
    novel = {
        "id": novel_id, "title": title.strip() or "未命名小说", "createdAt": now(), "updatedAt": now(),
        "model": model, "contextWindow": context_window,
        "settings": {"config": None, "spec": None, "savedAt": None}, "outline": None,
        "params": dict(DEFAULT_PARAMS), "arcSummary": "", "arcUpTo": 0,
        "tokenTotals": {"promptTokens": 0, "completionTokens": 0, "calls": 0},
    }
    with _lock:
        _write(_dir(novel_id) / "novel.json", novel)
    return novel


def get_novel(novel_id: str) -> dict:
    novel = _read(_dir(novel_id) / "novel.json")
    if novel is None:
        raise StoreError(f"工作区不存在：{novel_id}")
    return novel


def update_novel(novel_id: str, **fields) -> dict:
    with _lock:
        novel = get_novel(novel_id)
        novel.update(fields)
        novel["updatedAt"] = now()
        _write(_dir(novel_id) / "novel.json", novel)
        return novel


def add_token_usage(novel_id: str, prompt: int, completion: int) -> None:
    with _lock:
        novel = get_novel(novel_id)
        t = novel["tokenTotals"]
        t["promptTokens"] += prompt
        t["completionTokens"] += completion
        t["calls"] += 1
        _write(_dir(novel_id) / "novel.json", novel)


def list_novels() -> list[dict]:
    out = []
    for f in NOVELS_DIR.glob("*/novel.json"):
        n = _read(f)
        if n:
            chapters = list_chapters(n["id"])
            out.append({k: n[k] for k in ("id", "title", "createdAt", "updatedAt", "model", "contextWindow")}
                       | {"chapterCount": len(chapters), "totalChars": sum(c["chars"] for c in chapters),
                          "hasSettings": bool(n["settings"].get("spec"))})
    return sorted(out, key=lambda n: n["updatedAt"], reverse=True)


def delete_novel(novel_id: str) -> None:
    d = _dir(novel_id)
    if not (d / "novel.json").exists():
        raise StoreError(f"工作区不存在：{novel_id}")
    shutil.rmtree(d)


# ---------------------------------------------------------------- 章节

def _chapter_path(novel_id: str, index: int) -> Path:
    return _dir(novel_id) / "chapters" / f"{index:04d}.json"


def list_chapters(novel_id: str) -> list[dict]:
    """章节列表（不含正文和调用明细）。"""
    out = []
    for f in sorted((_dir(novel_id) / "chapters").glob("*.json")):
        c = _read(f)
        if c:
            out.append({k: c.get(k) for k in ("index", "title", "goal", "targetChars", "summary", "status", "error",
                                               "createdAt", "updatedAt", "totals")}
                       | {"chars": len(c.get("text", "")), "reviewIssues": _review_count(c)})
    return out


def _review_count(c: dict) -> int | None:
    """一致性检查发现的问题数（没检查过 / 检查失败 / 已忽略 = None）。"""
    r = c.get("review")
    return None if not r or r.get("ignored") or r.get("error") else len(r.get("issues") or [])


def get_chapter(novel_id: str, index: int) -> dict:
    c = _read(_chapter_path(novel_id, index))
    if c is None:
        raise StoreError(f"第 {index} 章不存在")
    return c


def save_chapter(novel_id: str, chapter: dict) -> None:
    chapter["updatedAt"] = now()
    with _lock:
        _write(_chapter_path(novel_id, chapter["index"]), chapter)


def delete_last_chapter(novel_id: str, index: int) -> None:
    chapters = list_chapters(novel_id)
    if not chapters or chapters[-1]["index"] != index:
        raise StoreError("只能删除最后一章（保证前情摘要连贯）")
    with _lock:
        _chapter_path(novel_id, index).unlink()
        f = get_facts(novel_id)  # 账本回滚：去掉这一章抽取的伏笔 / 角色状态 / 时间线
        facts_mod.drop_from(f, index)
        save_facts(novel_id, f)
    novel = get_novel(novel_id)
    if novel["arcUpTo"] >= index:  # 被合并进前情概要的章节被删除：清空概要，下次生成时重新合并
        update_novel(novel_id, arcSummary="", arcUpTo=0)


# ---------------------------------------------------------------- 故事账本

def get_facts(novel_id: str) -> dict:
    return facts_mod.sanitize(_read(_dir(novel_id) / "facts.json"))


def save_facts(novel_id: str, facts: dict) -> None:
    facts["updatedAt"] = now()
    with _lock:
        _write(_dir(novel_id) / "facts.json", facts)
