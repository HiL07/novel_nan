"""分段生成章节（后台线程）。

每段一次模型调用：上下文只带「本章此前内容的末尾」+ 分层设定/前情，不重复处理整章正文。
停止条件：达到目标字数 / 最后一段模型自然结束 / 用户取消 / 段数上限。
完成后用同一模型写章节摘要（供后续章节的 L2 前情），摘要过多时合并为前情概要。
每次调用的 token 明细（分层用量、实际 prompt/输出 token、结束原因）写入章节 JSON。
"""
import logging
import math
import re
import threading
import time
import uuid

from ..local import jobs as local_jobs
from . import context, prompts, spec as spec_mod, store
from .backends import GenerationError, GenParams, TextGenerator, get_generator

log = logging.getLogger("generation")

CHARS_PER_TOKEN = 1.6          # 初始估计（实测 Qwen2.5 中文正文约 1.6~1.7 字/token），生成中按实际比例修正
MERGE_THRESHOLD, MERGE_COUNT = 8, 5
# 模型偶尔自带的章节标题，含 Markdown 形式：**第1章《退婚》** / # 第1章 …
HEADING = re.compile(r"^\s*[#*\s]*(第[零〇一二三四五六七八九十百千\d]+章[^\n]{0,30}?|《[^》\n]{1,30}》)[*\s]*\n")
SENTENCE_END = "。！？!?…」”』）)"
# 正文中途出现的 Markdown 小标题（### xxx），整行去掉
MD_HEADING_LINE = re.compile(r"^[ \t]*#{1,6}[ \t]+[^\n]*\n?", re.MULTILINE)


def _trim_incomplete(text: str) -> str:
    """按长度上限截断时，结尾可能停在半句话：回退到最后一个句末标点。"""
    body = text.rstrip()
    if not body or body[-1] in SENTENCE_END:
        return text
    cut = max(body.rfind(ch) for ch in SENTENCE_END)
    return body[: cut + 1] + "\n" if cut >= len(body) - 300 else text
PREAMBLE = re.compile(r"^\s*(好的|以下是|下面是|当然)[^\n]{0,40}[：:]\s*\n")

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
                                     repetition_penalty=1.05, stop_event=stop))
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
    r = gen.generate(msgs, GenParams(max_new_tokens=450, temperature=0.3, repetition_penalty=1.05, stop_event=stop))
    if r.finish_reason == "cancelled":
        return
    store.update_novel(novel["id"], arcSummary=r.text.strip(), arcUpTo=batch[-1]["index"])
    _record(chapter, novel["id"], {"type": "arc", "promptTokens": r.prompt_tokens,
                                   "completionTokens": r.completion_tokens, "finishReason": r.finish_reason,
                                   "seconds": r.seconds, "mergedUpTo": batch[-1]["index"], "at": store.now()})


def _run(job: dict, req: dict) -> None:
    try:
        _write_chapter(job, req)
    except Exception as e:  # noqa: BLE001 —— 任何异常都落到 failed，已写的正文保留
        log.exception("章节生成失败 novel=%s chapter=%s", job["novelId"], job["chapterIndex"])
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
    gen = get_generator(novel["model"])
    cons = spec_mod.build(novel["settings"].get("spec"))
    index, target = job["chapterIndex"], req["targetChars"]
    seg_tokens = min(p["segmentTokens"], novel["contextWindow"] // 4)
    seg_chars = int(seg_tokens * CHARS_PER_TOKEN * 0.85)
    prev = store.list_chapters(novel["id"])
    prev_tail = store.get_chapter(novel["id"], prev[-1]["index"])["text"] if prev else ""
    chapter = {"index": index, "title": req["title"], "goal": req["goal"], "targetChars": target, "text": "",
               "summary": "", "status": "generating", "error": None, "createdAt": store.now(),
               "calls": [], "totals": {"promptTokens": 0, "completionTokens": 0, "calls": 0}}
    store.save_chapter(novel["id"], chapter)
    job["status"] = "running"
    max_segments = math.ceil(target / max(seg_chars, 1)) + 2
    out_chars = out_tokens = 0
    last_finish = None
    while not stop.is_set() and len(chapter["text"]) < target * 0.95 and job["segment"] < max_segments:
        remaining = target - len(chapter["text"])
        is_last = remaining <= seg_chars * 1.2
        state = context.ChapterState(index=index, title=req["title"], goal=req["goal"], target_chars=target,
                                     written=chapter["text"], segment_chars=min(seg_chars, max(remaining, 200)),
                                     is_last=is_last, prev_chapter_tail=prev_tail)
        ctx = context.build(gen, cons, state, summaries=_story_summaries(novel, index),
                            arc_summary=novel["arcSummary"], window=novel["contextWindow"],
                            max_new_tokens=seg_tokens, recent_max=p["recentTokens"])
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
        _summarize(gen, novel, chapter, stop)
        chapter["status"] = "cancelled" if stop.is_set() else "done"
    store.save_chapter(novel["id"], chapter)
    if chapter["status"] == "done":
        _merge_arc(gen, store.get_novel(novel["id"]), chapter, stop)
        store.save_chapter(novel["id"], chapter)
    job["status"] = chapter["status"] if chapter["status"] == "cancelled" else "succeeded"


def start(novel_id: str, req: dict) -> dict:
    """req: {goal, title, targetChars}。同一时间只允许一个生成任务；训练进行中拒绝。"""
    with _lock:
        if active_job():
            raise JobError("已有章节正在生成，请等待完成或取消")
        if local_jobs.gpu_busy():
            raise JobError("有训练任务正在使用 GPU，请等待训练完成")
        novel = store.get_novel(novel_id)
        get_generator(novel["model"]).ensure_ready()
        chapters = store.list_chapters(novel_id)
        if chapters and chapters[-1]["status"] == "generating":
            raise JobError(f"第 {chapters[-1]['index']} 章上次未完成（服务可能重启过），请先删除该章再继续")
        job = {"id": uuid.uuid4().hex[:12], "novelId": novel_id,
               "chapterIndex": (chapters[-1]["index"] + 1) if chapters else 1,
               "status": "queued", "phase": "writing", "segment": 0, "error": None, "lastContext": None,
               "startedAt": store.now(), "endedAt": None}
        _jobs[job["id"]] = job
        _events[job["id"]] = threading.Event()
    threading.Thread(target=_run, args=(job, req), daemon=True, name=f"gen-{job['id']}").start()
    time.sleep(0.05)
    return job


def preview(novel_id: str, req: dict) -> dict:
    """不生成，只组装下一章第一段的上下文，返回分层 token 用量与完整提示词。"""
    novel = store.get_novel(novel_id)
    gen = get_generator(novel["model"])
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
                        window=novel["contextWindow"], max_new_tokens=seg_tokens, recent_max=p["recentTokens"])
    est_segments = math.ceil(req["targetChars"] / max(seg_chars, 1))
    return {"chapterIndex": index, "context": ctx.report(), "messages": ctx.messages,
            "segmentTokens": seg_tokens, "segmentChars": seg_chars, "estimatedSegments": est_segments,
            "modelContextLimit": gen.context_limit,
            "cards": {"total": len(cons.cards), "core": len(cons.core), "open": cons.open}}
