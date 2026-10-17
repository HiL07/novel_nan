"""前端设定 → 生成约束。

输入为前端 buildSpec() 的结果（只含用户实际选择 / 填写过的内容，未改动的默认值不在其中）：
  [{key, label, custom, items: [{key, label, type, value, display, name?, children: [...]}]}]
  type: single / multi / text / textarea / number / slider / tags / group；
        group 的 children 为 type="groupItem" 的条目（name 为该条目的名称，如角色名）；
        选择项的细分选项以 type="option" 的条目挂在 children 下。

输出：
- core：始终放入上下文的核心规则（世界观、情节走向、文风、主角、角色名单）
- cards：按需检索的设定卡片（其他角色、情节节点、自定义元素…），带检索关键词
- open：未设定的分类（提示模型可自由发挥但不得冲突）
"""
from dataclasses import dataclass, field

CORE_CATEGORIES = ("world", "plot", "style")
# 生成参数而非故事事实：不写进提示词（每章字数作为默认目标字数使用）
PARAM_KEYS = {("plot", "chapters"), ("plot", "wordsPerChapter")}
BUILTIN = {"world": "世界观", "characters": "角色", "plot": "情节推进", "style": "文风"}
PROTAGONIST_WORDS = ("主角",)


@dataclass
class Card:
    id: str
    title: str
    text: str
    keywords: set[str] = field(default_factory=set)


@dataclass
class Constraints:
    core: list[str]           # 核心规则段落（已渲染）
    cards: list[Card]
    open: list[str]           # 未设定的内置分类名
    roster: list[str]         # 角色名单（名字 + 定位）


def _render(items: list[dict], depth: int = 0) -> list[str]:
    lines = []
    pad = "  " * depth
    for it in items:
        t = it.get("type")
        if t == "option":  # 细分选项的容器：直接展开其下内容
            lines.append(f"{pad}- 「{it['label']}」细分：")
            lines.extend(_render(it.get("children", []), depth + 1))
            continue
        if t == "group":
            for g in it.get("children", []):
                lines.append(f"{pad}- {g['label']}")
                lines.extend(_render(g.get("children", []), depth + 1))
            continue
        disp = it.get("display") or ""
        lines.append(f"{pad}- {it['label']}：{disp}" if disp else f"{pad}- {it['label']}")
        if it.get("children"):
            lines.extend(_render(it["children"], depth + 1))
    return lines


def _field(items: list[dict], *labels: str) -> str:
    for it in items:
        if it.get("label") in labels and it.get("display"):
            return it["display"]
    return ""


def _item_card(cat_key: str, cat_label: str, group: dict, gi: dict) -> Card:
    name = gi.get("name") or ""
    kw = {name} if name else set()
    text = "\n".join([f"【{cat_label}·{group['label']}】{gi['label']}"] + _render(gi.get("children", []), 1))
    return Card(id=f"{cat_key}.{group['key']}.{gi['key']}", title=f"{cat_label}：{name or gi['label']}", text=text,
                keywords=kw)


def build(spec: list[dict] | None) -> Constraints:
    core, cards, roster = [], [], []
    present = set()
    for cat in spec or []:
        key, label, items = cat["key"], cat["label"], cat.get("items", [])
        present.add(key)
        plain = [it for it in items if it.get("type") != "group" and (key, it.get("key")) not in PARAM_KEYS]
        groups = [it for it in items if it.get("type") == "group"]

        if key in CORE_CATEGORIES:
            if plain:
                core.append("\n".join([f"【{label}】"] + _render(plain)))
            for g in groups:  # 如情节节点：按需检索
                cards.extend(_item_card(key, label, g, gi) for gi in g.get("children", []))
        elif key == "characters":
            if plain:
                core.append("\n".join(["【人物关系与成长】"] + _render(plain)))
            for g in groups:
                for gi in g.get("children", []):
                    sub = gi.get("children", [])
                    role = _field(sub, "角色定位")
                    roster.append(f"{gi.get('name') or gi['label']}（{role or '定位未设定'}）")
                    card = _item_card(key, label, g, gi)
                    if any(w in role for w in PROTAGONIST_WORDS):
                        core.append(card.text.replace(f"【{label}·{g['label']}】", "【主角】", 1))
                    else:
                        cards.append(card)
        else:  # 自定义元素（怪物、势力…）与其他分类：整体一张卡 + 每个条目一张卡
            item_cards = [_item_card(key, label, g, gi) for g in groups for gi in g.get("children", [])]
            if plain:
                # 分类总述卡：提到该分类或其中任一条目（如某只怪物）时一并检索
                names = {k for c in item_cards for k in c.keywords}
                cards.append(Card(id=f"{key}", title=label, text="\n".join([f"【{label}】"] + _render(plain)),
                                  keywords={label} | names))
            cards.extend(item_cards)
    open_ = [v for k, v in BUILTIN.items() if k not in present]
    return Constraints(core=core, cards=cards, open=open_, roster=roster)


def default_target_chars(spec: list[dict] | None) -> int | None:
    """若用户在「情节推进」里明确设置了每章字数，作为默认目标字数。"""
    for cat in spec or []:
        if cat["key"] == "plot":
            for it in cat.get("items", []):
                if it.get("key") == "wordsPerChapter" and isinstance(it.get("value"), (int, float)):
                    return int(it["value"])
    return None
