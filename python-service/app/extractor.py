"""小说提取主流程：取文件 → 纯文本 → 切章/分块 → 并发调用模型 → 合并结果。"""
import logging
import re
import threading
from collections import Counter
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from typing import Callable

from . import config, llm_client, local_extract, materials, text_loader
from .llm_client import LLMError, ModelConfig

log = logging.getLogger(__name__)


class Cancelled(RuntimeError):
    """任务被用户取消。"""


def extract(file_id: int, file_ext: str, cfg: ModelConfig | None, on_progress: Callable[[int, str], None],
            material_opts: "materials.MaterialOptions | None" = None, *, local: dict | None = None,
            stop_event: threading.Event | None = None) -> dict:
    """cfg = 大模型（OpenAI 兼容，含本机 llama.cpp 等）；local = {baseId, chunkChars} 应用内本地模型（二选一）。
    stop_event 置位后不再开始新的分块，抛 Cancelled。"""
    if local:
        with local_extract.LocalSession(local["baseId"], stop_event) as session:
            return _extract(file_id, file_ext, on_progress, material_opts, stop_event,
                            analyze=session.analyze_chunk, chunk_chars=local["chunkChars"], concurrency=1,
                            model_name=session.name, source="local")
    return _extract(file_id, file_ext, on_progress, material_opts, stop_event,
                    analyze=lambda title, part, extra: llm_client.analyze_chunk(cfg, title, part, extra),
                    chunk_chars=config.CHUNK_CHARS, concurrency=cfg.concurrency, model_name=cfg.model,
                    source=llm_client.source_of(cfg))


def _extract(file_id: int, file_ext: str, on_progress: Callable[[int, str], None], material_opts,
             stop_event: threading.Event | None, *, analyze: Callable[[str, str, str], dict], chunk_chars: int,
             concurrency: int, model_name: str, source: str) -> dict:
    data = text_loader.fetch_file(file_id)
    text = text_loader.to_plain_text(data, file_ext)
    if not text:
        raise ValueError("文件中没有可提取的文本")

    chapters = text_loader.split_chapters(text)
    tasks = []  # (章节下标, 块文本)，顺序即章节内块顺序
    for ci, ch in enumerate(chapters):
        for part in text_loader.split_chunks(ch["content"], chunk_chars):
            tasks.append((ci, part))

    on_progress(0, f"共 {len(chapters)} 章，{len(tasks)} 个分块，{'本地模型' if source == 'local' else '模型'} "
                   f"{model_name}，并发 {concurrency}")
    results: list[dict | None] = [None] * len(tasks)
    extra = materials.prompt_fragment(material_opts) if material_opts and material_opts.enabled else ""
    lock = threading.Lock()
    state = {"done": 0, "failed": 0}

    def run(i: int) -> None:
        if stop_event and stop_event.is_set():
            raise Cancelled("已取消")
        ci, part = tasks[i]
        title = chapters[ci]["title"]
        try:
            results[i] = analyze(title, part, extra)
        except LLMError as e:
            if stop_event and stop_event.is_set():
                raise Cancelled("已取消") from e
            if e.fatal:
                raise  # 配置级错误：终止整个任务
            log.warning("分块解析失败 file=%s chapter=%s: %s", file_id, title, e)
            with lock:
                state["failed"] += 1
        with lock:
            state["done"] += 1
            done, failed = state["done"], state["failed"]
        on_progress(int(done * 100 / len(tasks)),
                    f"已解析 {done}/{len(tasks)}：{title}" + (f"（{failed} 块失败已跳过）" if failed else ""))

    pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="chunk")
    try:
        futures = [pool.submit(run, i) for i in range(len(tasks))]
        finished, _ = wait(futures, return_when=FIRST_EXCEPTION)
        for f in finished:
            if f.exception():
                raise f.exception()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if state["failed"] == len(tasks):
        raise LLMError("所有分块都解析失败，请检查模型配置或稍后重试"
                       + ("；本地小模型不擅长按格式输出，可换更大的模型或改用大模型" if source == "local" else ""))

    chunk_results: list[list[dict]] = [[] for _ in chapters]
    for (ci, _), r in zip(tasks, results):
        if r is not None:
            chunk_results[ci].append(r)
    result = merge(text, chapters, chunk_results, state["failed"])
    result["model"] = model_name
    result["source"] = source
    if material_opts and material_opts.enabled:
        merged = materials.merge_candidates(
            [(chapters[ci]["title"], r) for (ci, _), r in zip(tasks, results) if r], material_opts)
        result["materials"] = merged[:material_opts.maxCandidates]
        result["materialsTotal"] = len(merged)   # 合并去重后共识别的条数（超过上限时 > len(materials)）
        result["materialOptions"] = material_opts.model_dump()
    return result


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
                # 模型常返回「悬疑、压抑」这类组合，拆开计数
                tones.update(t.strip() for t in re.split(r"[、,，/;；\s]+", str(style["tone"])) if t.strip())
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
