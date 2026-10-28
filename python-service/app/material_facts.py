"""素材流程的前两步（分步进行，每步结果都可以先看、可以单独重做）：

① 提取 ``scan``（读原文）：每块（默认 3000 字，短章节合并成一块）列出设定实体和本块里关于它的**具体事实**，
   每条事实附原文摘抄 quote，由代码核对原文（对不上的丢弃 —— 不靠模型自查，专治小模型脑补）。
   rounds=2 时每块再读一遍：提示里给出本块出现过的已知实体（名字是否出现由代码判断），只补新事实和漏掉的实体。
   代码聚合（不用模型）：按 分类 + 规范化名称 / 别名归并实体，事实按字符重合去重。产出实体档案 + 章节摘要。
② 整理卡片 ``compile_cards``（只读实体档案和章节摘要，输入短，可换模型 / 换范围重做）：事实多的实体逐个整理，
   只有 1 条事实的 5 个一批；不实用的（只有空泛情绪 / 一次性动作）标 useful=false 不进候选箱。
   同一本书里同类世界观 ≥3 张再合成「体系卡」。剧情段：章节摘要每 20 章一窗，找跨章的完整剧情段，
   抽象成骨架（起因 / 冲突 / 转折 / 结果 / 功能），不留原作专有名词。

模型调用由调用方传入 ``call(messages, max_tokens) -> str``（大模型 / GGUF / 应用内本地模型共用），
断点由 ``extract_checkpoint.Checkpoint`` 记录，已完成的块 / 卡片在续跑时跳过。
"""
import hashlib
import json
import logging
import re
import threading
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from typing import Callable

from . import local_extract, text_loader
from .llm_client import LLMError
from .materials import CATEGORIES, MaterialOptions, _norm_title

log = logging.getLogger(__name__)

SYSTEM = "你是小说设定整理助手，只输出 JSON，不要任何多余文字。"
MERGE_CHAPTER_CHARS = 1500    # 短于这个字数的章节和相邻章节合成一块
MAX_KNOWN = 15                # 第二遍提示里最多列出几个已知实体
MAX_FACTS = 40                # 每个实体最多保留 / 交给模型的事实数
SINGLE_BATCH = 5              # 只有 1 条事实的实体，几个一批整理
ARC_WINDOW, ARC_STEP = 20, 17  # 剧情段：每窗 20 章，相邻窗口重叠 3 章
SYSTEM_MIN = 3                # 同一 subtype 的世界观卡 ≥ 3 张才合成体系卡
QUOTE_MIN_CHARS = 4
QUOTE_GRAM_RATIO = 0.6
FACT_DUP_RATIO = 0.6

_NOISE = re.compile(r"[\s\W_]+", re.UNICODE)
# 模型常把没有依据的属性写成这些空话：直接丢掉
_EMPTY_VALUE = re.compile(r"^(无|暂无|没有|不详|未知|未提及|未说明|无明确(信息|说明|记载)?|原文未提及|无相关信息)([。.，,；;].*)?$")

Call = Callable[[list[dict], int], str]


class Cancelled(RuntimeError):
    pass


# ---------------------------------------------------------------- 分块

def build_blocks(chapters: list[dict], limit: int) -> list[dict]:
    """→ [{text, spans: [(块内起点, 章节下标)]}]。长章节按段落切；相邻短章节合成一块（每章前加【标题】）。"""
    blocks: list[dict] = []
    cur: dict | None = None
    for ci, ch in enumerate(chapters):
        content = ch["content"].strip()
        if not content:
            continue
        head = f"【{ch['title']}】\n"
        if len(content) >= MERGE_CHAPTER_CHARS:
            if cur:
                blocks.append(cur)
                cur = None
            for part in text_loader.split_chunks(content, limit):
                blocks.append({"text": head + part, "spans": [(0, ci)]})
            continue
        piece = head + content
        if cur and len(cur["text"]) + len(piece) + 1 > limit:
            blocks.append(cur)
            cur = None
        if cur is None:
            cur = {"text": piece, "spans": [(0, ci)]}
        else:
            cur["spans"].append((len(cur["text"]) + 1, ci))
            cur["text"] += "\n" + piece
    if cur:
        blocks.append(cur)
    return blocks


