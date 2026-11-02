"""逐章串行提取（素材流程 ①，设计见 docs/素材提取改造方案.md §3.0 / §3.0.2）。

- 一章一次调用，短章不合并；超过 ``max_chars`` 的超长章按段落切成几份，按顺序读，最后由代码合成一章。
- 严格按章节顺序串行：每章的 prompt 带「滚动上下文」——上一章的一句话、本章原文里出现了名字的已知实体（只补新事实）、
  主角及其当前状态、未回收的伏笔（带编号 T<n>，回收 / 推进时引用）。所以读一遍就能把伏笔串起来。
- 同一次调用里出设定实体 + 事实和本章的章节卡；内容多少看档位 ``depth``：fast / standard / deep（§3.0.2）。
- 所有原文摘抄由代码核对（``material_facts.Source``）：事实对不上的进实体的 ``unverified``；章节卡条目对不上时保留条目、
  清空 quote、标 verified=false；金句必须逐字对上，否则丢掉。核对通过的记下在本章原文里的偏移 ``at``（原文高亮用）。
- 断点：``pass1`` 每章（或每份）一行，key = ``ci`` 或 ``ci:part``；续跑时按顺序重放，重建实体档案、伏笔表、主角状态。
  某章失败记一行 failed 继续下一章，整本读完后失败的章再试一次；连续 MAX_FAIL_STREAK 章失败就停下（任务可继续）。
- ``rounds: 2``：再按顺序读一遍，带全书已知实体，只补漏掉的事实和实体（``pass2``）。
"""
import logging
import re
import threading
from typing import Callable

from . import material_facts as mf
from . import text_loader
from .llm_client import LLMError
from .materials import CATEGORIES, MaterialOptions

log = logging.getLogger(__name__)

HOOK_POS = ("open", "mid", "end")
HOOK_TYPES = ("悬念", "危机", "反转", "期待", "情绪", "信息", "关系")
PAYOFF_TYPES = ("打脸", "装逼", "升级", "收获", "认可", "逆袭", "报复", "掌控", "越级", "情感", "团宠")
THREAD_KINDS = ("伏笔", "悬念", "承诺")
THREAD_ACTS = ("plant", "advance", "payoff")
FUNCTIONS = ("铺垫", "过渡", "冲突升级", "高潮", "转折", "揭秘", "日常", "收尾")
LEAD_FIELDS = ("实力", "金手指", "物品", "地位", "目标", "其他")
REL_TYPES = ("结盟", "反目", "师徒", "亲属", "暧昧", "主从", "敌对", "其他")
REL_CHANGES = ("新建", "加深", "破裂", "揭示")
MOVE_ACTS = ("首次登场", "获得", "使用", "击败", "失去", "揭示")
DEPTHS = ("fast", "standard", "deep")

TOKENS = {"fast": (1500, 1000), "standard": (3000, 2000), "deep": (3600, 2400)}  # (大模型, 本地 / GGUF)
SUPPLEMENT_TOKENS = (1500, 1000)
API_MAX_CHARS = 20000          # 大模型一次读的最多字数；本地 / GGUF 由调用方按上下文窗口给
GOLDEN_CHAPTERS = 3
PREV_LINES = 2
MAX_THREAD_CTX = 20
MAX_FAIL_STREAK = 5
MAX_UNVERIFIED = 10
MAX_LINES = 3
CARDS_VERSION = 1              # 改了 prompt / 输出格式就加 1，让旧断点作废


# ---------------------------------------------------------------- 分章任务

def chapter_jobs(chapters: list[dict], max_chars: int) -> list[dict]:
    """每章一份；超长章按段落切成几份。→ [{key, ci, part, parts, text, offset}]，offset = 这一份在章正文里的起点。"""
    jobs = []
    for ci, ch in enumerate(chapters):
        content = ch["content"]
        if not content.strip():
            continue
        parts = text_loader.split_chunks(content, max_chars) if len(content) > max_chars else [content]
        cursor = 0
        for k, part in enumerate(parts):
            off = content.find(part, cursor)
            off = cursor if off < 0 else off
            cursor = off + len(part)
            jobs.append({"key": str(ci) if len(parts) == 1 else f"{ci}:{k}", "ci": ci, "part": k, "parts": len(parts),
                         "text": part, "offset": off})
    return jobs


def paragraph_spans(text: str) -> list[tuple[int, int]]:
    """非空段落（行）在文本里的 [起点, 终点)。"""
    spans, pos = [], 0
    for line in text.split("\n"):
        if line.strip():
            spans.append((pos, pos + len(line)))
        pos += len(line) + 1
    return spans


