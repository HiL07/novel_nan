"""共鸣素材（卡片整理，2026-11-04）：把同一本书里同一个主题下的卡片（世界观卡 / 体系卡 / 实体卡）关联成一个整体——
节点 + 关系图、联动规则（改了谁就要跟着改谁）、综合描述（含缺口）、融入其他世界观的指南。

和世界观卡的区别：世界观卡把**实体**聚成一张卡；共鸣素材把**卡片**（可以含世界观卡）关联成一张大图，层级更高。

两步：
1. propose：模型按主题给卡片分组（只是建议，作者增删成员后才生成）；代码校验编号、每组 3–15 张、一张卡最多进 2 组。
2. compile_resonance：每组调用 1 次。节点由代码按成员卡编号（n1…nk），模型只能按编号写边 / 联动规则 / 融入指南；
   代码核对：两端节点不存在的边和规则丢掉，引用不存在节点的融入指南条目丢掉，没有一条合法边的结果算失败。
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from collections import Counter
from typing import Callable

from . import llm_client
from . import material_facts as mf
from .llm_client import ModelConfig, parse_json
from .materials import CATEGORIES, _norm_title

log = logging.getLogger(__name__)

BATCH = 120
MIN_MEMBERS, MAX_MEMBERS = 3, 15
MAX_GROUPS_PER_CARD = 2
MAX_CARD_FACTS = 6
MAX_FACTS = 40
CARD_TOKENS = 3000
ROLES = ("核心", "规则", "代价", "载体", "组织", "人物", "场所", "现象", "其他")
EDGE_TYPES = ("依赖", "限制", "产生", "对立", "属于", "层级", "制约")
KIND_LABEL = {"world": "世界观卡", "system": "体系卡", "entity": "实体卡"}
SYSTEM = "你是小说世界观架构师，只输出 JSON，不要任何多余文字。"


def _label(c: dict) -> str:
    cat = CATEGORIES.get(c.get("category"), (c.get("category") or "",))[0]
    return f"{KIND_LABEL.get(c.get('kind'), '卡')}·{cat}"


# ---------------------------------------------------------------- 1. 分组提议

def _group_prompt(cards: list[dict]) -> str:
    lines = [f"{i}. {c['title']}【{_label(c)}】：{str(c.get('summary') or '')[:50]}" for i, c in enumerate(cards, 1)]
    return ("下面是一本小说整理出的设定卡片（编号. 名称【类型】：一句话）。按**主题**把相关的卡片分成组，"
            "每组以后会被关联成一张「共鸣素材」：画出这些设定之间的依赖 / 限制 / 对立关系，以及改了一个其他哪些要跟着改。\n"
            "好的主题：一套力量体系（如魔法体系：环级、施法材料、精神力、法师组织、魔法书籍……），一个宗教 / 政治结构，"
            "一个职业或阶层体系，一个城市的势力格局。可以跨类型。\n"
            f"规则：每组 {MIN_MEMBERS}–{MAX_MEMBERS} 张；只是同一场景出现、但互相没有设定上的牵连的不要放一组；拿不准就不分；没有合适的输出空数组。\n"
            '输出：{"groups":[{"name":"主题名，不超过12字","ids":[编号,编号],"reason":"不超过30字"}]}\n\n' + "\n".join(lines))


def propose(cards: list[dict], cfg: ModelConfig) -> dict:
    """cards：[{id, kind, category, title, summary}] → {groups: [{name, cardIds, reason}], usage}"""
    usage: dict = llm_client.new_usage(cfg)
    items = [c for c in cards if isinstance(c, dict) and c.get("id") is not None and c.get("title")]
    groups: list[dict] = []
    count: Counter = Counter()
    for start in range(0, min(len(items), BATCH * 3), BATCH):
        batch = items[start:start + BATCH]
        if len(batch) < MIN_MEMBERS:
            continue
        text = llm_client.chat(cfg, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _group_prompt(batch)}],
                               max_tokens=min(4000, 400 + 25 * len(batch)), usage=usage)
        try:
            data = parse_json(text)
        except (ValueError, TypeError):
            log.warning("共鸣分组：模型输出不是 JSON（%d 张）", len(batch))
            continue
        for g in (data.get("groups") or []) if isinstance(data, dict) else []:
            if not isinstance(g, dict):
                continue
            ids = []
            for i in g.get("ids") or []:
                try:
                    i = int(i)
                except (TypeError, ValueError):
                    continue
                if 1 <= i <= len(batch):
                    cid = batch[i - 1]["id"]
                    if cid not in ids and count[cid] < MAX_GROUPS_PER_CARD:
                        ids.append(cid)
            name = str(g.get("name") or "").strip()[:20]
            if len(ids) < MIN_MEMBERS or not name:
                continue
            count.update(ids)
            groups.append({"name": name, "cardIds": ids[:MAX_MEMBERS], "reason": str(g.get("reason") or "").strip()[:60]})
    return {"groups": groups, "usage": usage}


# ---------------------------------------------------------------- 2. 生成

def _card_prompt(name: str, nodes: list[dict]) -> str:
    blocks = []
    for n in nodes:
        c = n["card"]
        attrs = "；".join(f"{k}：{str(v)[:80]}" for k, v in (c.get("attributes") or {}).items() if v)[:400]
        facts = "；".join(str(f.get("fact"))[:50] for f in (c.get("facts") or [])[:MAX_CARD_FACTS] if isinstance(f, dict))
        blocks.append(f"[{n['id']}] {c['title']}【{_label(c)}】\n概括：{c.get('summary') or ''}\n"
                      + (f"详细：{str(c.get('detail') or '')[:300]}\n" if c.get("detail") else "")
                      + (f"属性：{attrs}\n" if attrs else "") + (f"原文事实：{facts}" if facts else ""))
    return (f"主题「{name}」由下面这些设定节点组成（[编号] 名称【类型】）：\n\n" + "\n\n".join(blocks) +
            "\n\n把它们关联成一张共鸣素材，输出 JSON：\n"
            '{"title":"共鸣素材名称（不超过16字）","summary":"一句话说清这个主题（不超过60字）",'
            '"detail":"200–400字的综合描述：这些设定合在一起是怎样一个整体",'
            '"nodes":[{"id":"n1","role":"' + "/".join(ROLES) + '","note":"它在这个整体里起什么作用，不超过40字"}],'
            '"edges":[{"from":"n1","to":"n2","type":"' + "/".join(EDGE_TYPES) + '","note":"不超过30字"}],'
            '"rules":[{"if":{"node":"n1","change":"如果这个节点怎么改（不超过30字）"},"then":[{"node":"n2","effect":"它要跟着怎么改（不超过40字）"}]}],'
            '"fusion":{"keep":[{"node":"n3","why":"为什么能直接搬到别的世界（不超过30字）"}],'
            '"replace":[{"node":"n1","why":"为什么要换（不超过30字）","hint":"换成什么样的东西（不超过40字）"}],'
            '"cascade":"替换之后按联动规则还要调整什么（不超过150字）"},'
            '"gaps":["原书里这个主题还没讲清楚、借用时要自己补的地方（不超过40字）"]}\n'
            "要求：只能用上面给出的编号，不要新增节点；edges / rules 只写原文事实和卡片内容能支持的关系，不编造；"
            "rules 写 2–6 条最关键的联动；fusion 的 keep / replace 要覆盖大多数节点；gaps 0–5 条。")


def _node(v, ids: set[str]) -> str | None:
    s = str(v or "").strip().lower()
    return s if s in ids else None


def _names(text: str, titles: dict[str, str]) -> str:
    """模型在文字里写的节点编号（n3）换成节点名，读者看不懂编号。"""
    # 不用「单词边界」：中文字符也算单词字符，「n1的」里 1 和「的」之间没有边界
    def sub(m: re.Match) -> str:
        t = titles.get("n" + m.group(1))
        return f"「{t}」" if t else m.group(0)

    return re.sub(r"(?<![A-Za-z0-9])[nN](\d{1,2})(?![0-9])", sub, text or "")


def to_card(data: dict, name: str, nodes: list[dict]) -> dict | None:
    if not isinstance(data, dict):
        return None
    ids = {n["id"] for n in nodes}
    titles = {n["id"]: n["card"]["title"] for n in nodes}
    fix = lambda v, n: _names(mf._text(v, n), titles)  # noqa: E731
    meta = {}
    for x in data.get("nodes") or []:
        if isinstance(x, dict) and (nid := _node(x.get("id"), ids)):
            role = x.get("role") if x.get("role") in ROLES else "其他"
            meta[nid] = {"role": role, "note": fix(x.get("note"), 60)}
    out_nodes = [{"id": n["id"], "cardId": n["card"]["id"], "title": n["card"]["title"], "kind": n["card"].get("kind"),
                  "category": n["card"].get("category"), **meta.get(n["id"], {"role": "其他", "note": ""})} for n in nodes]
    edges, seen = [], set()
    for e in data.get("edges") or []:
        if not isinstance(e, dict):
            continue
        a, b = _node(e.get("from"), ids), _node(e.get("to"), ids)
        t = e.get("type") if e.get("type") in EDGE_TYPES else None
        if a and b and a != b and t and (a, b, t) not in seen:
            seen.add((a, b, t))
            edges.append({"from": a, "to": b, "type": t, "note": fix(e.get("note"), 50)})
    if not edges:
        return None
    rules = []
    for r in data.get("rules") or []:
        if not isinstance(r, dict) or not isinstance(r.get("if"), dict):
            continue
        src = _node(r["if"].get("node"), ids)
        change = fix(r["if"].get("change"), 60)
        then = [{"node": t, "effect": fix(x.get("effect"), 60)} for x in r.get("then") or []
                if isinstance(x, dict) and (t := _node(x.get("node"), ids)) and t != src and mf._text(x.get("effect"), 60)]
        if src and change and then:
            rules.append({"if": {"node": src, "change": change}, "then": then[:6]})
    fz = data.get("fusion") if isinstance(data.get("fusion"), dict) else {}
    keep = [{"node": n, "why": fix(x.get("why"), 60)} for x in fz.get("keep") or []
            if isinstance(x, dict) and (n := _node(x.get("node"), ids))]
    replace = [{"node": n, "why": fix(x.get("why"), 60), "hint": fix(x.get("hint"), 80)} for x in fz.get("replace") or []
               if isinstance(x, dict) and (n := _node(x.get("node"), ids))]
    gaps = [fix(g, 80) for g in data.get("gaps") or [] if mf._text(g, 80)][:5]
    facts = [{"fact": f.get("fact"), "quote": f.get("quote") or "", "chapter": f.get("chapter") or "", "entity": n["card"]["title"]}
             for n in nodes for f in (n["card"].get("facts") or [])[:MAX_CARD_FACTS] if isinstance(f, dict) and f.get("fact")][:MAX_FACTS]
    title = mf._text(data.get("title"), 40) or name
    attrs = {"节点": "、".join(n["title"] for n in out_nodes)[:300],
             "联动规则": "；".join(f"{r['if']['change']} → " + "，".join(t["effect"] for t in r["then"]) for r in rules)[:300],
             "融入指南": fix(fz.get("cascade"), 300),
             "缺口": "；".join(gaps)[:300]}
    return {
        "candidateId": "resonance:" + hashlib.sha1(_norm_title(name).encode()).hexdigest()[:12],
        "kind": "resonance",
        "category": "resonance",
        "subtype": "共鸣",
        "title": title,
        "theme": name,
        "summary": mf._text(data.get("summary"), 120),
        "detail": fix(data.get("detail"), 2000),
        "attributes": {k: v for k, v in attrs.items() if v},
        "tags": [name, "共鸣"],
        "excerpt": "",
        "chapters": sorted({str(f["chapter"]) for f in facts if f["chapter"]})[:50],
        "facts": facts,
        "nodes": out_nodes,
        "edges": edges,
        "rules": rules,
        "fusion": {"keep": keep, "replace": replace, "cascade": fix(fz.get("cascade"), 300)},
        "gaps": gaps,
    }


def compile_resonance(groups: list[dict], cards: list[dict], call: Callable[[list[dict], int], str], concurrency: int, ckpt,
                      on_progress: Callable[[int, str], None], stop: threading.Event | None) -> dict:
    """groups：[{name, cardIds}]（作者确认过）；cards：成员卡 [{id, kind, category, title, summary, detail, attributes, facts}]。"""
    by_id = {c["id"]: c for c in cards if isinstance(c, dict) and c.get("id") is not None}
    jobs = {}
    for g in groups:
        members = [by_id[i] for i in g.get("cardIds") or [] if i in by_id][:MAX_MEMBERS]
        if len(members) >= 2 and g.get("name"):
            nodes = [{"id": f"n{k}", "card": c} for k, c in enumerate(members, 1)]
            jobs[_norm_title(g["name"])] = (str(g["name"])[:20], nodes)
    stats = {"entities": sum(len(n) for _, n in jobs.values()), "cards": 0, "notUseful": 0, "systems": 0, "arcs": 0,
             "failedCards": 0, "resonanceCards": 0}
    lock = threading.Lock()
    done = ckpt.done("resonance")

    def make(k: str) -> None:
        name, nodes = jobs[k]
        text = call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": _card_prompt(name, nodes)}], CARD_TOKENS)
        with lock:
            ckpt.append("resonance", k, mf._parse(text))

    mf._parallel([k for k in jobs if k not in done], make, workers=concurrency, stop=stop, lock=lock,
                 on_progress=on_progress, label="整理共鸣素材", base=0, span=98, total=len(jobs),
                 failed=stats, fail_key="failedCards")
    out = []
    for k, (name, nodes) in jobs.items():
        card = to_card(ckpt.done("resonance").get(k), name, nodes)
        if card:
            out.append(card)
        else:
            stats["notUseful"] += 1
    stats["resonanceCards"] = stats["cards"] = len(out)
    return {"materials": out, "stats": stats}
