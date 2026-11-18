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
        return _extract_facts(file_id, file_ext, on_progress, material_opts, stop_event, call=_chat_fn(cfg, usage, stop=stop_event),
                              concurrency=cfg.concurrency if source == "api" else 1, model_name=cfg.model,
                              source=source, resume_key=resume_key, usage=usage, in_app=False)
    return _extract(file_id, file_ext, on_progress, stop_event,
                    analyze=lambda title, part, extra: llm_client.analyze_chunk(cfg, title, part, extra),
                    chunk_chars=config.CHUNK_CHARS, concurrency=cfg.concurrency, model_name=cfg.model,
                    source=llm_client.source_of(cfg), resume_key=resume_key)


def _chat_fn(cfg: ModelConfig, usage: dict, think: bool = False,
             stop: threading.Event | None = None) -> Callable[[list[dict], int], str]:
    """think=False：推理模型关掉思考（见 llm_client.chat）；评测脚本可以打开做对比。
    stop = 任务的取消标记：模型调用等待中途也能取消（llm_client._send）。"""
    lock = threading.Lock()

    def call(messages: list[dict], max_tokens: int) -> str:
        one: dict = {}
        text = llm_client.chat(cfg, messages, max_tokens=max_tokens, usage=one, think=think, cancel=stop)
        with lock:
            for k in ("calls", "promptTokens", "completionTokens", "cacheHitTokens", "reasoningTokens", "truncated"):
                usage[k] = usage.get(k, 0) + one.get(k, 0)
        return text

    return call


_books: "dict[tuple[int, str], dict]" = {}   # 最近 2 个文件的分章结果（逐章查看取原文、提取前预览章节用）
_books_lock = threading.Lock()


def load_book(file_id: int, file_ext: str) -> dict:
    """取文件 → 纯文本 → 分章（和提取时完全同一套流程）。→ {text, chapters, preface, warnings}，缓存最近 2 个文件。"""
    key = (file_id, file_ext.lower())
    with _books_lock:
        if key in _books:
            return _books[key]
    text = text_loader.to_plain_text(text_loader.fetch_file(file_id), file_ext)
    if not text:
        raise ValueError("文件中没有可提取的文本")
    book = text_loader.split_book(text)
    out = {"text": text, "chapters": book["chapters"] or [{"title": "全文", "content": text, "kind": "whole"}],
           "preface": book["preface"], "warnings": book["warnings"]}
    with _books_lock:
        while len(_books) >= 2:
            _books.pop(next(iter(_books)))
        _books[key] = out
    return out


def split_preview(file_id: int, file_ext: str) -> dict:
    """提取前选章节范围用：→ {chars, total, chapters: [{index (从 1 数), title, kind, chars, volume?}], prefaceChars, warnings}"""
    book = load_book(file_id, file_ext)
    rows = []
    for i, ch in enumerate(book["chapters"], 1):
        row = {"index": i, "title": ch["title"], "kind": ch.get("kind", "chapter"), "chars": len(ch["content"])}
        if ch.get("volume"):
            row["volume"] = ch["volume"]
        rows.append(row)
    return {"chars": len(book["text"]), "total": len(rows), "chapters": rows,
            "prefaceChars": len(book["preface"] or ""), "warnings": book["warnings"]}


def chapter_text(file_id: int, file_ext: str, index: int) -> dict:
    """第 index 章（从 0 数，全书下标）的原文 → {index, title, kind, text, total}。"""
    chapters = load_book(file_id, file_ext)["chapters"]
    if not 0 <= index < len(chapters):
        raise ValueError(f"没有第 {index + 1} 章（共 {len(chapters)} 章）")
    ch = chapters[index]
    return {"index": index, "title": ch["title"], "kind": ch.get("kind", "chapter"), "text": ch["content"],
            "total": len(chapters)}


def chapter_range(total: int, opts) -> tuple[int, int]:
    """MaterialOptions 的 fromChapter / toChapter（从 1 数，to = 0 到最后）→ 切片 [lo, hi)。"""
    lo = max(1, opts.fromChapter) - 1
    hi = min(total, opts.toChapter) if opts.toChapter else total
    if lo >= total:
        raise ValueError(f"起始章（第 {lo + 1} 章）超过了全书章数（{total} 章）")
    if hi <= lo:
        raise ValueError(f"章节范围不对：第 {lo + 1} 章到第 {hi} 章")
    return lo, hi