# ---------------------------------------------------------------- 滚动状态

class Threads:
    """伏笔 / 悬念 / 承诺表：plant 时由代码编号 T<n>，advance / payoff 引用编号。"""

    def __init__(self):
        self.items: list[dict] = []
        self.by_id: dict[str, dict] = {}
        self.next = 1

    def assign(self, ops: list[dict]) -> None:
        for op in ops:
            if op["op"] == "plant" and not op.get("id"):
                op["id"] = f"T{self.next}"
                self.next += 1

    def apply(self, ci: int, ops: list[dict]) -> None:
        for op in ops:
            if op["op"] == "plant" and op.get("id"):
                item = {"id": op["id"], "kind": op["kind"], "text": op["text"], "quote": op["quote"], "at": op["at"],
                        "plantCi": ci, "advances": [], "payoffCi": None, "status": "open"}
                self.items.append(item)
                self.by_id[op["id"]] = item
                m = re.fullmatch(r"T(\d+)", op["id"])
                if m:
                    self.next = max(self.next, int(m.group(1)) + 1)
            elif op.get("id") in self.by_id:
                item = self.by_id[op["id"]]
                item["advances"].append({"ci": ci, "act": op["op"], "text": op["text"], "quote": op["quote"], "at": op["at"]})
                if op["op"] == "payoff":
                    item["status"], item["payoffCi"] = "paid", ci

    def context(self, text: str) -> list[dict]:
        """给本章看的未回收线索：关键词出现在本章原文里的优先，其余按最近埋下。"""
        norm = mf._normalize(text)[0]
        scored = []
        for t in self.items:
            if t["status"] != "open":
                continue
            key = mf._normalize(t["text"] + t["quote"])[0]
            hits = sum(1 for i in range(0, max(0, len(key) - 3), 2) if key[i:i + 4] in norm)
            scored.append((hits >= 2, t["plantCi"], t))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [t for _, _, t in scored[:MAX_THREAD_CTX]]


class Lead:
    """主角：第一次判断出来的名字由代码记住；状态 = 各字段最新的 after。"""

    def __init__(self):
        self.name = ""
        self.state: dict[str, str] = {}

    def update(self, card: dict) -> None:
        name = (card.get("lead") or "").strip()
        if not self.name and 1 < len(name) <= 20:
            self.name = name
        for ch in card.get("leadChanges") or []:
            if ch.get("field") and ch.get("after"):
                self.state[ch["field"]] = ch["after"]

    def line(self) -> str:
        if not self.name:
            return ""
        state = "；".join(f"{k}：{v}" for k, v in self.state.items())
        return f"{self.name}" + (f"（目前 {state}）" if state else "")


# ---------------------------------------------------------------- prompt

ENTITY_RULES = """1. 设定实体：只记录原文明确写出的内容，不推测、不评价；每条事实要具体（外形、能力、弱点、规则、代价、习性、来历、限制等），能直接用于写作。
2. 每条事实附 quote：原文中能证明它的一小段，原样摘抄，不超过 30 字。普通路人、一次性的动作描写、纯情绪不要记录；name 用原文称呼，别称写进 aliases。"""

CARD_RULES_FAST = """3. oneLine 用一句话说清本章发生了什么、起什么作用；events 写推动剧情的 3 到 6 个关键事件，按发生顺序。"""

CARD_RULES = CARD_RULES_FAST + """
4. hooks：open = 开头几段吊住读者的，end = 章末留给下一章的，mid = 章中的；strength 1 弱、2 中、3 强；没有就空数组。
5. payoffs：本章兑现给读者的满足感（爽点）；amplified = 写了旁观者的震惊、议论；setup 写它靠前面什么铺垫；没有就空数组。
6. threads：plant = 本章新埋下的伏笔 / 悬念 / 承诺；advance = 推进【未回收的线索】里的某条；payoff = 回收其中某条。advance 和 payoff 必须写那条线索的编号 id，plant 不写 id。只写正文明确写出的。
7. function 选一个最贴切的本章功能；emotion 写开头、高潮、结尾的情绪。
8. lead 写主角名；leadChanges 只写主角本章明确发生的变化；relations 只写本章新出现或变化的人物关系；entityMoves 写设定实体在本章的动态（首次登场、获得、使用、击败、失去、揭示新能力）。
9. lines：最多 3 句最有辨识度的人物原话，必须一字不差摘自正文。
10. 带竖线的字段只能从给定的选项里选一个；拿不准的条目就不写。所有 quote 必须是正文中连续的原文。"""

