"""分层上下文组装（全部用模型自己的 tokenizer 计数）。

层级与裁剪顺序：
  L0 核心规则（system）        必须保留；放不下直接报错，不会被截断
  L4 本次任务（章节目标/分段指令） 必须保留
  L3 最近正文（本章此前内容的末尾；本章第一段时为上一章末尾）  先保留最少 RECENT_MIN，最后再用剩余预算扩展
  L2 前情（各章摘要 + 合并后的前情概要）  最近一章优先，越早越先被裁
  L1 按需设定卡片（按与本章目标 / 最近正文的相关度检索）  不相关的不放；预算不足时相关度低的先裁
  L1b 故事账本（未回收伏笔 / 本章相关角色状态 / 最近时间线）+ 下一章预告（只在本章最后一段带）
      优先级在相关卡片之后、早期摘要之前

输入预算 = 上下文窗口 − 本次最大输出 − 余量；最终用聊天模板精确计数校验。
"""
import re
from dataclasses import dataclass, field

from . import facts as facts_mod, prompts
from .backends import GenerationError, TextGenerator
from .spec import Card, Constraints

MARGIN = 64
RECENT_MIN = 256
SENTENCE_END = re.compile(r"[。！？!?…」”\n]")


@dataclass
class ChapterState:
    index: int
    title: str
    goal: str
    target_chars: int
    written: str              # 本章已写正文
    segment_chars: int
    is_last: bool
    prev_chapter_tail: str    # 上一章正文（本章第一段时用于衔接）
    plan: dict | None = None  # 本章规划 {beats, foreshadow, hook}（chapter._plan）


@dataclass
class BuiltContext:
    messages: list[dict]
    prompt_tokens: int
    input_budget: int
    window: int
    max_new_tokens: int
    layers: dict = field(default_factory=dict)
    included: dict = field(default_factory=dict)
    dropped: dict = field(default_factory=dict)

    def report(self) -> dict:
        return {"promptTokens": self.prompt_tokens, "inputBudget": self.input_budget, "window": self.window,
                "maxNewTokens": self.max_new_tokens, "layers": self.layers, "included": self.included,
                "dropped": self.dropped}


