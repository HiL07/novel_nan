"""世界观卡（卡片整理，2026-11-03）：把相关的实体（可以跨分类，如骑士、骑士侍从、骑士精神、贵族）总结成一张
「这个设定在这个世界里是什么」的卡，记下成员和与其他设定的关系（以后做关联的入口）。

两步：
1. propose_groups：模型提议分组（只是建议，作者在界面上改名 / 增删成员 / 不要整组之后才整理）。
   给模型的是名称、分类、第一条事实，再加代码算的「常在同一章出现」的提示；代码校验编号、≥2 个成员、每个实体最多进 2 组。
2. compile_world：每组调用 1 次，输入成员的事实（带原文）和已有的实体卡概括；只依据事实，不编造。
   代码核对：关系的对象必须是本组成员、别的分组或实体档案里的实体，否则丢掉；空属性丢掉。
"""
from __future__ import annotations

import hashlib
import logging
import threading
from collections import Counter
from itertools import combinations
from typing import Callable

from . import llm_client
from . import material_facts as mf
from .llm_client import ModelConfig, parse_json
from .materials import CATEGORIES, _norm_title

log = logging.getLogger(__name__)

BATCH = 150
MAX_GROUPS_PER_ENTITY = 2
MAX_MEMBER_FACTS = 10
MAX_FACTS = 40
CARD_TOKENS = 1600
SYSTEM = "你是小说世界观整理助手，只输出 JSON，不要任何多余文字。"
ATTRS = ["定义", "组成与层级", "规则与代价", "在世界中的位置", "原作用法", "借用提示"]


# ---------------------------------------------------------------- 1. 分组提议

def _chapters_of(e: dict) -> set:
    return {f.get("ci", f.get("chapter")) for f in e.get("facts") or [] if isinstance(f, dict)}


def _cooccur(items: list[dict], limit: int = 30) -> list[tuple[int, int, int]]:
    """同章出现最多的实体对（编号从 1 数）：[(i, j, 共同章数)]，共同 ≥2 章才算。"""
    chs = [_chapters_of(e) for e in items]
    pairs = []
    for i, j in combinations(range(len(items)), 2):
        n = len(chs[i] & chs[j])
        if n >= 2:
            pairs.append((n, i + 1, j + 1))
    pairs.sort(reverse=True)
    return [(i, j, n) for n, i, j in pairs[:limit]]


def _group_prompt(items: list[dict]) -> str:
    lines = []
    for i, e in enumerate(items, 1):
        fact = next((f.get("fact") for f in e.get("facts") or [] if isinstance(f, dict) and f.get("fact")), "")
        cat = CATEGORIES.get(e.get("category"), (e.get("category"),))[0]
        lines.append(f"{i}. {e['name']}【{cat}】：{str(fact)[:40]}")
    co = _cooccur(items)
    hint = ("\n常在同一章出现（编号对：共同章数）：" + "；".join(f"{i}-{j}:{n}" for i, j, n in co)) if co else ""
    return ("下面是一本小说的设定条目（编号. 名称【分类】：一条事实）。把属于同一个世界观主题的条目分成组，"
            "每组以后会被总结成一张「这个设定在这个世界里是什么」的世界观卡。\n"
            "好的分组：一个制度 / 职业 / 组织体系连同它的成员、规矩和相关概念（如「骑士」「骑士侍从」「骑士精神」「授勋仪式」→ 骑士制度），"
            "一套力量体系连同它的等级和代价，一种信仰连同它的教会、神职和禁忌。可以跨分类（人物、势力、物品、世界观、地点混在一组）。\n"
            "规则：只是在同一场景出现、但不属于同一主题的不要放一组；单个人物不要当成一个主题；每组 2–12 个条目；"
            "拿不准就不分；没有合适的就输出空数组。\n"
            '输出：{"groups":[{"name":"主题名，不超过12字","ids":[编号,编号],"reason":"不超过30字"}]}\n\n'
            + "\n".join(lines) + hint)


def propose_groups(entities: list[dict], cfg: ModelConfig) -> dict:
    """entities：实体档案（事实多的在前，带 facts[ci]）→ {groups: [{name, members: [key], reason}], usage}。"""
    usage: dict = llm_client.new_usage(cfg)
    items = [e for e in entities if isinstance(e, dict) and e.get("key") and e.get("name")]
    groups: list[dict] = []
    count: Counter = Counter()
    for start in range(0, min(len(items), BATCH * 3), BATCH):
        batch = items[start:start + BATCH]
        if len(batch) < 2:
            continue
        text = llm_client.chat(cfg, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _group_prompt(batch)}],
                               max_tokens=min(4000, 400 + 25 * len(batch)), usage=usage)
        try:
            data = parse_json(text)
        except (ValueError, TypeError):
            log.warning("世界观分组：模型输出不是 JSON（%d 个）", len(batch))
            continue
        for g in (data.get("groups") or []) if isinstance(data, dict) else []:
            if not isinstance(g, dict):
                continue
            keys = []
            for i in g.get("ids") or []:
                try:
                    i = int(i)
                except (TypeError, ValueError):
                    continue
                if 1 <= i <= len(batch):
                    k = batch[i - 1]["key"]
                    if k not in keys and count[k] < MAX_GROUPS_PER_ENTITY:
                        keys.append(k)
            name = str(g.get("name") or "").strip()[:20]
            if len(keys) < 2 or not name:
                continue
            count.update(keys)
            groups.append({"name": name, "members": keys[:12], "reason": str(g.get("reason") or "").strip()[:60]})
    return {"groups": groups, "usage": usage}


# ---------------------------------------------------------------- 2. 总结