GOLDEN_RULE = "\n11. 这是全书开篇的前三章之一，额外写 golden（黄金三章深拆），anchors 摘 2 到 3 句原文。"
NODES_RULE = "\n12. nodes：3 到 6 个情节节点，按顺序覆盖全章，from / to 是正文里 [n] 的段号，区间不重叠；hot = 是爽点或钩子所在。"


def _shape(depth: str, golden: bool) -> str:
    parts = ['"entities":[{"category":"分类代码","name":"名称","aliases":[],"facts":[{"fact":"事实，不超过40字","quote":"原文摘抄"}]}]',
             '"oneLine":"本章发生了什么、起什么作用，不超过40字"',
             '"events":["关键事件，不超过30字"]']
    if depth != "fast":
        parts += [
            f'"hooks":[{{"pos":"{"|".join(HOOK_POS)}","type":"{"|".join(HOOK_TYPES)}","text":"不超过30字","strength":1到3,"quote":"原文摘抄，可空"}}]',
            f'"payoffs":[{{"type":"{"|".join(PAYOFF_TYPES)}","strength":1到3,"amplified":true或false,"setup":"靠什么铺垫，可空","quote":"原文摘抄"}}]',
            f'"threads":[{{"act":"{"|".join(THREAD_ACTS)}","id":"advance / payoff 时写线索编号","kind":"{"|".join(THREAD_KINDS)}","text":"不超过30字","quote":"原文摘抄"}}]',
            f'"function":"{"|".join(FUNCTIONS)}"',
            '"emotion":{"open":"不超过8字","peak":"不超过8字","close":"不超过8字"}',
            '"lead":"主角名"',
            f'"leadChanges":[{{"field":"{"|".join(LEAD_FIELDS)}","before":"可空","after":"不超过30字","quote":"原文摘抄"}}]',
            f'"relations":[{{"a":"人物","b":"人物","rel":"{"|".join(REL_TYPES)}","change":"{"|".join(REL_CHANGES)}","text":"不超过30字","quote":"原文摘抄"}}]',
            f'"entityMoves":[{{"name":"名称","category":"分类代码","act":"{"|".join(MOVE_ACTS)}","text":"不超过30字","quote":"原文摘抄"}}]',
            '"lines":[{"speaker":"说话人","quote":"人物原话，原样摘抄，不超过40字"}]',
        ]
        if golden:
            parts.append('"golden":{"hook300":"前300字用什么钩住读者、是否奏效，60到100字","establish":"主角人设是否立住、靠什么立住，60到100字",'
                         '"dilemma":"本章抛出的核心困境与读者期待，60到100字","anchors":[{"quote":"原文摘抄，不超过40字","comment":"这句好在哪，不超过40字"}]}')
        if depth == "deep":
            parts.append('"nodes":[{"title":"节点名，4到8字","from":起始段号,"to":结束段号,"text":"这段做了什么、为什么有效，不超过60字","hot":true或false}]')
    return "{" + ",".join(parts) + "}"


def chapter_prompt(job: dict, title: str, *, depth: str, golden: bool, cats: list[str], focus: str,
                   prev: list[str], lead: str, known: list[dict], threads: list[dict]) -> str:
    ctx = []
    if prev:
        ctx.append("【上文】\n" + "\n".join(f"- {p}" for p in prev))
    if lead and depth != "fast":
        ctx.append(f"【主角】{lead}")
    if known:
        lines = "\n".join(f"- [{k['category']}] {k['name']}（已知：{'；'.join(k['facts']) or '无'}）" for k in known)
        ctx.append(f"【已知设定】这些实体前文已经记录过，只写本章里关于它们的新事实：\n{lines}")
    if threads and depth != "fast":
        ctx.append("【未回收的线索】\n" + "\n".join(f"- {t['id']} [{t['kind']}] {t['text']}" for t in threads))
    part = f"（这是本章的第 {job['part'] + 1}/{job['parts']} 部分）" if job["parts"] > 1 else ""
    rules = ENTITY_RULES + "\n" + (CARD_RULES_FAST if depth == "fast" else CARD_RULES)
    if golden and depth != "fast":
        rules += GOLDEN_RULE
    if depth == "deep":
        rules += NODES_RULE
        body = "\n".join(f"[{i}] {job['text'][a:b]}" for i, (a, b) in enumerate(paragraph_spans(job["text"]), 1))
    else:
        body = job["text"]
    focus_line = f"\n特别关注：{focus}" if focus else ""
    return ("\n\n".join(ctx) + "\n\n" if ctx else "") + (
        f"任务：读下面这一章《{title}》{part}，找出可供其他作者借鉴的设定实体和本章的写法，按要求输出 JSON。\n"
        f"实体分类（category 只能用代码）：{mf._cat_desc(cats)}。\n要求：\n{rules}{focus_line}\n"
        f"输出（只输出这一个 JSON 对象，字段按这个顺序）：{_shape(depth, golden)}\n\n正文：\n{body}")