def _chapter_at(block: dict, pos: int) -> int:
    ci = block["spans"][0][1]
    for start, idx in block["spans"]:
        if start <= pos:
            ci = idx
    return ci


# ---------------------------------------------------------------- 原文核对

def _normalize(text: str) -> tuple[str, list[int]]:
    """去掉空白和标点，返回 (规范化文本, 每个字符在原文中的位置)。"""
    chars, pos = [], []
    for i, ch in enumerate(text):
        if not _NOISE.fullmatch(ch):
            chars.append(ch.lower())
            pos.append(i)
    return "".join(chars), pos


def _grams(s: str, n: int = 3) -> set[str]:
    return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else {s} if s else set()


class Source:
    """一块原文：核对 quote 是否真的出自这里，并给出它在块内的位置（用来定位章节）。"""

    def __init__(self, text: str):
        self.text = text
        self.norm, self.pos = _normalize(text)
        self.grams: dict[str, int] = {}
        for i in range(len(self.norm) - 2):
            self.grams.setdefault(self.norm[i:i + 3], i)

    def locate(self, quote: str) -> int | None:
        q, _ = _normalize(quote or "")
        if len(q) < QUOTE_MIN_CHARS:
            return None
        i = self.norm.find(q)
        if i >= 0:
            return self.pos[i]
        grams = _grams(q)
        hits = [self.grams[g] for g in grams if g in self.grams]
        if grams and len(hits) / len(grams) >= QUOTE_GRAM_RATIO:
            return self.pos[min(hits)]
        return None


def _similar(a: str, b: str) -> bool:
    ga, gb = _grams(_normalize(a)[0], 2), _grams(_normalize(b)[0], 2)
    if not ga or not gb:
        return False
    return len(ga & gb) / min(len(ga), len(gb)) >= FACT_DUP_RATIO


# ---------------------------------------------------------------- 第一遍：事实扫描

def _cat_desc(cats: list[str]) -> str:
    desc = {"world": "世界观规则 / 力量体系 / 位面规则 / 修炼境界", "faction": "势力组织", "character": "有特点的角色",
            "monster": "怪物 / 种族 / 魔物", "location": "地点", "item": "物品 / 功法 / 技能 / 魔法"}
    return "；".join(f"{c}={desc[c]}" for c in cats if c in desc)


SCAN_RULES = """要求：
1. 只记录原文明确写出的内容，不推测、不评价；每条事实要具体（外形、能力、弱点、规则、代价、习性、来历、限制等），能直接用于写作。
2. 每条事实附 quote：原文中能证明它的一小段，原样摘抄，不超过 30 字。
3. 普通路人、一次性的动作描写、纯情绪不要记录；没有就输出空数组。
4. name 用原文中的称呼，有别称写进 aliases。"""


def scan_prompt(text: str, cats: list[str], focus: str, known: list[dict] | None) -> str:
    out = '输出：{"summary":"本段剧情摘要，不超过80字","entities":[{"category":"分类代码","name":"名称","aliases":[],' \
          '"facts":[{"fact":"事实，不超过40字","quote":"原文摘抄"}]}]}'
    focus_line = f"\n特别关注：{focus}" if focus else ""
    if known:
        lines = "\n".join(f"- [{k['category']}] {k['name']}（已知：{'；'.join(k['facts']) or '无'}）" for k in known)
        task = (f"下面这些实体在前文已经记录过，它们在本片段里也出现了：\n{lines}\n"
                "任务：1. 补充这些实体在本片段中**新的**具体事实（已知的不要重复）；2. 找出其他还没记录的实体。")
    else:
        task = "从下面的小说片段里，找出可供其他作者借鉴的设定实体，并记录片段中关于它们的具体事实。"
    return (f"{task}\n实体分类（category 只能用代码）：{_cat_desc(cats)}。\n{SCAN_RULES}{focus_line}\n{out}\n\n"
            f"正文：\n{text}")