def _extract_facts(file_id: int, file_ext: str, on_progress: Callable[[int, str], None], opts, stop_event, *,
                   call, concurrency: int, model_name: str, source: str, resume_key: str | None,
                   usage: dict | None, in_app: bool) -> dict:
    """逐章读原文（chapter_scan）：结果 = 章节列表（摘要由章节卡拼成）+ entities（实体档案）+ chapterCards / threads / pacing，
    不出候选。一次读的上限：大模型 2 万字；GGUF（本机服务）分段字数 × 2；应用内本地模型 = 分段字数（上下文窗口小）。"""
    from . import breakdown, chapter_scan

    book = load_book(file_id, file_ext)
    text, all_chapters = book["text"], book["chapters"]
    lo, hi = chapter_range(len(all_chapters), opts)
    chapters = all_chapters[lo:hi]
    rng = {"from": lo + 1, "to": hi, "total": len(all_chapters), "chars": sum(len(c["content"]) for c in chapters)}
    golden = {ci - lo for ci in chapter_scan.golden_of(all_chapters) if lo <= ci < hi}
    small = in_app or source == "local"
    max_chars = opts.chunkChars if in_app else opts.chunkChars * 2 if small else chapter_scan.API_MAX_CHARS
    jobs = chapter_scan.chapter_jobs(chapters, max_chars)
    # 指纹不含读到哪一章：同一起点读得更远时，已读的章可以接着用
    fingerprint = {"fileId": file_id, "chars": len(text), "chapters": len(all_chapters),
                   **chapter_scan.fingerprint(opts, max_chars)}
    ckpt = extract_checkpoint.Checkpoint(resume_key, fingerprint)
    parts = Counter(j["ci"] for j in jobs)
    ckpt.save_json("chapters", {"range": rng, "chapters": [
        {"ci": ci, "index": lo + ci, "title": ch["title"], "kind": ch.get("kind", "chapter"), "chars": len(ch["content"]),
         "parts": parts.get(ci, 0)} for ci, ch in enumerate(chapters)]})
    resumed = sum(len(ckpt.done(s)) for s in ("pass1", "pass2"))
    depth_label = {"fast": "快速", "standard": "标准", "deep": "深拆"}.get(opts.depth, opts.depth)
    scope = f"第 {lo + 1}–{hi} 章（全书 {len(all_chapters)} 章）" if (lo, hi) != (0, len(all_chapters)) else f"共 {len(chapters)} 章"
    on_progress(0, f"{scope}，{len(jobs)} 份，逐章读、{depth_label}档、读 {opts.rounds} 遍，模型 {model_name}"
                   + (f"，从断点继续（已读完 {resumed} 份次）" if resumed else ""))
    try:
        out = material_facts.scan(chapters, opts, call, concurrency, ckpt, on_progress, stop_event, local=small,
                                  max_chars=max_chars, golden=golden)
    except material_facts.Cancelled as e:
        raise Cancelled(str(e)) from e
    finally:
        ckpt.close()
    stats = out["stats"]
    if jobs and stats["failedChunks"] >= len(jobs) * opts.rounds:
        raise LLMError("所有章节都解析失败，请检查模型配置或稍后重试")

    out_chapters, counts, first = [], Counter(), {}
    for ch, info, card in zip(chapters, out["chapters"], out["chapterCards"]):
        row = {"title": ch["title"], "wordCount": len(ch["content"]), "summary": info["summary"],
               "characters": info["characters"], "events": [{"summary": e} for e in card.get("events") or []],
               "foreshadowing": [], "kind": ch.get("kind", "chapter")}
        if ch.get("volume"):
            row["volume"] = ch["volume"]
        out_chapters.append(row)
        counts.update(info["characters"])
        for n in info["characters"]:
            first.setdefault(n, ch["title"])
    result = {
        "wordCount": len(text),
        "chapterCount": len(chapters),
        "range": rng,            # 读了哪几章（从 1 数，全书下标）；chapters / chapterCards 只含这几章，ci 从范围起点数
        "failedChunks": stats["failedChunks"],
        "characters": [{"name": n, "role": "", "firstAppear": first[n], "chapterCount": c}
                       for n, c in counts.most_common()],
        "style": {"dialogRatio": dialog_ratio("\n".join(c["content"] for c in chapters)), "pace": "", "tones": []},
        "chapters": out_chapters,
        "model": model_name,
        "source": source,
        "entities": out["entities"],
        "factStats": stats,
        "materialOptions": opts.model_dump(),
        "preface": book["preface"][:2000],      # 书头（书名 / 作者 / 简介），不算章、不读
        "splitWarnings": book["warnings"],
        "chapterCards": out["chapterCards"],
        "threads": out["threads"],
        "lead": out["lead"],
        "pacing": breakdown.pacing(out["chapterCards"], out["threads"]),
    }
    if usage:
        result["usage"] = usage
    on_progress(100, f"完成：{stats['entities']} 个实体、{stats['factsVerified']} 条事实、{stats['cards']} 张章节卡")
    return result