# ---------------------------------------------------------------- 解析与核对

def _t(v, n: int) -> str:
    return mf._text(v, n)


def _enum(v, allowed) -> str | None:
    s = str(v or "").strip()
    return s if s in allowed else None


def _strength(v) -> int:
    try:
        return max(1, min(3, int(v)))
    except (TypeError, ValueError):
        return 2


def _exact(src: "mf.Source", quote: str) -> int | None:
    """规范化后逐字出现（不接受 trigram 近似），→ 原文位置。"""
    q = mf._normalize(quote)[0]
    if len(q) < mf.QUOTE_MIN_CHARS:
        return None
    i = src.norm.find(q)
    return src.pos[i] if i >= 0 else None


def _quote(src: "mf.Source", q, offset: int, stats: dict, exact: bool = False) -> dict:
    q = _t(q, 80)
    pos = (_exact(src, q) if exact else src.locate(q)) if q else None
    if q and pos is None:
        stats["cardQuotesUnverified"] += 1
    return {"quote": q if pos is not None else "", "at": offset + pos if pos is not None else None,
            "verified": pos is not None}


def parse_entities(data: dict, src: "mf.Source", offset: int, ci: int, cats: set[str]) -> tuple[list[dict], int, int]:
    out, ok, bad = [], 0, 0
    for e in data.get("entities") or []:
        if not isinstance(e, dict):
            continue
        cat, name = str(e.get("category") or "").strip(), str(e.get("name") or "").strip()[:40]
        if cat not in cats or not name:
            continue
        facts, unverified = [], []
        for f in e.get("facts") or []:
            if not isinstance(f, dict):
                continue
            fact, quote = str(f.get("fact") or "").strip()[:80], str(f.get("quote") or "").strip()[:80]
            if not fact:
                continue
            pos = src.locate(quote)
            if pos is None:
                bad += 1
                if len(unverified) < MAX_UNVERIFIED:
                    unverified.append({"fact": fact, "quote": quote, "chapter": ci})
                continue
            ok += 1
            facts.append({"fact": fact, "quote": quote, "chapter": ci, "at": offset + pos})
        aliases = [str(a).strip()[:40] for a in e.get("aliases") or [] if str(a).strip()][:5]
        if facts or unverified:
            out.append({"category": cat, "name": name, "aliases": aliases, "facts": facts, "unverified": unverified})
    return out, ok, bad


