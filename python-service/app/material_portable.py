"""架空加工（素材库，2026-11-06）：把一条原素材加工成「能搬到别的小说里用」的架空版——通用名、
可移植内核、原作绑定、叙事用途、换世界时替换 / 保留什么，再加一段放进另一个世界的架空示例。

思路同跨世界观角色卡（persona）：先分出核心和原世界专属，再由代码查原作专名有没有漏进示例。
每张卡调用 1 次模型；代码做的校验（不靠模型自觉）：
- bindings 的 term 必须真的出现在卡片原文里，否则丢掉；
- portability：有「依赖设定」类绑定 = adapt，否则 direct（模型给的不算）；
- example 里查原作专名（专名类绑定 + 人物 / 势力 / 地点 / 物品类卡片的名称和别名 + 共鸣卡里这些类节点的名称），
  漏了就带着「不要出现 X」重试 1 次，还漏就保留结果、把漏掉的词记进 leaks（页面标红）。
共鸣卡：整个关系网一起架空，nodeMap 给每个节点一个通用「角色 / 功能」+ 换成什么，联动规则改写成不带专名的通用形式。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable

from . import material_facts as mf
from .materials import CATEGORIES

log = logging.getLogger(__name__)

SYSTEM = "你是小说素材的架空改编师：把一部小说里的设定提炼成可以搬到别的小说里用的素材。只输出 JSON，不要任何多余文字。"
TOKENS = 2500
# 名称本身就是原作专名的分类：示例里不能出现它们的名字（世界观 / 写法 / 共鸣卡的名称多是通用概念，不查）
NAMED_CATS = ("character", "faction", "location", "item", "monster")
BIND_KINDS = ("专名", "依赖设定")


def _clip(v, n: int) -> str:
    if isinstance(v, (dict, list)):
        v = json.dumps(v, ensure_ascii=False)
    return str(v or "").strip()[:n]


def card_text(c: dict) -> str:
    """卡片原文（给模型看，也用来核对 bindings）"""
    parts = [f"名称：{c.get('title') or ''}"]
    if c.get("aliases"):
        parts.append("别名：" + "、".join(map(str, c["aliases"]))[:120])
    for k, label in (("subtype", "细分"), ("summary", "概括"), ("detail", "详细")):
        if c.get(k):
            parts.append(f"{label}：{_clip(c[k], 1200)}")
    attrs = c.get("attributes") or {}
    if isinstance(attrs, dict) and attrs:
        parts.append("属性：" + "；".join(f"{k}：{_clip(v, 150)}" for k, v in attrs.items() if v)[:900])
    facts = [f for f in c.get("facts") or [] if isinstance(f, dict) and f.get("fact")][:8]
    if facts:
        parts.append("原文事实：" + "；".join(_clip(f["fact"], 60) for f in facts))
    if c.get("kind") == "craft" and c.get("rules"):
        parts.append("规律：" + "；".join(_clip(r.get("text") if isinstance(r, dict) else r, 120) for r in c["rules"][:8]))
    if c.get("kind") == "resonance":
        nodes = c.get("nodes") or []
        parts.append("节点：" + "；".join(f"[{n.get('id')}] {n.get('title')}（{n.get('role') or ''}：{_clip(n.get('note'), 40)}）"
                                         for n in nodes if isinstance(n, dict)))
        titles = {n.get("id"): n.get("title") for n in nodes if isinstance(n, dict)}
        rules = []
        for r in c.get("rules") or []:
            if isinstance(r, dict) and isinstance(r.get("if"), dict):
                then = "，".join(f"{titles.get(t.get('node'), t.get('node'))}{_clip(t.get('effect'), 40)}" for t in r.get("then") or []
                                if isinstance(t, dict))
                rules.append(f"{titles.get(r['if'].get('node'), '')}{_clip(r['if'].get('change'), 40)} → {then}")
        if rules:
            parts.append("联动规则：" + "；".join(rules)[:800])
    return "\n".join(parts)


def _kind(c: dict) -> str:
    k = c.get("kind")
    if k in ("craft", "resonance"):
        return k
    if k in ("world", "system") or c.get("category") == "world":
        return "world"
    return "entity"


FOCUS = {
    "entity": "core 写成去掉人名地名后的人物 / 东西的骨架（它是什么样的存在、靠什么立住）；uses 写它在故事里能承担的功能（视角人物、对手、导师、钩子、冲突来源……）。",
    "world": "core 写成这套制度 / 体系的运转机制（谁掌握、凭什么、代价是什么、怎么晋升 / 失效）；uses 写它天然能产生的冲突和剧情。",
    "craft": "这是一张写法卡：bindings 只列规律里引用的原作例子（人名、事件名）；core 写去掉例子后的手法本身；example 换一个题材演示这条手法（可以是一小段示范写法）；uses 写这条手法适合用在什么场景。",
    "resonance": "这是一张共鸣素材（一组互相牵连的设定）：要把整个关系网一起架空。nodeMap 给每个节点一个通用的「角色 / 功能」（如「门槛型力量来源」「授权机构」），并说明在新世界换成什么；"
                 "rules 把联动规则改写成不带原作专名的通用形式（如「力量来源被削弱 → 授权机构失去合法性」）；example 写整套体系放进新世界之后是什么样子。",
}


def prompt(c: dict, target_world: str = "", avoid: list[str] | None = None) -> str:
    k = _kind(c)
    world = (f"架空示例放进这个世界：{target_world}。" if target_world
             else "架空示例自己选一个和原作类型差别大的世界（比如原作是西幻就换成修仙 / 科幻 / 现代都市等），在 exampleWorld 里写明。")
    extra = ""
    if k == "resonance":
        extra = ('"nodeMap":[{"node":"n1","role":"通用角色 / 功能，不超过12字","replaceWith":"在示例世界里换成什么，不超过20字"}],'
                 '"rules":[{"if":"通用的「某类节点怎么变」，不超过30字","then":"其他节点要跟着怎么变，不超过40字"}],')
    out = ('{"title":"架空版的通用名，不出现原作专名，不超过12字（如「异乡学徒」「血脉骑士制度」）",'
           '"core":"可移植内核，不出现原作专名，不超过80字",'
           '"bindings":[{"term":"原文里出现的词","kind":"' + "/".join(BIND_KINDS) + '","note":"它绑定在原作的什么上，不超过30字"}],'
           '"uses":["叙事用途，不超过40字"],'
           '"replace":[{"from":"原作里的东西","to":"换世界时换成什么样的东西"}],'
           '"keep":["换到哪个世界都要保留的要点，不超过30字"],' + extra +
           '"exampleWorld":"示例用的世界，不超过20字","example":"架空示例：200–400 字"}')
    ban = f"\n示例里绝对不要出现这些词：{'、'.join(avoid)}。" if avoid else ""
    return (f"下面是从一部小说里整理出的一张卡片：\n\n{card_text(c)}\n\n"
            "把它加工成能搬到别的小说里用的素材。\n"
            f"{FOCUS[k]}\n"
            "bindings：只列原文里真的出现的、绑定原作的词，分两种——「专名」= 只是名字（人名 / 地名 / 组织名 / 物品名），换个名字就行；"
            "「依赖设定」= 它要成立必须有的原作设定（力量来源、血脉、宗教 / 政治机构、穿越、金手指……），换到新世界必须找一个替代物，否则它就不成立。"
            "像「血脉」「教会」这种决定它怎么运转的，算依赖设定，不算专名。没有就输出空数组。\n"
            "uses 3–5 条；replace 列换世界时要替换的东西；keep 2–5 条，少了就不是它了。\n"
            f"{world}示例里不能出现原作的人名、地名、组织名和专有术语，要换成新世界自己的东西；"
            f"不要只把原名改一两个字（「圣光护盾」改成「圣光灵盾」不行），要按新世界的风格重新起名。{ban}\n"
            f"输出 JSON：{out}")


def _named_terms(c: dict) -> list[str]:
    terms = []
    if c.get("category") in NAMED_CATS:
        terms.append(str(c.get("title") or ""))
        terms += [str(a) for a in c.get("aliases") or []]
    for n in c.get("nodes") or []:
        if isinstance(n, dict) and n.get("category") in NAMED_CATS:
            terms.append(str(n.get("title") or ""))
    return terms


def leak_terms(text: str, terms: list[str]) -> list[str]:
    """示例里漏出来的原作专名（≥2 字，去重保序）"""
    seen, out = set(), []
    for t in terms:
        t = t.strip()
        if len(t) >= 2 and t not in seen and t in text:
            seen.add(t)
            out.append(t)
    return out


def to_portable(data: dict, c: dict) -> dict | None:
    """模型输出 → 档案（校验 bindings、自动判断 portability、查泄漏）；没有 core 或 example 算失败 → None"""
    if not isinstance(data, dict):
        return None
    core = mf._text(data.get("core"), 160)
    example = re.sub(r"^\s*(架空示例|示例)\s*[:：]\s*", "", mf._text(data.get("example"), 1200))
    if not core or not example:
        return None
    source = card_text(c)
    bindings, seen = [], set()
    for b in data.get("bindings") or []:
        if not isinstance(b, dict):
            continue
        term = mf._text(b.get("term"), 30)
        if len(term) < 2 or term in seen or term not in source:  # 原文里没有的词不算绑定（模型编的）
            continue
        seen.add(term)
        bindings.append({"term": term, "kind": b.get("kind") if b.get("kind") in BIND_KINDS else "专名",
                         "note": mf._text(b.get("note"), 60)})
    replace = []
    for r in data.get("replace") or []:
        if isinstance(r, dict) and mf._text(r.get("from"), 40) and mf._text(r.get("to"), 60):
            replace.append({"from": mf._text(r.get("from"), 40), "to": mf._text(r.get("to"), 60)})
    title = mf._text(data.get("title"), 24)
    out = {
        "title": title,
        "core": core,
        "bindings": bindings[:20],
        "uses": [mf._text(u, 80) for u in data.get("uses") or [] if mf._text(u, 80)][:6],
        "replace": replace[:10],
        "keep": [mf._text(k, 60) for k in data.get("keep") or [] if mf._text(k, 60)][:6],
        "portability": "adapt" if any(b["kind"] == "依赖设定" for b in bindings) else "direct",
        "exampleWorld": mf._text(data.get("exampleWorld"), 40),
        "example": example,
    }
    if _kind(c) == "resonance":
        ids = {n.get("id"): n for n in c.get("nodes") or [] if isinstance(n, dict)}
        node_map = []
        for x in data.get("nodeMap") or []:
            if isinstance(x, dict) and (n := ids.get(str(x.get("node") or "").strip().lower())):
                node_map.append({"node": n["id"], "title": n.get("title") or "", "role": mf._text(x.get("role"), 30),
                                 "replaceWith": mf._text(x.get("replaceWith"), 40)})
        out["nodeMap"] = node_map
        out["rules"] = [{"if": mf._text(r.get("if"), 60), "then": mf._text(r.get("then"), 80)}
                        for r in data.get("rules") or [] if isinstance(r, dict) and mf._text(r.get("if"), 60)][:8]
    terms = [b["term"] for b in bindings if b["kind"] == "专名"] + _named_terms(c)
    out["leaks"] = leak_terms(out["title"] + " " + out["example"] + " " + " ".join(r.get("then", "") for r in out.get("rules", [])), terms)
    return out


def portable_one(c: dict, call: Callable[[list[dict], int], str], target_world: str = "") -> dict | None:
    """一张卡：调 1 次模型，示例漏了原作专名再重试 1 次（带禁用词），还漏就保留并记 leaks"""
    def ask(avoid=None) -> dict | None:
        text = call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt(c, target_world, avoid)}], TOKENS)
        return to_portable(mf._parse(text), c)

    first = ask()
    if first and first["leaks"]:
        try:
            second = ask(first["leaks"])
        except Exception as e:  # noqa: BLE001 重试失败就用第一次的结果
            if getattr(e, "fatal", False):
                raise
            log.warning("架空加工重试失败：%s", e)
            second = None
        if second and len(second["leaks"]) < len(first["leaks"]):
            first = second
    if first:
        first["targetWorld"] = target_world
    return first


if __name__ == "__main__":  # 离线自测（不调模型）
    card = {"id": 1, "version": 2, "kind": "entity", "category": "character", "title": "夏风", "aliases": ["路西恩"],
            "summary": "内向腼腆的穿越学生，在阿尔托城的书店边打工边学文字谋生",
            "facts": [{"fact": "夏风穿越到阿尔托城"}]}
    good = {"core": "异乡人靠学语言从底层立足的成长型角色",
            "bindings": [{"term": "穿越", "kind": "依赖设定"}, {"term": "阿尔托城", "kind": "专名"}, {"term": "魔网", "kind": "专名"}],
            "uses": ["视角人物"], "replace": [{"from": "穿越", "to": "外来者"}], "keep": ["内向"],
            "exampleWorld": "修仙", "example": "少年林舟逃难到青云宗，在杂役房做工认符文。"}
    p = to_portable(good, card)
    assert [b["term"] for b in p["bindings"]] == ["穿越", "阿尔托城"], p["bindings"]   # 魔网不在原文：丢掉
    assert p["portability"] == "adapt" and p["leaks"] == []
    leak = dict(good, example="夏风来到青云宗，在阿尔托城一样的集市打工。")
    assert to_portable(leak, card)["leaks"] == ["阿尔托城", "夏风"]
    assert to_portable(dict(good, bindings=[{"term": "阿尔托城", "kind": "专名"}]), card)["portability"] == "direct"
    assert to_portable({"core": "x"}, card) is None
    calls = []

    def fake(msgs, _n):
        calls.append(msgs[-1]["content"])
        return json.dumps(leak if len(calls) == 1 else good, ensure_ascii=False)

    r = portable_one(card, fake)
    assert len(calls) == 2 and "不要出现" in calls[1] and r["leaks"] == []
    assert to_portable(dict(good, title="夏风式学徒"), card)["leaks"] == ["夏风"]   # 通用名里也不能有原作专名
    res = {"core": "c", "example": "力量之源衰竭后，授权的宗门失去号召力。", "nodeMap": [{"node": "N1", "role": "力量来源", "replaceWith": "灵脉"}, {"node": "n9"}],
           "rules": [{"if": "力量来源被削弱", "then": "授权机构失去合法性"}]}
    rc = {"kind": "resonance", "category": "resonance", "title": "神恩体系",
          "nodes": [{"id": "n1", "title": "神恩", "category": "world"}, {"id": "n2", "title": "圣光教会", "category": "faction"}]}
    pr = to_portable(res, rc)
    assert [x["node"] for x in pr["nodeMap"]] == ["n1"] and pr["rules"] and pr["leaks"] == []
    assert to_portable(dict(res, example="圣光教会失去号召力"), rc)["leaks"] == ["圣光教会"]
    print("material_portable 自测通过")
