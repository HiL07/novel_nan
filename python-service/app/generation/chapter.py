"""分段生成章节（后台线程）。

每段一次模型调用：上下文只带「本章此前内容的末尾」+ 分层设定/前情，不重复处理整章正文。
停止条件：达到目标字数 / 最后一段模型自然结束 / 用户取消 / 段数上限。
完成后用同一基础模型写章节摘要（停用 LoRA 风格适配器：续写式微调会削弱指令遵循），供后续章节的 L2 前情；
摘要过多时合并为前情概要。
写作流程（工作区 params，均可关）：
  planChapter   动笔前规划 3~6 个节拍 + 章末钩子（chapter.plan），每段的任务说明带「本段写到第几个节拍」
  extractFacts  摘要调用同时抽取伏笔 / 角色状态 / 时间线，合并进故事账本（facts.py），写作时作为 L1b 注入；
                JSON 解析失败时退回纯文本摘要（chapter.factsError），不影响章节完成
  reviewChapter 写完对照设定 / 账本 / 前情检查一致性（chapter.review，只报告不改稿；None = 大模型开、本地关）
手动修改正文后可「重新提取」（kind=recheck 任务：重新抽取本章事实，可选再检查一次）。
可选「润色」：生成后（或对已有章节单独发起）用本地基础模型 + LoRA 适配器逐段改写，原文保存在 originalText，可恢复；
长度变化过大 / 被截断的段落保留原文，避免小模型改坏情节。
每次调用的 token 明细（分层用量、实际 prompt/输出 token、结束原因）写入章节 JSON。
"""
import json
import logging
import math
import re
import threading
import time
import uuid

from ..local import inference, jobs as local_jobs, registry
from . import context, facts as facts_mod, prompts, spec as spec_mod, store
from .backends import GenerationError, GenParams, LocalHFGenerator, TextGenerator, get_generator

log = logging.getLogger("generation")

CHARS_PER_TOKEN = 1.6          # 初始估计（实测 Qwen2.5 中文正文约 1.6~1.7 字/token），生成中按实际比例修正
MERGE_THRESHOLD, MERGE_COUNT = 8, 5
# 模型偶尔自带的章节标题，含 Markdown 形式：**第1章《退婚》** / # 第1章 …
HEADING = re.compile(r"^\s*[#*【\s]*(第[零〇一二三四五六七八九十百千\d]+章[^\n]{0,30}?|《[^》\n]{1,30}》)[*】\s]*\n")
SENTENCE_END = "。！？!?…」”』）)"
# 小模型偶尔把提示词的分节标题连同内容复述出来：从第一个这样的标题起截断
PROMPT_ECHO = re.compile(r"【(本次任务|核心设定|相关设定|本章此前内容|已设定的角色|尚未设定|前情|上一章结尾|故事账本|下一章预告)"
                         r"[^】\n]{0,8}】")
# 正文中途出现的 Markdown 小标题（### xxx），整行去掉
MD_HEADING_LINE = re.compile(r"^[ \t]*#{1,6}[ \t]+[^\n]*\n?", re.MULTILINE)


def _trim_incomplete(text: str) -> str:
    """按长度上限截断时，结尾可能停在半句话：回退到最后一个句末标点。"""
    body = text.rstrip()
    if not body or body[-1] in SENTENCE_END:
        return text
    cut = max(body.rfind(ch) for ch in SENTENCE_END)
    return body[: cut + 1] + "\n" if cut >= len(body) - 300 else text
PREAMBLE = re.compile(r"^\s*(?:[^\n]{0,12}[！!。]\s*)?(好的|以下是|下面是|当然|润色后)[^\n]{0,40}[：:]\s*\n")
POLISH_CHUNK_CHARS = 300       # 每次润色的原文长度：小模型一次改写太长容易丢内容
POLISH_RATIO = (0.7, 1.4)      # 润色结果与原文的字数比超出此范围视为改坏，保留原文

_jobs: dict[str, dict] = {}
_events: dict[str, threading.Event] = {}
_lock = threading.Lock()


class JobError(RuntimeError):
    pass


def active_job() -> dict | None:
    return next((j for j in _jobs.values() if j["status"] in ("queued", "running")), None)


def get_job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise JobError("生成任务不存在（服务重启后任务记录会清空，章节内容已保存在工作区）")
    return job


def cancel(job_id: str) -> dict:
    job = get_job(job_id)
    if job["status"] in ("queued", "running"):
        _events[job_id].set()
    return job