def parse_scan(data: dict, block: dict, source: Source, cats: set[str]) -> tuple[list[dict], int, int]:
    """核对模型给出的事实 → ([{category, name, aliases, facts: [{fact, quote, chapter}]}], 通过数, 丢弃数)"""
    out, ok, bad = [], 0, 0
    for e in data.get("entities") or []:
        if not isinstance(e, dict):
            continue
        cat, name = str(e.get("category") or "").strip(), str(e.get("name") or "").strip()[:40]
        if cat not in cats or not name:
            continue
        facts = []
        for f in e.get("facts") or []:
            if not isinstance(f, dict):
                continue
            fact, quote = str(f.get("fact") or "").strip()[:80], str(f.get("quote") or "").strip()[:80]
            pos = source.locate(quote) if fact else None
            if pos is None:
                bad += 1 if fact else 0
                continue
            ok += 1
            facts.append({"fact": fact, "quote": quote, "chapter": _chapter_at(block, pos)})
        aliases = [str(a).strip()[:40] for a in e.get("aliases") or [] if str(a).strip()][:5]
        if facts:
            out.append({"category": cat, "name": name, "aliases": aliases, "facts": facts})
    return out, ok, bad


# ---------------------------------------------------------------- 聚合（代码）

class Book:
    """全书的实体档案：分类 + 规范化名称 / 别名归并，事实去重。"""

    def __init__(self):
        self.entities: dict[str, dict] = {}
        self.index: dict[str, str] = {}   # "分类:规范化名称或别名" → 实体键

    def add(self, items: list[dict]) -> None:
        for e in items:
            cat = e["category"]
            names = [e["name"], *e.get("aliases", [])]
            key = next((self.index[f"{cat}:{_norm_title(n)}"] for n in names if f"{cat}:{_norm_title(n)}" in self.index), None)
            if key is None:
                key = f"{cat}:{_norm_title(e['name'])}"
                self.entities[key] = {"key": key, "category": cat, "name": e["name"], "aliases": [], "facts": []}
            ent = self.entities[key]
            for n in names:
                nk = f"{cat}:{_norm_title(n)}"
                if _norm_title(n) and nk not in self.index:
                    self.index[nk] = key
                if n != ent["name"] and n not in ent["aliases"] and len(ent["aliases"]) < 8:
                    ent["aliases"].append(n)
            for f in e["facts"]:
                if len(ent["facts"]) < MAX_FACTS * 2 and not any(_similar(f["fact"], g["fact"]) for g in ent["facts"]):
                    ent["facts"].append(f)

    def known_in(self, text: str) -> list[dict]:
        """本块原文里出现过名字 / 别名的已知实体（事实多的优先），供第二遍提示。"""
        found = []
        for ent in self.entities.values():
            if any(len(n) >= 2 and n in text for n in [ent["name"], *ent["aliases"]]):
                found.append(ent)
        found.sort(key=lambda x: -len(x["facts"]))
        return [{"category": e["category"], "name": e["name"], "facts": [f["fact"][:20] for f in e["facts"][:4]]}
                for e in found[:MAX_KNOWN]]


# ---------------------------------------------------------------- 成卡片

CARD_FIELDS = ('"useful":true,"title":"名称","subtype":"细分类型","summary":"一句话说清它是什么，不超过60字",'
               '"detail":"完整描述，100~300字，保留具体细节","attributes":{"属性名":"值"},'
               '"usage":"原作者怎么用它制造冲突或推动剧情，不超过80字","borrowTip":"借到别的小说时哪些可直接用、哪些要改，不超过60字",'
               '"tags":["3~6个标签"]')

CARD_RULES = """要求：只依据给出的事实，不编造、不补充原因或来历；没有依据的属性直接省略（不要写「无」「未提及」）。
useful：有没有具体、可借鉴的信息（外形 / 能力 / 规则 / 代价 / 习性等）；只有空泛情绪或一次性动作的写 false。"""


def _facts_text(ent: dict) -> str:
    return "\n".join(f"{i}. {f['fact']}" for i, f in enumerate(ent["facts"][:MAX_FACTS], 1))


