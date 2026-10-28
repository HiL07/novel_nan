"""小说提取主流程：取文件 → 纯文本 → 切章/分块 → 并发调用模型 → 合并结果；以及之后单独的一步「整理卡片」。

- 不记录素材：逐块章节分析（摘要 / 人物 / 事件 / 伏笔），``_extract``；
- 记录素材（materials.enabled）：只读原文，记设定实体和核实过的事实（material_facts.scan），产出实体档案 + 章节摘要；
- 整理卡片（``compile_job``）：对一次提取的实体档案单独发起，可换模型 / 换范围重做，产出素材候选。
所有路径都按块 / 卡片写断点（extract_checkpoint），中断后从断点继续。
"""
import hashlib
import json
import logging
import re
import threading
from collections import Counter
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from typing import Callable

from . import config, extract_checkpoint, llm_client, local_extract, material_facts, materials, text_loader
from .llm_client import LLMError, ModelConfig

log = logging.getLogger(__name__)


class Cancelled(RuntimeError):
    """任务被用户取消。"""


def extract(file_id: int, file_ext: str, cfg: ModelConfig | None, on_progress: Callable[[int, str], None],
            material_opts: "materials.MaterialOptions | None" = None, *, local: dict | None = None,
            stop_event: threading.Event | None = None, resume_key: str | None = None) -> dict:
    """cfg = 大模型（OpenAI 兼容，含本机 llama.cpp 等）；local = {baseId, chunkChars} 应用内本地模型（二选一）。
    stop_event 置位后不再开始新的分块，抛 Cancelled；resume_key = 断点键（data/extract-cache/<key>/）。"""
    facts = bool(material_opts and material_opts.enabled)
    if local:
        with local_extract.LocalSession(local["baseId"], stop_event) as session:
            if facts:
                return _extract_facts(file_id, file_ext, on_progress, material_opts, stop_event, call=session.chat,
                                      concurrency=1, model_name=session.name, source="local", resume_key=resume_key,
                                      usage=None, in_app=True)
            return _extract(file_id, file_ext, on_progress, stop_event,
                            analyze=session.analyze_chunk, chunk_chars=local["chunkChars"], concurrency=1,
                            model_name=session.name, source="local", resume_key=resume_key)
    if facts:
        usage = llm_client.new_usage(cfg)
        source = llm_client.source_of(cfg)
        return _extract_facts(file_id, file_ext, on_progress, material_opts, stop_event, call=_chat_fn(cfg, usage),
                              concurrency=cfg.concurrency if source == "api" else 1, model_name=cfg.model,
                              source=source, resume_key=resume_key, usage=usage, in_app=False)
    return _extract(file_id, file_ext, on_progress, stop_event,
                    analyze=lambda title, part, extra: llm_client.analyze_chunk(cfg, title, part, extra),
                    chunk_chars=config.CHUNK_CHARS, concurrency=cfg.concurrency, model_name=cfg.model,
                    source=llm_client.source_of(cfg), resume_key=resume_key)


def _chat_fn(cfg: ModelConfig, usage: dict) -> Callable[[list[dict], int], str]:
    lock = threading.Lock()

    def call(messages: list[dict], max_tokens: int) -> str:
        one: dict = {}
        text = llm_client.chat(cfg, messages, max_tokens=max_tokens, usage=one)
        with lock:
            for k in ("calls", "promptTokens", "completionTokens", "cacheHitTokens"):
                usage[k] = usage.get(k, 0) + one.get(k, 0)
        return text

    return call


def _extract_facts(file_id: int, file_ext: str, on_progress: Callable[[int, str], None], opts, stop_event, *,
                   call, concurrency: int, model_name: str, source: str, resume_key: str | None,
                   usage: dict | None, in_app: bool) -> dict:
    """读原文记实体和事实（material_facts.scan）：结果 = 章节列表（摘要来自第一遍）+ entities（实体档案），不出候选。"""
    data = text_loader.fetch_file(file_id)
    text = text_loader.to_plain_text(data, file_ext)
    if not text:
        raise ValueError("文件中没有可提取的文本")
    chapters = text_loader.split_chapters(text)
    blocks = material_facts.build_blocks(chapters, opts.chunkChars)
    fingerprint = {"fileId": file_id, "chars": len(text), "chunkChars": opts.chunkChars, "blocks": len(blocks),
                   "rounds": opts.rounds, "categories": sorted(opts.active_categories()), "focus": opts.focus.strip()}
    ckpt = extract_checkpoint.Checkpoint(resume_key, fingerprint)
    resumed = sum(len(ckpt.done(s)) for s in ("pass1", "pass2"))
    on_progress(0, f"共 {len(chapters)} 章，{len(blocks)} 块，每块读 {opts.rounds} 遍，模型 {model_name}"
                   + (f"，从断点继续（已读完 {resumed} 块次）" if resumed else ""))
    try:
        out = material_facts.scan(chapters, opts, call, concurrency, ckpt, on_progress, stop_event, local=in_app)
    except material_facts.Cancelled as e:
        raise Cancelled(str(e)) from e
    finally:
        ckpt.close()
    stats = out["stats"]
    if stats["failedChunks"] >= len(blocks) * opts.rounds:
        raise LLMError("所有分块都解析失败，请检查模型配置或稍后重试")

    out_chapters, counts, first = [], Counter(), {}
    for ch, info in zip(chapters, out["chapters"]):
        out_chapters.append({"title": ch["title"], "wordCount": len(ch["content"]), "summary": info["summary"],
                             "characters": info["characters"], "events": [], "foreshadowing": []})
        counts.update(info["characters"])
        for n in info["characters"]:
            first.setdefault(n, ch["title"])
    result = {
        "wordCount": len(text),
        "chapterCount": len(chapters),
        "failedChunks": stats["failedChunks"],
        "characters": [{"name": n, "role": "", "firstAppear": first[n], "chapterCount": c}
                       for n, c in counts.most_common()],
        "style": {"dialogRatio": dialog_ratio(text), "pace": "", "tones": []},
        "chapters": out_chapters,
        "model": model_name,
        "source": source,
        "entities": out["entities"],
        "factStats": stats,
        "materialOptions": opts.model_dump(),
    }
    if usage:
        result["usage"] = usage
    on_progress(100, f"完成：{stats['entities']} 个实体、{stats['factsVerified']} 条事实")
    return result


