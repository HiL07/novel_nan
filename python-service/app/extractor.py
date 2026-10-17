"""小说提取主流程：取文件 → 纯文本 → 切章/分块 → 逐块调千问 → 合并结果。"""
import logging
from collections import Counter
from typing import Callable

from . import config, qwen_client, text_loader

log = logging.getLogger(__name__)


def extract(file_id: int, file_ext: str, on_progress: Callable[[int, str], None]) -> dict:
    data = text_loader.fetch_file(file_id)
    text = text_loader.to_plain_text(data, file_ext)
    if not text:
        raise ValueError("文件中没有可提取的文本")

    chapters = text_loader.split_chapters(text)
    tasks = []  # (章节下标, 块文本)
    for ci, ch in enumerate(chapters):
        for part in text_loader.split_chunks(ch["content"], config.CHUNK_CHARS):
            tasks.append((ci, part))

    on_progress(0, f"共 {len(chapters)} 章，{len(tasks)} 个分块")
    chunk_results: list[list[dict]] = [[] for _ in chapters]
    failed = 0
    for i, (ci, part) in enumerate(tasks, start=1):
        title = chapters[ci]["title"]
        try:
            chunk_results[ci].append(qwen_client.analyze_chunk(title, part))
        except qwen_client.QwenError as e:
            # 单块失败不影响整体；千问整体不可用时由上层快速失败
            failed += 1
            log.warning("分块解析失败 file=%s chapter=%s: %s", file_id, title, e)
            if not qwen_client.health():
                raise
        on_progress(int(i * 100 / len(tasks)), f"已解析 {i}/{len(tasks)}：{title}")

    return merge(text, chapters, chunk_results, failed)


def merge(text: str, chapters: list[dict], chunk_results: list[list[dict]], failed: int) -> dict:
    out_chapters = []
    char_roles: dict[str, str] = {}
    char_count: Counter = Counter()
    char_first: dict[str, str] = {}
    paces: Counter = Counter()
    tones: Counter = Counter()

    for ch, results in zip(chapters, chunk_results):
        summaries, events, foreshadowing, names = [], [], [], []
        for r in results:
            if r.get("summary"):
                summaries.append(str(r["summary"]))
            events += [e for e in _list(r.get("events")) if isinstance(e, dict)]
            foreshadowing += [str(f) for f in _list(r.get("foreshadowing")) if f and f != "无"]
            for c in _list(r.get("characters")):
                name = str(c.get("name", "")).strip() if isinstance(c, dict) else ""
                if not name:
                    continue
                if name not in names:
                    names.append(name)
                char_roles.setdefault(name, str(c.get("role", "")))
                char_first.setdefault(name, ch["title"])
            style = r.get("style") if isinstance(r.get("style"), dict) else {}
            if style.get("pace"):
                paces[str(style["pace"])] += 1
            if style.get("tone"):
                tones[str(style["tone"])] += 1
        char_count.update(names)
        out_chapters.append({
            "title": ch["title"],
            "wordCount": len(ch["content"]),
            "summary": " ".join(summaries),
            "characters": names,
            "events": events,
            "foreshadowing": foreshadowing,
        })

    characters = [
        {"name": n, "role": char_roles[n], "firstAppear": char_first[n], "chapterCount": cnt}
        for n, cnt in char_count.most_common()
    ]
    return {
        "wordCount": len(text),
        "chapterCount": len(chapters),
        "failedChunks": failed,
        "characters": characters,
        "style": {
            "dialogRatio": dialog_ratio(text),
            "pace": paces.most_common(1)[0][0] if paces else "",
            "tones": [t for t, _ in tones.most_common(3)],
        },
        "chapters": out_chapters,
    }


def dialog_ratio(text: str) -> float:
    """对话占比：引号内字数 / 总字数（程序统计，比让模型估算更可靠）。
    支持中英文弯引号 “”、「」『』 以及英文直引号（成对切换，每段重置，防止漏配对拖垮整篇）。"""
    inside, total, depth, straight = 0, 0, 0, False
    for ch in text:
        if ch in "“「『":
            depth += 1
        elif ch in "”」』":
            depth = max(depth - 1, 0)
        elif ch == '"':
            straight = not straight
        elif ch == "\n":
            # 引号不跨段统计：漏写的右引号只影响当前段
            depth, straight = 0, False
        elif not ch.isspace():
            total += 1
            if depth or straight:
                inside += 1
    return round(inside / total, 3) if total else 0.0


def _list(value) -> list:
    return value if isinstance(value, list) else []