def card_prompt(ent: dict) -> str:
    label, attrs = CATEGORIES[ent["category"]]
    alias = f"（又称 {'、'.join(ent['aliases'])}）" if ent["aliases"] else ""
    return (f"下面是小说中「{ent['name']}」{alias}（{label}）的已知事实，都来自原文：\n{_facts_text(ent)}\n\n"
            f"把它整理成一张创作素材卡，供其他作者借鉴。属性按这些填写：{'、'.join(attrs)}。\n{CARD_RULES}\n"
            f"输出：{{{CARD_FIELDS}}}")


def batch_prompt(ents: list[dict]) -> str:
    label = CATEGORIES[ents[0]["category"]][0]
    attrs = CATEGORIES[ents[0]["category"]][1]
    lines = "\n".join(f"- {e['name']}：{'；'.join(f['fact'] for f in e['facts'])}" for e in ents)
    return (f"下面是小说中几个{label}的已知事实，都来自原文：\n{lines}\n\n"
            f"把每个整理成一张创作素材卡（detail 可以短一些，50~150 字）。属性按这些填写：{'、'.join(attrs)}。\n{CARD_RULES}\n"
            f'输出：{{"cards":[{{"name":"上面的名称",{CARD_FIELDS}}}]}}')


def system_prompt(cards: list[dict], subtype: str) -> str:
    lines = "\n".join(f"- {c['title']}：{c['summary']}" + ("；" + "；".join(f"{k}：{v}" for k, v in c["attributes"].items())
                                                          if c["attributes"] else "") for c in cards[:25])
    return (f"下面是同一部小说里属于「{subtype}」的若干世界观设定：\n{lines}\n\n"
            "把它们整理成一张完整的体系卡：这个体系由哪些部分组成、各部分的关系（层级 / 顺序 / 克制）、规则、代价和限制。\n"
            f"属性按这些填写：组成、层级与顺序、核心规则、代价、限制。只依据给出的内容。\n输出：{{{CARD_FIELDS}}}")


def _text(v, limit: int) -> str:
    if isinstance(v, list):
        v = "、".join(map(str, v))
    return str(v or "").strip()[:limit]


def to_candidate(data: dict, ent: dict, chapters: list[dict]) -> dict | None:
    """模型给的卡片 + 实体档案 → 候选（与 v1 同结构，另带 detail / facts）；useful=false 返回 None。"""
    if not isinstance(data, dict) or data.get("useful") is False:
        return None
    title = _text(data.get("title"), 100) or ent["name"]
    attrs = {}
    for k, v in (data.get("attributes") or {}).items() if isinstance(data.get("attributes"), dict) else []:
        k, v = str(k).strip()[:20], _text(v, 300)
        if k and v and not _EMPTY_VALUE.match(v):
            attrs[k] = v
    for k, field in (("作者用法", "usage"), ("借用提示", "borrowTip")):
        if _text(data.get(field), 200):
            attrs[k] = _text(data.get(field), 200)
    chap_ids = sorted({f["chapter"] for f in ent["facts"]})
    return {
        "candidateId": hashlib.sha1(ent["key"].encode()).hexdigest()[:12],
        "category": ent["category"], "subtype": _text(data.get("subtype"), 32), "title": title,
        "summary": _text(data.get("summary"), 300), "detail": _text(data.get("detail"), 2000), "attributes": attrs,
        "tags": [_text(t, 20) for t in data.get("tags") or [] if _text(t, 20)][:8] if isinstance(data.get("tags"), list) else [],
        "excerpt": ent["facts"][0]["quote"] if ent["facts"] else "",
        "chapters": [chapters[i]["title"] for i in chap_ids][:50],
        "facts": [{"fact": f["fact"], "quote": f["quote"], "chapter": chapters[f["chapter"]]["title"]}
                  for f in ent["facts"][:MAX_FACTS]],
        "aliases": ent["aliases"],
    }


# ---------------------------------------------------------------- 剧情段