def parse_card(data: dict, src: "mf.Source", job: dict, depth: str, golden: bool, open_ids: set[str],
               stats: dict) -> tuple[dict, list[dict]]:
    """→ (章节卡, 伏笔操作)。quote 位置换算成本章内偏移。"""
    off = job["offset"]
    card = {"oneLine": _t(data.get("oneLine"), 120),
            "events": [_t(e, 60) for e in data.get("events") or [] if _t(e, 60)][:8]}
    ops: list[dict] = []
    if depth == "fast":
        return card, ops

    def items(key):
        return [x for x in data.get(key) or [] if isinstance(x, dict)]

    hooks = []
    for h in items("hooks"):
        pos, typ = _enum(h.get("pos"), HOOK_POS), _enum(h.get("type"), HOOK_TYPES)
        if pos and typ:
            hooks.append({"pos": pos, "type": typ, "text": _t(h.get("text"), 60), "strength": _strength(h.get("strength")),
                          **_quote(src, h.get("quote"), off, stats)})
    card["hooks"] = hooks[:6]
    pays = []
    for p in items("payoffs"):
        typ = _enum(p.get("type"), PAYOFF_TYPES)
        if typ:
            pays.append({"type": typ, "strength": _strength(p.get("strength")), "amplified": p.get("amplified") is True,
                         "setup": _t(p.get("setup"), 60), **_quote(src, p.get("quote"), off, stats)})
    card["payoffs"] = pays[:6]
    for t in items("threads"):
        act = _enum(t.get("act"), THREAD_ACTS)
        text = _t(t.get("text"), 60)
        if not act or not text:
            continue
        tid = str(t.get("id") or "").strip().upper()
        ops.append({"op": act, "id": tid if act != "plant" and tid in open_ids else None,
                    "kind": _enum(t.get("kind"), THREAD_KINDS) or "伏笔", "text": text,
                    **_quote(src, t.get("quote"), off, stats)})
    ops = ops[:8]
    card["function"] = _enum(data.get("function"), FUNCTIONS) or ""
    emo = data.get("emotion") if isinstance(data.get("emotion"), dict) else {}
    card["emotion"] = {k: _t(emo.get(k), 16) for k in ("open", "peak", "close")}
    card["lead"] = _t(data.get("lead"), 20)
    card["leadChanges"] = [{"field": f, "before": _t(c.get("before"), 60), "after": _t(c.get("after"), 60),
                            **_quote(src, c.get("quote"), off, stats)}
                           for c in items("leadChanges") if (f := _enum(c.get("field"), LEAD_FIELDS)) and _t(c.get("after"), 60)][:6]
    card["relations"] = [{"a": _t(r.get("a"), 20), "b": _t(r.get("b"), 20), "rel": _enum(r.get("rel"), REL_TYPES) or "其他",
                          "change": _enum(r.get("change"), REL_CHANGES) or "新建", "text": _t(r.get("text"), 60),
                          **_quote(src, r.get("quote"), off, stats)}
                         for r in items("relations") if _t(r.get("a"), 20) and _t(r.get("b"), 20)][:8]
    card["entityMoves"] = [{"name": _t(m.get("name"), 40), "category": m.get("category") if m.get("category") in CATEGORIES else "",
                            "act": a, "text": _t(m.get("text"), 60), **_quote(src, m.get("quote"), off, stats)}
                           for m in items("entityMoves") if (a := _enum(m.get("act"), MOVE_ACTS)) and _t(m.get("name"), 40)][:10]
    lines = []
    for ln in items("lines"):
        q = _quote(src, ln.get("quote"), off, stats, exact=True)
        if q["verified"]:
            lines.append({"speaker": _t(ln.get("speaker"), 20), "quote": q["quote"], "at": q["at"]})
    card["lines"] = lines[:MAX_LINES]
    g = data.get("golden") if golden and isinstance(data.get("golden"), dict) else None
    if g:
        card["golden"] = {"hook300": _t(g.get("hook300"), 200), "establish": _t(g.get("establish"), 200),
                          "dilemma": _t(g.get("dilemma"), 200),
                          "anchors": [{"comment": _t(a.get("comment"), 80), **_quote(src, a.get("quote"), off, stats)}
                                      for a in g.get("anchors") or [] if isinstance(a, dict)][:3]}
    if depth == "deep":
        card["nodes"] = _nodes(items("nodes"), job)
    return card, ops


def _nodes(raw: list[dict], job: dict) -> list[dict]:
    spans = paragraph_spans(job["text"])
    if not spans:
        return []
    rows = []
    for n in raw:
        try:
            a, b = int(n.get("from")), int(n.get("to"))
        except (TypeError, ValueError):
            continue
        a, b = max(1, min(a, len(spans))), max(1, min(b, len(spans)))
        rows.append((min(a, b), max(a, b), n))
    rows.sort(key=lambda r: r[0])
    out, last = [], 0
    for a, b, n in rows:
        a = max(a, last + 1)
        if a > b or not _t(n.get("title"), 20):
            continue
        out.append({"title": _t(n.get("title"), 20), "text": _t(n.get("text"), 120), "hot": n.get("hot") is True,
                    "start": job["offset"] + spans[a - 1][0], "end": job["offset"] + spans[b - 1][1]})
        last = b
    return out[:8]


def merge_parts(cards: list[dict]) -> dict:
    """超长章各份的章节卡 → 一章（docs §3.4）。"""
    if len(cards) == 1:
        return cards[0]
    first, last = cards[0], cards[-1]
    out = {"oneLine": "；".join(c["oneLine"] for c in cards if c.get("oneLine"))[:160]}
    events = [c.get("events") or [] for c in cards]
    picked = [e[0] for e in events if e] + [x for e in events for x in e[1:]]
    out["events"] = picked[:8]
    if "hooks" not in first:
        return out
    out["hooks"] = ([h for h in first.get("hooks") or [] if h["pos"] == "open"]
                    + [h for c in cards for h in c.get("hooks") or [] if h["pos"] == "mid"][:3]
                    + [h for h in last.get("hooks") or [] if h["pos"] == "end"])
    for k in ("payoffs", "leadChanges", "relations", "entityMoves", "lines", "nodes"):
        if any(k in c for c in cards):
            out[k] = [x for c in cards for x in c.get(k) or []]
    out["lines"] = out.get("lines", [])[:MAX_LINES]
    peak = max(cards, key=lambda c: max((p["strength"] for p in c.get("payoffs") or []), default=0))
    out["function"] = peak.get("function") or first.get("function") or ""
    out["emotion"] = {"open": (first.get("emotion") or {}).get("open", ""),
                      "peak": (peak.get("emotion") or {}).get("peak", ""),
                      "close": (last.get("emotion") or {}).get("close", "")}
    out["lead"] = next((c["lead"] for c in cards if c.get("lead")), "")
    if first.get("golden"):
        out["golden"] = first["golden"]
    return out