def compile_job(entities: list[dict], chapters: list[dict], cfg: ModelConfig | None, on_progress, *,
                local: dict | None = None, plot: bool = True, stop_event: threading.Event | None = None,
                resume_key: str | None = None, mode: str = "entity", craft: dict | None = None,
                groups: list[dict] | None = None, summaries: dict | None = None,
                resonance_cards: list[dict] | None = None) -> dict:
    """整理卡片 → {materials, stats, usage, model, source}。cfg = 大模型 / GGUF，local = 应用内本地模型。
    mode：entity = 实体档案 + 章节摘要 → 实体卡 / 体系卡 / 剧情段；craft = 章节卡 + 伏笔表 → 写法卡（craft_cards）；
    world = 作者确认的分组 + 成员实体 → 世界观卡（world_cards）。
    断点指纹 = mode + 输入签名：同一输入续跑时已整理的卡片不重做。"""
    from . import craft_cards, resonance_cards as rc, world_cards

    if mode == "craft":
        cards = (craft or {}).get("cards") or []
        sig_src = [(c.get("ci"), c.get("oneLine")) for c in cards]
    elif mode == "world":
        sig_src = [(g.get("name"), g.get("members")) for g in groups or []] + [(e.get("key"), len(e.get("facts") or [])) for e in entities]
    elif mode == "resonance":
        sig_src = [(g.get("name"), g.get("cardIds")) for g in groups or []] + [(c.get("id"), c.get("title")) for c in resonance_cards or []]
    else:
        sig_src = [(e.get("key"), len(e.get("facts") or [])) for e in entities]
    sig = hashlib.sha1(json.dumps(sig_src, ensure_ascii=False).encode()).hexdigest()
    fp = {"compile": sig, "plot": plot, "chapters": len(chapters)}
    if mode != "entity":
        fp = {"compile": sig, "mode": mode}
    ckpt = extract_checkpoint.Checkpoint(resume_key, fp)
    stage = {"craft": "craft", "world": "world", "resonance": "resonance"}.get(mode, "cards")
    resumed = len(ckpt.done(stage))
    what = {"craft": "写法卡", "world": f"{len(groups or [])} 组世界观卡",
            "resonance": f"{len(groups or [])} 组共鸣素材"}.get(mode, f"{len(entities)} 个实体")

    def run(call, concurrency: int, is_local: bool) -> dict:
        if mode == "craft":
            return craft_cards.compile_craft(craft or {}, call, concurrency, ckpt, on_progress, stop_event)
        if mode == "resonance":
            return rc.compile_resonance(groups or [], resonance_cards or [], call, concurrency, ckpt, on_progress, stop_event)
        if mode == "world":
            return world_cards.compile_world(entities, groups or [], summaries or {}, call, concurrency, ckpt, on_progress, stop_event)
        return material_facts.compile_cards(entities, chapters, call, concurrency, ckpt, on_progress, stop_event,
                                            local=is_local, plot=plot)

    try:
        if local:
            with local_extract.LocalSession(local["baseId"], stop_event) as session:
                on_progress(0, f"{what}，模型 {session.name}" + (f"，从断点继续（已整理 {resumed} 批）" if resumed else ""))
                out = run(session.chat, 1, True)
                model_name, source, usage = session.name, "local", None
        else:
            usage = llm_client.new_usage(cfg)
            source = llm_client.source_of(cfg)
            on_progress(0, f"{what}，模型 {cfg.model}" + (f"，从断点继续（已整理 {resumed} 批）" if resumed else ""))
            out = run(_chat_fn(cfg, usage, stop=stop_event), cfg.concurrency if source == "api" else 1, False)
            model_name = cfg.model
    except material_facts.Cancelled as e:
        raise Cancelled(str(e)) from e
    finally:
        ckpt.close()
    st = out["stats"]
    if st["failedCards"] and not (st["cards"] or st["notUseful"]) and (st["entities"] or mode != "entity"):
        raise LLMError("所有卡片都整理失败，请检查模型配置或稍后重试")
    if mode == "craft":
        on_progress(100, f"完成：{st['cards']} 张写法卡" + (f"，{len(st['skipped'])} 类缺少依据" if st.get("skipped") else ""))
    elif mode == "world":
        on_progress(100, f"完成：{st['cards']} 张世界观卡")
    elif mode == "resonance":
        on_progress(100, f"完成：{st['cards']} 张共鸣素材")
    else:
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
