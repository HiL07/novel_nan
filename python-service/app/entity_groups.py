"""实体 AI 归并（提取工作区「全书实体」的合并选项之一）：让模型找出实体档案里

- same：同一个东西的不同叫法 / 不同写法（如「神术与魔法世界」「魔法世界」）；
- system：同一体系的几个条目，适合并成一个总条目（如铜费尔 / 银纳尔 / 金塔勒 → 货币体系）。

只是建议：结果交给前端，作者在「对比」视图里看合并前 / 后，逐组采用或拆出；确认后才写回实体档案。
按分类分批（同分类才能合并），一批 ≤ BATCH 个，每个实体只给名字、别名和第一条事实。编号由代码给、由代码校验。
实测（《奥术神座》前 13 章 74 个实体，deepseek-v4.1-flash，2026-11-03）：会把两个不同的人、母子、头目和手下合到一起，
所以只对物品 / 世界观 / 怪物 / 地点做（人物 / 势力靠提取时的别名归并 + 手动合并）；这几类里约 6 成建议合理
（货币体系、同一地点两种叫法），其余要作者拆掉（两个不同的徽章、两个城区），所以默认不生效、逐组采用。两次跑结果也不完全一样。
"""
import logging

from . import llm_client
from .llm_client import ModelConfig, parse_json
from .materials import CATEGORIES

log = logging.getLogger(__name__)

BATCH = 120
TYPES = ("same", "system")
SYSTEM_OK = {"item", "world", "monster", "location"}

SYSTEM = "你是小说设定整理助手。只输出 JSON。"

KINDS_SYSTEM = (
    "- same：其实是同一个东西，只是叫法 / 写法不同（事实描述的是同一个对象）；\n"
    "- system：同一体系里并列的几个条目，合成一个总条目更好用（如几种货币 → 货币体系，几个境界 → 修炼境界）。"
    "只是在同一个地方、同一个场景出现的不算体系。\n")
KINDS_SAME = ("- same：确实是同一个对象，只是叫法不同（别名、昵称、本名 / 化名），事实要能对上。"
              "两个不同的人 / 组织、上下级、同伙都不算。\n")
RULES = ("规则：只是有关联、但其实是不同东西的（如普通老鼠和变异巨鼠、主教的徽章和主角的徽章、师父和徒弟）不要合并；"
         "每个编号最多出现在一组里；拿不准就不合并；没有可合并的就输出空数组。\n")


def _prompt(cat: str, items: list[dict]) -> str:
    lines = []
    for i, e in enumerate(items, 1):
        alias = f"（又名：{'、'.join(e.get('aliases') or [])[:40]}）" if e.get("aliases") else ""
        lines.append(f"{i}. {e['name']}{alias}：{(e.get('fact') or '')[:40]}")
    system_ok = cat in SYSTEM_OK
    shape = '"type":"same|system"' if system_ok else '"type":"same"'
    return (f"下面是一本小说里【{CATEGORIES[cat][0]}】类的设定条目（编号. 名称（别名）：一条事实）。找出应该合并的组：\n"
            + (KINDS_SYSTEM if system_ok else KINDS_SAME) + RULES
            + '输出：{"groups":[{"ids":[编号,编号],' + shape + ',"name":"合并后的名称，不超过12字","reason":"不超过20字"}]}\n\n'
            + "\n".join(lines))


def group(entities: list[dict], cfg: ModelConfig) -> dict:
    """entities：[{key, category, name, aliases, fact}] → {groups: [{keys, category, type, name, reason}], usage}。"""
    usage: dict = llm_client.new_usage(cfg)
    by_cat: dict[str, list[dict]] = {}
    for e in entities:
        # 人物 / 势力不交给 AI：别名在提取时已按名字归并，实测模型仍会把「骂主角的人」「母子」当成同一个人
        if e.get("category") in SYSTEM_OK and e.get("key") and e.get("name"):
            by_cat.setdefault(e["category"], []).append(e)
    groups = []
    for cat, items in by_cat.items():
        for start in range(0, len(items), BATCH):
            batch = items[start:start + BATCH]
            if len(batch) < 2:
                continue
            text = llm_client.chat(cfg, [{"role": "system", "content": SYSTEM},
                                         {"role": "user", "content": _prompt(cat, batch)}],
                                   max_tokens=min(4000, 300 + 40 * len(batch)), usage=usage)
            try:
                data = parse_json(text)
            except (ValueError, TypeError):
                log.warning("实体归并：模型输出不是 JSON（%s，%d 个）", cat, len(batch))
                continue
            used: set[int] = set()
            for g in (data.get("groups") or []) if isinstance(data, dict) else []:
                if not isinstance(g, dict):
                    continue
                ids = []
                for i in g.get("ids") or []:
                    try:
                        i = int(i)
                    except (TypeError, ValueError):
                        continue
                    if 1 <= i <= len(batch) and i not in used and i not in ids:
                        ids.append(i)
                if len(ids) < 2:
                    continue
                used.update(ids)
                kind = g.get("type") if g.get("type") in TYPES and cat in SYSTEM_OK else "same"
                groups.append({"keys": [batch[i - 1]["key"] for i in ids], "category": cat, "type": kind,
                               "name": str(g.get("name") or "").strip()[:20],
                               "reason": str(g.get("reason") or "").strip()[:40]})
    return {"groups": groups, "usage": usage}