def compile_job(entities: list[dict], chapters: list[dict], cfg: ModelConfig | None, on_progress, *,
                local: dict | None = None, plot: bool = True, stop_event: threading.Event | None = None,
                resume_key: str | None = None) -> dict:
    """整理卡片：实体档案 + 章节摘要 → {materials, stats, usage, model, source}。cfg = 大模型 / GGUF，local = 应用内本地模型。
    断点指纹 = 实体键 + 事实数 + 是否整理剧情段：同一范围续跑时已整理的卡片不重做。"""
    sig = hashlib.sha1(json.dumps([(e.get("key"), len(e.get("facts") or [])) for e in entities],
                                  ensure_ascii=False).encode()).hexdigest()
    ckpt = extract_checkpoint.Checkpoint(resume_key, {"compile": sig, "plot": plot, "chapters": len(chapters)})
    resumed = len(ckpt.done("cards"))
    try:
        if local:
            with local_extract.LocalSession(local["baseId"], stop_event) as session:
                on_progress(0, f"{len(entities)} 个实体，模型 {session.name}" + (f"，从断点继续（已整理 {resumed} 批）" if resumed else ""))
                out = material_facts.compile_cards(entities, chapters, session.chat, 1, ckpt, on_progress, stop_event,
                                                   local=True, plot=plot)
                model_name, source, usage = session.name, "local", None
        else:
            usage = llm_client.new_usage(cfg)
            source = llm_client.source_of(cfg)
            on_progress(0, f"{len(entities)} 个实体，模型 {cfg.model}" + (f"，从断点继续（已整理 {resumed} 批）" if resumed else ""))
            out = material_facts.compile_cards(entities, chapters, _chat_fn(cfg, usage),
                                               cfg.concurrency if source == "api" else 1, ckpt, on_progress, stop_event,
                                               local=False, plot=plot)
            model_name = cfg.model
    except material_facts.Cancelled as e:
        raise Cancelled(str(e)) from e
    finally:
        ckpt.close()
    st = out["stats"]
    if st["entities"] and st["failedCards"] and not (st["cards"] or st["notUseful"]):
        raise LLMError("所有卡片都整理失败，请检查模型配置或稍后重试")
    on_progress(100, f"完成：{st['cards'] + st['systems']} 张素材卡、{st['arcs']} 个剧情段")
    result = {"materials": out["materials"], "stats": st, "model": model_name, "source": source}
    if usage:
        result["usage"] = usage
    return result


def _extract(file_id: int, file_ext: str, on_progress: Callable[[int, str], None],
             stop_event: threading.Event | None, *, analyze: Callable[[str, str, str], dict], chunk_chars: int,
             concurrency: int, model_name: str, source: str, resume_key: str | None = None) -> dict:
    """逐块章节分析（摘要 / 人物 / 事件 / 伏笔）。resume_key 不为空时每块结果写断点，续跑时跳过。"""
    data = text_loader.fetch_file(file_id)
    text = text_loader.to_plain_text(data, file_ext)
    if not text:
        raise ValueError("文件中没有可提取的文本")

    chapters = text_loader.split_chapters(text)
    tasks = []  # (章节下标, 块文本)，顺序即章节内块顺序
    for ci, ch in enumerate(chapters):
        for part in text_loader.split_chunks(ch["content"], chunk_chars):
            tasks.append((ci, part))

    extra = ""
    ckpt = extract_checkpoint.Checkpoint(resume_key, {"fileId": file_id, "chars": len(text), "mode": "chunks",
                                                      "chunkChars": chunk_chars, "chunks": len(tasks), "extra": extra})
    saved = ckpt.done("chunks")
    results: list[dict | None] = [saved.get(str(i)) for i in range(len(tasks))]
    on_progress(int(len(saved) * 100 / max(1, len(tasks))),
                f"共 {len(chapters)} 章，{len(tasks)} 个分块，{'本地模型' if source == 'local' else '模型'} "
                f"{model_name}，并发 {concurrency}" + (f"，从断点继续（已完成 {len(saved)} 块）" if saved else ""))
    lock = threading.Lock()
    state = {"done": len(saved), "failed": 0}

    def run(i: int) -> None:
        if stop_event and stop_event.is_set():
            raise Cancelled("已取消")
        ci, part = tasks[i]
        title = chapters[ci]["title"]
        try:
            results[i] = analyze(title, part, extra)
            with lock:
                ckpt.append("chunks", i, results[i])
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
        futures = [pool.submit(run, i) for i in range(len(tasks)) if results[i] is None]
        finished, _ = wait(futures, return_when=FIRST_EXCEPTION)
        for f in finished:
            if f.exception():
                raise f.exception()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        ckpt.close()

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