def _clean(piece: str, written: str) -> str:
    """去掉模型偶尔加的开场白 / 章节标题，以及与前文末尾的重复。"""
    piece = PREAMBLE.sub("", piece, count=1)
    echo = PROMPT_ECHO.search(piece)
    if echo:
        piece = piece[:echo.start()]
    piece = HEADING.sub("", piece, count=1)
    piece = MD_HEADING_LINE.sub("", piece)
    if written:
        tail = written.rstrip()
        for k in range(min(40, len(tail)), 7, -1):
            if piece.lstrip().startswith(tail[-k:]):
                piece = piece.lstrip()[k:]
                break
    else:
        piece = piece.lstrip()
    return piece.rstrip() + "\n"


def _story_summaries(novel: dict, before_index: int) -> list[dict]:
    return [{"index": c["index"], "summary": c["summary"]}
            for c in store.list_chapters(novel["id"])
            if c["index"] < before_index and c["index"] > novel["arcUpTo"] and c.get("summary")]


def _record(chapter: dict, novel_id: str, call: dict) -> None:
    chapter["calls"].append(call)
    t = chapter["totals"]
    t["promptTokens"] += call["promptTokens"]
    t["completionTokens"] += call["completionTokens"]
    t["calls"] += 1
    store.add_token_usage(novel_id, call["promptTokens"], call["completionTokens"])


