"""跨世界观角色卡：提取人物内核 → 原型卡 → 适配到新世界观 → 用于写作 / 试聊 → 辨识度测试。

- **提取**（`extract`，后台任务）：① 定位（代码）：资料整篇都关于他、或不长时全文读；小说里按名字 / 别名找提及位置取前后
  约 800 字的窗口，按全书位置分层抽样（开头 / 中段 / 结尾），最多 ``max_blocks`` 块；② 逐块记证据（每块一次调用）：
  「这段说明了这个人什么」+ 原文摘抄，摘抄由代码核对原文（``material_facts.Source.locate``），对不上丢弃；
  ③ 汇总（1 次调用）：只读证据清单（带编号），写成原型卡。约 20% 的证据随机留出不给汇总，只给辨识度测试的评委作参照。
- **出处由代码判定**：特征 / 规则引用了真实存在的证据编号 → ``quoted``（原文），否则 → ``inferred``（推断），
  用户手写 → ``user``；置信度按证据条数。只有形容词、没有任何行为规则引用的人格 / 思维特征列进不确定项。
- **适配**（`adapt`，1 次调用）：核心特征和锁定特征由代码原样复制，模型只写「在新世界怎么体现」；代码检查每个核心特征
  都有体现、扫描原世界专属术语（泄漏），并按固定格式拼出写作用的精简版 ``brief``。
- **试聊**（`chat`）：系统提示 = 内核 + 决策规则 + 说话方式 + 禁止项 + 他不知道的事 + 世界；按这句话检索最相关的经历记忆和
  示例台词；超过 ``CHAT_KEEP`` 条的旧对话压成摘要；每轮最后补一条「人物锚点」；每 ``DRIFT_EVERY`` 轮做一次走偏检查。
- **辨识度测试**（`identity_test`，后台任务）：情境场景 A（适配版）/ B（只有姓名身份的对照）+ 匿名扣分制评委；
  保护性场景（诱导说出他不该知道的事）；心理访谈（原型 vs 适配版答案的一致性）；同一场景两次决策是否一致。

模型调用由调用方传入 ``call(messages, max_tokens, json_mode=True, temperature=None) -> str``。
"""
import hashlib
import json
import random
import re
import threading
from typing import Callable

from . import material_facts, text_loader
from .llm_client import LLMError

SITUATIONS = ["面对未知现象", "与自身理论矛盾的证据", "权威压制", "失败", "危险", "利益冲突"]
LAYERS = {"personality": "核心性格", "values": "价值观 / 道德观", "desire": "欲望 / 执念", "fear": "恐惧",
          "contradiction": "内在矛盾", "thinking": "思维模式", "behavior": "行为倾向", "expertise": "专业特征",
          "voice": "语言与表达", "arc": "人物弧光", "signature": "辨识度"}
ADJECTIVE_LAYERS = ("personality", "thinking")   # 这两层的特征必须有行为规则支撑
WINDOW = 800              # 提及位置前后各取多少字
WHOLE_LIMIT = 30000       # 不超过这个字数直接全文读
HOLDOUT = 0.2             # 留给评委的证据比例
CHAT_KEEP = 20            # 试聊保留原文的最近消息数，更早的压成摘要
DRIFT_EVERY = 8           # 每多少轮角色回复检查一次走偏
INTERVIEW = ["你这辈子最想弄明白、或者最想得到的是什么？为什么？",
             "如果你一直坚信的东西被证明是错的，你会怎么做？",
             "有地位很高的人命令你放弃正在做的事，你会怎么回应？",
             "你最害怕的是什么？",
             "失败了很多次之后，是什么让你继续（或者放弃）？",
             "为了达成目标，有什么事是你绝对不会做的？"]

SYSTEM = "你是小说人物分析助手，只输出 JSON，不要任何多余文字。"

Call = Callable[..., str]


class Cancelled(RuntimeError):
    pass


# ---------------------------------------------------------------- 工具

def _text(v, limit: int) -> str:
    if isinstance(v, list):
        v = "、".join(map(str, v))
    return str(v or "").strip()[:limit]


def _parse(text: str) -> dict:
    return material_facts._parse(text)


def _ids(v) -> list[str]:
    out = []
    for x in v if isinstance(v, list) else ([v] if v else []):
        m = re.search(r"E?(\d+)", str(x))
        if m:
            out.append(f"E{int(m.group(1))}")
    return list(dict.fromkeys(out))


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[\s\W_]+", "", text or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


# ---------------------------------------------------------------- ① 定位

def locate(text: str, names: list[str], whole: bool, max_blocks: int = 60, chunk: int = 3000) -> dict:
    """→ {blocks: [str], mentions, windows, sampled}。whole / 短文本：全文切块；否则只取提及人物的窗口并分层抽样。"""
    names = [n for n in dict.fromkeys(n.strip() for n in names if n and n.strip()) if len(n) >= 2]
    if whole or len(text) <= WHOLE_LIMIT or not names:
        blocks = text_loader.split_chunks(text, chunk)
        return {"blocks": _sample(blocks, max_blocks), "mentions": None, "windows": len(blocks), "sampled": len(blocks) > max_blocks}
    spans = []
    for n in names:
        for m in re.finditer(re.escape(n), text):
            spans.append((max(0, m.start() - WINDOW), min(len(text), m.end() + WINDOW)))
    if not spans:
        return {"blocks": [], "mentions": 0, "windows": 0, "sampled": False}
    spans.sort()
    merged = [list(spans[0])]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    blocks, cur = [], ""
    for s, e in merged:  # 相邻窗口拼成约 chunk 字的块，窗口之间用「……」隔开
        piece = text[s:e].strip()
        if len(piece) > chunk:
            blocks.extend(text_loader.split_chunks(piece, chunk))
            continue
        if cur and len(cur) + len(piece) + 3 > chunk:
            blocks.append(cur)
            cur = ""
        cur = f"{cur}\n……\n{piece}" if cur else piece
    if cur:
        blocks.append(cur)
    return {"blocks": _sample(blocks, max_blocks), "mentions": len(spans), "windows": len(merged),
            "sampled": len(blocks) > max_blocks}