# ---------------------------------------------------------------- 代码统计

def chapter_stats(content: str) -> dict:
    from .extractor import dialog_ratio  # 延迟导入：extractor 依赖本模块

    paras = [p for p in content.split("\n") if p.strip()]
    chars = len(re.sub(r"\s", "", content))
    return {"chars": chars, "paragraphs": len(paras), "avgParagraph": round(chars / len(paras), 1) if paras else 0,
            "dialogRatio": dialog_ratio(content)}


def appearances(chapters: list[dict], entities: list[dict]) -> list[list[dict]]:
    """每章出现了哪些已知实体（名字 / 别名在原文出现，≥2 字），一个正则扫一遍。"""
    names: dict[str, dict] = {}
    for e in entities:
        for n in [e["name"], *e.get("aliases", [])]:
            if len(n) >= 2 and n not in names:
                names[n] = e
    if not names:
        return [[] for _ in chapters]
    pattern = re.compile("|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)))
    out = []
    for ch in chapters:
        seen: dict[str, dict] = {}
        for m in pattern.finditer(ch["content"]):
            e = names[m.group(0)]
            seen.setdefault(e["key"], {"key": e["key"], "category": e["category"], "name": e["name"]})
        out.append(list(seen.values())[:40])
    return out


# ---------------------------------------------------------------- 主流程

def golden_of(chapters: list[dict]) -> set[int]:
    """全书开篇的前 3 个正文章（kind = chapter）；没有就是前 3 个。"""
    cis = sorted(ci for ci, ch in enumerate(chapters) if ch.get("kind", "chapter") == "chapter")
    return set(cis[:GOLDEN_CHAPTERS]) if cis else set(range(min(GOLDEN_CHAPTERS, len(chapters))))


def scan(chapters: list[dict], opts: MaterialOptions, call: Callable[[list[dict], int], str], ckpt,
         on_progress: Callable[[int, str], None], stop: threading.Event | None, *, local: bool, max_chars: int,
         golden: set[int] | None = None) -> dict:
    """读原文 → {chapters: [{summary, characters}], entities, chapterCards, threads, lead, stats}。
    golden = 要做黄金三章深拆的章序号（None = 按 chapters 自己的前 3 个正文章；只读一段范围时由调用方按全书算）。"""
    depth = opts.depth if opts.depth in DEPTHS else "standard"
    cats = [c for c in opts.active_categories() if c != "plot"]
    jobs = chapter_jobs(chapters, max_chars)
    golden_cis = golden if golden is not None else golden_of(chapters)
    tokens = TOKENS[depth][1 if local else 0]
    stats = {"rounds": opts.rounds, "depth": depth, "chunks": len(jobs), "chapters": len(chapters), "failedChunks": 0,
             "factsVerified": 0, "factsUnverified": 0, "entities": 0, "cards": 0, "cardsFailed": 0,
             "cardQuotesUnverified": 0, "threadLinks": 0}
    book, threads, lead = mf.Book(), Threads(), Lead()
    prev: list[str] = []
    part_cards: dict[int, dict[int, dict]] = {}
    failed: dict[int, str] = {}
    span = 98 if opts.rounds == 1 else 70
    done = ckpt.done("pass1")

    def read(job: dict) -> dict:
        if stop and stop.is_set():
            raise mf.Cancelled("已取消")
        title = chapters[job["ci"]]["title"]
        golden = job["ci"] in golden_cis and job["part"] == 0
        ctx_threads = threads.context(job["text"])
        prompt = chapter_prompt(job, title, depth=depth, golden=golden, cats=cats, focus=opts.focus.strip(),
                                prev=prev[-PREV_LINES:], lead=lead.line(), known=book.known_in(job["text"]),
                                threads=ctx_threads)
        try:
            data = mf._parse(call([{"role": "system", "content": mf.SYSTEM}, {"role": "user", "content": prompt}], tokens))
        except LLMError as e:
            if e.fatal or (stop and stop.is_set()):
                raise
            return {"ci": job["ci"], "part": job["part"], "failed": True, "error": str(e)[:200]}
        src = mf.Source(job["text"])
        local_stats = {"cardQuotesUnverified": 0}
        ents, ok, bad = parse_entities(data, src, job["offset"], job["ci"], set(cats))
        card, ops = parse_card(data, src, job, depth, golden, {t["id"] for t in ctx_threads}, local_stats)
        threads.assign(ops)
        return {"ci": job["ci"], "part": job["part"], "entities": ents, "card": card, "ops": ops, "ok": ok, "bad": bad,
                "cardQuotesUnverified": local_stats["cardQuotesUnverified"]}

    def apply(row: dict) -> None:
        ci = row["ci"]
        if row.get("failed"):
            failed[ci] = row.get("error") or "提取失败"
            return
        failed.pop(ci, None)
        book.add(row["entities"])
        threads.apply(ci, row.get("ops") or [])
        lead.update(row["card"])
        part_cards.setdefault(ci, {})[row["part"]] = row["card"]
        if row["card"].get("oneLine"):
            prev.append(row["card"]["oneLine"])

    streak = 0
    for n, job in enumerate(jobs, 1):
        row = done.get(job["key"])
        if row is None:
            ckpt.reading(job["ci"])
            row = read(job)
            ckpt.append("pass1", job["key"], row)
            streak = streak + 1 if row.get("failed") else 0
            if streak >= MAX_FAIL_STREAK:
                raise LLMError(f"连续 {streak} 章提取失败，已暂停（最近一次：{row.get('error')}），可以稍后继续")
        apply(row)
        title = chapters[job["ci"]]["title"]
        part = f"（{job['part'] + 1}/{job['parts']}）" if job["parts"] > 1 else ""
        on_progress(int(span * n / max(1, len(jobs))), f"逐章读：第 {n}/{len(jobs)} 份《{title}》{part}")

    # 失败的章整本读完后再试一次（滚动上下文就是此刻的状态）；再失败的标 retried，续跑时不再重试
    for job in jobs:
        row = done.get(job["key"]) or {}
        if row.get("failed") and not row.get("retried"):
            ckpt.reading(job["ci"])
            row = read(job)
            if row.get("failed"):
                row["retried"] = True
            ckpt.append("pass1", job["key"], row)
            apply(row)

    ckpt.reading(None)
    if opts.rounds == 2:
        done2 = ckpt.done("pass2")
        for n, job in enumerate(jobs, 1):
            if job["key"] not in done2:
                if stop and stop.is_set():
                    raise mf.Cancelled("已取消")
                title = chapters[job["ci"]]["title"]
                text = f"【{title}】\n" + job["text"]
                try:
                    data = mf._parse(call([{"role": "system", "content": mf.SYSTEM},
                                           {"role": "user", "content": mf.scan_prompt(text, cats, opts.focus.strip(),
                                                                                      book.known_in(job["text"]))}],
                                          SUPPLEMENT_TOKENS[1 if local else 0]))
                    src = mf.Source(job["text"])
                    ents, ok, bad = parse_entities(data, src, job["offset"], job["ci"], set(cats))
                    ckpt.append("pass2", job["key"], {"entities": ents, "ok": ok, "bad": bad})
                except LLMError as e:
                    if e.fatal or (stop and stop.is_set()):
                        raise
                    ckpt.append("pass2", job["key"], {"failed": True, "error": str(e)[:200]})
            row2 = done2.get(job["key"]) or {}
            if not row2.get("failed"):
                book.add(row2.get("entities") or [])
            on_progress(70 + int(28 * n / max(1, len(jobs))), f"第2遍补漏：{n}/{len(jobs)}")

    for stage in ("pass1", "pass2"):
        for row in ckpt.done(stage).values():
            if row.get("failed"):
                stats["failedChunks"] += 1
                continue
            stats["factsVerified"] += row.get("ok", 0)
            stats["factsUnverified"] += row.get("bad", 0)
            stats["cardQuotesUnverified"] += row.get("cardQuotesUnverified", 0)
            stats["threadLinks"] += sum(1 for op in row.get("ops") or [] if op["op"] != "plant" and op.get("id"))

    # ---- 输出
    entities = []
    for ent in sorted(book.entities.values(), key=lambda e: -len(e["facts"])):
        if not ent["facts"]:
            continue  # 只有未核实事实的实体不进档案
        entities.append({"key": ent["key"], "category": ent["category"], "name": ent["name"], "aliases": ent["aliases"],
                         "facts": [{"fact": f["fact"], "quote": f["quote"], "chapter": chapters[f["chapter"]]["title"],
                                    "ci": f["chapter"], "at": f.get("at")} for f in ent["facts"]],
                         "unverified": [{"fact": u["fact"], "quote": u["quote"], "chapter": chapters[u["chapter"]]["title"],
                                         "ci": u["chapter"]} for u in ent.get("unverified", [])]})
    stats["entities"] = len(entities)
    seen_at = appearances(chapters, entities)
    first_ci = {e["key"]: min(f["ci"] for f in e["facts"]) for e in entities}
    cards, out_chapters = [], []
    for ci, ch in enumerate(chapters):
        parts = part_cards.get(ci)
        card = merge_parts([parts[k] for k in sorted(parts)]) if parts else {}
        status = "done" if parts else ("failed" if ci in failed else "empty")
        if parts and not card.get("oneLine"):
            stats["cardsFailed"] += 1
        elif parts:
            stats["cards"] += 1
        row = {"ci": ci, "title": ch["title"], "kind": ch.get("kind", "chapter"), "status": status, **card,
               "stats": {**chapter_stats(ch["content"]), "appear": seen_at[ci],
                         "newEntities": sum(1 for v in first_ci.values() if v == ci)}}
        if ci in failed:
            row["error"] = failed[ci]
        cards.append(row)
        summary = "；".join([card["oneLine"], *card.get("events", [])[:3]] if card.get("oneLine") else card.get("events", [])[:3])
        out_chapters.append({"summary": summary[:200],
                             "characters": [a["name"] for a in seen_at[ci] if a["category"] == "character"][:20]})
    return {"chapters": out_chapters, "entities": entities, "chapterCards": cards, "threads": threads.items,
            "lead": {"name": lead.name, "state": lead.state}, "stats": stats}


# ---------------------------------------------------------------- 逐章查看（提取中读断点）

def live(key: str, since: int = 0) -> dict:
    """断点 → 逐章查看的增量数据（docs/素材提取改造方案.md §E）。
    since = 上次拿到的 pass1 行数；返回这之后有变化的章（整章重算：超长章的几份合成一张卡）。
    → {exists, range, chapters (since=0 时才带：[{ci, index, title, kind, chars, parts}]), rows: [{ci, status done|failed|partial,
       card, entities, threadOps, error}], next, current}"""
    from . import extract_checkpoint as ec

    meta = ec.load_json(key, "chapters")
    if not meta:
        return {"exists": False, "rows": [], "next": 0, "current": None}
    lines = ec.read_lines(key, "pass1")
    since = max(0, min(since, len(lines)))
    touched = sorted({row.get("ci") for _, row in lines[since:] if isinstance(row, dict) and "ci" in row})
    latest: dict[str, dict] = {}
    for k, row in lines:
        if isinstance(row, dict):
            latest[k] = row
    parts_of = {c["ci"]: c.get("parts", 1) for c in meta.get("chapters") or []}
    out_rows = []
    for ci in touched:
        rows = sorted((r for r in latest.values() if r.get("ci") == ci), key=lambda r: r.get("part", 0))
        ok_rows = [r for r in rows if not r.get("failed")]
        bad = [r for r in rows if r.get("failed")]
        status = "failed" if bad else "done" if len(ok_rows) >= parts_of.get(ci, 1) else "partial"
        ents: dict[tuple[str, str], dict] = {}
        for r in ok_rows:
            for e in r.get("entities") or []:
                cur = ents.setdefault((e["category"], e["name"]), {"category": e["category"], "name": e["name"],
                                                                  "facts": [], "unverified": []})
                cur["facts"] += [{"fact": f["fact"], "quote": f["quote"], "at": f.get("at")} for f in e.get("facts") or []]
                cur["unverified"] += [{"fact": f["fact"], "quote": f["quote"]} for f in e.get("unverified") or []]
        out_rows.append({"ci": ci, "status": status,
                         "card": merge_parts([r["card"] for r in ok_rows]) if ok_rows else {},
                         "entities": list(ents.values()),
                         "threadOps": [op for r in ok_rows for op in r.get("ops") or []],
                         "error": bad[-1].get("error", "") if bad else ""})
    out = {"exists": True, "range": meta.get("range"), "rows": out_rows, "next": len(lines),
           "current": ec.READING.get(key)}
    if since == 0:
        out["chapters"] = meta.get("chapters") or []
    return out


def fingerprint(opts: MaterialOptions, max_chars: int) -> dict:
    """断点指纹里和逐章提取有关的部分（extractor 再加上文件 / 章数等）。"""
    # 不含 toChapter：同一起点只是读得更远时，已读的章可以接着用（以后「接着读到第 N 章」）
    return {"mode": "serial-v1", "cardsV": CARDS_VERSION, "depth": opts.depth, "maxChapterChars": max_chars,
            "rounds": opts.rounds, "categories": sorted(opts.active_categories()), "focus": opts.focus.strip(),
            "fromChapter": opts.fromChapter}


__all__ = ["scan", "chapter_jobs", "fingerprint", "live", "DEPTHS", "API_MAX_CHARS"]