def _fit_for_summary(gen: TextGenerator, text: str, budget: int) -> str:
    tokens = gen.count_text(text)
    if tokens <= budget:
        return text
    n = int(len(text) * budget / tokens * 0.95)
    return text[: n // 2] + "\n……（中间省略）……\n" + text[-(n // 2):]


def _summarize(gen: TextGenerator, novel: dict, chapter: dict, stop: threading.Event) -> None:
    window = min(novel["contextWindow"], gen.context_limit)
    budget = window - 300 - context.MARGIN - 200
    text = _fit_for_summary(gen, chapter["text"], budget)
    msgs = [{"role": "system", "content": prompts.SUMMARY_SYSTEM},
            {"role": "user", "content": prompts.summary_user(chapter["index"], chapter["title"], text)}]
    r = gen.generate(msgs, GenParams(max_new_tokens=300, temperature=0.3, top_p=0.8, top_k=20,
                                     repetition_penalty=1.05, use_adapter=False, stop_event=stop))
    chapter["summary"] = r.text.strip()
    _record(chapter, novel["id"], {"type": "summary", "promptTokens": r.prompt_tokens,
                                   "completionTokens": r.completion_tokens, "finishReason": r.finish_reason,
                                   "seconds": r.seconds, "at": store.now()})


def _merge_arc(gen: TextGenerator, novel: dict, chapter: dict, stop: threading.Event) -> None:
    """未合并的章节摘要超过阈值时，把最早的几章并入前情概要（L2 长期记忆，控制 token 增长）。"""
    pending = [c for c in store.list_chapters(novel["id"]) if c["index"] > novel["arcUpTo"] and c.get("summary")]
    if len(pending) <= MERGE_THRESHOLD:
        return
    batch = pending[:MERGE_COUNT]
    msgs = [{"role": "system", "content": prompts.SUMMARY_SYSTEM},
            {"role": "user", "content": prompts.arc_user(novel["arcSummary"],
                                                         [f"第{c['index']}章：{c['summary']}" for c in batch])}]
    r = gen.generate(msgs, GenParams(max_new_tokens=450, temperature=0.3, repetition_penalty=1.05, use_adapter=False,
                                     stop_event=stop))
    if r.finish_reason == "cancelled":
        return
    store.update_novel(novel["id"], arcSummary=r.text.strip(), arcUpTo=batch[-1]["index"])
    _record(chapter, novel["id"], {"type": "arc", "promptTokens": r.prompt_tokens,
                                   "completionTokens": r.completion_tokens, "finishReason": r.finish_reason,
                                   "seconds": r.seconds, "mergedUpTo": batch[-1]["index"], "at": store.now()})


# ---------------------------------------------------------------- 规划 / 事实抽取 / 一致性检查

_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _parse_json(text: str) -> dict | None:
    """容错解析模型输出的 JSON 对象（```json 包裹、前后废话、尾逗号）；失败返回 None。"""
    body = re.sub(r"^```\w*\s*|\s*```$", "", (text or "").strip())
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(_TRAILING_COMMA.sub(r"\1", body[start:end + 1]))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _flag(novel: dict, key: str) -> bool:
    """写作流程开关；reviewChapter 为 None（默认）时：大模型开、本地模型关（小模型查不准）。"""
    v = novel["params"].get(key, store.DEFAULT_PARAMS[key])
    if v is None:
        return novel["model"].get("source") == "api"
    return bool(v)


def _input_budget(gen: TextGenerator, novel: dict, max_tokens: int) -> int:
    return min(novel["contextWindow"], gen.context_limit) - max_tokens - context.MARGIN


def _core_text(cons: spec_mod.Constraints) -> str:
    core = "\n\n".join(cons.core)
    if cons.roster:
        core += ("\n\n" if core else "") + "【已设定的角色】" + "、".join(cons.roster)
    return core


def _next_outline(novel: dict, index: int) -> str:
    """大纲中下一章（index + 1）的标题与目标；没有大纲 / 没写到时为空。"""
    for c in (novel.get("outline") or {}).get("chapters") or []:
        if c.get("index") == index + 1:
            return f"第{index + 1}章" + (f"《{c['title']}》" if c.get("title") else "") + f"：{c.get('goal') or ''}"
    return ""


def _json_call(gen: TextGenerator, novel: dict, chapter: dict, msgs: list[dict], *, kind: str, max_tokens: int,
               temperature: float, stop: threading.Event) -> tuple[dict | None, str | None]:
    """一次 JSON 输出的指令型调用（停用 LoRA 适配器）；记录 token 明细。返回 (数据, 错误说明)。"""
    r = gen.generate(msgs, GenParams(max_new_tokens=max_tokens, temperature=temperature, top_p=0.9, top_k=20,
                                     repetition_penalty=1.05, use_adapter=False, json_mode=True, stop_event=stop))
    _record(chapter, novel["id"], {"type": kind, "promptTokens": r.prompt_tokens,
                                   "completionTokens": r.completion_tokens, "finishReason": r.finish_reason,
                                   "seconds": r.seconds, "at": store.now()})
    if r.finish_reason == "cancelled":
        return None, "已取消"
    data = _parse_json(r.text)
    if data is None:
        why = "输出被截断" if r.finish_reason == "length" else "输出不是有效的 JSON"
        hint = "（本地小模型不擅长按格式输出，可换用大模型或关闭该步骤）" if novel["model"].get("source") != "api" else ""
        return None, why + hint
    return data, None


def _strs(v, n: int, limit: int) -> list[str]:
    return [str(x).strip()[:limit] for x in (v if isinstance(v, list) else []) if str(x).strip()][:n]


def _plan(gen: TextGenerator, novel: dict, cons: spec_mod.Constraints, chapter: dict, facts: dict,
          stop: threading.Event) -> None:
    """动笔前规划本章节拍。失败不影响写作（记录 planError，按本章目标直接写）。"""
    index = chapter["index"]
    prev = [c for c in store.list_chapters(novel["id"]) if c["index"] < index and c.get("summary")]
    prev_summary = prev[-1]["summary"] if prev else ""
    ledger = facts_mod.context_text(facts, " ".join([chapter["title"], chapter["goal"], prev_summary]))
    pieces = {"core": _core_text(cons), "facts": ledger, "prev_summary": prev_summary,
              "next_outline": _next_outline(novel, index)}
    max_tokens = 700
    budget = _input_budget(gen, novel, max_tokens)

    def build() -> list[dict]:
        return [{"role": "system", "content": prompts.PLAN_SYSTEM},
                {"role": "user", "content": prompts.plan_user(chapter_index=index, title=chapter["title"],
                                                              goal=chapter["goal"],
                                                              target_chars=chapter["targetChars"], **pieces)}]
    msgs = build()
    for drop in ("facts", "prev_summary", "core"):  # 放不下时依次去掉
        if gen.count_messages(msgs) <= budget:
            break
        pieces[drop] = ""
        msgs = build()
    if gen.count_messages(msgs) > budget:
        chapter["planError"] = "上下文窗口放不下规划所需的内容，已跳过规划"
        return
    data, err = _json_call(gen, novel, chapter, msgs, kind="plan", max_tokens=max_tokens, temperature=0.5, stop=stop)
    beats = _strs((data or {}).get("beats"), 8, 120)
    if not beats:
        chapter["planError"] = err or "模型没有给出节拍"
        return
    chapter["plan"] = {"beats": beats, "foreshadow": _strs(data.get("foreshadow"), 6, 120),
                       "hook": str(data.get("hook") or "").strip()[:200]}
    chapter.pop("planError", None)


def _digest(gen: TextGenerator, novel: dict, chapter: dict, stop: threading.Event) -> None:
    """写章节摘要；开启 extractFacts 时同一次调用抽取本章事实并合并进故事账本。
    抽取失败（多为本地小模型 JSON 格式不对）→ 记录 factsError，退回纯文本摘要。"""
    if not _flag(novel, "extractFacts"):
        _summarize(gen, novel, chapter, stop)
        return
    index = chapter["index"]
    known = facts_mod.known_lines(facts_mod.view_before(store.get_facts(novel["id"]), index))
    max_tokens = 900

    def build(text: str) -> list[dict]:
        return [{"role": "system", "content": prompts.DIGEST_SYSTEM},
                {"role": "user", "content": prompts.digest_user(index, chapter["title"], text, known)}]
    budget = _input_budget(gen, novel, max_tokens) - gen.count_messages(build(""))
    if budget < 500:  # 账本太长放不下正文：不带账本（伏笔只能新建，不能引用已有编号）
        known = ""
        budget = _input_budget(gen, novel, max_tokens) - gen.count_messages(build(""))
    data, err = _json_call(gen, novel, chapter, build(_fit_for_summary(gen, chapter["text"], budget)),
                           kind="digest", max_tokens=max_tokens, temperature=0.3, stop=stop)
    summary = str((data or {}).get("summary") or "").strip()
    if data is None or not summary:
        chapter["factsError"] = err or "模型没有给出摘要"
        if not stop.is_set():
            _summarize(gen, novel, chapter, stop)
        return
    chapter["summary"] = summary[:600]
    f = store.get_facts(novel["id"])
    chapter["facts"] = facts_mod.merge(f, index, data)
    store.save_facts(novel["id"], f)
    chapter.pop("factsError", None)
    chapter.pop("factsStale", None)


def _review(gen: TextGenerator, novel: dict, cons: spec_mod.Constraints, chapter: dict,
            stop: threading.Event) -> None:
    """对照核心设定 / 本章之前的账本 / 前情检查本章一致性。只报告，不改正文。"""
    index, text = chapter["index"], chapter["text"]
    before = facts_mod.view_before(store.get_facts(novel["id"]), index)
    sums = [c for c in store.list_chapters(novel["id"]) if c["index"] < index and c.get("summary")]
    story = ([f"（更早章节）{novel['arcSummary']}"] if novel.get("arcSummary") else []) + \
            [f"第{c['index']}章：{c['summary']}" for c in sums[-3:]]
    plan = "；".join((chapter.get("plan") or {}).get("beats") or [])
    pieces = {"core": _core_text(cons), "facts": facts_mod.context_text(before, text), "story": "\n".join(story),
              "plan": plan}
    max_tokens = 1500

    def build(body: str) -> list[dict]:
        return [{"role": "system", "content": prompts.REVIEW_SYSTEM},
                {"role": "user", "content": prompts.review_user(chapter_index=index, title=chapter["title"],
                                                                goal=chapter["goal"], text=body, **pieces)}]
    budget = _input_budget(gen, novel, max_tokens) - gen.count_messages(build(""))
    for drop in ("story", "facts"):  # 正文至少留一半预算
        if budget >= gen.count_text(text) or budget >= 1500:
            break
        pieces[drop] = ""
        budget = _input_budget(gen, novel, max_tokens) - gen.count_messages(build(""))
    if budget < 300:
        chapter["review"] = {"issues": [], "error": "上下文窗口放不下检查所需的内容", "at": store.now()}
        return
    data, err = _json_call(gen, novel, chapter, build(_fit_for_summary(gen, text, budget)), kind="review",
                           max_tokens=max_tokens, temperature=0.2, stop=stop)
    if data is None:
        chapter["review"] = {"issues": [], "error": err, "at": store.now()}
        return
    issues = []
    for it in (data.get("issues") if isinstance(data.get("issues"), list) else [])[:10]:
        if not isinstance(it, dict) or not str(it.get("detail") or "").strip():
            continue
        quote = str(it.get("quote") or "").strip().strip("「」“”\"")[:120]
        issues.append({"type": it.get("type") if it.get("type") in prompts.REVIEW_TYPES else "logic",
                       "quote": quote, "found": bool(quote) and quote in text,
                       "detail": str(it["detail"]).strip()[:400], "fix": str(it.get("fix") or "").strip()[:400]})
    chapter["review"] = {"issues": issues, "at": store.now(), "model": gen.name, "ignored": False}


def _run(job: dict, req: dict) -> None:
    try:
        if job["kind"] == "polish":
            _polish_only(job, req)
        elif job["kind"] == "recheck":
            _recheck(job, req)
        else:
            _write_chapter(job, req)
    except Exception as e:  # noqa: BLE001 —— 任何异常都落到 failed，已写的正文保留
        log.exception("章节生成失败 novel=%s chapter=%s", job["novelId"], job["chapterIndex"])
        if job["kind"] == "recheck":  # 重新提取失败不影响已完成的章节
            job["status"], job["error"] = "failed", str(e) or e.__class__.__name__
            return
        try:  # 已写的正文保留，章节标记为失败
            chapter = store.get_chapter(job["novelId"], job["chapterIndex"])
            chapter["status"], chapter["error"] = "failed", str(e) or e.__class__.__name__
            store.save_chapter(job["novelId"], chapter)
        except store.StoreError:
            pass
        job["status"], job["error"] = "failed", str(e) or e.__class__.__name__
    finally:
        job["endedAt"] = store.now()


def _write_chapter(job: dict, req: dict) -> None:
    stop = _events[job["id"]]
    novel = store.get_novel(job["novelId"])
    p = novel["params"]
    gen = get_generator(novel["model"], req.get("api"))
    cons = spec_mod.build(novel["settings"].get("spec"))
    index, target = job["chapterIndex"], req["targetChars"]
    seg_tokens = min(p["segmentTokens"], novel["contextWindow"] // 4)
    seg_chars = int(seg_tokens * CHARS_PER_TOKEN * 0.85)
    prev = store.list_chapters(novel["id"])
    prev_tail = store.get_chapter(novel["id"], prev[-1]["index"])["text"] if prev else ""
    chapter = {"index": index, "title": req["title"], "goal": req["goal"], "targetChars": target, "text": "",
               "summary": "", "status": "generating", "error": None, "createdAt": store.now(),
               "model": _model_record(novel["model"], gen),
               "calls": [], "totals": {"promptTokens": 0, "completionTokens": 0, "calls": 0}}
    store.save_chapter(novel["id"], chapter)
    job["status"] = "running"
    facts = store.get_facts(novel["id"])
    next_outline = _next_outline(novel, index)
    if _flag(novel, "planChapter"):
        job["phase"] = "plan"
        _plan(gen, novel, cons, chapter, facts, stop)
        store.save_chapter(novel["id"], chapter)
        job["phase"] = "writing"
    max_segments = math.ceil(target / max(seg_chars, 1)) + 2
    out_chars = out_tokens = 0
    last_finish = None
    while not stop.is_set() and len(chapter["text"]) < target * 0.95 and job["segment"] < max_segments:
        remaining = target - len(chapter["text"])
        is_last = remaining <= seg_chars * 1.2
        state = context.ChapterState(index=index, title=req["title"], goal=req["goal"], target_chars=target,
                                     written=chapter["text"], segment_chars=min(seg_chars, max(remaining, 200)),
                                     is_last=is_last, prev_chapter_tail=prev_tail, plan=chapter.get("plan"))
        ctx = context.build(gen, cons, state, summaries=_story_summaries(novel, index),
                            arc_summary=novel["arcSummary"], window=novel["contextWindow"],
                            max_new_tokens=seg_tokens, recent_max=p["recentTokens"], facts=facts,
                            next_outline=next_outline)
        job["lastContext"] = ctx.report()
        # 模型不严格遵守「约 N 字」：按剩余字数给本段设硬上限（留 30% 余量让它写完整句），避免最后一段严重超长
        ratio = out_chars / out_tokens if out_tokens else CHARS_PER_TOKEN
        cap = min(seg_tokens, int(remaining / ratio * 1.3) + 64)
        r = gen.generate(ctx.messages, GenParams(max_new_tokens=cap, temperature=p["temperature"],
                                                 top_p=p["topP"], top_k=p["topK"],
                                                 repetition_penalty=p["repetitionPenalty"], stop_event=stop))
        piece = _clean(r.text, chapter["text"])
        job["segment"] += 1
        _record(chapter, novel["id"], {"type": "segment", "segment": job["segment"], "promptTokens": r.prompt_tokens,
                                       "completionTokens": r.completion_tokens, "finishReason": r.finish_reason,
                                       "seconds": r.seconds, "chars": len(piece), "context": ctx.report(),
                                       "at": store.now()})
        last_finish = r.finish_reason
        if piece.strip():
            chapter["text"] += piece
            # 用实际「字/token」修正后续每段的字数估计
            out_chars += len(piece)
            out_tokens += r.completion_tokens
            seg_chars = int(seg_tokens * (out_chars / max(out_tokens, 1)) * 0.85)
        store.save_chapter(novel["id"], chapter)
        if r.finish_reason == "stop" and is_last:
            break
        if not piece.strip() and r.finish_reason != "cancelled":
            raise GenerationError("模型输出为空，已停止；可尝试提高温度或修改本章目标")
    if last_finish == "length":
        chapter["text"] = _trim_incomplete(chapter["text"])
    if stop.is_set():
        chapter["status"] = "cancelled"
    else:
        job["phase"] = "summary"
        _digest(gen, novel, chapter, stop)
        store.save_chapter(novel["id"], chapter)
        if not stop.is_set() and _flag(novel, "reviewChapter"):
            job["phase"] = "review"
            _review(gen, novel, cons, chapter, stop)
        chapter["status"] = "cancelled" if stop.is_set() else "done"
    store.save_chapter(novel["id"], chapter)
    if chapter["status"] == "done":
        _merge_arc(gen, store.get_novel(novel["id"]), chapter, stop)
        store.save_chapter(novel["id"], chapter)
    if chapter["status"] == "done" and (req.get("polish") or {}).get("enabled"):
        _polish(job, store.get_novel(novel["id"]), chapter, req["polish"], stop)
    job["status"] = chapter["status"] if chapter["status"] == "cancelled" else "succeeded"


def _model_record(model: dict, gen: TextGenerator) -> dict:
    """章节上记录写作所用的模型（不含任何密钥）。"""
    if model.get("source") in ("api", "gguf"):
        return {"source": model["source"], "name": gen.name}
    return {"source": "local", "baseId": model.get("baseId"), "adapterId": model.get("adapterId")}


# ---------------------------------------------------------------- 润色（本地模型 + LoRA）

def _polish_chunks(text: str) -> list[str]:
    """按段落切成不超过 POLISH_CHUNK_CHARS 的块（超长单段落独立成块），块内保留换行。"""
    chunks, cur = [], ""
    for para in text.splitlines(keepends=True):
        if cur and len(cur) + len(para) > POLISH_CHUNK_CHARS:
            chunks.append(cur)
            cur = ""
        cur += para
    if cur:
        chunks.append(cur)
    return chunks


def _check_polish(polish: dict) -> None:
    if not polish.get("baseId"):
        raise JobError("润色需要选择本地基础模型")
    if polish.get("adapterId"):
        inference.check_adapter(polish["adapterId"], polish["baseId"])
    else:
        registry.get_base(polish["baseId"])


def _ensure_local(base_id: str, adapter_id: str | None, stop: threading.Event) -> LocalHFGenerator:
    """确保本地模型（+ 适配器）已加载：同一基础模型已驻留时只切换适配器。"""
    loaded = inference.loaded_model()
    if not loaded or loaded["baseId"] != base_id or loaded["adapterId"] != adapter_id:
        inference.load(base_id, adapter_id, "auto", from_generation=True)
        inference.wait_loaded(stop_event=stop)
    return LocalHFGenerator(base_id, adapter_id)


def _polish(job: dict, novel: dict, chapter: dict, polish: dict, stop: threading.Event) -> None:
    """逐块润色。原文（首次润色前的正文）存入 originalText；再次润色总是从原文开始。取消时保留原文不变。"""
    source = chapter.get("originalText") or chapter["text"]
    chunks = _polish_chunks(source)
    job.update(phase="polish", polishDone=0, polishTotal=len(chunks))
    gen = _ensure_local(polish["baseId"], polish.get("adapterId") or None, stop)
    out, changed, kept = [], 0, 0
    for chunk in chunks:
        if stop.is_set():
            break
        if not chunk.strip():
            out.append(chunk)
            job["polishDone"] += 1
            continue
        msgs = [{"role": "system", "content": prompts.POLISH_SYSTEM},
                {"role": "user", "content": prompts.polish_user(chunk.strip())}]
        r = gen.generate(msgs, GenParams(max_new_tokens=int(gen.count_text(chunk) * 1.5) + 64, temperature=0.4,
                                         top_p=0.8, top_k=20, repetition_penalty=1.05, stop_event=stop))
        text = PREAMBLE.sub("", r.text, count=1).strip()
        ratio = len(re.sub(r"\s", "", text)) / max(len(re.sub(r"\s", "", chunk)), 1)
        ok = r.finish_reason == "stop" and POLISH_RATIO[0] <= ratio <= POLISH_RATIO[1]
        if ok:
            out.append(text + ("\n" if chunk.endswith("\n") else ""))
            changed += 1
        else:
            out.append(chunk)
            kept += 1
        job["polishDone"] += 1
        chapter["polishDraft"] = "".join(out)
        _record(chapter, novel["id"], {"type": "polish", "promptTokens": r.prompt_tokens,
                                       "completionTokens": r.completion_tokens, "finishReason": r.finish_reason,
                                       "seconds": r.seconds, "chars": len(chunk), "kept": not ok,
                                       "at": store.now()})
        store.save_chapter(novel["id"], chapter)
    chapter.pop("polishDraft", None)
    if not stop.is_set():
        adapter = registry.get_adapter(polish["adapterId"]) if polish.get("adapterId") else None
        chapter["originalText"] = source
        chapter["text"] = "".join(out)
        chapter["polish"] = {"baseId": polish["baseId"], "adapterId": polish.get("adapterId"),
                             "adapterName": adapter["name"] if adapter else None, "at": store.now(),
                             "chunks": len(chunks), "changed": changed, "kept": kept}
    store.save_chapter(novel["id"], chapter)
    m = novel["model"]  # 本地工作区：润色换了适配器时切回工作区自己的（同一基础模型只切换适配器，很快）
    if m.get("source") == "local" and m.get("baseId") == polish["baseId"] and \
            (m.get("adapterId") or None) != (polish.get("adapterId") or None):
        try:
            inference.load(m["baseId"], m.get("adapterId") or None, "auto", from_generation=True)
        except RuntimeError:
            log.warning("润色后切回工作区适配器失败", exc_info=True)


def _recheck(job: dict, req: dict) -> None:
    """已完成章节：重新抽取本章事实（替换该章在账本里的旧记录）和 / 或重新检查一致性。"""
    stop = _events[job["id"]]
    novel = store.get_novel(job["novelId"])
    chapter = store.get_chapter(novel["id"], job["chapterIndex"])
    gen = get_generator(novel["model"], req.get("api"))
    job["status"] = "running"
    if req.get("digest"):
        job["phase"] = "summary"
        novel = novel | {"params": novel["params"] | {"extractFacts": True}}  # 显式要求提取：不受开关影响
        _digest(gen, novel, chapter, stop)
        store.save_chapter(novel["id"], chapter)
    if req.get("review") and not stop.is_set():
        job["phase"] = "review"
        _review(gen, novel, spec_mod.build(novel["settings"].get("spec")), chapter, stop)
        store.save_chapter(novel["id"], chapter)
    job["status"] = "cancelled" if stop.is_set() else "succeeded"


def _polish_only(job: dict, req: dict) -> None:
    stop = _events[job["id"]]
    novel = store.get_novel(job["novelId"])
    chapter = store.get_chapter(novel["id"], job["chapterIndex"])
    job["status"] = "running"
    _polish(job, novel, chapter, req["polish"], stop)
    job["status"] = "cancelled" if stop.is_set() else "succeeded"


def _new_job(novel_id: str, kind: str, chapter_index: int) -> dict:
    job = {"id": uuid.uuid4().hex[:12], "novelId": novel_id, "kind": kind, "chapterIndex": chapter_index,
           "status": "queued", "phase": {"polish": "polish", "recheck": "summary"}.get(kind, "writing"),
           "segment": 0, "error": None,
           "lastContext": None, "polishDone": 0, "polishTotal": 0, "startedAt": store.now(), "endedAt": None}
    _jobs[job["id"]] = job
    _events[job["id"]] = threading.Event()
    return job


def _launch(job: dict, req: dict) -> dict:
    threading.Thread(target=_run, args=(job, req), daemon=True, name=f"gen-{job['id']}").start()
    time.sleep(0.05)
    return job


def start(novel_id: str, req: dict) -> dict:
    """req: {goal, title, targetChars, api?, polish?{enabled, baseId, adapterId}}。
    api = Java 附带的大模型配置（工作区为大模型时必需），只在本次任务内存中使用，不进任务状态。
    同一时间只允许一个生成任务；训练进行中拒绝。"""
    with _lock:
        if active_job():
            raise JobError("已有章节正在生成，请等待完成或取消")
        novel = store.get_novel(novel_id)
        polish = (req.get("polish") or {}).get("enabled")
        # 大模型 / GGUF（llama.cpp 独立进程）不占本服务的 GPU 模型，训练期间也可以写；本地生成 / 润色要用 GPU
        in_process = novel["model"].get("source") not in ("api", "gguf")
        if local_jobs.gpu_busy() and (in_process or polish):
            raise JobError("有训练任务正在使用 GPU，请等待训练完成" + ("（或关闭「润色」）" if polish else ""))
        if inference.extract_busy() and (in_process or polish):
            raise JobError("小说提取正在使用本地模型，请等待提取完成或取消" + ("（或关闭「润色」）" if polish else ""))
        get_generator(novel["model"], req.get("api")).ensure_ready()
        if polish:
            _check_polish(req["polish"])
        chapters = store.list_chapters(novel_id)
        if chapters and chapters[-1]["status"] == "generating":
            raise JobError(f"第 {chapters[-1]['index']} 章上次未完成（服务可能重启过），请先删除该章再继续")
        job = _new_job(novel_id, "chapter", (chapters[-1]["index"] + 1) if chapters else 1)
    return _launch(job, req)


def start_polish(novel_id: str, index: int, polish: dict) -> dict:
    """对已完成的章节单独润色（后台任务，与章节生成共用「同一时间一个任务」）。"""
    with _lock:
        if active_job():
            raise JobError("已有章节正在生成或润色，请等待完成或取消")
        if local_jobs.gpu_busy():
            raise JobError("有训练任务正在使用 GPU，请等待训练完成")
        if inference.extract_busy():
            raise JobError("小说提取正在使用本地模型，请等待提取完成或取消")
        chapter = store.get_chapter(novel_id, index)
        if chapter["status"] != "done":
            raise JobError("只能润色已完成的章节")
        _check_polish(polish)
        job = _new_job(novel_id, "polish", index)
    return _launch(job, {"polish": polish})


def start_recheck(novel_id: str, index: int, req: dict) -> dict:
    """req: {digest: bool, review: bool, api?}。digest = 重新抽取本章摘要与事实；review = 重新检查一致性。
    本地模型须已加载工作区的模型；与章节生成共用「同一时间一个任务」。"""
    if not req.get("digest") and not req.get("review"):
        raise JobError("请选择要重新提取事实还是重新检查")
    with _lock:
        if active_job():
            raise JobError("已有章节正在生成或处理，请等待完成或取消")
        novel = store.get_novel(novel_id)
        if novel["model"].get("source") not in ("api", "gguf"):
            if local_jobs.gpu_busy():
                raise JobError("有训练任务正在使用 GPU，请等待训练完成")
            if inference.extract_busy():
                raise JobError("小说提取正在使用本地模型，请等待提取完成或取消")
        get_generator(novel["model"], req.get("api")).ensure_ready()
        chapter = store.get_chapter(novel_id, index)
        if chapter["status"] != "done":
            raise JobError("只能处理已完成的章节")
        job = _new_job(novel_id, "recheck", index)
        job["phase"] = "summary" if req.get("digest") else "review"
    return _launch(job, req)


def set_review_ignored(novel_id: str, index: int, ignored: bool) -> dict:
    """把本章的一致性检查结果标记为已读 / 忽略（章节列表不再提示问题数）。"""
    chapter = store.get_chapter(novel_id, index)
    if not chapter.get("review"):
        raise JobError("本章还没有一致性检查结果")
    chapter["review"]["ignored"] = bool(ignored)
    store.save_chapter(novel_id, chapter)
    return chapter


def edit_chapter(novel_id: str, index: int, fields: dict) -> dict:
    """手动修改章节（标题 / 目标 / 正文 / 摘要）。正文修改后，润色前的原文 originalText 仍保留（恢复原文会丢掉手动修改）。
    摘要用于后续章节的前情；已并入前情概要的章节，改摘要不会自动改概要（概要可单独修改）。"""
    job = active_job()
    if job and job["novelId"] == novel_id and job["chapterIndex"] == index:
        raise JobError("本章正在生成或润色，完成后再修改")
    chapter = store.get_chapter(novel_id, index)
    if chapter["status"] == "generating":
        raise JobError("本章还没有生成完")
    changed = [k for k, v in fields.items() if v is not None and chapter.get(k) != v]
    if not changed:
        return chapter
    for k in changed:
        chapter[k] = fields[k]
    if "text" in changed:
        chapter["text"] = chapter["text"].rstrip() + "\n"
        chapter["factsStale"] = True  # 账本里本章的事实来自修改前的正文：界面提示「重新提取」
    chapter["editedAt"] = store.now()
    chapter["edited"] = sorted(set(chapter.get("edited") or []) | set(changed))
    store.save_chapter(novel_id, chapter)
    return chapter


def revert_polish(novel_id: str, index: int) -> dict:
    job = active_job()
    if job and job["novelId"] == novel_id and job["chapterIndex"] == index:
        raise JobError("本章正在处理中，请稍候")
    chapter = store.get_chapter(novel_id, index)
    if not chapter.get("originalText"):
        raise JobError("本章没有润色过")
    chapter["text"] = chapter.pop("originalText")
    chapter.pop("polish", None)
    store.save_chapter(novel_id, chapter)
    return chapter


def preview(novel_id: str, req: dict) -> dict:
    """不生成，只组装下一章第一段的上下文，返回分层 token 用量与完整提示词。"""
    novel = store.get_novel(novel_id)
    gen = get_generator(novel["model"])  # 大模型工作区：不带配置，只按字符估算 token
    cons = spec_mod.build(novel["settings"].get("spec"))
    chapters = store.list_chapters(novel_id)
    index = (chapters[-1]["index"] + 1) if chapters else 1
    p = novel["params"]
    seg_tokens = min(p["segmentTokens"], novel["contextWindow"] // 4)
    seg_chars = int(seg_tokens * CHARS_PER_TOKEN * 0.85)
    prev_tail = store.get_chapter(novel_id, chapters[-1]["index"])["text"] if chapters else ""
    state = context.ChapterState(index=index, title=req.get("title", ""), goal=req["goal"],
                                 target_chars=req["targetChars"], written="",
                                 segment_chars=min(seg_chars, req["targetChars"]),
                                 is_last=req["targetChars"] <= seg_chars * 1.2, prev_chapter_tail=prev_tail)
    ctx = context.build(gen, cons, state, summaries=_story_summaries(novel, index), arc_summary=novel["arcSummary"],
                        window=novel["contextWindow"], max_new_tokens=seg_tokens, recent_max=p["recentTokens"],
                        facts=store.get_facts(novel_id), next_outline=_next_outline(novel, index))
    est_segments = math.ceil(req["targetChars"] / max(seg_chars, 1))
    return {"chapterIndex": index, "context": ctx.report(), "messages": ctx.messages,
            "segmentTokens": seg_tokens, "segmentChars": seg_chars, "estimatedSegments": est_segments,
            "modelContextLimit": gen.context_limit,
            "cards": {"total": len(cons.cards), "core": len(cons.core), "open": cons.open}}