def arc_prompt(rows: list[tuple[int, dict]]) -> str:
    lines = "\n".join(f"[{i + 1}] {ch['title']}：{ch['summary']}" for i, ch in rows)
    return (f"下面是一部小说若干章的章节摘要（方括号里是章号）：\n{lines}\n\n"
            "找出其中完整的、值得借鉴的剧情段（跨若干章、有起因有结果的一段故事；1~3 个，没有完整的就少给或给空数组）。\n"
            "把它抽象成剧情骨架：人物用「主角 / 对手 / 盟友 / 甲 / 乙」等角色代称，不写原作的人名、地名和专有名词。\n"
            '输出：{"arcs":[{"title":"剧情段名称，不超过12字","start":起始章号,"end":结束章号,'
            '"function":"开局 / 打脸 / 升级 / 反转 / 救场 / 揭秘 / 其他","cause":"起因","conflict":"冲突","turn":"转折",'
            '"result":"结果","borrowTip":"借鉴要点，不超过60字","tags":["2~5个标签"]}]}')


def arc_candidates(data: dict, chapters: list[dict]) -> list[dict]:
    out = []
    for a in data.get("arcs") or []:
        if not isinstance(a, dict) or not _text(a.get("title"), 40) or not _text(a.get("conflict"), 10):
            continue
        try:
            start, end = int(a.get("start")), int(a.get("end"))
        except (TypeError, ValueError):
            start = end = 0
        start, end = max(1, min(start, len(chapters))), max(1, min(max(start, end), len(chapters)))
        attrs = {k: _text(a.get(f), 300) for k, f in (("起因", "cause"), ("冲突", "conflict"), ("转折", "turn"),
                                                      ("结果", "result"), ("功能", "function"), ("借用提示", "borrowTip"))
                 if _text(a.get(f), 300)}
        title = _text(a.get("title"), 40)
        out.append({
            "candidateId": hashlib.sha1(f"plot:{_norm_title(title)}:{start}".encode()).hexdigest()[:12],
            "category": "plot", "subtype": _text(a.get("function"), 32), "title": title,
            "summary": _text(f"{attrs.get('冲突', '')}；{attrs.get('转折', '')}".strip("；"), 300),
            "detail": "；".join(f"{k}：{v}" for k, v in attrs.items() if k != "借用提示")[:2000],
            "attributes": attrs,
            "tags": [_text(t, 20) for t in a.get("tags") or [] if _text(t, 20)][:8] if isinstance(a.get("tags"), list) else [],
            "excerpt": "", "chapters": [chapters[i]["title"] for i in range(start - 1, end)][:50],
            "facts": [], "range": [start, end],
        })
    return out


def _overlap(a: list[int], b: list[int]) -> float:
    inter = min(a[1], b[1]) - max(a[0], b[0]) + 1
    return max(0, inter) / max(1, min(a[1] - a[0] + 1, b[1] - b[0] + 1))


# ---------------------------------------------------------------- 主流程

def _parse(text: str) -> dict:
    """容错解析；输出被 max_tokens 截断时，退回到最后一个完整的对象并补齐括号（前面已写完的实体不丢）。"""
    try:
        data = local_extract.parse_lenient(text)
        if "entities" in data or "cards" in data or "arcs" in data or "title" in data:
            return data
    except LLMError:
        data = None
    repaired = _close_truncated(text)
    if repaired is not None:
        return repaired
    if data is not None:
        return data
    raise LLMError("模型没有按 JSON 格式输出")


