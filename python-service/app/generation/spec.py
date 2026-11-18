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

借鉴世界书（SillyTavern World Info / NovelAI Lorebook）的「按时间放行」，时间按章节算：
- 分组条目可带 appear {from, span, exclude}（前端「出场条件」）：from = 从第几章起登场，没到的卡片不进提示词
  （apply_chapter 移进 not_yet，一致性检查扫描提前登场）；span = 登场后持续几章（context.build 里即使本章没提到也保留）；
  exclude = 排除词（检索文本里出现时不带这张卡）。
- 情节推进的「阶段表」（分组 stages：章节范围 / 主角实力 / 对手上限）不当卡片，stage_at 查第 n 章所在的那一行，
  写正文时进核心设定【当前阶段】，灵感墙按它定量级上限。
"""
import re
from dataclasses import dataclass, field

CORE_CATEGORIES = ("world", "plot", "style")
# 生成参数而非故事事实：不写进提示词（每章字数作为默认目标字数使用）
PARAM_KEYS = {("plot", "chapters"), ("plot", "wordsPerChapter")}
BUILTIN = {"world": "世界观", "characters": "角色", "plot": "情节推进", "style": "文风"}
PROTAGONIST_WORDS = ("主角",)
STAGE_GROUP = ("plot", "stages")   # 阶段表


@dataclass
class Card:
    id: str
    title: str
    text: str
    keywords: set[str] = field(default_factory=set)
    appear: dict = field(default_factory=dict)   # {from, span, exclude}，见模块说明


@dataclass
class Constraints:
    core: list[str]           # 核心规则段落（已渲染）
    cards: list[Card]
    open: list[str]           # 未设定的内置分类名
    roster: list[str]         # 角色名单（名字 + 定位）
    personas: list[dict] = field(default_factory=list)   # 人物内核快照（apply_personas）
    not_yet: list[Card] = field(default_factory=list)    # 还没到登场章节的卡片（apply_chapter）
    stage: dict | None = None                            # 当前章所在的阶段表行（apply_chapter）


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


def _appear(gi: dict) -> dict:
    """前端「出场条件」→ {from, span, exclude}（都可空）"""
    a = gi.get("appear") if isinstance(gi.get("appear"), dict) else {}
    out = {}
    for k in ("from", "span"):
        try:
            v = int(a.get(k) or 0)
        except (TypeError, ValueError):
            v = 0
        if v > 0:
            out[k] = v
    words = a.get("exclude")
    words = re.split(r"[，,、\s]+", words) if isinstance(words, str) else words if isinstance(words, list) else []
    words = [str(w).strip()[:20] for w in words if str(w).strip()][:10]
    if words:
        out["exclude"] = words
    return out


def _item_card(cat_key: str, cat_label: str, group: dict, gi: dict) -> Card:
    name = gi.get("name") or ""
    kw = {name} if name else set()
    text = "\n".join([f"【{cat_label}·{group['label']}】{gi['label']}"] + _render(gi.get("children", []), 1))
    return Card(id=f"{cat_key}.{group['key']}.{gi['key']}", title=f"{cat_label}：{name or gi['label']}", text=text,
                keywords=kw, appear=_appear(gi))


def build(spec: list[dict] | None) -> Constraints:
    core, cards, roster = [], [], []
    present = set()
    for cat in spec or []:
        key, label, items = cat["key"], cat["label"], cat.get("items", [])
        present.add(key)
        plain = [it for it in items if it.get("type") != "group" and (key, it.get("key")) not in PARAM_KEYS]
        groups = [it for it in items if it.get("type") == "group" and (key, it.get("key")) != STAGE_GROUP]

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


# ---------------------------------------------------------------- 跨世界观角色卡（novel.personas，见 app/persona.py）

PERSONA_ROLE_WORDS = ("主角",)


def apply_personas(cons: Constraints, personas: list[dict] | None) -> Constraints:
    """把写进工作区的人物内核加进约束：主角的进核心设定（不会被裁掉），其他人按名字 / 别名检索成卡片（id 以 persona. 开头，
    context.build 里排在普通卡片前面）。原始快照留在 cons.personas，供规划 / 一致性检查用。"""
    from .. import persona as persona_mod

    cons.personas = [p for p in personas or [] if isinstance(p, dict) and p.get("name")]
    for p in cons.personas:
        text = p.get("brief") or persona_mod.render_brief(p)
        if any(w in (p.get("role") or "") for w in PERSONA_ROLE_WORDS):
            cons.core.append(text)
        else:
            cons.cards.append(Card(id=f"persona.{p['name']}", title=f"人物内核：{p['name']}", text=text,
                                   keywords={p["name"], *[a for a in p.get("aliases") or [] if a]}))
    return cons


# ---------------------------------------------------------------- 阶段表 / 出场条件（按章节放行）

def _range(text: str) -> tuple[int, int] | None:
    """「1-50」「1～50章」「第51章到200章」→ (1, 50)；「200以后」「200+」「200」→ (200, ∞)"""
    nums = [int(n) for n in re.findall(r"\d+", text or "")][:2]
    if not nums:
        return None
    if len(nums) == 1:
        return nums[0], 10 ** 9
    return min(nums), max(nums)


def stage_rows(spec: list[dict] | None) -> list[dict]:
    """阶段表 → [{start, end, range, power, tierMax, note}]（章节范围认不出的行跳过）"""
    rows = []
    for cat in spec or []:
        if cat.get("key") != STAGE_GROUP[0]:
            continue
        for it in cat.get("items", []):
            if it.get("type") != "group" or it.get("key") != STAGE_GROUP[1]:
                continue
            for gi in it.get("children", []):
                sub = {c.get("key"): c for c in gi.get("children", [])}
                text = lambda k: str((sub.get(k) or {}).get("display") or "")  # noqa: E731
                rng = _range(text("range"))
                if not rng:
                    continue
                m = re.search(r"[1-5]", text("tierMax"))
                rows.append({"start": rng[0], "end": rng[1], "range": text("range"), "power": text("power"),
                             "tierMax": int(m.group()) if m else None, "note": text("note")})
    return sorted(rows, key=lambda r: r["start"])


def stage_at(spec: list[dict] | None, n: int) -> dict | None:
    """第 n 章所在的阶段表行；不在任何一行里 = None"""
    hit = [r for r in stage_rows(spec) if r["start"] <= n <= r["end"]]
    return hit[-1] if hit else None


TIER_NAMES = {1: "个人 / 街头", 2: "地方", 3: "一国 / 大宗门", 4: "大陆 / 天下", 5: "神明 / 世界之外"}


def stage_text(row: dict) -> str:
    lines = [f"【当前阶段】第 {row['range']} 章"]
    if row.get("power"):
        lines.append(f"- 主角实力：{row['power']}")
    if row.get("tierMax"):
        lines.append(f"- 主角能正面面对的对手不超过「{TIER_NAMES[row['tierMax']]}」级；更强的存在只能作为传说、背景或伏笔，"
                     "不能和主角正面交手")
    if row.get("note"):
        lines.append(f"- {row['note']}")
    return "\n".join(lines)


def apply_chapter(cons: Constraints, spec: list[dict] | None, n: int) -> Constraints:
    """写第 n 章（或为第 n 章构思）时：没到登场章节的卡片移进 not_yet；阶段表这一行进核心设定。"""
    keep = []
    for c in cons.cards:
        (cons.not_yet if c.appear.get("from", 0) > n else keep).append(c)
    cons.cards = keep
    cons.stage = stage_at(spec, n)
    if cons.stage:
        cons.core.append(stage_text(cons.stage))
    return cons


def scan_early(cons: Constraints, text: str) -> list[dict]:
    """正文里出现了还没到登场章节的设定（名字）→ 一致性检查的问题条目（代码扫描，不用模型）"""
    out = []
    for c in cons.not_yet:
        hit = next((k for k in c.keywords if k and len(k) >= 2 and k in text), None)
        if hit:
            out.append({"type": "setting", "quote": hit, "found": True,
                        "detail": f"「{hit}」设定为第 {c.appear['from']} 章起才登场，这一章提前出现了",
                        "fix": "删掉，或改成传闻 / 伏笔；确实要提前，就改它的出场条件"})
    return out


def build_for(novel: dict, spec: list[dict] | None = None, chapter: int | None = None) -> Constraints:
    """工作区的约束 = 作品定位 + 设定（spec 为空时用已保存的）+ 人物内核；chapter = 第几章，按出场条件 / 阶段表放行。"""
    spec = spec if spec is not None else novel["settings"].get("spec")
    cons = apply_personas(build(spec), novel.get("personas"))
    pos = positioning_text(novel.get("bookConfig"), words=False)
    if pos:
        cons.core.insert(0, "【作品定位】\n" + pos)
    return apply_chapter(cons, spec, chapter) if chapter else cons


# ---------------------------------------------------------------- 写作参数（novel.bookConfig，自动规划「故事优先」第一步填）

BOOK_CONFIG_FIELDS = (("platform", "平台"), ("genre", "题材"), ("tags", "标签"), ("audience", "目标读者"),
                      ("sellingPoint", "核心卖点"), ("pov", "叙事人称"), ("style", "文风"),
                      ("targetWords", "目标字数"), ("chapterWords", "单章字数"))
_WORD_FIELDS = ("targetWords", "chapterWords")


def clean_book_config(cfg) -> dict | None:
    """写作参数：只留认识的字段；tags 为字符串列表，其余为短文本；全空 = None"""
    if not isinstance(cfg, dict):
        return None
    out = {}
    for k, _ in BOOK_CONFIG_FIELDS:
        v = cfg.get(k)
        if k == "tags":
            items = v if isinstance(v, list) else re.split(r"[、,，;；]", str(v or ""))
            v = [str(x).strip()[:20] for x in items if str(x).strip()][:10]
        else:
            v = str(v or "").strip()[:200 if k == "sellingPoint" else 60]
        if v:
            out[k] = v
    return out or None


def positioning_text(cfg, words: bool = True) -> str:
    """写作参数 → 提示词里的几行「平台：… / 题材：…」；words = False 时不带字数（写正文时字数由本章目标字数管）"""
    cfg = clean_book_config(cfg) or {}
    lines = []
    for k, label in BOOK_CONFIG_FIELDS:
        if (k in _WORD_FIELDS and not words) or k not in cfg:
            continue
        v = cfg[k]
        lines.append(f"{label}：{'、'.join(v) if isinstance(v, list) else v}")
    return "\n".join(lines)


def word_count(v) -> int:
    """「100万字」「3000字」「3千」「50w」→ 字数；认不出 = 0"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(万|w|W|千|k|K)?", str(v or ""))
    if not m:
        return 0
    return int(float(m.group(1)) * {"万": 10000, "w": 10000, "W": 10000, "千": 1000, "k": 1000, "K": 1000}.get(m.group(2), 1))