def _card_prompt(group: dict, members: list[dict], summaries: dict, others: list[str]) -> str:
    blocks = []
    for e in members:
        cat = CATEGORIES.get(e.get("category"), (e.get("category"),))[0]
        head = f"【{e['name']}】（{cat}）" + (f" 概括：{summaries[e['key']]}" if summaries.get(e["key"]) else "")
        facts = [f"- {f.get('fact')}（原文：{str(f.get('quote') or '')[:40]}）"
                 for f in (e.get("facts") or [])[:MAX_MEMBER_FACTS] if isinstance(f, dict) and f.get("fact")]
        blocks.append(head + "\n" + "\n".join(facts))
    other = f"\n这本书里其他的世界观主题：{'、'.join(others[:20])}" if others else ""
    return (f"主题「{group['name']}」包含下面这些设定条目和它们在原文里的事实：\n\n" + "\n\n".join(blocks) + other +
            "\n\n把它们总结成一张世界观卡：这个设定在这个世界里是什么、由什么组成、有什么规矩和代价、在世界里处于什么位置、原作怎么用它。输出 JSON：\n"
            '{"title":"世界观卡名称（不超过16字）","summary":"一句话说清它是什么（不超过60字）","detail":"100–300字的整体介绍",'
            '"attributes":{"定义":"","组成与层级":"","规则与代价":"","在世界中的位置":"","原作用法":"","借用提示":""},'
            '"related":[{"target":"有关系的设定名（本组条目或上面列出的其他主题）","relation":"关系，不超过10字，如 效忠 / 属于 / 对立 / 依赖"}],'
            '"tier":1到5的整数（影响范围：1个人 2地方 3一国 4大陆 5神明 / 世界之外，拿不准取低的）}\n'
            "要求：只依据给出的事实，不编造、不补充原因或来历；没有依据的属性直接省略（不要写「无」「未提及」）。")


def to_card(data: dict, group: dict, members: list[dict], names: set[str]) -> dict | None:
    if not isinstance(data, dict):
        return None
    attrs = {}
    raw = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}
    for k in ATTRS:
        v = mf._text(raw.get(k), 300)
        if v and not mf._EMPTY_VALUE.match(v):
            attrs[k] = v
    summary = mf._text(data.get("summary"), 120)
    if not summary and not attrs:
        return None
    related = []
    for r in data.get("related") or []:
        if not isinstance(r, dict):
            continue
        target, rel = mf._text(r.get("target"), 30), mf._text(r.get("relation"), 12)
        if target and rel and _norm_title(target) in names and target not in [x["target"] for x in related]:
            related.append({"target": target, "relation": rel})
    facts = [{"fact": f.get("fact"), "quote": f.get("quote") or "", "chapter": f.get("chapter") or "", "entity": e["name"]}
             for e in members for f in (e.get("facts") or [])[:MAX_MEMBER_FACTS] if isinstance(f, dict) and f.get("fact")][:MAX_FACTS]
    title = mf._text(data.get("title"), 40) or group["name"]
    tier = data.get("tier")
    return {
        "candidateId": "world:" + hashlib.sha1(_norm_title(group["name"]).encode()).hexdigest()[:12],
        "kind": "world",
        "category": "world",
        "subtype": "世界观",
        "title": title,
        "summary": summary,
        "detail": mf._text(data.get("detail"), 2000),
        "attributes": attrs,
        "tags": [group["name"]][:1] + ["世界观"],
        "excerpt": "",
        "chapters": sorted({str(f["chapter"]) for f in facts if f["chapter"]})[:50],
        "facts": facts,
        "members": [e["key"] for e in members],
        "memberNames": [e["name"] for e in members],
        "related": related,
        "group": group["name"],
        "tier": tier if isinstance(tier, int) and 1 <= tier <= 5 else None,
    }


def compile_world(entities: list[dict], groups: list[dict], summaries: dict, call: Callable[[list[dict], int], str],
                  concurrency: int, ckpt, on_progress: Callable[[int, str], None], stop: threading.Event | None) -> dict:
    """groups：[{name, members: [实体键]}]（作者确认过的）；summaries：{实体键: 已有实体卡的概括} → {materials, stats}。"""
    by_key = {e["key"]: e for e in entities if isinstance(e, dict) and e.get("key")}
    names = {_norm_title(e.get("name") or "") for e in by_key.values()}
    names |= {_norm_title(a) for e in by_key.values() for a in e.get("aliases") or []}
    names |= {_norm_title(g.get("name") or "") for g in groups}
    jobs = {}
    for g in groups:
        members = [by_key[k] for k in g.get("members") or [] if k in by_key]
        if len(members) >= 1 and g.get("name"):
            jobs[_norm_title(g["name"])] = ({"name": str(g["name"])[:20]}, members)
    stats = {"entities": sum(len(m) for _, m in jobs.values()), "cards": 0, "notUseful": 0, "systems": 0, "arcs": 0,
             "failedCards": 0, "worldCards": 0}
    others = [g["name"] for g, _ in jobs.values()]
    lock = threading.Lock()
    done = ckpt.done("world")

    def make(k: str) -> None:
        g, members = jobs[k]
        text = call([{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": _card_prompt(g, members, summaries, [o for o in others if o != g["name"]])}],
                    CARD_TOKENS)
        with lock:
            ckpt.append("world", k, mf._parse(text))

    mf._parallel([k for k in jobs if k not in done], make, workers=concurrency, stop=stop, lock=lock,
                 on_progress=on_progress, label="整理世界观卡", base=0, span=98, total=len(jobs),
                 failed=stats, fail_key="failedCards")
    out = []
    for k, (g, members) in jobs.items():
        card = to_card(ckpt.done("world").get(k), g, members, names)
        if card:
            out.append(card)
        else:
            stats["notUseful"] += 1
    stats["worldCards"] = stats["cards"] = len(out)
    return {"materials": out, "stats": stats}