def _close_truncated(text: str) -> dict | None:
    start = text.find("{")
    if start < 0:
        return None
    body = text[start:]
    stack, in_str, esc, cuts = [], False, False, []
    for i, ch in enumerate(body):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack:
                break
            stack.pop()
            if ch == "}":
                cuts.append((i, "".join("}" if c == "{" else "]" for c in reversed(stack))))
    for i, closers in reversed(cuts[-40:]):
        try:
            data = json.loads(body[:i + 1] + closers)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _parallel(keys: list, fn: Callable, *, workers: int, stop: threading.Event | None, lock: threading.Lock,
              on_progress: Callable[[int, str], None], label: str, base: int, span: int, total: int,
              failed: dict, fail_key: str) -> None:
    """并发执行 fn(key)：配置级错误（fatal）终止整个任务，其余记一次失败继续。total 含断点里已完成的。"""
    state = {"done": total - len(keys)}

    def one(k):
        if stop and stop.is_set():
            raise Cancelled("已取消")
        try:
            fn(k)
        except LLMError as e:
            if stop and stop.is_set():
                raise Cancelled("已取消") from e
            if e.fatal:
                raise
            log.warning("%s %s 失败：%s", label, k, e)
            with lock:
                failed[fail_key] += 1
        with lock:
            state["done"] += 1
            done = state["done"]
        on_progress(base + int(span * done / max(1, total)), f"{label} {done}/{total}")

    if not keys:
        return
    pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="material")
    try:
        futures = [pool.submit(one, k) for k in keys]
        finished, _ = wait(futures, return_when=FIRST_EXCEPTION)
        for f in finished:
            if f.exception():
                raise f.exception()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------- ① 提取：只读原文