def _clip_to_sentence(text: str) -> str:
    """尾部截取后开头可能是半句话：从开头 25% 范围内的第一个句末标点之后开始。"""
    m = SENTENCE_END.search(text, 0, max(1, len(text) // 4))
    return text[m.end():].lstrip() if m else text


def score_card(card: Card, haystack: str) -> int:
    return sum(haystack.count(k) for k in card.keywords if k)


def build(gen: TextGenerator, cons: Constraints, ch: ChapterState, *, summaries: list[dict], arc_summary: str,
          window: int, max_new_tokens: int, recent_max: int, facts: dict | None = None,
          next_outline: str = "") -> BuiltContext:
    window = min(window, gen.context_limit)
    budget = window - max_new_tokens - MARGIN
    system = prompts.system(cons.core, cons.open, cons.roster)
    task = prompts.task(chapter_index=ch.index, title=ch.title, goal=ch.goal, target_chars=ch.target_chars,
                        written_chars=len(ch.written), segment_chars=ch.segment_chars,
                        is_first=not ch.written, is_last=ch.is_last, plan=ch.plan)

    def messages(cards: list[Card], sums: list[dict], arc: bool, recent: str, ledger: str = "",
                 preview: str = "") -> list[dict]:
        parts = []
        if cards:
            parts.append("【相关设定】\n" + "\n\n".join(c.text for c in cards))
        if ledger:
            parts.append("【故事账本】\n" + ledger)
        if preview:
            parts.append("【下一章预告】" + preview + "\n（只用于本章结尾的铺垫，不要提前写下一章的内容）")
        story = []
        if arc and arc_summary:
            story.append(f"（更早章节）{arc_summary}")
        story += [f"第{s['index']}章：{s['summary']}" for s in sorted(sums, key=lambda s: s["index"])]
        if story:
            parts.append("【前情提要】\n" + "\n".join(story))
        if recent:
            label = "【本章此前内容（末尾）】" if ch.written else "【上一章结尾】"
            parts.append(f"{label}\n{recent}")
        parts.append("【本次任务】\n" + task)
        return [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(parts)}]

    base_tokens = gen.count_messages(messages([], [], False, ""))
    if base_tokens > budget:
        raise GenerationError(f"核心设定 + 本次任务已占 {base_tokens} tokens，超过输入预算 {budget}"
                              f"（窗口 {window} − 输出 {max_new_tokens}）。请精简核心设定、改用 32768 窗口或减小每段生成长度")

    source_text = ch.written or ch.prev_chapter_tail
    beats = (ch.plan or {}).get("beats") or []
    haystack = " ".join([ch.title, ch.goal, source_text[-3000:]] + beats + [s["summary"] for s in summaries[-2:]])
    scored = sorted(((score_card(c, haystack), c) for c in cons.cards), key=lambda x: -x[0])
    relevant = [c for s, c in scored if s > 0]
    irrelevant = [c for s, c in scored if s <= 0]
    recent_sums = sorted(summaries, key=lambda s: -s["index"])

    # 依优先级贪心加入，用逐段计数估算，最后整体精确校验
    used = base_tokens
    recent_min = _clip_to_sentence(gen.tail_tokens(source_text, RECENT_MIN)) if source_text else ""
    chosen_cards: list[Card] = []
    chosen_sums: list[dict] = []
    use_arc = False
    dropped_cards, dropped_sums = [c.title for c in irrelevant], []

    def try_add(text: str) -> bool:
        nonlocal used
        cost = gen.count_text(text) + 8
        if used + cost <= budget:
            used += cost
            return True
        return False

    if recent_min and not try_add(recent_min):
        recent_min = ""
    if recent_sums and try_add(recent_sums[0]["summary"]):
        chosen_sums.append(recent_sums[0])
    elif recent_sums:
        dropped_sums.append(recent_sums[0]["index"])
    for c in relevant:
        (chosen_cards.append(c) if try_add(c.text) else dropped_cards.append(c.title))
    ledger = facts_mod.context_text(facts, haystack) if facts else ""
    if ledger and not try_add(ledger):
        ledger = ""
    preview = next_outline if ch.is_last else ""
    if preview and not try_add(preview):
        preview = ""
    has_ledger, has_preview = bool(ledger), bool(preview)
    if arc_summary:
        use_arc = try_add(arc_summary)
    for s in recent_sums[1:]:
        (chosen_sums.append(s) if try_add(s["summary"]) else dropped_sums.append(s["index"]))

    # 剩余预算扩展最近正文
    recent = recent_min
    if source_text:
        extra = min(recent_max, RECENT_MIN + max(0, budget - used))
        if extra > RECENT_MIN:
            recent = _clip_to_sentence(gen.tail_tokens(source_text, extra))

    # 精确校验：超出则按「扩展的正文 → 早期摘要 → 下一章预告 → 故事账本 → 低相关卡片 → 前情概要」顺序回退
    msgs = messages(chosen_cards, chosen_sums, use_arc, recent, ledger, preview)
    total = gen.count_messages(msgs)
    while total > budget:
        if recent != recent_min:
            recent = recent_min
        elif len(chosen_sums) > 1:
            dropped_sums.append(chosen_sums.pop()["index"])
        elif preview:
            preview = ""
        elif ledger:
            ledger = ""
        elif chosen_cards:
            dropped_cards.append(chosen_cards.pop().title)
        elif use_arc:
            use_arc = False
        elif chosen_sums:
            dropped_sums.append(chosen_sums.pop()["index"])
        elif recent:
            recent = ""
        else:
            break
        msgs = messages(chosen_cards, chosen_sums, use_arc, recent, ledger, preview)
        total = gen.count_messages(msgs)

    layers = {
        "L0_core": gen.count_text(system),
        "L1_cards": gen.count_text("\n\n".join(c.text for c in chosen_cards)),
        "L1b_facts": gen.count_text(ledger + preview),
        "L2_story": gen.count_text("\n".join(([arc_summary] if use_arc else []) + [s["summary"] for s in chosen_sums])),
        "L3_recent": gen.count_text(recent),
        "L4_task": gen.count_text(task),
    }
    return BuiltContext(
        messages=msgs, prompt_tokens=total, input_budget=budget, window=window, max_new_tokens=max_new_tokens,
        layers=layers,
        included={"cards": [c.title for c in chosen_cards], "summaries": sorted(s["index"] for s in chosen_sums),
                  "arcSummary": use_arc, "recentChars": len(recent), "facts": bool(ledger),
                  "nextPreview": bool(preview)},
        dropped={"cards": dropped_cards, "summaries": sorted(dropped_sums),
                 "facts": has_ledger and not ledger, "nextPreview": has_preview and not preview},
    )