def _sample(blocks: list[str], limit: int) -> list[str]:
    """超过上限时按位置分层抽样：开头 / 中段 / 结尾三段各取约 1/3，段内均匀取，保留原顺序。"""
    if len(blocks) <= limit:
        return blocks
    n = len(blocks)
    thirds = [range(0, n // 3), range(n // 3, 2 * n // 3), range(2 * n // 3, n)]
    quota = [limit // 3 + (1 if i < limit % 3 else 0) for i in range(3)]
    picked = []
    for r, q in zip(thirds, quota):
        idx = list(r)
        if not idx or q <= 0:
            continue
        step = len(idx) / q
        picked += [idx[min(len(idx) - 1, int(k * step))] for k in range(q)]
    return [blocks[i] for i in sorted(set(picked))]


# ---------------------------------------------------------------- ② 逐块记证据

def notes_prompt(block: str, name: str, aliases: list[str]) -> str:
    alias = f"（也叫 {'、'.join(aliases)}）" if aliases else ""
    layers = "；".join(f"{k}={v}" for k, v in LAYERS.items() if k not in ("signature", "arc")) + "；arc=人物弧光（经历如何改变了他）"
    return (f"下面是一段和人物「{name}」{alias}有关的文字。只记录这段文字**说明了这个人什么**："
            "他怎么想问题、看重什么、怕什么、遇到某种情境时怎么反应、怎么说话、有什么专业本事和习惯。\n"
            f"layer 只能用：{layers}。\n"
            "要求：observation 写具体的观察（≤50 字），不要空泛形容词；能看出「情境 → 反应」的，填 situation 和 reaction；"
            "能看出他心里怎么想的，填 thought；quote 原样摘抄能证明它的原文（≤40 字）；"
            "能体现他说话方式的原话，layer 用 voice，quote 填那句原话。和他无关的不要记；没有就输出空数组。\n"
            '输出：{"notes":[{"layer":"","observation":"","situation":"","reaction":"","thought":"","quote":""}]}\n\n'
            f"文字：\n{block}")


def parse_notes(data: dict, block: str) -> tuple[list[dict], int, int]:
    src = material_facts.Source(block)
    out, ok, bad = [], 0, 0
    for n in data.get("notes") or []:
        if not isinstance(n, dict):
            continue
        obs, quote = _text(n.get("observation"), 120), _text(n.get("quote"), 80)
        if not obs:
            continue
        if src.locate(quote) is None:
            bad += 1
            continue
        ok += 1
        layer = n.get("layer") if n.get("layer") in LAYERS else "behavior"
        out.append({"layer": layer, "observation": obs, "situation": _text(n.get("situation"), 80),
                    "reaction": _text(n.get("reaction"), 120), "thought": _text(n.get("thought"), 120), "quote": quote})
    return out, ok, bad


def _dedupe(notes: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for n in notes:
        if not any(k["layer"] == n["layer"] and material_facts._similar(k["observation"], n["observation"]) for k in kept):
            kept.append(n)
    return kept


# ---------------------------------------------------------------- ③ 汇总成原型

def synth_prompt(name: str, notes: list[dict]) -> str:
    by_layer: dict[str, list[str]] = {}
    for n in notes:
        extra = "".join([f"；情境：{n['situation']} → {n['reaction']}" if n.get("situation") else "",
                         f"；内心：{n['thought']}" if n.get("thought") else ""])
        by_layer.setdefault(n["layer"], []).append(f"[{n['id']}] {n['observation']}{extra}（原文：{n['quote']}）")
    body = "\n".join(f"【{LAYERS[k]}】\n" + "\n".join(v) for k, v in by_layer.items())
    sits = "、".join(SITUATIONS)
    return (f"下面是从资料里核实过的、关于人物「{name}」的证据（方括号里是证据编号）：\n{body}\n\n"
            "把它整理成一张「跨世界观原型卡」：提取这个人真正有辨识度的**内核**——思维方式、价值观、行为逻辑——"
            "而不是外貌、身份、经历这些表层。以后会把他放进完全不同的世界（没有原来的知识和工具，物理法则也可能不同）。\n"
            "要求：\n"
            "1. traits：每条一个特征（≤60 字，具体、可观察），layer 用证据里的分类；kind 提议 core（不可变的内核：去掉就不是他了）"
            "或 adaptable（可以随世界改变的外壳：职业、知识体系、身份、具体做法）；evidence 写支撑它的证据编号，没有证据的是你的推断，"
            "evidence 留空。\n"
            f"2. rules：行为规则，必须覆盖这六类情境：{sits}，可以再加别的。每条写 reaction（他会怎么做）、reasoning（为什么，"
            "背后的思维逻辑）、traits（对应的特征序号，从 1 开始）、evidence。每条人格 / 思维特征都要有至少一条规则体现。\n"
            "3. expertise：knowledge（知识结构）、methods（研究 / 做事方法）、intuition（专业直觉）、logic（这些能力背后的思维逻辑）、"
            "worldBound（原世界专属、换了世界就不该有的知识 / 工具 / 术语，5~15 个词）。\n"
            "4. voice：style（说话风格）、argumentation（论证方式）、tendencies（常用表达倾向）、emotion（情绪表达）、"
            "lines（最能体现说话方式的原话证据编号）。\n"
            "5. arc：formative（[{experience: 经历类型, change: 造成的改变}]）、growth（可能的成长）、fall（可能的堕落 / 转变）。\n"
            "6. signature：mustKeep（必须保留的特征序号）、easyToLose（改写时最容易丢掉的点）。\n"
            "7. memories：关键经历记忆（3~8 条）[{scene, situation, thought, action, evidence}]。\n"
            "8. uncertain：证据不足、互相矛盾、需要作者决定的问题。\n"
            "只依据证据，不编造原文没有的事实；推断的部分不写 evidence。\n"
            '输出：{"summary":"一句话概括这个人的内核","kind":"分类（如 学者 / 战士 / 商人）","traits":[{"layer":"","text":"",'
            '"kind":"core","evidence":["E1"]}],"rules":[{"situation":"","reaction":"","reasoning":"","traits":[1],"evidence":[]}],'
            '"expertise":{"knowledge":"","methods":"","intuition":"","logic":"","worldBound":[]},'
            '"voice":{"style":"","argumentation":"","tendencies":"","emotion":"","lines":[]},'
            '"arc":{"formative":[{"experience":"","change":""}],"growth":"","fall":""},'
            '"signature":{"mustKeep":[1],"easyToLose":[]},"memories":[{"scene":"","situation":"","thought":"","action":"","evidence":[]}],'
            '"uncertain":[]}')


def _confidence(n: int) -> str:
    return "high" if n >= 3 else "medium" if n == 2 else "low"


def build_prototype(data: dict, name: str, aliases: list[str], notes: list[dict], holdout: list[dict]) -> dict:
    """模型汇总 → 原型卡（出处、置信度由代码判定）。"""
    ev = {n["id"]: n for n in notes}

    def evidence(v) -> list[dict]:
        return [{"id": i, "quote": ev[i]["quote"], "observation": ev[i]["observation"]} for i in _ids(v) if i in ev]

    traits = []
    for i, t in enumerate(data.get("traits") or [], 1):
        if not isinstance(t, dict) or not _text(t.get("text"), 200):
            continue
        e = evidence(t.get("evidence"))
        traits.append({"id": f"t{i}", "layer": t.get("layer") if t.get("layer") in LAYERS else "personality",
                       "text": _text(t.get("text"), 200), "kind": "core" if t.get("kind") == "core" else "adaptable",
                       "locked": False, "provenance": "quoted" if e else "inferred",
                       "confidence": _confidence(len(e)) if e else "low", "evidence": e, "editedBy": "ai",
                       "aiText": "", "note": ""})
    tid = {str(int(t["id"][1:])): t["id"] for t in traits}
    rules = []
    for r in data.get("rules") or []:
        if not isinstance(r, dict) or not _text(r.get("reaction"), 300):
            continue
        e = evidence(r.get("evidence"))
        refs = []
        for x in r.get("traits") or []:
            k = str(x).strip().lstrip("t")
            if k in tid and tid[k] not in refs:
                refs.append(tid[k])
        rules.append({"id": f"r{len(rules) + 1}", "situation": _text(r.get("situation"), 80),
                      "reaction": _text(r.get("reaction"), 300), "reasoning": _text(r.get("reasoning"), 300),
                      "traitRefs": refs, "provenance": "quoted" if e else "inferred", "evidence": e, "editedBy": "ai"})
    exp = data.get("expertise") if isinstance(data.get("expertise"), dict) else {}
    voice = data.get("voice") if isinstance(data.get("voice"), dict) else {}
    lines = [{"line": e["quote"], "id": e["id"], "observation": e["observation"]} for e in evidence(voice.get("lines"))]
    lines += [{"line": n["quote"], "id": n["id"], "observation": n["observation"]}
              for n in notes if n["layer"] == "voice" and n["id"] not in {x["id"] for x in lines}][:12]
    memories = []
    for m in data.get("memories") or []:
        if isinstance(m, dict) and _text(m.get("action"), 300):
            e = evidence(m.get("evidence"))
            memories.append({"scene": _text(m.get("scene"), 120), "situation": _text(m.get("situation"), 120),
                             "thought": _text(m.get("thought"), 200), "action": _text(m.get("action"), 300),
                             "provenance": "quoted" if e else "inferred", "evidence": e})
    arc = data.get("arc") if isinstance(data.get("arc"), dict) else {}
    sig = data.get("signature") if isinstance(data.get("signature"), dict) else {}
    uncertain = [_text(u, 200) for u in data.get("uncertain") or [] if _text(u, 200)]
    covered = {r["situation"] for r in rules}
    for s in SITUATIONS:
        if not any(s in c or c in s for c in covered if c):
            uncertain.append(f"缺少「{s}」时的行为规则：资料里看不出来，需要作者补充或判断")
    backed = {ref for r in rules for ref in r["traitRefs"]}
    for t in traits:
        if t["layer"] in ADJECTIVE_LAYERS and t["id"] not in backed:
            uncertain.append(f"「{t['text']}」只有描述，没有对应的行为规则（他遇到什么情况会怎样体现它？）")
    return {
        "name": name, "aliases": aliases, "summary": _text(data.get("summary"), 200), "kind": _text(data.get("kind"), 20),
        "traits": traits, "rules": rules,
        "expertise": {"knowledge": _text(exp.get("knowledge"), 300), "methods": _text(exp.get("methods"), 300),
                      "intuition": _text(exp.get("intuition"), 300), "logic": _text(exp.get("logic"), 300),
                      "worldBound": [_text(w, 30) for w in exp.get("worldBound") or [] if _text(w, 30)][:20]},
        "voice": {"style": _text(voice.get("style"), 200), "argumentation": _text(voice.get("argumentation"), 200),
                  "tendencies": _text(voice.get("tendencies"), 200), "emotion": _text(voice.get("emotion"), 200)},
        "lines": lines,
        "arc": {"formative": [{"experience": _text(f.get("experience"), 120), "change": _text(f.get("change"), 120)}
                              for f in arc.get("formative") or [] if isinstance(f, dict)][:8],
                "growth": _text(arc.get("growth"), 200), "fall": _text(arc.get("fall"), 200)},
        "signature": {"mustKeep": [tid[str(x).lstrip("t")] for x in sig.get("mustKeep") or [] if str(x).lstrip("t") in tid],
                      "easyToLose": [_text(x, 120) for x in sig.get("easyToLose") or [] if _text(x, 120)]},
        "memories": memories, "uncertain": list(dict.fromkeys(uncertain)),
        "holdout": [{"layer": n["layer"], "observation": n["observation"], "quote": n["quote"],
                     "situation": n.get("situation", ""), "reaction": n.get("reaction", "")} for n in holdout],
        "evidenceCount": len(notes) + len(holdout), "coreConfirmed": False,
    }


def extract(text: str, name: str, aliases: list[str], whole: bool, seed_facts: list[dict], call: Call, ckpt,
            on_progress: Callable[[int, str], None], stop: threading.Event | None, *, max_blocks: int = 60,
            chunk: int = 3000, local: bool = False) -> dict:
    """资料 → 原型卡。断点阶段 notes（每块一行）/ synth。"""
    loc = locate(text, [name, *aliases], whole, max_blocks, chunk)
    blocks = loc["blocks"]
    if not blocks and not seed_facts:
        raise ValueError(f"资料里没有找到「{name}」（也没有别名命中），请检查名字或勾选「整篇都关于他」")
    done = ckpt.done("notes")
    stats = {"blocks": len(blocks), "mentions": loc["mentions"], "sampled": loc["sampled"], "verified": 0, "dropped": 0,
             "failed": 0}
    for i, block in enumerate(blocks):
        if str(i) in done:
            continue
        if stop and stop.is_set():
            raise Cancelled("已取消")
        try:
            raw = call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": notes_prompt(block, name, aliases)}],
                       1000 if local else 1500)
            notes, ok, bad = parse_notes(_parse(raw), block)
            ckpt.append("notes", i, {"notes": notes, "ok": ok, "bad": bad})
        except LLMError as e:
            if e.fatal:
                raise
            stats["failed"] += 1
        on_progress(int(80 * (i + 1) / max(1, len(blocks))), f"读资料 {i + 1}/{len(blocks)}")
    notes = []
    for k in sorted(ckpt.done("notes"), key=int):
        row = ckpt.done("notes")[k]
        notes += row["notes"]
        stats["verified"] += row.get("ok", 0)
        stats["dropped"] += row.get("bad", 0)
    for f in seed_facts:  # 实体档案里已核实的事实
        if f.get("fact") and f.get("quote"):
            notes.append({"layer": "behavior", "observation": _text(f["fact"], 120), "situation": "", "reaction": "",
                          "thought": "", "quote": _text(f["quote"], 80)})
    notes = _dedupe(notes)
    if not notes:
        raise ValueError("没有提取到任何有原文依据的证据")
    rng = random.Random(hashlib.sha1(name.encode()).hexdigest())
    order = list(range(len(notes)))
    rng.shuffle(order)
    n_hold = int(len(notes) * HOLDOUT) if len(notes) >= 10 else 0
    hold_idx = set(order[:n_hold])
    used = [n for i, n in enumerate(notes) if i not in hold_idx]
    holdout = [n for i, n in enumerate(notes) if i in hold_idx]
    for i, n in enumerate(used, 1):
        n["id"] = f"E{i}"
    if stop and stop.is_set():
        raise Cancelled("已取消")
    on_progress(85, f"汇总原型（{len(used)} 条证据，留出 {len(holdout)} 条给评委）")
    synth = ckpt.done("synth").get("0")
    if synth is None:
        raw = call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": synth_prompt(name, used)}], 4000)
        synth = _parse(raw)
        ckpt.append("synth", 0, synth)
    proto = build_prototype(synth, name, aliases, used, holdout)
    stats["traits"], stats["rules"] = len(proto["traits"]), len(proto["rules"])
    on_progress(100, f"完成：{len(proto['traits'])} 条特征、{len(proto['rules'])} 条行为规则")
    return {"prototype": proto, "stats": stats}


# ---------------------------------------------------------------- 适配到新世界观

def _trait_lines(proto: dict, kinds: tuple[str, ...]) -> str:
    return "\n".join(f"- {t['id']}【{LAYERS.get(t['layer'], t['layer'])}】{t['text']}" + ("（锁定）" if t.get("locked") else "")
                     for t in proto.get("traits", []) if t.get("kind") in kinds)


def adapt_prompt(proto: dict, world: str, wish: str) -> str:
    rules = "\n".join(f"- {r['situation']}：{r['reaction']}（因为 {r['reasoning']}）" for r in proto.get("rules", []))
    exp = proto.get("expertise", {})
    voice = proto.get("voice", {})
    mem = "\n".join(f"- {m['scene']}：{m['situation']} → 想：{m['thought']} → 做：{m['action']}" for m in proto.get("memories", [])[:6])
    sits = "、".join(SITUATIONS)
    return (f"把原型人物「{proto['name']}」放进一个新的世界。保留他的内核，重新解释他的外壳。\n\n"
            f"【原型一句话】{proto.get('summary', '')}\n"
            f"【不可变的内核（必须原样保留，只写在新世界怎么体现）】\n{_trait_lines(proto, ('core',)) or '（无）'}\n"
            f"【可以改变的外壳（按新世界重新解释）】\n{_trait_lines(proto, ('adaptable',)) or '（无）'}\n"
            f"【原型的行为规则】\n{rules or '（无）'}\n"
            f"【专业特征】知识：{exp.get('knowledge', '')}；方法：{exp.get('methods', '')}；直觉：{exp.get('intuition', '')}；"
            f"背后的思维逻辑：{exp.get('logic', '')}\n【原世界专属（新世界里不能有）】{'、'.join(exp.get('worldBound', []))}\n"
            f"【说话方式】{voice.get('style', '')}；论证：{voice.get('argumentation', '')}；情绪：{voice.get('emotion', '')}\n"
            f"【经历记忆】\n{mem or '（无）'}\n\n【目标世界观】\n{world or '（作者没有给出，按通用奇幻世界处理，并把不确定的写进 open）'}\n"
            + (f"【作者希望他在这个世界的身份】{wish}\n" if wish else "") +
            "\n要求：\n"
            "1. coreManifest：上面每一条不可变内核（按编号）都要写一条：它在新世界里具体怎么体现（≤80 字）。不要改写内核本身。\n"
            "2. adaptedTraits：每条可变外壳写新世界里的版本（adapted）和理由（why）。\n"
            "3. expertiseMap：原来的专业能力在新世界变成什么（inWorld），受到什么限制（constraint）。**不得使用原世界专属的知识、工具、"
            "术语**；不要默认新世界遵守现实物理定律，只能用目标世界观写明的规则，没写明的写进 open。\n"
            f"4. rules：把行为规则改写成新世界里的具体情境，必须覆盖：{sits}。\n"
            "5. voice：新世界里的说话方式（保留论证方式和情绪表达，换掉原世界的术语）。\n"
            "6. forbidden：写作时禁止的事（如「不得使用现代化学术语」）；unknowns：他在新世界不可能知道的原世界知识（5~10 个词）。\n"
            "7. examples：3~5 句新世界里的示例台词，每句带 context（什么情况下说的），每句 30~80 字。\n"
            "8. memories：把经历记忆换成新世界里对应的经历（只换外壳，心理过程不变）。\n"
            "9. identity：他在新世界的身份、职业、处境；card：角色卡字段（name 新世界里的名字可以沿用或另起、tagline、role、"
            "personality、speech、goal、fear、secret、bottomLine、abilities、background、arc）。\n"
            "10. open：需要作者决定的问题。\n"
            '输出：{"identity":"","coreManifest":[{"traitId":"t1","inWorld":""}],"adaptedTraits":[{"traitId":"t2","adapted":"","why":""}],'
            '"expertiseMap":[{"original":"","inWorld":"","constraint":""}],"rules":[{"situation":"","reaction":"","reasoning":""}],'
            '"voice":"","forbidden":[],"unknowns":[],"examples":[{"context":"","line":""}],'
            '"memories":[{"scene":"","thought":"","action":""}],"card":{},"open":[]}')


CARD_KEYS = ("name", "tagline", "role", "personality", "speech", "goal", "fear", "secret", "bottomLine", "abilities",
             "background", "arc")


def build_adaptation(data: dict, proto: dict, world: str) -> dict:
    """模型适配结果 → 适配版本；核心 / 锁定特征由代码原样复制；检查覆盖和泄漏，拼出 brief。"""
    traits = {t["id"]: t for t in proto.get("traits", [])}
    manifest = {}
    for m in data.get("coreManifest") or []:
        if isinstance(m, dict) and m.get("traitId") in traits and _text(m.get("inWorld"), 300):
            manifest[m["traitId"]] = _text(m.get("inWorld"), 300)
    core = [{"traitId": t["id"], "text": t["text"], "locked": bool(t.get("locked")), "inWorld": manifest.get(t["id"], "")}
            for t in proto.get("traits", []) if t.get("kind") == "core" or t.get("locked")]
    adapted = []
    for a in data.get("adaptedTraits") or []:
        if isinstance(a, dict) and a.get("traitId") in traits and traits[a["traitId"]].get("kind") != "core" \
                and not traits[a["traitId"]].get("locked") and _text(a.get("adapted"), 300):
            adapted.append({"traitId": a["traitId"], "original": traits[a["traitId"]]["text"],
                            "adapted": _text(a.get("adapted"), 300), "why": _text(a.get("why"), 200)})
    card = data.get("card") if isinstance(data.get("card"), dict) else {}
    out = {
        "name": _text(card.get("name"), 40) or proto["name"], "aliases": list(proto.get("aliases") or []),
        "identity": _text(data.get("identity"), 300), "core": core, "adaptedTraits": adapted,
        "expertiseMap": [{"original": _text(e.get("original"), 120), "inWorld": _text(e.get("inWorld"), 200),
                          "constraint": _text(e.get("constraint"), 200)} for e in data.get("expertiseMap") or [] if isinstance(e, dict)],
        "rules": [{"situation": _text(r.get("situation"), 100), "reaction": _text(r.get("reaction"), 300),
                   "reasoning": _text(r.get("reasoning"), 300)} for r in data.get("rules") or []
                  if isinstance(r, dict) and _text(r.get("reaction"), 10)],
        "voice": _text(data.get("voice"), 400),
        "forbidden": [_text(x, 80) for x in data.get("forbidden") or [] if _text(x, 80)][:10],
        "unknowns": list(dict.fromkeys([_text(x, 30) for x in (data.get("unknowns") or []) if _text(x, 30)]
                                       + list(proto.get("expertise", {}).get("worldBound") or [])))[:20],
        "examples": [{"context": _text(e.get("context"), 80), "line": _text(e.get("line"), 200)}
                     for e in data.get("examples") or [] if isinstance(e, dict) and _text(e.get("line"), 5)][:8],
        "memories": [{"scene": _text(m.get("scene"), 120), "thought": _text(m.get("thought"), 200),
                      "action": _text(m.get("action"), 300)} for m in data.get("memories") or [] if isinstance(m, dict)][:8],
        "card": {k: _text(card.get(k), 400) for k in CARD_KEYS if _text(card.get(k), 400)},
        "open": [_text(x, 200) for x in data.get("open") or [] if _text(x, 200)],
        "world": world[:2000],
    }
    out["card"].setdefault("name", out["name"])
    out["checks"] = check_adaptation(out, proto)
    out["brief"] = render_brief(out)
    return out


def leak_terms(text: str, terms: list[str]) -> list[str]:
    return [t for t in terms if len(t) >= 2 and t in text]


def check_adaptation(ad: dict, proto: dict) -> dict:
    missing = [c["text"] for c in ad["core"] if not c["inWorld"]]
    changed = [t["text"] for t in proto.get("traits", []) if t.get("locked")
               and not any(c["traitId"] == t["id"] and c["text"] == t["text"] for c in ad["core"])]
    body = json.dumps({k: ad[k] for k in ("identity", "core", "adaptedTraits", "expertiseMap", "rules", "voice", "examples",
                                          "memories", "card")}, ensure_ascii=False)
    leaks = leak_terms(body, ad["unknowns"])
    sits = [s for s in SITUATIONS if not any(s in r["situation"] or r["situation"] in s for r in ad["rules"] if r["situation"])]
    return {"missingManifest": missing, "changedLocked": changed, "leaks": leaks, "missingSituations": sits,
            "ok": not (missing or changed or leaks)}


def render_brief(p: dict) -> str:
    """写作 / 试聊用的精简版人物内核（固定格式，由代码拼）。"""
    lines = [f"【人物内核·{p['name']}】（来自角色卡库，写他时必须遵守）"]
    if p.get("identity"):
        lines.append(f"身份：{p['identity']}")
    if p.get("core"):
        lines.append("不可改变的内核：")
        lines += [f"- {c['text']}" + (f"——在本世界表现为：{c['inWorld']}" if c.get("inWorld") else "") for c in p["core"]]
    if p.get("rules"):
        lines.append("决策规则（情境 → 反应 → 原因）：")
        lines += [f"- {r['situation']} → {r['reaction']}" + (f"（{r['reasoning']}）" if r.get("reasoning") else "")
                  for r in p["rules"][:8]]
    if p.get("voice"):
        lines.append(f"说话方式：{p['voice']}")
    if p.get("forbidden"):
        lines.append("禁止：" + "；".join(p["forbidden"]))
    if p.get("unknowns"):
        lines.append("他不知道（不能出现在他的言行里）：" + "、".join(p["unknowns"]))
    return "\n".join(lines)


def snapshot(ad: dict, adaptation_id, version: str, role: str = "") -> dict:
    """写进 novel.json 的 personas 条目（生成时不依赖 Java）。"""
    keys = ("name", "aliases", "identity", "core", "rules", "voice", "forbidden", "unknowns", "examples", "memories", "brief")
    snap = {k: ad.get(k) for k in keys}
    snap.update({"adaptationId": adaptation_id, "version": version, "role": role or ad.get("card", {}).get("role", "")})
    return snap


def recheck(ad: dict, proto: dict) -> dict:
    """作者编辑适配版本后：重新跑代码检查、重新拼 brief（不调模型）。"""
    ad = dict(ad)
    for k, d in (("core", []), ("rules", []), ("unknowns", []), ("forbidden", []), ("examples", []), ("memories", []),
                 ("adaptedTraits", []), ("expertiseMap", []), ("card", {})):
        ad.setdefault(k, d)
    ad.setdefault("name", proto.get("name", ""))
    ad["checks"] = check_adaptation(ad, proto)
    ad["brief"] = render_brief(ad)
    return ad


def as_persona(p: dict | None) -> dict | None:
    """原型卡（有 traits）也能直接试聊：转成适配版本的形状（核心特征 + 规则 + 说话方式 + 原话）。"""
    if not p or "traits" not in p:
        return p
    v = p.get("voice") or {}
    out = {"name": p.get("name", ""), "aliases": p.get("aliases") or [], "identity": p.get("summary", ""),
           "core": [{"traitId": t["id"], "text": t["text"], "inWorld": ""} for t in p.get("traits", [])
                    if t.get("kind") == "core" or t.get("locked")] or
                   [{"traitId": t["id"], "text": t["text"], "inWorld": ""} for t in p.get("traits", [])[:6]],
           "rules": [{"situation": r["situation"], "reaction": r["reaction"], "reasoning": r.get("reasoning", "")}
                     for r in p.get("rules", [])],
           "voice": "；".join(x for x in (v.get("style"), v.get("argumentation"), v.get("emotion")) if x),
           "forbidden": [], "unknowns": [],
           "examples": [{"context": l.get("observation", ""), "line": l["line"]} for l in p.get("lines", [])],
           "memories": [{"scene": m.get("scene", ""), "thought": m.get("thought", ""), "action": m.get("action", "")}
                        for m in p.get("memories", [])]}
    out["brief"] = render_brief(out)
    return out


def adapt(proto: dict, world: str, wish: str, call: Call) -> dict:
    raw = call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": adapt_prompt(proto, world, wish)}], 3500)
    return build_adaptation(_parse(raw), proto, world)


# ---------------------------------------------------------------- 写作接入（spec / plan / review）

def mentioned(personas: list[dict], text: str) -> list[dict]:
    return [p for p in personas or [] if any(n and n in text for n in [p.get("name"), *(p.get("aliases") or [])])]


def rules_text(personas: list[dict]) -> str:
    return "\n\n".join(p.get("brief") or render_brief(p) for p in personas)


def scan_unknowns(personas: list[dict], text: str) -> list[dict]:
    """正文里出现了某个人物「不该知道」的原世界术语（只查这个人物在正文里出现的情况）。"""
    issues = []
    for p in mentioned(personas, text):
        for term in leak_terms(text, p.get("unknowns") or []):
            i = text.find(term)
            quote = text[max(0, i - 15): i + len(term) + 15].strip()
            issues.append({"type": "persona", "quote": quote, "found": quote in text,
                           "detail": f"出现了「{term}」：这是「{p['name']}」原世界专属的知识 / 术语，他在这个世界不该知道",
                           "fix": f"删掉或换成本世界里的说法（按他的专业能力在本世界的对应：见人物内核）"})
    return issues


# ---------------------------------------------------------------- 试聊

CHAT_RULES = """你正在扮演小说里的人物「{name}」，和作者对话（作者借此检验人物）。
规则：
1. 始终以「{name}」的身份、思维方式、价值观和说话方式回应；遇到下面的「决策规则」里的情境，按规则做选择。
2. 不要跳出角色，不要提及自己是 AI；不知道的事就表现得不知道——尤其是「他不知道」里列出的东西。
3. 回复格式：台词直接写，动作、神态写在（）里；{inner}
4. 1~4 小段，合计不超过 220 字；有来有往，可以反问、表露情绪。"""
INNER_ON = "最后用〔〕写一句他此刻的内心想法（他为什么这么说 / 这么做）。"
INNER_OFF = "不要写内心独白。"


def _score(query: str, text: str) -> float:
    q, t = _bigrams(query), _bigrams(text)
    return len(q & t) / (len(q) or 1)


def chat_system(character: dict, persona: dict | None, world: str, mode: str, scene: dict, inner: bool,
                retrieved: list[str], summary: str) -> str:
    name = character.get("name") or (persona or {}).get("name") or "角色"
    parts = [CHAT_RULES.format(name=name, inner=INNER_ON if inner else INNER_OFF)]
    if persona:
        parts.append(persona.get("brief") or render_brief(persona))
    card = [f"- {k}：{_text(v, 400)}" for k, v in (character.get("card") or {}).items() if _text(v, 400)]
    if card:
        parts.append("【角色卡】\n" + "\n".join(card))
    if world:
        parts.append("【世界设定】\n" + world[:1500])
    if retrieved:
        parts.append("【参考：他的经历和说话例子（体会方式，不要照抄）】\n" + "\n".join(retrieved))
    if mode == "scene" and scene:
        lines = [f"【当前情境】{_text(scene.get('description'), 400)}"]
        for o in scene.get("others") or []:
            if isinstance(o, dict) and o.get("name"):
                lines.append(f"- 在场的「{_text(o['name'], 20)}」：{_text(o.get('motive'), 120)}")
        if scene.get("narrator"):
            lines.append("作者的话里可能包含环境变化或其他人物的言行；你只扮演「%s」，不要替别人说话。" % name)
        parts.append("\n".join(lines))
    if mode == "interview":
        parts.append("【心理访谈】作者会问一些关于价值观、恐惧、选择的问题。以「%s」的身份如实、具体地回答，"
                     "可以举自己的经历为例，不要说空话。" % name)
    if character.get("userRole"):
        parts.append(f"【对方身份】作者扮演：{_text(character['userRole'], 100)}")
    if summary:
        parts.append(f"【更早的对话（摘要）】{summary}")
    return "\n\n".join(parts)


def anchor(persona: dict | None, name: str, boost: bool) -> str:
    core = "；".join(c["text"] for c in (persona or {}).get("core", [])[:3])
    voice = (persona or {}).get("voice", "")
    text = f"（提醒：你是「{name}」。" + (f"内核：{core}。" if core else "") + (f"说话方式：{voice[:80]}。" if voice else "")
    if boost:
        text += "前几轮有些偏离人物，这一轮请格外贴近上面的内核和决策规则，不要迎合对方。"
    return text + "不要说出他不知道的事。）"


def retrieve(persona: dict | None, query: str, k: int = 3) -> list[str]:
    if not persona or not query:
        return []
    cands = [f"经历：{m.get('scene', '')}——想：{m.get('thought', '')}；做：{m.get('action', '')}" for m in persona.get("memories") or []]
    cands += [f"他说过：「{e.get('line', '')}」（{e.get('context', '')}）" for e in persona.get("examples") or []]
    ranked = sorted(cands, key=lambda c: -_score(query, c))
    return [c for c in ranked[:k] if _score(query, c) > 0] or ranked[:1]


def split_inner(reply: str) -> tuple[str, str]:
    inner = "；".join(x.strip() for x in re.findall(r"〔([^〕]*)〕", reply) if x.strip())
    return re.sub(r"〔[^〕]*〕", "", reply).strip(), inner


def chat(*, character: dict, persona: dict | None, world: str, mode: str, scene: dict, inner: bool,
         messages: list[dict], summary: str, boost: bool, call: Call, summarized_upto: int = 0) -> dict:
    """→ {reply, inner, summary?, summarizedUpTo?, drift?}。messages：全部会话消息（Java 存的）；
    前 summarized_upto 条已经压进 summary，不再发送；没压的超过 CHAT_KEEP + 6 条时把较早的那部分并进摘要。"""
    persona = as_persona(persona)
    name = character.get("name") or (persona or {}).get("name") or "角色"
    messages = [m for m in messages if m.get("role") in ("user", "assistant") and _text(m.get("content"), 1000)]
    upto = max(0, min(summarized_upto, len(messages) - 1)) if summary else 0
    hist = [{"role": m["role"], "content": _text(m.get("content"), 1000)} for m in messages[upto:]]
    if not hist or hist[-1]["role"] != "user":
        raise ValueError("请先输入要对角色说的话")
    out: dict = {}
    if len(hist) > CHAT_KEEP + 6:  # 旧对话压成摘要：摘要已覆盖的不重复压
        old = hist[:-CHAT_KEEP]
        text = "\n".join(f"{'作者' if m['role'] == 'user' else name}：{m['content']}" for m in old)
        raw = call([{"role": "user", "content": (f"已有摘要：{summary}\n\n" if summary else "") +
                     f"把下面这段对话压成 200 字以内的摘要，保留发生了什么、{name}表露出的态度和做过的承诺：\n{text}"}],
                   500, json_mode=False, temperature=0.3)
        summary = _text(raw, 600)
        out["summary"] = summary
        out["summarizedUpTo"] = upto + len(old)   # 绝对位置（在 messages 里）
        hist = hist[-CHAT_KEEP:]
        if hist[0]["role"] == "assistant":  # 部分接口要求 user 先说
            hist.insert(0, {"role": "user", "content": "（接着之前的对话）"})
    system = chat_system(character, persona, world, mode, scene, inner, retrieve(persona, hist[-1]["content"]), summary)
    msgs = [{"role": "system", "content": system}, *hist, {"role": "system", "content": anchor(persona, name, boost)}]
    raw = call(msgs, 600, json_mode=False, temperature=0.85)
    reply = re.sub(rf"^\s*{re.escape(name)}\s*[：:]\s*", "", raw.strip())
    speech, thought = split_inner(reply)
    if not speech:
        raise ValueError("模型没有给出回复，请重试")
    out.update({"reply": speech, "inner": thought})
    turns = sum(1 for m in hist if m["role"] == "assistant") + 1
    if persona and turns % DRIFT_EVERY == 0:
        out["drift"] = drift_check(persona, name, hist[-12:] + [{"role": "assistant", "content": speech}], call)
    return out


def drift_check(persona: dict, name: str, recent: list[dict], call: Call) -> dict:
    text = "\n".join(f"{'作者' if m['role'] == 'user' else name}：{m['content']}" for m in recent)
    leaks = leak_terms("\n".join(m["content"] for m in recent if m["role"] == "assistant"), persona.get("unknowns") or [])
    raw = call([{"role": "system", "content": SYSTEM}, {"role": "user", "content":
                f"{render_brief(persona)}\n\n【最近的对话】\n{text}\n\n检查「{name}」最近的回复有没有偏离上面的人物内核："
                "违背决策规则、说话方式不像、变得一味顺从对方、说出他不该知道的事。只报告确实存在的。\n"
                '输出：{"drift":false,"issues":["…"]}'}], 500)
    data = _parse(raw)
    issues = [_text(x, 200) for x in data.get("issues") or [] if _text(x, 200)]
    issues += [f"说出了他不该知道的「{t}」" for t in leaks]
    return {"drift": bool(data.get("drift")) or bool(leaks), "issues": issues}


# ---------------------------------------------------------------- 辨识度测试

def _anon(text: str, names: list[str]) -> str:
    for n in sorted({x for x in names if x and len(x) >= 2}, key=len, reverse=True):
        text = text.replace(n, "此人")
    return text


def _respond(call: Call, system: str, scene: str, max_chars: int = 220) -> str:
    raw = call([{"role": "system", "content": system},
                {"role": "user", "content": f"【场景】{scene}\n\n以这个人物的身份写出他的反应：他怎么想、怎么做、说什么（{max_chars} 字以内，"
                                            "动作写在（）里，内心写在〔〕里）。"}], 500, json_mode=False, temperature=0.8)
    return _text(raw, max_chars * 2)


def identity_test(proto: dict, ad: dict, call: Call, judge: Call, on_progress, stop: threading.Event | None,
                  *, consistency: int = 2) -> dict:
    """→ 测试报告。A = 适配版人物，B = 只有姓名 / 身份 / 一句话的对照。评委看到的两份反应匿名、顺序打乱。"""
    names = [ad.get("name"), proto.get("name"), *(ad.get("aliases") or []), *(proto.get("aliases") or [])]
    world = ad.get("world", "")
    sys_a = chat_system({"name": ad["name"]}, ad, world, "free", {}, True, [], "")
    sys_b = (f"你扮演小说人物「{ad['name']}」。身份：{ad.get('identity') or ad.get('card', {}).get('role', '')}。"
             f"一句话：{ad.get('card', {}).get('tagline', '') or proto.get('summary', '')}\n【世界设定】{world[:800]}")
    raw = call([{"role": "system", "content": SYSTEM}, {"role": "user", "content":
                f"【世界设定】{world[:1500]}\n【人物】{ad['name']}：{ad.get('identity', '')}\n"
                f"为测试这个人物，出 {len(SITUATIONS)} 个这个世界里的具体场景，分别对应：{'、'.join(SITUATIONS)}；"
                f"再出 2 个「诱导场景」：有人问他、或者情境需要他用到这些他不可能知道的知识：{'、'.join(ad.get('unknowns', [])[:6])}"
                "（场景里不要直接说出这些词以外的提示）。每个场景 40~100 字，写清发生了什么、他需要做什么选择。\n"
                '输出：{"scenes":[{"situation":"面对未知现象","scene":""}],"protective":[{"term":"","scene":""}]}'}], 1500)
    data = _parse(raw)
    scenes = [s for s in data.get("scenes") or [] if isinstance(s, dict) and _text(s.get("scene"), 400)][:len(SITUATIONS)]
    protective = [s for s in data.get("protective") or [] if isinstance(s, dict) and _text(s.get("scene"), 400)][:2]
    if not scenes:
        raise ValueError("没有生成测试场景")
    core_list = "\n".join(f"- {t['text']}" for t in proto.get("traits", []) if t.get("kind") == "core") or \
        "\n".join(f"- {t['text']}" for t in proto.get("traits", [])[:6])
    rules_list = "\n".join(f"- {r['situation']}：{r['reaction']}" for r in proto.get("rules", [])[:8])
    hold = "\n".join(f"- {h['observation']}（原文：{h['quote']}）" for h in proto.get("holdout", [])[:12])
    total = len(scenes) + len(protective) + 2
    step = 0
    results = []
    rng = random.Random(42)

    def tick(msg):
        nonlocal step
        if stop and stop.is_set():
            raise Cancelled("已取消")
        step += 1
        on_progress(int(95 * step / total), msg)

    for i, s in enumerate(scenes):
        a, b = _respond(call, sys_a, s["scene"]), _respond(call, sys_b, s["scene"])
        flip = rng.random() < 0.5
        first, second = (b, a) if flip else (a, b)
        raw = judge([{"role": "system", "content": SYSTEM}, {"role": "user", "content":
                     f"【原型人物的核心特征】\n{core_list}\n【原型的行为规则】\n{rules_list}\n"
                     + (f"【参照：原文里关于他的其他证据】\n{hold}\n" if hold else "") +
                     f"\n【场景】{s['scene']}\n\n【反应 1】{_anon(first, names)}\n\n【反应 2】{_anon(second, names)}\n\n"
                     "你是严格的评委。分别检查两份反应：逐条列出缺陷（违背了哪条核心特征 / 行为规则、哪里不像这个原型），"
                     "每条按 1~5 分严重度扣分，从 100 分扣起；再逐条判断每个核心特征是「体现 / 未体现 / 违背」；最后判断哪一份更像原型人物。\n"
                     '输出：{"r1":{"flaws":[{"issue":"","severity":3}],"traits":{"体现":0,"未体现":0,"违背":0}},'
                     '"r2":{"flaws":[],"traits":{"体现":0,"未体现":0,"违背":0}},"closer":1,"reason":""}'}], 1500)
        j = _parse(raw)
        ra, rb = (j.get("r2"), j.get("r1")) if flip else (j.get("r1"), j.get("r2"))
        closer = re.sub(r"\D", "", str(j.get("closer") or ""))
        picked_a = (closer == "2") if flip else (closer == "1")
        results.append({"situation": _text(s.get("situation"), 40), "scene": _text(s["scene"], 400), "a": a, "b": b,
                        "judgeA": _judged(ra, len(a)), "judgeB": _judged(rb, len(b)), "pickedA": bool(picked_a),
                        "reason": _text(j.get("reason"), 300)})
        tick(f"情境测试 {i + 1}/{len(scenes)}")
    prot = []
    for s in protective:
        a = _respond(call, sys_a, s["scene"])
        term = _text(s.get("term"), 30)
        leaked = leak_terms(a, ad.get("unknowns") or [])
        prot.append({"term": term, "scene": _text(s["scene"], 400), "reply": a, "leaked": leaked})
        tick("保护性测试")
    # 心理访谈：原型（原世界）vs 适配版
    proto_sys = (f"你扮演「{proto['name']}」（在他原来的世界里）。{proto.get('summary', '')}\n"
                 f"核心：{'；'.join(t['text'] for t in proto.get('traits', [])[:8])}\n"
                 f"说话：{proto.get('voice', {}).get('style', '')}")
    qs = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(INTERVIEW))
    ask = (f"依次回答下面的问题（以人物的身份，每题 30~80 字）：\n{qs}\n" + '输出：{"answers":["…"]}')
    ans_p = _parse(call([{"role": "system", "content": proto_sys}, {"role": "user", "content": ask}], 1500)).get("answers") or []
    ans_a = _parse(call([{"role": "system", "content": sys_a}, {"role": "user", "content": ask}], 1500)).get("answers") or []
    pairs = "\n".join(f"{i + 1}. 问：{q}\n   甲：{_anon(_text(x, 200), names)}\n   乙：{_anon(_text(y, 200), names)}"
                      for i, (q, x, y) in enumerate(zip(INTERVIEW, ans_p, ans_a)))
    jv = _parse(judge([{"role": "system", "content": SYSTEM}, {"role": "user", "content":
                f"甲、乙是同一个人物放在两个不同世界里的回答。忽略世界背景、职业和用词的差别，只比较价值观、恐惧、面对选择时的倾向"
                f"是否一致。逐题判断 一致 / 部分一致 / 不一致。\n{pairs}\n" + '输出：{"items":["一致"],"note":""}'}], 800))
    items = [str(x) for x in jv.get("items") or []]
    agree = sum(1 for x in items if x.startswith("一致")) + 0.5 * sum(1 for x in items if x.startswith("部分"))
    tick("心理访谈")
    # 一致性：同一场景再生成一次，判断两次决策是否一致
    cons = []
    for s in scenes[:consistency]:
        again = _respond(call, sys_a, s["scene"])
        first = next(r["a"] for r in results if r["scene"] == _text(s["scene"], 400))
        jc = _parse(judge([{"role": "system", "content": SYSTEM}, {"role": "user", "content":
                     f"【场景】{s['scene']}\n【第一次】{first}\n【第二次】{again}\n两次里人物做出的决策和态度是否一致（措辞不同不算）？"
                     '输出：{"consistent":true,"note":""}'}], 300))
        cons.append({"scene": _text(s["scene"], 200), "again": again, "consistent": bool(jc.get("consistent")),
                     "note": _text(jc.get("note"), 200)})
    tick("一致性")
    n = len(results)
    summary = {
        "scenes": n,
        "scoreA": round(sum(r["judgeA"]["score"] for r in results) / n, 1),
        "scoreB": round(sum(r["judgeB"]["score"] for r in results) / n, 1),
        "manifestA": _rate(results, "judgeA"), "manifestB": _rate(results, "judgeB"),
        "violationsA": sum(r["judgeA"]["traits"].get("违背", 0) for r in results),
        "pickedA": round(sum(r["pickedA"] for r in results) / n, 2),
        "leaks": sum(len(p["leaked"]) for p in prot) + sum(len(leak_terms(r["a"], ad.get("unknowns") or [])) for r in results),
        "interviewAgreement": round(agree / len(items), 2) if items else None,
        "consistency": round(sum(c["consistent"] for c in cons) / len(cons), 2) if cons else None,
    }
    on_progress(100, f"完成：A {summary['scoreA']} 分 vs 对照 {summary['scoreB']} 分，评委选中 A {int(summary['pickedA'] * 100)}%")
    return {"summary": summary, "scenes": results, "protective": prot,
            "interview": {"questions": INTERVIEW, "prototype": ans_p, "adapted": ans_a, "verdicts": items,
                          "note": _text(jv.get("note"), 300)},
            "consistency": cons}


def _judged(r, length: int) -> dict:
    r = r if isinstance(r, dict) else {}
    def num(v, default: int) -> int:
        m = re.search(r"\d+", str(v if v is not None else ""))
        return int(m.group()) if m else default

    flaws = [{"issue": _text(f.get("issue"), 200), "severity": max(1, min(5, num(f.get("severity"), 1)))}
             for f in r.get("flaws") or [] if isinstance(f, dict) and _text(f.get("issue"), 200)]
    raw = 100 - sum(f["severity"] * 4 for f in flaws)
    score = max(0, min(100, raw + min(10, length // 100)))  # 长度校正：越长越容易被挑出缺陷
    t = r.get("traits") if isinstance(r.get("traits"), dict) else {}
    return {"flaws": flaws, "score": score, "traits": {k: num(t.get(k), 0) for k in ("体现", "未体现", "违背")}}


def _rate(results: list[dict], key: str) -> float | None:
    shown = sum(r[key]["traits"]["体现"] for r in results)
    total = sum(sum(r[key]["traits"].values()) for r in results)
    return round(shown / total, 2) if total else None


def call_for(cfg=None, session=None, usage: dict | None = None) -> Call:
    """统一的模型调用：cfg = OpenAI 兼容（大模型 / GGUF），session = 应用内本地模型（LocalSession）。"""
    from . import llm_client

    def call(messages, max_tokens, json_mode=True, temperature=None):
        if session is not None:  # 应用内本地模型：温度固定（LocalSession.chat 为提取设计，0.2）
            return session.chat(messages, max_tokens)
        if json_mode and temperature is None:
            return llm_client.chat(cfg, messages, max_tokens=max_tokens, usage=usage)
        r = llm_client.complete(cfg, messages, max_tokens=max_tokens, temperature=temperature or 0.7, top_p=0.95,
                                json_mode=json_mode)
        if usage is not None:
            usage["calls"] = usage.get("calls", 0) + 1
            usage["promptTokens"] = usage.get("promptTokens", 0) + r["promptTokens"]
            usage["completionTokens"] = usage.get("completionTokens", 0) + r["completionTokens"]
        return r["text"]

    return call