def scan(chapters: list[dict], opts: MaterialOptions, call: Call, concurrency: int, ckpt,
         on_progress: Callable[[int, str], None], stop: threading.Event | None, local: bool) -> dict:
    """读原文 → {chapters: [{summary, characters}], entities: [实体档案], stats}。断点阶段 pass1 / pass2。
    实体档案：[{key, category, name, aliases, facts: [{fact, quote, chapter: 章节标题, ci: 章节下标}]}]，事实多的在前。"""
    cats = [c for c in opts.active_categories() if c != "plot"]
    blocks = build_blocks(chapters, opts.chunkChars)
    stats = {"rounds": opts.rounds, "chunks": len(blocks), "failedChunks": 0, "factsVerified": 0, "factsUnverified": 0,
             "entities": 0}
    scan_tokens = 1000 if local else 1500
    lock = threading.Lock()
    book = Book()
    summaries: dict[int, str] = {}

    spans = [(0, 98)] if opts.rounds == 1 else [(0, 55), (55, 43)]
    for rnd in range(1, opts.rounds + 1):
        stage = f"pass{rnd}"
        done = ckpt.done(stage)
        for k in sorted(done, key=int):   # 断点里已有的块按顺序并入（第二遍的已知实体要用）
            book.add(done[k]["entities"])
            if rnd == 1 and done[k].get("summary"):
                summaries[int(k)] = done[k]["summary"]
        todo = [i for i in range(len(blocks)) if str(i) not in done]

        def read(i: int, rnd=rnd, stage=stage):
            if rnd == 2:
                with lock:  # 其他线程可能正在往 book 里加实体
                    known = book.known_in(blocks[i]["text"])
            else:
                known = None
            text = call([{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": scan_prompt(blocks[i]["text"], cats, opts.focus.strip(), known)}],
                        scan_tokens)
            data = _parse(text)
            ents, ok, bad = parse_scan(data, blocks[i], Source(blocks[i]["text"]), set(cats))
            row = {"entities": ents, "summary": _text(data.get("summary"), 200) if rnd == 1 else "", "ok": ok, "bad": bad}
            with lock:
                ckpt.append(stage, i, row)
                book.add(ents)
                if row["summary"]:
                    summaries[i] = row["summary"]

        base, span = spans[rnd - 1]
        # 第二遍要看全书已知实体，所以等第一遍全部完成再开始；同一遍里的块可以并发
        _parallel(todo, read, workers=concurrency, stop=stop, lock=lock, on_progress=on_progress,
                  label=f"第{rnd}遍阅读", base=base, span=span, total=len(blocks), failed=stats, fail_key="failedChunks")
        for row in ckpt.done(stage).values():
            stats["factsVerified"] += row.get("ok", 0)
            stats["factsUnverified"] += row.get("bad", 0)

    chap_summary: dict[int, list[str]] = {}
    for i, s in sorted(summaries.items()):
        for _, ci in blocks[i]["spans"]:  # 合并成一块的短章节共用这块的摘要
            chap_summary.setdefault(ci, []).append(s)
    chap_chars: dict[int, list[str]] = {}
    for ent in book.entities.values():
        if ent["category"] == "character":
            for ci in sorted({f["chapter"] for f in ent["facts"]}):
                chap_chars.setdefault(ci, []).append(ent["name"])
    out_chapters = [{"summary": " ".join(chap_summary.get(ci, [])), "characters": chap_chars.get(ci, [])}
                    for ci in range(len(chapters))]
    entities = []
    for ent in sorted(book.entities.values(), key=lambda e: -len(e["facts"])):
        entities.append({"key": ent["key"], "category": ent["category"], "name": ent["name"], "aliases": ent["aliases"],
                         "facts": [{"fact": f["fact"], "quote": f["quote"], "chapter": chapters[f["chapter"]]["title"],
                                    "ci": f["chapter"]} for f in ent["facts"]]})
    stats["entities"] = len(entities)
    return {"chapters": out_chapters, "entities": entities, "stats": stats}


# ---------------------------------------------------------------- ② 整理卡片

def _internal(entities: list[dict], chapters: list[dict]) -> list[dict]:
    """实体档案（可能被用户在页面上改过）→ 内部结构：事实的 chapter 换成章节下标（ci 缺失时按标题找）。"""
    index = {}
    for i, ch in enumerate(chapters):
        index.setdefault(ch.get("title", ""), i)
    out = []
    for e in entities:
        if not isinstance(e, dict) or e.get("category") not in CATEGORIES or not str(e.get("name") or "").strip():
            continue
        facts = []
        for f in e.get("facts") or []:
            if not isinstance(f, dict) or not str(f.get("fact") or "").strip():
                continue
            ci = f.get("ci")
            if not isinstance(ci, int) or not 0 <= ci < len(chapters):
                ci = index.get(f.get("chapter"), 0)
            facts.append({"fact": str(f["fact"])[:80], "quote": str(f.get("quote") or "")[:80], "chapter": ci})
        if facts:
            name = str(e["name"]).strip()[:40]
            out.append({"key": str(e.get("key") or f"{e['category']}:{_norm_title(name)}"), "category": e["category"],
                        "name": name, "aliases": [str(a)[:40] for a in e.get("aliases") or []][:8], "facts": facts[:MAX_FACTS]})
    return out


def compile_cards(entities: list[dict], chapters: list[dict], call: Call, concurrency: int, ckpt,
                  on_progress: Callable[[int, str], None], stop: threading.Event | None, local: bool,
                  plot: bool = True) -> dict:
    """实体档案 + 章节摘要 → {materials: [候选], stats}。断点阶段 cards / systems / arcs。
    chapters：[{title, summary}]，与提取结果的章节顺序一致（事实的 ci 指向这里）。"""
    ents = _internal(entities, chapters)
    stats = {"entities": len(ents), "cards": 0, "notUseful": 0, "systems": 0, "arcs": 0, "failedCards": 0}
    card_tokens = 900 if local else 1100
    lock = threading.Lock()
    multi = [e for e in ents if len(e["facts"]) >= 2]
    singles: dict[str, list[dict]] = {}
    for e in ents:
        if len(e["facts"]) < 2:
            singles.setdefault(e["category"], []).append(e)
    jobs = [("one", e["key"], [e]) for e in multi]
    for group in singles.values():
        for j in range(0, len(group), SINGLE_BATCH):
            part = group[j:j + SINGLE_BATCH]
            jobs.append(("batch", "b:" + part[0]["key"], part))
    cards_done = ckpt.done("cards")

    def make_card(job):
        kind, key, group = job
        if kind == "one":
            text = call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": card_prompt(group[0])}],
                        card_tokens)
            datas = {group[0]["key"]: _parse(text)}
        else:
            text = call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": batch_prompt(group)}],
                        card_tokens + 300 * len(group))
            got = {_norm_title(str(c.get("name") or c.get("title") or "")): c
                   for c in _parse(text).get("cards") or [] if isinstance(c, dict)}
            datas = {e["key"]: got.get(_norm_title(e["name"]), {"useful": False}) for e in group}
        with lock:
            ckpt.append("cards", key, datas)

    span_cards = 80 if plot else 92
    _parallel([j for j in jobs if j[1] not in cards_done], make_card, workers=concurrency, stop=stop, lock=lock,
              on_progress=on_progress, label="整理素材卡", base=0, span=span_cards, total=len(jobs),
              failed=stats, fail_key="failedCards")
    by_key = {e["key"]: e for e in ents}
    order = {e["key"]: n for n, e in enumerate(ents)}
    ranked = []
    for datas in ckpt.done("cards").values():
        for k, data in (datas or {}).items():
            if k in by_key:
                c = to_candidate(data, by_key[k], chapters)
                if c:
                    ranked.append((order[k], c))
                else:
                    stats["notUseful"] += 1
    cards = [c for _, c in sorted(ranked, key=lambda x: x[0])]  # 事实多的在前
    stats["cards"] = len(cards)

    # ---- 体系卡：同一 subtype 的世界观 ≥3 张
    groups: dict[str, list[dict]] = {}
    for c in cards:
        if c["category"] == "world" and c["subtype"]:
            groups.setdefault(_norm_title(c["subtype"]), []).append(c)
    sys_jobs = [(k, g) for k, g in groups.items() if len(g) >= SYSTEM_MIN]
    sys_done = ckpt.done("systems")

    def make_system(job):
        k, group = job
        text = call([{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": system_prompt(group, group[0]["subtype"])}], card_tokens + 200)
        with lock:
            ckpt.append("systems", k, _parse(text))

    _parallel([j for j in sys_jobs if j[0] not in sys_done], make_system, workers=concurrency, stop=stop, lock=lock,
              on_progress=on_progress, label="整理体系卡", base=span_cards, span=5, total=len(sys_jobs),
              failed=stats, fail_key="failedCards")
    title_index = {}
    for i, ch in enumerate(chapters):
        title_index.setdefault(ch.get("title", ""), i)
    systems = []
    for k, group in sys_jobs:
        data = ckpt.done("systems").get(k)
        ent = {"key": f"world:体系:{k}", "category": "world", "name": f"{group[0]['subtype']}体系", "aliases": [], "facts": []}
        c = to_candidate(data, ent, chapters) if data else None
        if c:
            c["subtype"] = "体系"
            c["chapters"] = sorted({ch for g in group for ch in g["chapters"]}, key=lambda t: title_index.get(t, 0))[:50]
            c["facts"] = [f for g in group for f in g["facts"]][:MAX_FACTS]
            c["parts"] = [g["title"] for g in group]
            systems.append(c)
    stats["systems"] = len(systems)

    # ---- 剧情段（章节摘要；合并成一块的短章节摘要相同，只列第一章）
    arcs: list[dict] = []
    if plot:
        rows, last = [], None
        for ci, ch in enumerate(chapters):
            s = str(ch.get("summary") or "").strip()
            if s and s != last:
                rows.append((ci, {"title": ch.get("title", ""), "summary": s}))
            last = s
        windows = [rows[j:j + ARC_WINDOW] for j in range(0, max(1, len(rows) - (ARC_WINDOW - ARC_STEP)), ARC_STEP)]
        windows = [w for w in windows if len(w) >= 3]
        arcs_done = ckpt.done("arcs")

        def make_arcs(w: int):
            text = call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": arc_prompt(windows[w])}], 1300)
            with lock:
                ckpt.append("arcs", w, _parse(text))

        _parallel([w for w in range(len(windows)) if str(w) not in arcs_done], make_arcs, workers=concurrency,
                  stop=stop, lock=lock, on_progress=on_progress, label="整理剧情段", base=span_cards + 5, span=14,
                  total=len(windows), failed=stats, fail_key="failedCards")
        for w in sorted(ckpt.done("arcs"), key=int):
            for a in arc_candidates(ckpt.done("arcs")[w] or {}, chapters):
                if not any(_norm_title(a["title"]) == _norm_title(b["title"])
                           or (_overlap(a["range"], b["range"]) > 0.5 and a["subtype"] == b["subtype"]) for b in arcs):
                    arcs.append(a)
        for a in arcs:
            a.pop("range", None)
        stats["arcs"] = len(arcs)

    return {"materials": systems + cards + arcs, "stats": stats}
