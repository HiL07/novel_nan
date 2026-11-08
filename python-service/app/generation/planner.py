"""自动规划（设计见 docs/自动规划.md），故事优先（不依赖素材库）：
写作参数 + 灵感（idea）→ 设定（世界 + 主角）→ 全书骨架（book：卷 / 阶段）+ 配角 / 元素（cast）
→ 写进工作区；素材点睛（enrich）/ 当前阶段的 10 章大纲 / 审稿的接口还在，暂不在界面流程里。
（原来的「素材优先」路线 2026-11-02 删掉了，素材怎么融入故事优先另行设计。）

只产出「用来写小说的内容」：设定（世界观 / 角色 / 元素 / 阶段表 / 出场条件）、大纲、故事账本里的计划伏笔与定时事件。
不生成正文，不改写作流程。每一步都是单独的接口（作者可以看、改、重来），Java 负责带模型配置（点睛时也负责本地检索素材）。

开篇（工作区还没写章节）：设定 / 大纲 / 审稿都套 OPENING_RULES，代码再数前 3 章的新人物、新名词，查章末钩子。
已写过章节：从世界书的局面出发规划接下来 10 章，只补新元素，不套开篇规则；有全书骨架时按骨架找到当前阶段。

设定的 JSON 结构本身就是「要填满的清单」：故事优先的设定要求世界背景卡、力量体系（境界）、能力、机制、资源，
没有素材时模型靠题材常识把这些槽位填满（借鉴 easy-writing 的工作流建书），代码再查数量够不够。
"""
import json
import re

from . import facts as facts_mod, ideas, inspire, spec as spec_mod, store, worldbook
from .inspire import InspireError

ROLE_LABELS = ("主角", "女主 / 男主", "反派", "导师", "伙伴", "宿敌", "配角")
OPPONENT_ROLES = ("反派", "宿敌")
ELEMENT_FIELDS = {   # 设定编辑器里各元素列表的字段（frontend mock/novelOptionSchema.js）
    "faction": {"stance": "立场：友方 / 中立 / 敌对", "feature": "特点（结构、目标、资源、内部矛盾）"},
    "location": {"kind": "类型：城市 / 秘境 / 遗迹 / 荒野…", "detail": "描述（特征、危险、特殊规则）"},
    "item": {"kind": "类别：武器 / 防具 / 丹药 / 法宝…", "effect": "作用、代价、获取方式"},
    "monster": {"appearance": "外形", "abilities": "能力（数组）", "weakness": "弱点（数组）", "habitat": "栖息地"},
}
CHAPTERS = 10
OPENING_CHAPTERS = 3
MAX_NEW_NAMES = 3      # 开篇每章新出场的有名有姓人物
MAX_NEW_TERMS = 5      # 开篇每章新出现的专有名词
MIN_PAYOFF_GAP = 2     # 伏笔至少隔几章再回收
FIRST_CHAPTER_TERMS = 3   # 第 1 章新专有名词上限（评测裁判反复说故事优先「第 1 章信息密度偏高」）

OPENING_RULES = """【开篇规则】（这是全书开头，大纲必须满足）
- 第 1 章：开场就有冲突或悬念（不要从日常 / 世界介绍写起）；主角在第 1 章就亮出他想要什么、他的缺陷；章末发生激励事件，把主角推出原来的生活
- 前 3 章内确立核心卖点（金手指 / 核心矛盾 / 这本书最吸引人的设定），让读者知道这本书「好看在哪」
- 世界观随情节露出：哪一章用到哪条规则才露出哪条，不安排「介绍世界」的章节、不在节拍里写大段设定说明
- 第 1 章只露出眼下这场冲突用得到的设定：新专有名词不超过 3 个，最多点到 1 个境界 / 等级名、1 处世界背景；
  力量体系、势力格局、世界历史留到后面用到时再露（设定准备得多不等于第 1 章要讲多）
- 人物逐个登场：每章新出场的有名有姓人物不超过 3 个，新的专有名词（地名、组织、功法、物品）不超过 5 个
- 对手量级不超过阶段上限：开篇的敌人是主角打得过、或者需要智取的
- 每章结尾都要有钩子（悬念、危机、反转、新目标），让读者想看下一章"""

SYSTEM = "你是资深网络小说策划编辑，擅长从素材出发搭建设定和大纲。只输出 JSON，不要任何多余文字。"
STORY_SYSTEM = ("你是资深网络小说策划编辑，擅长原创：从作者的想法和题材常识出发，搭出完整、具体、有卖点的故事和设定。"
                "只输出 JSON，不要任何多余文字。")
REVIEW_SYSTEM = "你是严格的网络小说审稿编辑，专门挑大纲和设定的问题。评审要具体，不说空话。只输出 JSON。"
TIER_HINT = "1 个人 / 街头，2 地方，3 一国 / 大宗门，4 大陆，5 神明"
IDEA_FIELDS = (("core", "核心设定"), ("situation", "主角处境"), ("conflict", "核心冲突"), ("payoff", "爽点方向"),
               ("hook", "一句话卖点"))
DEFAULT_BOOK_CHAPTERS = 300   # 写作参数里没有目标字数时，全书骨架按这么多章搭
MIN_COUNTS = {"realms": 4}   # 故事优先设定的槽位下限（代码检查；配角 / 元素的在 CAST_MIN）


def _call(req: dict, messages: list[dict], max_tokens: int, temperature: float) -> tuple[dict, dict, str]:
    """一次 JSON 调用：截断 → 报错；JSON 坏了（长输出里没转义的引号等）→ 降温重试一次 → (data, usage, model)"""
    usage = {"promptTokens": 0, "completionTokens": 0}
    last = None
    for t in (temperature, min(temperature, 0.3)):
        r, model = inspire._run(req, messages, max_tokens, temperature=t)
        usage["promptTokens"] += r["promptTokens"]
        usage["completionTokens"] += r["completionTokens"]
        if r["finishReason"] == "length":
            raise InspireError("模型输出被截断，请减少素材 / 章节后重试")
        try:
            return inspire._parse(r["text"], req), usage, model
        except InspireError as e:
            last = e
    raise last


def _clip(v, n: int) -> str:
    return inspire._clip(v, n)


def _strs(v, n: int = 200, limit: int = 20) -> list[str]:
    items = v if isinstance(v, list) else re.split(r"[、,，;；]", str(v or ""))
    return [str(x).strip()[:n] for x in items if str(x).strip()][:limit]


def _int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _written(novel_id: str | None) -> int:
    if not novel_id:
        return 0
    chapters = store.list_chapters(novel_id)
    return chapters[-1]["index"] if chapters else 0


def _stage(req: dict) -> dict:
    """开篇：作者没另定阶段时 = 开篇、对手上限 2；已写过章节 = 按工作区算（inspire.stage_of）"""
    if not _written(req.get("novelId")) and not (isinstance(req.get("stage"), dict) and req["stage"].get("source") == "user"):
        return {"phase": "opening", "tierMax": 2, "protagonist": "", "source": "user"}
    return inspire.stage_of(req)


def _premise(req: dict) -> str:
    """作者的构思 + 选定的灵感 + 写作参数 + 基调 / 补充要求：每一步提示词的开头"""
    lines = [f"作者的构思：{_clip(req.get('premise'), 500)}"] if _clip(req.get("premise"), 500) else []
    it = idea_text(req.get("idea"))
    if it:
        lines.append("【故事灵感】（作者选定的方向）\n" + it)
    cfg = spec_mod.positioning_text(req.get("bookConfig"))
    if cfg:
        lines.append("【写作参数】\n" + cfg)
    if _clip(req.get("tone"), 200):
        lines.append(f"基调：{_clip(req.get('tone'), 200)}")
    if _clip(req.get("conditions"), 500):
        lines.append(f"补充要求（必须满足）：{_clip(req.get('conditions'), 500)}")
    return "\n".join(lines)


def _situation(req: dict) -> str:
    """已写过章节的工作区：世界书的局面；开篇：空"""
    if not _written(req.get("novelId")):
        return ""
    return worldbook.snapshot(worldbook.compile(req["novelId"]), max_chars=5000)


# ---------------------------------------------------------------- 故事优先 ① 灵感（不依赖素材库）

def idea_text(idea) -> str:
    if not isinstance(idea, dict):
        return ""
    lines = [f"{lab}：{_clip(idea.get(k), 300)}" for k, lab in IDEA_FIELDS if _clip(idea.get(k), 300)]
    if lines and _clip(idea.get("title"), 40):
        lines.insert(0, f"暂定名：{_clip(idea.get('title'), 40)}")
    return "\n".join(lines)


def _clean_idea(d) -> dict | None:
    if not isinstance(d, dict):
        return None
    out = {"title": _clip(d.get("title"), 40), **{k: _clip(d.get(k), 300) for k, _ in IDEA_FIELDS}}
    return out if out["core"] and (out["situation"] or out["conflict"]) else None


def feedback_text(feedback) -> str:
    """作者对之前几批灵感的反馈 → 提示词。每次「重新生成」记一条 {dislike, want, rejected[被否掉的灵感]}，全部带上（越后越新）"""
    rows = [f for f in feedback if isinstance(f, dict)] if isinstance(feedback, list) else []
    lines = []
    for n, f in enumerate(rows[-10:], 1):
        bits = []
        if _clip(f.get("dislike"), 300):
            bits.append(f"不满意：{_clip(f.get('dislike'), 300)}")
        if _clip(f.get("want"), 300):
            bits.append(f"希望：{_clip(f.get('want'), 300)}")
        rejected = _strs(f.get("rejected"), 80, 10)
        if rejected:
            bits.append("被否掉的灵感：" + "；".join(rejected))
        if bits:
            lines.append(f"第 {n} 次：" + "｜".join(bits))
    if not lines:
        return ""
    return ("【作者对之前几批灵感的反馈】（按时间先后，越后越新；「希望」是必须满足的要求；"
            "新灵感不要和被否掉的重复，也不要换个名字再来一遍）\n" + "\n".join(lines))


def idea(req: dict) -> dict:
    """{premise?, directions?[], bookConfig?, tone?, conditions?, count?, materials?[架空版]}
    → {ideas[{title, core, situation, conflict, payoff, hook, materials?[{id, title, used}]}]}
    一句话（可以为空）扩成几个完整的故事灵感，彼此明显不同，作者挑一个再改。带素材时每个灵感至少用上一条，但核心来自作者写的内容。"""
    count = max(1, min(5, _int(req.get("count"), 3)))
    directions = _strs(req.get("directions"), 20, 8)
    parts = [f"作者的想法：{_clip(req.get('premise'), 500)}" if _clip(req.get("premise"), 500)
             else "作者还没有具体想法：按写作参数和创作方向自由构思。"]
    if directions:
        parts.append("创作方向：" + "、".join(directions))
    cfg = spec_mod.positioning_text(req.get("bookConfig"))
    if cfg:
        parts.append("【写作参数】\n" + cfg)
    if _clip(req.get("tone"), 200):
        parts.append(f"基调：{_clip(req.get('tone'), 200)}")
    if _clip(req.get("conditions"), 500):
        parts.append(f"补充要求（必须满足）：{_clip(req.get('conditions'), 500)}")
    fb = feedback_text(req.get("feedback"))
    if fb:
        parts.append(fb)
    block, refs = _portable_block(req.get("materials"))
    if block and not _has_author_input(req):
        raise InspireError(NO_AUTHOR_INPUT)
    if block:
        parts.append(f"{AUTHOR_FIRST}\n【可参考的架空素材】\n{block}")
    parts.append(
        f"【任务】把作者的想法扩写成 {count} 个完整的故事灵感，彼此在核心设定 / 冲突 / 卖点上明显不同（不要只换名字）。每个：\n"
        "- title 暂定书名（12 字内）\n"
        "- core 核心设定：这个故事最独特的那条设定（世界规则或金手指），具体到能想象出画面（80 字内）\n"
        "- situation 主角处境：主角是谁、现在缺什么、被什么困住（80 字内）\n"
        "- conflict 核心冲突：贯穿全书的对立是什么、对手是谁（80 字内）\n"
        "- payoff 爽点方向：读者追下去的爽点 / 情绪回报在哪（60 字内）\n"
        "- hook 一句话卖点，像书封文案（30 字内）\n"
        "要贴合写作参数里的平台和读者；题材常见的套路可以用，但每个灵感至少有一处让人眼前一亮的变化。\n"
        + ("每个灵感至少用上一条架空素材的机制或用途（起新名字），但故事的核心必须来自作者的想法和创作方向。\n"
           "另外输出 sources（用到的素材编号，如 [\"S1\"]）和 used（用了素材的哪一点，20 字内）。\n" if block else "")
        + '输出 {"ideas": [{"title": "…", "core": "…", "situation": "…", "conflict": "…", "payoff": "…", "hook": "…"'
        + (', "sources": ["S1"], "used": "…"' if block else "") + "}]}")
    messages = [{"role": "system", "content": STORY_SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]
    data, usage, model = _call(req, messages, 6000 if block else 2500, 0.95)  # 带素材时提示词长、模型思考多，3000 实测会截断
    found = []
    for d in data.get("ideas") or data.get("items") or []:
        x = _clean_idea(d)
        if x and block:  # 编号由代码核对：对不上的丢掉，一条都没对上的灵感保留，页面标「没用上素材」
            used = _clip(d.get("used"), 40)
            ids = inspire._refs(d.get("sources"), {k: m["id"] for k, m in refs.items()})
            x["materials"] = [{"id": m["id"], "title": _clip(m.get("title"), 30), "used": used} for m in refs.values() if m["id"] in ids]
        if x:
            found.append(x)
    found = found[:count]
    if not found:
        raise InspireError("模型没有给出可用的灵感，请重试")
    return {"ideas": found, "usage": usage, "model": model}


# ---------------------------------------------------------------- 参数这一步的小帮手（创作方向 / 文风 / 补充要求 / 你的想法）

ASSIST_KINDS = {
    # 种类 → (要求, 输出最大 token)
    "direction": ("根据作者的描述，提炼一个创作方向标签：7 个字以内，像「重生逆袭」「规则怪谈」「师徒羁绊」这样的短词，"
                  "只输出标签本身", 40),
    "style": ("根据作者的描述，概括一个文风：7 个字以内，如「轻松幽默」「冷峻克制」「细腻温情」，只输出文风本身", 40),
    "conditions": ("把作者随手写的话整理成明确的补充要求：一条一行，每条一句话、能直接拿来约束创作（如「不要后宫」「主角是女性」），"
                   "只保留作者真的提出的要求，不要自己加；最多 8 条，只输出要求本身，不要编号、不要解释", 400),
    "premise": ("润色作者的故事想法：保留原意和作者写到的所有要素，把它写得更清楚、更具体（可以补一两处细节让想法更完整），"
                "100 字以内，只输出润色后的想法本身", 300),
    "sellingPoint": ("根据作者写的内容提炼这本书的核心卖点：读者为什么追这本书，1–2 句话、60 字以内、要具体（不要「爽点密集」这种空话），"
                     "只输出卖点本身", 200),
}


def _short_label(text: str, limit: int = 7) -> str:
    """模型给的短标签：去掉引号 / 标点 / 前缀，截到 limit 个字"""
    t = re.sub(r"^(创作方向|文风|标签)[：:]\s*", "", str(text or "").strip().splitlines()[0] if str(text or "").strip() else "")
    t = re.sub(r"[「」『』\"'“”‘’《》\s]", "", t)
    t = re.split(r"[，,、；;。！？!?.]", t)[0] or t   # 模型多写了半句：只要第一个短语，不在词中间截断
    return t[:limit]


AUTHOR_FIRST = ("【主次】上面作者写的内容是主体，必须保留、不能被替换；下面的架空素材只是补充，用来让内容更具体、更有新意。"
                "可以借用素材的机制、用途和关系，但名字要起新的，输出里不要提到素材的名称；不要把素材原样搬进来，也不要让素材盖过作者的想法。")
NO_AUTHOR_INPUT = "先填写作参数（题材 / 标签等）或写几句你的想法，素材只做补充"
MATERIAL_ASSIST = ("sellingPoint", "style", "premise", "conditions")
_MATERIAL_MARK = re.compile(r"[（(]\s*(?:来自素材\s*)?S\s*(\d+)\s*[）)]\s*$", re.I)


def _portable_block(materials) -> tuple[str, dict[str, dict]]:
    """架空版 → 提示词块（[S1]…）和 编号 → 素材。按档案字段写，不用通用的素材文本：
    那里只留 260 字，示例会把叙事用途 / 一定保留挤掉；也不写来源书、原作绑定和被替换的原作词（from）。"""
    lines, refs = [], {}
    for m in [x for x in materials or [] if isinstance(x, dict) and isinstance(x.get("portable"), dict)][:8]:
        p = m["portable"]
        key = f"S{len(refs) + 1}"
        refs[key] = m
        bits = [_clip(p.get("core"), 160)]
        for label, values in (("叙事用途", p.get("uses")), ("一定保留", p.get("keep")),
                              ("换世界时可以换成", [r.get("to") for r in p.get("replace") or [] if isinstance(r, dict)]),
                              ("节点角色", [n.get("role") for n in p.get("nodeMap") or [] if isinstance(n, dict)]),
                              ("联动规则", [f"{r.get('if')} → {r.get('then')}" for r in p.get("rules") or [] if isinstance(r, dict)])):
            items = _strs(values, 80, 6)
            if items:
                bits.append(f"{label}：" + "；".join(items))
        cat = ideas.CATEGORY_LABELS.get(m.get("category"), "写法" if m.get("category") == "craft" else "素材")
        lines.append(f"[{key}]【{cat}】{_clip(m.get('title'), 30)}：" + "。".join(b for b in bits if b))
    return "\n".join(lines), refs


def _has_author_input(req: dict, text: str = "") -> bool:
    """作者自己填过东西吗（平台 / 读者 / 人称 / 字数是表单默认值，不算）"""
    cfg = req.get("bookConfig") if isinstance(req.get("bookConfig"), dict) else {}
    return bool(text or _clip(req.get("premise"), 500) or _clip(req.get("conditions"), 500) or _strs(req.get("directions"), 20, 8)
                or any(cfg.get(k) for k in ("genre", "tags", "sellingPoint", "style")))


def _assist_task(kind: str, need: str, text: str, has_materials: bool) -> str:
    if not has_materials:
        return need
    if kind == "premise":
        return ("润色作者的故事想法：保留原意和作者写到的所有要素，把素材里合适的一两处机制融进去（起新名字），100 字以内，只输出想法本身" if text else
                "作者还没写想法：以写作参数和创作方向为主，写一个 100 字以内的故事想法，可以用上素材里一两处机制（起新名字），只输出想法本身")
    if kind == "conditions":
        return ("分两部分输出，一条一行、不要编号、不要解释：先把作者随手写的话整理成明确的要求（只保留作者真的提出的，不要自己加）；"
                "再从素材的「一定保留」里挑和作者的想法直接相关的（最多 3 条，一个素材最多 1 条，不相关的不要加，可以一条都不加），"
                "每条一句话、30 字以内，改写成要求（不出现素材的名字），放在后面，结尾写来源编号，如（S1）。总共最多 8 条")
    if kind == "style":
        return need + "。参考下面写法素材的手法，作者的描述优先"
    return need + "。可以从素材的叙事用途和内核里找能放大的点，但卖点要落在作者的题材和想法上"


def _clean_conditions(out: str, refs: dict[str, dict]) -> str:
    """作者的要求排前面；素材来的最多 3 条、标明来自哪条素材，编号对不上的丢掉"""
    own, from_material = [], []
    for row in out.splitlines():
        row = re.sub(r"^\s*(\d+[.、．)]|[-•·*])\s*", "", row).strip()
        if not row:
            continue
        mark = _MATERIAL_MARK.search(row)
        if not mark:
            own.append(row)
        elif (m := refs.get(f"S{mark.group(1)}")) and len(from_material) < 3:
            from_material.append(f"{row[:mark.start()].rstrip()}（来自素材「{_clip(m.get('title'), 20)}」）")
    return "\n".join((own + from_material)[:8])[:500]


def assist(req: dict) -> dict:
    """{kind: direction|style|conditions|premise|sellingPoint, text, bookConfig?, premise?, conditions?, directions?, materials?} → {kind, value}
    参数这一步的小帮手：一句描述 → 7 字以内的创作方向 / 文风；随手写的话 → 一条条补充要求；润色「你的想法」；提炼核心卖点。
    materials = 作者选的架空版：只作补充，作者什么都没填时不生成。不用 JSON，直接要正文"""
    kind = str(req.get("kind") or "")
    if kind not in ASSIST_KINDS:
        raise InspireError(f"不认识的帮手种类：{kind}")
    text = _clip(req.get("text"), 1000)
    materials = (req.get("materials") or []) if kind in MATERIAL_ASSIST else []
    if kind == "style":  # 文风只参考写法类素材
        materials = [m for m in materials if isinstance(m, dict) and m.get("category") == "craft"]
    block, refs = _portable_block(materials)
    if not text and not (kind == "sellingPoint" or block):
        raise InspireError("素材篮里没有写法类素材，先写几句想要的感觉" if kind == "style" and req.get("materials") else "先写几句描述")
    if not _has_author_input(req, text):
        raise InspireError(NO_AUTHOR_INPUT)
    need, max_tokens = ASSIST_KINDS[kind]
    if block:
        max_tokens = max(max_tokens, 500 if kind == "conditions" else 300 if kind == "sellingPoint" else max_tokens)
    parts = []
    cfg = spec_mod.positioning_text(req.get("bookConfig"))
    if cfg and (kind in ("direction", "premise", "sellingPoint") or block):
        parts.append("【写作参数】（参考）\n" + cfg)
    directions = _strs(req.get("directions"), 20, 8)
    if directions and kind in ("premise", "sellingPoint"):
        parts.append("创作方向：" + "、".join(directions))
    if kind != "premise" and _clip(req.get("premise"), 500):
        parts.append(f"作者的故事想法（参考）：{_clip(req.get('premise'), 500)}")
    if kind in ("premise", "sellingPoint") and _clip(req.get("conditions"), 500):
        parts.append(f"补充要求（参考）：{_clip(req.get('conditions'), 500)}")
    if text:
        parts.append(f"作者写的：{text}")
    if block:
        parts.append(f"{AUTHOR_FIRST}\n【可参考的架空素材】\n{block}")
    parts.append(f"【任务】{_assist_task(kind, need, text, bool(block))}。")
    messages = [{"role": "system", "content": "你是网络小说编辑，帮作者把零散的想法整理成清楚的说法。只输出要求的内容，不要任何解释。"},
                {"role": "user", "content": "\n\n".join(parts)}]
    try:
        if req.get("local") and (req.get("local") or {}).get("baseId"):
            r, model = ideas._run_local(req["local"], messages, max_tokens, temperature=0.5, use_adapter=False)
        elif req.get("api"):
            r, model = ideas._run_api(req["api"], messages, max_tokens, temperature=0.7, json_mode=False, think=False)  # 短任务：思考会吃光上限
        else:
            raise InspireError("请选择大模型、GGUF 或本地模型")
    except ideas.IdeaError as e:
        raise InspireError(str(e)) from e
    out = (r.get("text") or "").strip()
    if kind in ("direction", "style"):
        value = _short_label(out)
    elif kind == "conditions" and block:
        value = _clean_conditions(out, refs)
    elif kind == "sellingPoint":
        value = _clip(re.sub(r"^(核心)?卖点[：:]\s*", "", out), 200)
    elif kind == "conditions":
        rows = [re.sub(r"^\s*(\d+[.、．)]|[-•·*])\s*", "", x).strip() for x in out.splitlines()]
        value = "\n".join(x for x in rows if x)[:500]
    else:
        value = _clip(re.sub(r"^(润色后?的?想法|想法)[：:]\s*", "", out), 500)
    if not value:
        raise InspireError("模型没有给出可用的结果，请重试")
    return {"kind": kind, "value": value, "usage": {"promptTokens": r.get("promptTokens", 0),
                                                     "completionTokens": r.get("completionTokens", 0)}, "model": model}


# ---------------------------------------------------------------- 故事优先 ② 全书骨架（卷 / 阶段）

def planned_chapters(cfg) -> int:
    """写作参数的 目标字数 ÷ 单章字数（默认 3000）；没填目标字数 = 0"""
    cfg = cfg if isinstance(cfg, dict) else {}
    total = spec_mod.word_count(cfg.get("targetWords"))
    per = spec_mod.word_count(cfg.get("chapterWords")) or 3000
    return max(30, min(2000, round(total / per))) if total else 0


def _clean_stage(s: dict) -> dict | None:
    if not isinstance(s, dict) or not (_clip(s.get("goal"), 300) or _clip(s.get("title"), 40)):
        return None
    t = _int(s.get("tierMax"))
    return {"title": _clip(s.get("title"), 40), "chapters": max(0, _int(s.get("chapters"))),
            "goal": _clip(s.get("goal"), 300), "startState": _clip(s.get("startState"), 200),
            "endState": _clip(s.get("endState"), 200), "power": _clip(s.get("power"), 60),
            "mustHappen": _strs(s.get("mustHappen"), 120, 4), "forbidden": _strs(s.get("forbidden"), 120, 4),
            "tierMax": t if 1 <= t <= 5 else None}


def clean_book(d) -> dict | None:
    """全书骨架：{titleOptions, logline, storyHook, sellingPoints, worldPoints, volumes[{title, summary, chapters, stages[]}]}"""
    if not isinstance(d, dict):
        return None
    volumes = []
    for v in d.get("volumes") or []:
        if not isinstance(v, dict) or not _clip(v.get("title"), 40):
            continue
        stages = [x for x in (_clean_stage(s) for s in v.get("stages") or []) if x][:4]
        volumes.append({"title": _clip(v.get("title"), 40), "summary": _clip(v.get("summary"), 400),
                        "chapters": max(0, _int(v.get("chapters"))), "stages": stages})
    if not volumes:
        return None
    titles = [x.get("name") if isinstance(x, dict) else x for x in d.get("titleOptions") or []]
    return {"titleOptions": _strs(titles, 40, 5), "logline": _clip(d.get("logline"), 200),
            "storyHook": _clip(d.get("storyHook"), 200), "sellingPoints": _strs(d.get("sellingPoints"), 80, 5),
            "worldPoints": _strs(d.get("worldPoints"), 120, 8), "volumes": volumes[:8]}


def book_layout(book: dict | None) -> list[dict]:
    """骨架 → 按章节排好的阶段 [{volume, stage, volumeTitle, title, goal, …, start, end}]。
    阶段没写章数时把本卷剩下的章数平均分给它们；卷也没写章数时按 30 章算。"""
    rows, n = [], 1
    for vi, v in enumerate((book or {}).get("volumes") or []):
        stages = v.get("stages") or [{"title": v["title"], "chapters": 0, "goal": v.get("summary") or "", "startState": "",
                                      "endState": "", "power": "", "mustHappen": [], "forbidden": [], "tierMax": None}]
        given = [s.get("chapters") or 0 for s in stages]
        total = v.get("chapters") or sum(given) or 30
        missing = [i for i, g in enumerate(given) if not g]
        if missing:
            share = max(1, (total - sum(given)) // len(missing))
            for i in missing:
                given[i] = share
        for si, s in enumerate(stages):
            rows.append({**s, "volume": vi, "stage": si, "volumeTitle": v["title"], "start": n, "end": n + given[si] - 1})
            n += given[si]
    return rows


def book_position(book: dict | None, chapter: int) -> dict | None:
    """第 chapter 章在骨架的哪一阶段；超出骨架 = None"""
    return next((r for r in book_layout(book) if r["start"] <= chapter <= r["end"]), None)


def book_stages(book: dict | None) -> list[dict]:
    """骨架的阶段 → 设定编辑器的阶段表行（章节范围 / 主角实力 / 对手上限 / 备注 = 阶段目标 + 必须发生）"""
    rows = []
    for r in book_layout(book):
        note = f"{r['volumeTitle']}·{r['title'] or '阶段'}：{r['goal']}"
        if r["mustHappen"]:
            note += "；必须发生：" + "、".join(r["mustHappen"])
        rows.append({"range": f"{r['start']}-{r['end']}", "power": r["power"] or r["endState"][:60],
                     "tierMax": r["tierMax"], "note": note[:300]})
    return rows


def book_text(book: dict | None, detail: bool = True) -> str:
    """骨架 → 提示词文字（detail = False 只给卷名和一句话目标）"""
    if not book:
        return ""
    lines = []
    if book.get("logline"):
        lines.append(f"一句话：{book['logline']}")
    if book.get("storyHook"):
        lines.append(f"核心钩子：{book['storyHook']}")
    if detail and book.get("worldPoints"):
        lines.append("世界观要点：" + "；".join(book["worldPoints"]))
    for r in book_layout(book):
        head = f"第{r['volume'] + 1}卷《{r['volumeTitle']}》· {r['title'] or '阶段'}（第{r['start']}~{r['end']}章）"
        if not detail:
            lines.append(f"{head}：{r['goal']}")
            continue
        bits = [f"目标：{r['goal']}"]
        if r["startState"] or r["endState"]:
            bits.append(f"{r['startState'] or '?'} → {r['endState'] or '?'}")
        if r["mustHappen"]:
            bits.append("必须发生：" + "、".join(r["mustHappen"]))
        if r["tierMax"]:
            bits.append(f"对手上限 {r['tierMax']}")
        lines.append(f"{head}｜" + "｜".join(bits))
    return "\n".join(lines)


def stage_block(book: dict | None, start: int, count: int) -> tuple[str, dict | None]:
    """大纲 / 审稿用：这次规划的章节落在骨架的哪个阶段 → (提示词段落, 当前阶段行)"""
    row = book_position(book, start)
    if not row:
        return "", None
    end = start + count - 1
    lines = [f"【当前阶段】第{row['volume'] + 1}卷《{row['volumeTitle']}》· {row['title'] or '阶段'}（第{row['start']}~{row['end']}章）",
             f"- 阶段目标：{row['goal']}"]
    if row["startState"] or row["endState"]:
        lines.append(f"- 起点：{row['startState'] or '（未写）'} → 终点：{row['endState'] or '（未写）'}")
    if row["mustHappen"]:
        lines.append("- 必须发生：" + "；".join(row["mustHappen"]))
    if row["forbidden"]:
        lines.append("- 这一阶段不能发生：" + "；".join(row["forbidden"]))
    if row["end"] <= end:
        lines.append(f"- 本阶段在第 {row['end']} 章结束：到那一章要达到终点状态，「必须发生」的事都要发生")
        nxt = book_position(book, row["end"] + 1)
        if nxt and nxt["start"] <= end:
            lines.append(f"- 第 {nxt['start']} 章起进入下一阶段「{nxt['title']}」：{nxt['goal']}"
                         + (f"（必须发生：{'；'.join(nxt['mustHappen'])}）" if nxt["mustHappen"] else ""))
    else:
        lines.append(f"- 这 {count} 章只是本阶段的一部分（本阶段到第 {row['end']} 章）：推进阶段目标，"
                     "不要提前达到终点状态，不要提前解决本阶段的核心冲突")
    return "\n".join(lines), row


def book_issues(book: dict, cfg) -> list[dict]:
    """代码检查：阶段首尾状态、必须发生、章数和写作参数对不上"""
    issues = []
    rows = book_layout(book)
    for a, b in zip(rows, rows[1:]):
        if not a["endState"] or not b["startState"]:
            issues.append({"type": "book", "detail": f"「{a['title']}」→「{b['title']}」：阶段之间的终点 / 起点状态没写，衔接不清楚"})
    for r in rows:
        if not r["mustHappen"]:
            issues.append({"type": "book", "detail": f"阶段「{r['title']}」没有写「必须发生」的事"})
    planned = planned_chapters(cfg)
    total = rows[-1]["end"] if rows else 0
    if planned and total and abs(total - planned) / planned > 0.5:
        issues.append({"type": "book", "detail": f"骨架共 {total} 章，写作参数估算约 {planned} 章，差得较多"})
    return issues


PACES = {
    "slow": "节奏慢热：每卷只把主线推进一小步，舞台和核心元素尽量不换；换地图 / 换舞台前要有足够铺垫，前几卷的主要舞台基本不变",
    "normal": "节奏适中：每卷有一个清楚的新目标，舞台可以逐步扩大",
    "fast": "节奏偏快：每卷都有明显升级或换地图，冲突密集",
}
_RANK = re.compile(r"[一二三四五六七八九十百两\d]+\s*(阶|级|层|重|星|品|段|转)")


def invented_issues(bk: dict, settings_text: str) -> list[dict]:
    """骨架里出现「二阶」「三级」这类等级，而设定里根本没有这种等级说法 → 可能是骨架在发明设定（只是提示）"""
    if not settings_text:
        return []
    text = book_text(bk)
    have = {m.group(1) for m in _RANK.finditer(settings_text)}
    out, seen = [], set()
    for m in _RANK.finditer(text):
        unit = m.group(1)
        if unit in have or m.group(0) in seen:
            continue
        seen.add(m.group(0))
        out.append({"type": "invented", "term": m.group(0),
                    "detail": f"骨架提到「{m.group(0)}」，设定里没有「…{unit}」这种等级说法，可能是骨架自己发明了设定"
                              "（改设定或改骨架，二者要一致）"})
    return out[:5]


def _volume_plan_text(req: dict) -> str:
    """作者写的分卷意图（每卷一句话）+ 卷数 + 节奏 → 提示词；都没填 = 空"""
    plan = _strs(req.get("volumePlan"), 200, 8)
    lines = [f"第 {i} 卷：{t}" for i, t in enumerate(plan, 1)]
    n = _int(req.get("volumeCount"))
    if n:
        lines.insert(0, f"卷数：{max(1, min(8, n))} 卷")
    pace = PACES.get(str(req.get("pace") or ""))
    if pace:
        lines.append(pace)
    return ("【作者定的分卷方向】（必须照着来，不要自作主张提前换舞台 / 跳剧情）\n" + "\n".join(lines)) if lines else ""


def book(req: dict) -> dict:
    """{premise?, idea?, bookConfig?, settings?, volumePlan?[], volumeCount?, pace?, tone?, conditions?, book?, regen?}
    → {book, issues, stages, extended, regenerated}
    - 第一次：按灵感 + **设定**搭全书骨架（不许发明设定里没有的规则 / 等级），作者的分卷意图和节奏必须照着来；
    - 带 book：保留原有各卷，只追加 1~2 卷；
    - 带 book + regen {index, instruction?}：只重新生成第 index 卷（0 起），其余卷原样不动。"""
    cfg = req.get("bookConfig")
    old = clean_book(req.get("book"))
    regen = req.get("regen") if isinstance(req.get("regen"), dict) else None
    if not (_clip(req.get("premise"), 500) or idea_text(req.get("idea")) or old):
        raise InspireError("先写一句构思，或者选一个灵感")
    draft = req.get("settings") if isinstance(req.get("settings"), dict) else {}
    st_text = _settings_text(draft) if draft else ""
    parts = [_premise(req)]
    if st_text:
        parts.append("【设定】（骨架必须建立在这些设定上：只能用设定里有的规则、等级、体系和势力；"
                     "设定里没有的等级 / 阶数 / 体系不要自己发明，需要的话用设定里已有的说法）\n" + st_text)
    vp = _volume_plan_text(req)
    if vp:
        parts.append(vp)
    volume_shape = ('{"title": "卷名", "summary": "本卷主线（120 字内）", "chapters": 100, "stages": [{"title": "阶段名",'
                    ' "chapters": 40, "goal": "阶段目标", "startState": "起点状态", "endState": "终点状态", "power": "主角实力 / 身份",'
                    ' "mustHappen": ["…"], "forbidden": ["…"], "tierMax": 2}]}')
    shape = '{"volumes": [' + volume_shape + ']'
    stage_rules = (f"- 每卷 1~3 个阶段 stages：title；chapters 本阶段章数（加起来等于本卷章数）；goal 阶段目标；startState 起点状态、"
                   "endState 终点状态（主角的处境 / 实力 / 关系到这里变成什么样）；power 这一阶段主角的实力或身份（30 字内，用设定里的说法）；"
                   "mustHappen 必须发生的 1~3 件事；forbidden 这一阶段不能发生的事（如「不能暴露身世」「不能和最终反派正面决战」）；"
                   f"tierMax 对手量级上限 1~5（{TIER_HINT}）\n"
                   "- 阶段之间首尾相接：下一阶段的 startState 就是上一阶段的 endState；量级随卷逐步升高\n")
    mode = "regen" if old and regen else "extend" if old else "new"
    i = 0
    if mode == "regen":
        i = max(0, min(len(old["volumes"]) - 1, _int(regen.get("index"))))
        rows = book_layout(old)
        prev = next((r for r in reversed(rows) if r["volume"] == i - 1), None)
        nxt = next((r for r in rows if r["volume"] == i + 1), None)
        parts.append("【全书骨架】（只重写其中一卷，其余卷不变）\n" + book_text(old))
        ask = _clip(regen.get("instruction"), 500)
        parts.append(
            f"【任务】只重新设计第 {i + 1} 卷（原来是《{old['volumes'][i]['title']}》）。"
            + (f"作者的要求：{ask}。" if ask else "写得更好、更贴合分卷方向和设定。")
            + (f"开头接上上一卷的结尾「{prev['endState'] or prev['goal']}」；" if prev else "")
            + (f"结尾要能接上下一卷的开头「{nxt['startState'] or nxt['goal']}」；" if nxt else "")
            + f"章数保持约 {old['volumes'][i]['chapters'] or 100} 章。\n" + stage_rules +
            "只输出这一卷：" + volume_shape)
    elif mode == "extend":
        last = book_layout(old)[-1]
        parts.append("【已有的全书骨架】（原样保留，不要重写）\n" + book_text(old))
        situation = _situation(req)
        if situation:
            parts.append(f"【已写内容的局面】\n{situation}")
        parts.append(
            f"【任务】已有骨架写到第 {last['end']} 章。接着往后追加 1~2 卷（从第 {last['end'] + 1} 章开始），"
            f"第一个新阶段的 startState 接上「{last['endState'] or last['goal']}」，把核心钩子往前推，矛盾升级。\n"
            "- 每卷 title、summary（本卷主线，120 字内）、chapters 本卷章数\n" + stage_rules +
            "只输出新追加的卷：" + shape + "}")
    else:
        total = planned_chapters(cfg) or DEFAULT_BOOK_CHAPTERS
        n = _int(req.get("volumeCount"))
        vols = f"{max(1, min(8, n))} 卷" if n else "2~4 卷"
        parts.append(
            f"【任务】为这本书搭全书骨架（全书约 {total} 章）。\n"
            "- titleOptions：3 个候选书名\n"
            "- logline 一句话故事（40 字内）；storyHook 贯穿全书的核心钩子：读者最想知道答案的那个问题（60 字内）\n"
            "- sellingPoints 2~4 个卖点（每个 30 字内）\n"
            "- worldPoints 3~6 条世界观要点：从【设定】里挑最能代表这个世界的（每条 40 字内）\n"
            f"- volumes {vols}，各卷章数加起来约 {total} 章；每卷 title、summary（本卷主线，120 字内）、chapters 本卷章数\n"
            + stage_rules +
            "- 第一卷第一阶段 tierMax 不超过 2；第一阶段要在前几章就亮出核心卖点，主角主动出手\n"
            '输出 {"titleOptions": ["…", "…", "…"], "logline": "…", "storyHook": "…", "sellingPoints": ["…"], "worldPoints": ["…"], '
            + shape[1:] + "}")
    messages = [{"role": "system", "content": STORY_SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]
    data, usage, model = _call(req, messages, 2500 if mode == "regen" else 4500, 0.9)
    if mode == "regen":
        vol = data["volumes"][0] if isinstance(data.get("volumes"), list) and data["volumes"] else data
        fixed = clean_book({"volumes": [vol]})
        if not fixed:
            raise InspireError("模型没有给出这一卷，请重试")
        vols = list(old["volumes"])
        vols[i] = fixed["volumes"][0]
        out = {**old, "volumes": vols}
    elif mode == "extend":
        added = clean_book({"volumes": data.get("volumes") or []})
        if not added:
            raise InspireError("模型没有给出新的卷，请重试")
        out = {**old, "volumes": (old["volumes"] + added["volumes"])[:8]}
    else:
        out = clean_book(data)
        if not out:
            raise InspireError("模型没有给出分卷，请重试")
        first = out["volumes"][0]["stages"][:1]
        if first and (first[0]["tierMax"] or 0) > 2:
            first[0]["tierMax"] = 2   # 开篇对手上限 2
    issues = book_issues(out, cfg) + invented_issues(out, st_text)
    return {"book": out, "issues": issues, "stages": book_stages(out), "extended": mode == "extend",
            "regenerated": i if mode == "regen" else None, "usage": usage, "model": model}


# ---------------------------------------------------------------- 设定（世界 + 主角）

def _element_schema() -> str:
    return "\n".join(f"  {cat}：" + "；".join(f"{k} = {v}" for k, v in fields.items()) for cat, fields in ELEMENT_FIELDS.items())


STORY_WORLD_SHAPE = (
    '"world": {"rules": ["…"], "note": "…",'
    ' "power": {"intro": "…", "realms": [{"name": "…", "desc": "…", "cost": "…"}], "beyond": "…"},'
    ' "abilities": {"innate": "…", "acquired": "…", "dimensions": ["…"]},'
    ' "mechanics": [{"title": "…", "desc": "…"}], "resources": [{"title": "…", "desc": "…"}]}')


LEAD_SHAPE = ('"characters": [{"name": "…", "role": "主角", "tagline": "一句话人设", "personality": ["性格词，≤4 个"], "goal": "…",'
              ' "fear": "…", "secret": "…", "abilities": ["…"], "background": "…（100 字内）", "arc": "成长弧光（60 字内）"}]')


def _settings_story(req: dict, opening: bool, stage: dict) -> dict:
    """故事优先 ② 设定：只做世界 + 主角，依据写作参数和选中的灵感（不需要素材，选了素材就当可选参考）。
    配角、势力 / 地点 / 物品 / 怪物、阶段表要按全书骨架的阶段安排，放到骨架那一步（cast）生成。
    JSON 结构里的槽位（境界 / 能力 / 机制 / 资源）就是要模型填满的清单。
    不生成世界背景卡（和世界规则重叠）和书名（书名在骨架那一步选，灵感的暂定名是候选之一）。"""
    block, refs = inspire._material_block(req.get("materials") or [])
    parts = [_premise(req)]
    situation = _situation(req)
    if situation:
        parts.append(f"【这本书现在的局面】（已有的设定不要重复，只补新东西）\n{situation}")
    if block:
        parts.append("【可参考的素材】（可选：用得上就改编进来，名字换新，sources 写编号；用不上就不用）\n" + block)
    parts.append(
        "【任务】为这本书做世界设定和主角（配角、势力、地点等之后按全书骨架再配，这里不要写）。\n"
        "- world.rules 3~6 条这个世界独有的规则（每条 40 字内）；world.note 世界观补充（200 字内，"
        "写这个世界最有画面感的地方 / 体系 / 历史，如浮空城、法师塔、旧神战争）\n"
        "- world.power 力量体系：intro 怎么获得、怎么变强（120 字内）；realms 4~8 个境界 / 等级，从低到高，每个 name + desc"
        "（这个境界能做到什么，50 字内）+ cost（突破的门槛或代价，40 字内）；beyond 更高层次的留白（60 字内）。"
        "题材没有修炼 / 等级概念的（都市、悬疑…）就写成主角能力或地位的成长阶梯\n"
        "- world.abilities 能力：innate 先天（谁天生有什么）、acquired 后天（怎么学会 / 换来）、dimensions 衡量能力的维度"
        "（如 魔力量、施法速度、元素亲和）\n"
        "- world.mechanics 2~5 条世界机制（这个世界怎么运转：制度、交易、周期性现象的具体做法和数字），title + desc（60 字内）；"
        "和世界规则写的是同一件事时只写在一处\n"
        "- world.resources 2~5 种关键资源（谁控制、为什么值得争），title + desc（60 字内）\n"
        "- characters 只写主角 1 个：必须有欲望（goal）、缺陷 / 恐惧（fear）、秘密（secret），能力要有代价；role 填「主角」；"
        "名字贴题材、好记，不要用烂大街的名字\n"
        "- 都要贴合选定的灵感和写作参数（题材、文风、卖点）\n"
        '输出 {' + STORY_WORLD_SHAPE + ', ' + LEAD_SHAPE + '}')
    messages = [{"role": "system", "content": STORY_SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]
    data, usage, model = _call(req, messages, 4000, 0.9)
    draft = _clean_settings(data, refs, opening)
    draft["characters"] = [c for c in draft["characters"] if c["role"] == "主角"][:1]
    draft["elements"], draft["stages"] = [], []
    issues = settings_issues(draft, req.get("materials") or [], stage, _written(req.get("novelId")) + 1)
    issues += story_issues(draft, None, opening)
    return {"draft": draft, "issues": issues, "opening": opening, "stage": stage, "usage": usage, "model": model}


CAST_MIN = {"characters": 3, "elements": 4}   # 骨架那一步配角 / 元素的下限（代码检查）
CAST_ELEMENT_SHAPE = '{"category": "faction", "name": "…", "fields": {"stance": "敌对", "feature": "…"}, "tier": 2, "appearFrom": 1}'
CAST_CHARACTER_SHAPE = ('{"name": "…", "role": "反派", "tagline": "一句话人设", "personality": ["性格词，≤4 个"], "goal": "…",'
                        ' "fear": "…", "secret": "…", "abilities": ["…"], "background": "…（100 字内）", "arc": "成长弧光（60 字内）",'
                        ' "relationToLead": "与主角的关系", "appearFrom": 1}')
CAST_RULES = ("- appearFrom = 第几章登场，必须落在骨架里第一次需要它的那个阶段的章节范围内\n"
              "- 对手（反派、宿敌、敌对势力、怪物）的量级不能超过它登场那个阶段的「对手上限」；更强的存在可以有，"
              "但只作传说，或者 appearFrom 放到上限够高的阶段\n"
              "- 骨架「必须发生」里点了名的人物 / 势力 / 地点 / 物品，都要有对应的卡（名字一致）\n"
              "- 名字贴题材、好记，不要用烂大街的名字\n")


def cast(req: dict) -> dict:
    """故事优先 ③ 骨架这一步的人物与元素：{settings（世界 + 主角）, book, premise?, idea?, bookConfig?}
    → {characters（配角，不含主角）, elements, stages, issues}。登场章节落在需要它的阶段里，对手量级不超过所在阶段的上限，
    骨架「必须发生」里点了名的人物 / 势力都要有卡（代码再查一遍）。"""
    bk = clean_book(req.get("book"))
    if not bk:
        raise InspireError("先生成全书骨架")
    draft = req.get("settings") if isinstance(req.get("settings"), dict) else {}
    opening = not _written(req.get("novelId"))
    lead = [c for c in draft.get("characters") or [] if isinstance(c, dict) and c.get("role") == "主角"]
    world_only = {**draft, "characters": lead, "elements": [], "stages": []}
    parts = [_premise(req),
             "【设定】（世界和主角已经定好：人物和元素要建立在这些设定上，不要改、不要另起一套规则或等级）\n"
             + (_settings_text(world_only) or "（还没有设定）"),
             "【全书骨架】\n" + book_text(bk)]
    situation = _situation(req)
    if situation:
        parts.append(f"【这本书现在的局面】（已有的人物 / 元素不要重复，只补接下来需要的）\n{situation}")
    parts.append(
        "【任务】按全书骨架给这本书配人物和元素（主角已经有了，不要再写主角）。\n"
        f"- 配角 4~8 个，role 只能是 {' / '.join(ROLE_LABELS[1:])}；每个人的欲望要和主角冲突或互补\n"
        "- 元素（势力 / 地点 / 物品 / 怪物）5~10 个，覆盖骨架的各个阶段，fields 按下面的字段写；"
        f"tier = 量级 1~5（{TIER_HINT}）\n"
        f"{_element_schema()}\n" + CAST_RULES +
        '输出 {"characters": [' + CAST_CHARACTER_SHAPE + '], "elements": [' + CAST_ELEMENT_SHAPE + ']}')
    messages = [{"role": "system", "content": STORY_SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]
    data, usage, model = _call(req, messages, 6000, 0.9)
    got = _clean_settings({"characters": data.get("characters"), "elements": data.get("elements")}, {}, opening, need_lead=False)
    chars = [c for c in got["characters"] if c["role"] != "主角"]
    issues = cast_issues({**draft, "characters": lead + chars, "elements": got["elements"]}, bk, opening)
    return {"characters": chars, "elements": got["elements"], "stages": book_stages(bk), "issues": issues,
            "usage": usage, "model": model}


def cast_issues(draft: dict, bk: dict, opening: bool) -> list[dict]:
    """骨架这一步的代码检查：人物 / 元素够不够（开篇才查）、对手量级超过登场阶段的上限、骨架点名的东西有没有卡"""
    issues = []
    if opening:
        have = {"characters": sum(1 for c in draft.get("characters") or [] if c.get("role") != "主角"),
                "elements": len(draft.get("elements") or [])}
        for k, lab in (("characters", "配角"), ("elements", "势力 / 地点 / 物品 / 怪物")):
            if have[k] < CAST_MIN[k]:
                issues.append({"type": "thin", "detail": f"{lab}只有 {have[k]} 个（建议至少 {CAST_MIN[k]} 个）"})
    for e in draft.get("elements") or []:
        hostile = e.get("category") == "monster" or "敌" in str((e.get("fields") or {}).get("stance") or "")
        row = book_position(bk, e.get("appearFrom") or 1)
        if hostile and row and row.get("tierMax") and (e.get("tier") or 0) > row["tierMax"]:
            issues.append({"type": "tier", "term": e["name"],
                           "detail": f"「{e['name']}」量级 {e['tier']} 超过登场阶段「{row['title'] or row['volumeTitle']}」"
                                     f"的对手上限 {row['tierMax']}（第{e.get('appearFrom') or 1}章登场）"})
    issues += story_issues(draft, bk, False)
    return issues


def story_issues(draft: dict, bk: dict | None, opening: bool) -> list[dict]:
    """故事优先设定的代码检查：槽位够不够（开篇才查，续规划只补新东西）、骨架「必须发生」里点名的东西设定里有没有"""
    issues = []
    w = draft.get("world") or {}
    if opening:
        realms = len((w.get("power") or {}).get("realms") or [])
        if realms < MIN_COUNTS["realms"]:
            issues.append({"type": "thin", "detail": f"力量体系的境界只有 {realms} 个（建议至少 {MIN_COUNTS['realms']} 个），设定偏单薄"})
    if bk:
        text = _settings_text(draft)
        for r in book_layout(bk):
            for m in r["mustHappen"]:
                for term in re.findall(r"[「《“]([^」》”]{2,12})[」》”]", m):
                    if term not in text:
                        issues.append({"type": "book", "term": term,
                                       "detail": f"骨架「{r['title']}」必须发生的事提到「{term}」，设定里还没有它"})
    return issues


def settings(req: dict) -> dict:
    """{novelId, premise, tone?, materials[], stage?, book?, idea?, bookConfig?, api|local} → {draft, issues, usage, model}
    draft = {world{rules[], note, power, abilities, mechanics, resources}, characters[主角], elements[], stages[]}。
    （素材优先路线 2026-11-02 删掉了，只剩故事优先）"""
    return _settings_story(req, not _written(req.get("novelId")), _stage(req))


# ---------------------------------------------------------------- 设定的单个模块重新生成（四种方式：给不给方向 × 参考不参考已有）

PART_MODULES = {
    # 模块 → (名称, 要求, 输出形状)
    "rules": ("世界规则", "3~6 条这个世界独有的规则，每条 40 字内", '{"rules": ["…"]}'),
    "note": ("世界观补充", "一段世界观补充，200 字内", '{"note": "…"}'),
    "power": ("力量体系", "intro 怎么获得、怎么变强（120 字内）；realms 4~8 个境界 / 等级，从低到高，每个 name + desc（能做到什么，50 字内）"
              "+ cost（突破的门槛或代价，40 字内）；beyond 更高层次的留白（60 字内）。题材没有等级概念的就写成能力 / 地位的成长阶梯",
              '{"power": {"intro": "…", "realms": [{"name": "…", "desc": "…", "cost": "…"}], "beyond": "…"}}'),
    "abilities": ("能力", "innate 先天（谁天生有什么）、acquired 后天（怎么学会 / 换来）、dimensions 衡量能力的维度",
                  '{"abilities": {"innate": "…", "acquired": "…", "dimensions": ["…"]}}'),
    "mechanics": ("世界机制", "2~5 条世界机制（这个世界怎么运转：交易、律法、禁忌…），title + desc（60 字内）",
                  '{"mechanics": [{"title": "…", "desc": "…"}]}'),
    "resources": ("关键资源", "2~5 种关键资源（谁控制、为什么值得争），title + desc（60 字内）",
                  '{"resources": [{"title": "…", "desc": "…"}]}'),
    "lead": ("主角", "主角 1 个（必须有 goal 欲望、fear 缺陷 / 恐惧、secret 秘密，能力有代价，role 填「主角」）", '{' + LEAD_SHAPE + '}'),
    "characters": ("配角", f"配角 4~8 个（role 只能是 {' / '.join(ROLE_LABELS[1:])}，欲望和主角冲突或互补，appearFrom = 第几章登场；"
                   "不要写主角）",
                   '{"characters": [{"name": "…", "role": "主角", "tagline": "…", "personality": ["…"], "goal": "…", "fear": "…",'
                   ' "secret": "…", "abilities": ["…"], "background": "…", "arc": "…", "relationToLead": "…", "appearFrom": 1}]}'),
    "elements": ("势力 / 地点 / 物品 / 怪物", "4~8 个，fields 按字段写，tier = 量级 1~5（" + TIER_HINT + "），appearFrom = 第几章登场",
                 '{"elements": [{"category": "faction", "name": "…", "fields": {"stance": "敌对", "feature": "…"}, "tier": 2, "appearFrom": 1}]}'),
}
WORLD_MODULES = ("rules", "note", "cards", "power", "abilities", "mechanics", "resources")


def _module_value(draft: dict, module: str, category: str = ""):
    if module in WORLD_MODULES:
        return (draft.get("world") or {}).get(module)
    if module == "elements" and category:
        return [e for e in draft.get("elements") or [] if e.get("category") == category]
    if module in ("lead", "characters"):   # 主角 / 配角都在 characters 里，按 role 分开
        lead = module == "lead"
        return [c for c in draft.get("characters") or [] if isinstance(c, dict) and (c.get("role") == "主角") == lead]
    return draft.get(module)


def _without(draft: dict, module: str, category: str = "") -> dict:
    """去掉要重写的那一块（剩下的作为「其余设定」给模型对齐）"""
    d = {**draft, "world": dict(draft.get("world") or {})}
    if module in WORLD_MODULES:
        d["world"].pop(module, None)
    elif module == "elements":
        d["elements"] = [e for e in d.get("elements") or [] if category and e.get("category") != category]
    elif module in ("lead", "characters"):
        lead = module == "lead"
        d["characters"] = [c for c in d.get("characters") or [] if isinstance(c, dict) and (c.get("role") == "主角") != lead]
    else:
        d[module] = []
    return d


def settings_part(req: dict) -> dict:
    """{settings, module, category?（elements 时只重写这一类）, direction?, keep?, premise?, idea?, bookConfig?, book?}
    → {module, category, value, keep, usage}。四种方式：direction 给 / 不给 × keep（参考已有：先读已有内容，保留并补充，不重复）。
    只返回这一块的新内容，前端整块替换（可撤销）。"""
    module = str(req.get("module") or "")
    if module not in PART_MODULES:
        raise InspireError(f"不认识的设定模块：{module}")
    draft = req.get("settings") if isinstance(req.get("settings"), dict) else {}
    category = str(req.get("category") or "") if module == "elements" else ""
    if category and category not in ELEMENT_FIELDS:
        raise InspireError(f"不认识的元素类别：{category}")
    label, need, shape = PART_MODULES[module]
    if category:
        label = ELEMENT_LABELS_ZH[category]
        need = (f"3~6 个{label}，category 都填 {category}；fields 按字段写，tier = 量级 1~5（{TIER_HINT}），"
                "appearFrom = 第几章登场")
    direction = _clip(req.get("direction"), 500)
    keep = bool(req.get("keep"))
    existing = _module_value(draft, module, category)
    opening = not _written(req.get("novelId"))
    parts = [_premise(req)]
    bk = clean_book(req.get("book"))
    if bk:
        parts.append("【全书骨架】\n" + book_text(bk, detail=False))
    rest = _settings_text(_without(draft, module, category))
    if rest and direction:
        # 给了方向：其余设定按块列出（带块名），模型才能说清楚哪一块和方向矛盾
        parts.append("【其余设定】（按块列出；新内容要和这些一致）\n" + _blocks_text(draft, module, category))
    elif rest:
        parts.append("【其余设定】（新内容要和这些一致，不要矛盾）\n" + rest)
    if keep and existing:
        parts.append(f"【已有的{label}】\n" + json.dumps(existing, ensure_ascii=False)[:4000])
    task = [f"【任务】重新生成「{label}」：{need}。"]
    if direction:
        task.append(f"作者给的方向（必须照着来）：{direction}")
    if keep and existing:
        task.append(f"在【已有的{label}】基础上做：已有的保留（作者的方向要求修改的才改），再补充新的，不要和已有的重复；"
                    f"输出完整的{label}（已有的 + 新的）。")
    else:
        task.append("不用管原来的版本，整块重新设计，和【其余设定】保持一致。")
    if module == "elements":
        task.append(_element_schema())
    if module in ("characters", "elements") and bk:
        task.append(CAST_RULES)
    elif module in ("characters", "lead"):
        task.append("名字贴题材、好记。")
    out_shape = shape
    if direction and rest:
        keys = "、".join(CONFLICT_KEYS)
        task.append("另外检查【其余设定】：有和作者这次的方向矛盾的句子，就在 conflicts 里列出 {block: 所在的块（只能是 " + keys + "），"
                    "text: 矛盾的那句（照抄，40 字内）}；只是提到同一个东西、并不矛盾的不算；没有就空数组。")
        out_shape = shape[:-1] + ', "conflicts": [{"block": "rules", "text": "…"}]}'
    task.append("只输出 " + out_shape)
    parts.append("\n".join(task))
    messages = [{"role": "system", "content": STORY_SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]
    max_tokens = 3500 if module in ("characters", "elements") else 1800
    data, usage, model = _call(req, messages, max_tokens, 0.9)
    if module == "lead":
        raw = data.get("characters") or data.get("lead") or []
        raw = [raw] if isinstance(raw, dict) else raw
        value = [{**c, "role": "主角"} for c in _clean_settings({"characters": raw[:1]}, {}, opening)["characters"]]
    elif module in ("characters", "elements"):
        raw = data.get(module) or data.get("items") or []
        if category:   # 只重写一类：模型偶尔不填 / 填错 category，统一改成这一类
            raw = [{**e, "category": category} for e in raw if isinstance(e, dict)]
        got = _clean_settings({module: raw}, {}, opening, need_lead=False)[module]
        value = [c for c in got if c.get("role") != "主角"] if module == "characters" else got
    elif module == "rules":
        value = _strs(data.get("rules"), 60, 8)
    elif module == "note":
        value = _clip(data.get("note"), 800)
    else:
        value = _clean_world_extra({module: data.get(module)}).get(module)
    if not value:
        raise InspireError(f"模型没有给出可用的「{label}」，请重试")
    return {"module": module, "category": category, "value": value, "keep": keep,
            "related": conflicts_of(data, module, category), "usage": usage, "model": model}


CONFLICT_KEYS = ("rules", "note", "power", "abilities", "mechanics", "resources", "lead", "characters",
                 "faction", "location", "item", "monster")


def _blocks_text(draft: dict, module: str, category: str) -> str:
    """其余设定按块列出：[块名] 名称：内容（每块 ≤800 字）"""
    lines = []
    for key in CONFLICT_KEYS:
        m, cat = ("elements", key) if key in ELEMENT_FIELDS else (key, "")
        if (m, cat) == (module, category):
            continue
        v = _module_value(draft, m, cat)
        if not v:
            continue
        label = ELEMENT_LABELS_ZH[cat] if cat else PART_MODULES[m][0]
        text = v if isinstance(v, str) else "；".join(v) if m == "rules" else json.dumps(v, ensure_ascii=False)
        lines.append(f"[{key}] {label}：{text[:800]}")
    return "\n".join(lines)


def conflicts_of(data: dict, module: str, category: str) -> list[dict]:
    """模型指出的「其余设定里和方向矛盾的句子」→ [{module, category, label, term}]：按方向重写一块后提醒作者一起改
    （例：方向「法师塔没有阶数」只改了力量体系，世界规则里还写着「塔每层试炼解锁」）。只认合法的块名，每块一条。
    最早用「方向里的词在别的块里出现」来判断，核心名词（法师塔）几乎每块都有，提醒全是噪音，所以改成让模型判断矛盾"""
    out, seen = [], set()
    for c in data.get("conflicts") or []:
        if not isinstance(c, dict):
            continue
        block = str(c.get("block") or "").strip()
        if block not in CONFLICT_KEYS:
            continue
        m, cat = ("elements", block) if block in ELEMENT_FIELDS else (block, "")
        if (m, cat) == (module, category) or (m, cat) in seen:
            continue
        seen.add((m, cat))
        out.append({"module": m, "category": cat, "label": ELEMENT_LABELS_ZH[cat] if cat else PART_MODULES[m][0],
                    "term": _clip(c.get("text"), 60)})
    return out[:6]


def _clean_settings(d: dict, refs: dict[str, int], opening: bool, need_lead: bool = True) -> dict:
    chars = []
    for c in d.get("characters") or []:
        if not isinstance(c, dict) or not _clip(c.get("name"), 40):
            continue
        role = next((x for x in ROLE_LABELS if x in str(c.get("role") or "")), "配角")
        chars.append({"name": _clip(c.get("name"), 40), "role": role, "tagline": _clip(c.get("tagline"), 80),
                      "personality": _strs(c.get("personality"), 8, 4), "goal": _clip(c.get("goal"), 120),
                      "fear": _clip(c.get("fear"), 120), "secret": _clip(c.get("secret"), 300),
                      "abilities": _strs(c.get("abilities"), 40, 8), "background": _clip(c.get("background"), 600),
                      "arc": _clip(c.get("arc"), 300), "relationToLead": _clip(c.get("relationToLead"), 80),
                      "appearFrom": max(1, _int(c.get("appearFrom"), 1)) if role != "主角" else 1,
                      "sources": inspire._refs(c.get("sources"), refs), "adapted": _clip(c.get("adapted"), 120)})
    if need_lead and chars and not any(c["role"] == "主角" for c in chars):
        chars[0]["role"], chars[0]["appearFrom"] = "主角", 1
    elements = []
    for e in d.get("elements") or []:
        if not isinstance(e, dict) or e.get("category") not in ELEMENT_FIELDS or not _clip(e.get("name"), 40):
            continue
        allowed = ELEMENT_FIELDS[e["category"]]
        fields = {k: (_strs(v, 40, 8) if isinstance(v, list) or k in ("abilities", "weakness") else _clip(v, 600))
                  for k, v in (e.get("fields") or {}).items() if k in allowed and v}
        tier = _int(e.get("tier"))
        elements.append({"category": e["category"], "name": _clip(e.get("name"), 40), "fields": fields,
                         "tier": tier if 1 <= tier <= 5 else None, "appearFrom": max(1, _int(e.get("appearFrom"), 1)),
                         "sources": inspire._refs(e.get("sources"), refs), "adapted": _clip(e.get("adapted"), 120)})
    world = d.get("world") if isinstance(d.get("world"), dict) else {}
    stages = []
    for s in d.get("stages") or []:
        if isinstance(s, dict) and _clip(s.get("range"), 20):
            t = _int(s.get("tierMax"))
            stages.append({"range": _clip(s.get("range"), 20), "power": _clip(s.get("power"), 80),
                           "tierMax": t if 1 <= t <= 5 else None, "note": _clip(s.get("note"), 80)})
    if opening and stages and (stages[0]["tierMax"] or 0) > 2:
        stages[0]["tierMax"] = 2   # 开篇对手上限 2
    return {"title": _clip(d.get("title"), 40), "world": {"rules": _strs(world.get("rules"), 60, 8),
                                                          "note": _clip(world.get("note"), 800), **_clean_world_extra(world)},
            "characters": chars[:8], "elements": elements[:10], "stages": stages[:6]}


def _pairs(v, n: int, limit: int, text_key: str = "desc") -> list[dict]:
    """[{title, desc}]（模型偶尔给字符串「标题：说明」也接住）"""
    out = []
    for x in v if isinstance(v, list) else []:
        if isinstance(x, dict):
            title, desc = _clip(x.get("title") or x.get("name"), 40), _clip(x.get(text_key) or x.get("desc"), n)
        else:
            title, _, desc = str(x or "").partition("：")
            title, desc = _clip(title, 40), _clip(desc, n)
        if title:
            out.append({"title": title, text_key: desc})
    return out[:limit]


def _clean_world_extra(world: dict) -> dict:
    """故事优先的世界观槽位：背景卡 / 力量体系（境界）/ 能力 / 机制 / 资源；没有的键不出现（素材优先的草案不变）"""
    out = {}
    cards = []
    for c in world.get("cards") or []:
        if isinstance(c, dict) and _clip(c.get("title"), 40):
            cards.append({"title": _clip(c.get("title"), 40), "content": _clip(c.get("content") or c.get("desc"), 400),
                          "tags": _strs(c.get("tags"), 12, 5)})
    if cards:
        out["cards"] = cards[:8]
    p = world.get("power") if isinstance(world.get("power"), dict) else {}
    realms = []
    for r in p.get("realms") or []:
        if isinstance(r, dict) and _clip(r.get("name"), 30):
            realms.append({"name": _clip(r.get("name"), 30), "desc": _clip(r.get("desc"), 200), "cost": _clip(r.get("cost"), 160)})
        elif isinstance(r, str) and r.strip():
            realms.append({"name": _clip(r, 30), "desc": "", "cost": ""})
    if realms or _clip(p.get("intro"), 400):
        out["power"] = {"intro": _clip(p.get("intro"), 400), "realms": realms[:10], "beyond": _clip(p.get("beyond"), 200)}
    a = world.get("abilities") if isinstance(world.get("abilities"), dict) else {}
    if any(a.get(k) for k in ("innate", "acquired", "dimensions")):
        out["abilities"] = {"innate": _clip(a.get("innate"), 300), "acquired": _clip(a.get("acquired"), 300),
                            "dimensions": _strs(a.get("dimensions"), 20, 8)}
    for k in ("mechanics", "resources"):
        items = _pairs(world.get(k), 240, 6)
        if items:
            out[k] = items
    return out


# 网文通用词：由它们拼成的素材名（黑市、法师公会、冒险者学院…）不算「照搬原书专有名词」
GENERIC_WORDS = (
    "法师 魔法师 魔导师 剑士 骑士 冒险者 佣兵 盗贼 猎人 刺客 牧师 术士 炼金术士 修士 修仙者 武者 剑修 丹师 器师 阵师 "
    "公会 协会 学院 学府 学宫 商会 帝国 王国 王朝 帝都 王都 皇城 城邦 宗门 门派 世家 家族 教会 神殿 圣殿 议会 联盟 部落 军团 卫队 "
    "黑市 拍卖行 酒馆 旅馆 集市 港口 遗迹 秘境 禁地 深渊 森林 荒原 雪山 沙漠 海域 地下城 地牢 高塔 法师塔 浮空城 "
    "魔法 魔力 灵气 斗气 元素 契约 诅咒 血脉 灵根 功法 秘籍 丹药 灵石 魔晶 魔核 神器 法宝 圣物 "
    "魔兽 妖兽 魔物 亡灵 巨龙 精灵 矮人 兽人 恶魔 天使 神明 吸血鬼 狼人 "
    "主角 反派 导师 伙伴 宿敌 系统 金手指 退婚 打脸 逆袭"
).split()


def _generic(term: str) -> bool:
    """能完全由通用词拼出来（如「法师公会」=「法师」+「公会」）"""
    t = term.strip()
    if not t:
        return True
    return any(t.startswith(w) and (len(t) == len(w) or _generic(t[len(w):])) for w in GENERIC_WORDS)


def _leak_terms(materials: list[dict]) -> dict[str, str]:
    """来源素材的专有名词（名称、多版本的版本名）→ 来源书；草案里出现 = 没改名。通用词拼成的名字不算"""
    terms = {}
    for m in materials:
        for t in [m.get("title"), *[v.get("label") for v in m.get("variants") or [] if isinstance(v, dict)]]:
            t = str(t or "").strip()
            if len(t) >= 2 and not _generic(t):
                terms[t] = m.get("book") or ""
    return terms


def _settings_text(draft: dict) -> str:
    """设定草案 → 提示词文字（大纲 / 审稿用）"""
    lines = []
    w = draft.get("world") or {}
    if w.get("rules") or w.get("note"):
        lines.append("【世界观】" + "；".join(w.get("rules") or []) + (f"\n{w['note']}" if w.get("note") else ""))
    for c in w.get("cards") or []:
        lines.append(f"【背景】{c['title']}：{c['content']}")
    p = w.get("power") or {}
    if p.get("intro") or p.get("realms"):
        realms = " → ".join(r["name"] + (f"（{r['desc']}）" if r.get("desc") else "") for r in p.get("realms") or [])
        lines.append(f"【力量体系】{p.get('intro') or ''}" + (f"\n境界：{realms}" if realms else ""))
    a = w.get("abilities") or {}
    if a:
        lines.append("【能力】" + "；".join(x for x in (a.get("innate") and f"先天：{a['innate']}",
                                                     a.get("acquired") and f"后天：{a['acquired']}") if x))
    for k, lab in (("mechanics", "机制"), ("resources", "资源")):
        for x in w.get(k) or []:
            lines.append(f"【{lab}】{x['title']}：{x['desc']}")
    for c in draft.get("characters") or []:
        bits = [f"{c['name']}（{c['role']}，第{c.get('appearFrom') or 1}章登场）：{c.get('tagline') or ''}"]
        for k, lab in (("goal", "想要"), ("fear", "缺陷 / 恐惧"), ("secret", "秘密"), ("relationToLead", "与主角"), ("arc", "成长")):
            if c.get(k):
                bits.append(f"{lab}：{c[k]}")
        if c.get("abilities"):
            bits.append("能力：" + "、".join(c["abilities"]))
        lines.append("【人物】" + "｜".join(bits))
    for e in draft.get("elements") or []:
        f = "；".join(f"{v if isinstance(v, str) else '、'.join(v)}" for v in (e.get("fields") or {}).values())
        lines.append(f"【{e['category']}】{e['name']}（量级 {e.get('tier') or '?'}，第{e.get('appearFrom') or 1}章登场）：{f}")
    for s in draft.get("stages") or []:
        lines.append(f"【阶段】第{s['range']}章：主角 {s.get('power') or ''}，对手上限 {s.get('tierMax') or '?'}")
    return "\n".join(lines)


def settings_issues(draft: dict, materials: list[dict], stage: dict, start: int) -> list[dict]:
    """代码能确定的问题：原书名词泄漏、前 10 章的对手超量级、没有主角 / 主角缺欲望缺陷"""
    issues = []
    text = _settings_text(draft) + " " + (draft.get("title") or "")
    for term, book in _leak_terms(materials).items():
        if term in text:
            issues.append({"type": "leak", "term": term,
                           "detail": f"「{term}」是素材原名" + (f"（来自《{book}》）" if book else "") + "，改编时一般要换掉"})
    tier_max = stage.get("tierMax")
    end = start + CHAPTERS - 1
    if tier_max:
        for e in draft.get("elements") or []:
            hostile = e["category"] == "monster" or "敌" in str((e.get("fields") or {}).get("stance") or "")
            if hostile and (e.get("tier") or 0) > tier_max and (e.get("appearFrom") or 1) <= end:
                issues.append({"type": "tier", "term": e["name"],
                               "detail": f"「{e['name']}」量级 {e['tier']} 超过阶段上限 {tier_max}，却在第{e.get('appearFrom') or 1}章登场"
                                         "（改成第 10 章以后登场，或只作传说）"})
    leads = [c for c in draft.get("characters") or [] if c["role"] == "主角"]
    if not leads:
        issues.append({"type": "lead", "detail": "没有主角"})
    for c in leads:
        missing = [lab for k, lab in (("goal", "欲望"), ("fear", "缺陷"), ("secret", "秘密")) if not c.get(k)]
        if missing:
            issues.append({"type": "lead", "term": c["name"], "detail": f"主角缺少：{'、'.join(missing)}"})
    return issues


# ---------------------------------------------------------------- ③ 大纲 + 伏笔计划

def outline(req: dict) -> dict:
    """{novelId, premise, tone?, settings(draft), materials[], stage?, count?, api|local}
    → {outline{title, logline, synopsis, chapters[], foreshadows[], clocks[]}, issues, usage, model}"""
    draft = req.get("settings") if isinstance(req.get("settings"), dict) else {}
    start = _written(req.get("novelId")) + 1
    count = max(3, min(CHAPTERS, _int(req.get("count"), CHAPTERS)))
    opening = start == 1
    stage = _stage(req)
    block, _ = inspire._material_block(req.get("materials") or [])
    bk = clean_book(req.get("book"))
    parts = [_premise(req)]
    if bk:
        parts.append("【全书骨架】\n" + book_text(bk, detail=False))
    parts.append("【设定】\n" + (_settings_text(draft) or "（还没有设定）"))
    situation = _situation(req)
    if situation:
        parts.append(f"【已写内容的局面】\n{situation}")
        opens = facts_mod.open_foreshadows(store.get_facts(req["novelId"]))
        if opens:
            parts.append("【账本里未回收的伏笔】（可以推进 / 回收，引用编号 F…）\n"
                         + "\n".join(f"- {f['id']}：{f['text']}" for f in opens[-15:]))
    sb, row = stage_block(bk, start, count)
    if sb:
        parts.append(sb)
    st = inspire._stage_text({**stage, "chapter": start})
    if st:
        parts.append(st)
    if block:
        parts.append(f"【素材】（参考，已改编进设定）\n{block}")
    if opening:
        parts.append(OPENING_RULES)
    parts.append(
        f"【任务】规划第 {start}~{start + count - 1} 章（共 {count} 章）的大纲，并设计伏笔和定时事件。\n"
        + ("- 这些章要推进【当前阶段】的目标，遵守「不能发生」；伏笔可以为后面的阶段埋\n" if row else "") +
        "- 每章：title 标题；goal 本章目标（这一章具体发生什么、推进什么冲突，60~120 字）；beats 3~5 个节拍；"
        "cast 本章出场的有名有姓人物；newTerms 本章第一次出现的专有名词（地名、组织、功法、物品）；"
        "foreshadow 本章对伏笔做什么 [{key, action: plant 埋下 / advance 推进 / resolve 回收}]；clocks 本章定下或到期的定时事件 key；"
        "hook 章末钩子（30 字内）" + ("；openingNote 本章的开篇要点（作者写的时候注意什么，40 字内）" if opening else "") + "\n"
        "- 人物只用设定里的（可以有无名路人），并且不早于他的登场章节出场；配角登场那一章的节拍里要写出他想要什么、"
        "为什么这么做（不要只当推动主角的工具人）\n"
        "- 不要保守：每章都要有让读者想追下一章的强冲突或强悬念（有人付出代价、关系破裂、计划败露、局势失控），"
        "主角要主动出手而不是被事件推着走；合理不等于平淡\n"
        f"- foreshadows：3~6 条伏笔，key 用 P1、P2…，plantIn 埋下的章，payoffIn 回收的章（至少隔 {MIN_PAYOFF_GAP} 章；"
        f"可以留到第 {start + count - 1} 章以后，写 0）；每条伏笔在 chapters 的 foreshadow 里至少出现一次 plant\n"
        "- clocks：0~3 个定时事件（「三天后的入学考核」），key 用 K1…，setIn 定下的章，dueIn 到期的章（可以 0 = 规划之后）\n"
        '输出 {"title": "书名", "logline": "一句话故事（40 字内）", "synopsis": "梗概（200~400 字）",'
        ' "chapters": [{"index": ' + str(start) + ', "title": "…", "goal": "…", "beats": ["…"], "cast": ["…"], "newTerms": ["…"],'
        ' "foreshadow": [{"key": "P1", "action": "plant"}], "clocks": ["K1"], "hook": "…", "openingNote": "…"}],'
        ' "foreshadows": [{"key": "P1", "text": "伏笔内容（40 字内）", "plantIn": 1, "payoffIn": 6}],'
        ' "clocks": [{"key": "K1", "text": "…", "due": "三天后", "setIn": 2, "dueIn": 5}]}')
    system = SYSTEM if block else STORY_SYSTEM
    messages = [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(parts)}]
    data, usage, model = _call(req, messages, 6000, 0.8)
    out = _clean_outline(data, start, count)
    issues = outline_issues(out, draft, opening, start) + stage_issues(out, row)
    return {"outline": out, "issues": issues, "opening": opening, "stage": stage, "bookStage": row,
            "usage": usage, "model": model}


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[\s，。、；：！？「」“”《》（）,.;:!?()]", "", text or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


def stage_issues(out: dict, row: dict | None) -> list[dict]:
    """当前阶段在这批章节里结束时：「必须发生」的事在章节目标 / 节拍里有没有（字二元组重合 ≥ 30%，只是提示）"""
    if not row or not out["chapters"] or row["end"] > out["chapters"][-1]["index"]:
        return []
    text = _bigrams(" ".join(c["goal"] + " ".join(c.get("beats") or []) for c in out["chapters"]))
    issues = []
    for m in row["mustHappen"]:
        grams = _bigrams(m)
        if grams and len(grams & text) / len(grams) < 0.3:
            issues.append({"type": "stage", "detail": f"阶段「{row['title']}」在第 {row['end']} 章结束，但「{m}」在大纲里没找到"})
    return issues


def _clean_outline(d: dict, start: int, count: int) -> dict:
    chapters = []
    for i, c in enumerate(x for x in d.get("chapters") or [] if isinstance(x, dict) and _clip(x.get("goal"), 2000)):
        if i >= count:
            break
        refs = [{"key": _clip(r.get("key") or r.get("id"), 20),
                 "action": r.get("action") if r.get("action") in ("plant", "advance", "resolve") else "advance"}
                for r in c.get("foreshadow") or [] if isinstance(r, dict) and (r.get("key") or r.get("id"))][:8]
        chapters.append({"index": start + i, "title": _clip(c.get("title"), 60), "goal": _clip(c.get("goal"), 2000),
                         "beats": _strs(c.get("beats"), 200, 6), "cast": _strs(c.get("cast"), 40, 12),
                         "newTerms": _strs(c.get("newTerms"), 30, 12), "foreshadow": refs,
                         "clocks": _strs(c.get("clocks"), 20, 5), "hook": _clip(c.get("hook"), 120),
                         "openingNote": _clip(c.get("openingNote"), 120)})
    fs = [{"key": _clip(f.get("key"), 20), "text": _clip(f.get("text"), 120), "plantIn": _int(f.get("plantIn")),
           "payoffIn": _int(f.get("payoffIn"))}
          for f in d.get("foreshadows") or [] if isinstance(f, dict) and _clip(f.get("key"), 20) and _clip(f.get("text"), 120)][:8]
    # 计划章节以每章的引用为准（埋下 = 第一次 plant，回收 = resolve）
    for f in fs:
        plants = [c["index"] for c in chapters for r in c["foreshadow"] if r["key"] == f["key"] and r["action"] == "plant"]
        pays = [c["index"] for c in chapters for r in c["foreshadow"] if r["key"] == f["key"] and r["action"] == "resolve"]
        if plants:
            f["plantIn"] = plants[0]
        if pays:
            f["payoffIn"] = pays[-1]
    clocks = [{"key": _clip(k.get("key"), 20), "text": _clip(k.get("text"), 120), "due": _clip(k.get("due"), 60),
               "setIn": _int(k.get("setIn")), "dueIn": _int(k.get("dueIn"))}
              for k in d.get("clocks") or [] if isinstance(k, dict) and _clip(k.get("key"), 20) and _clip(k.get("text"), 120)][:4]
    return {"title": _clip(d.get("title"), 40), "logline": _clip(d.get("logline"), 200),
            "synopsis": _clip(d.get("synopsis"), 3000), "chapters": chapters, "foreshadows": fs, "clocks": clocks}


def outline_issues(out: dict, draft: dict, opening: bool, start: int) -> list[dict]:
    """代码检查：开篇前 3 章的新人物 / 新名词数量、章末钩子、人物提前登场、伏笔埋了没收 / 隔得太近 / 引用不存在"""
    issues = []
    appear = {c["name"]: c.get("appearFrom") or 1 for c in draft.get("characters") or []}
    appear.update({e["name"]: e.get("appearFrom") or 1 for e in draft.get("elements") or []})
    seen: set[str] = set()
    keys = {f["key"] for f in out["foreshadows"]}
    for c in out["chapters"]:
        n = c["index"]
        if not c.get("hook"):
            issues.append({"chapter": n, "type": "hook", "detail": "没有章末钩子"})
        new_names = [x for x in c.get("cast") or [] if x not in seen]
        seen.update(c.get("cast") or [])
        if opening and n < start + OPENING_CHAPTERS:
            if len(new_names) > MAX_NEW_NAMES:
                issues.append({"chapter": n, "type": "opening",
                               "detail": f"新出场人物 {len(new_names)} 个（{'、'.join(new_names)}），开篇每章不超过 {MAX_NEW_NAMES} 个"})
            limit = FIRST_CHAPTER_TERMS if n == start else MAX_NEW_TERMS
            if len(c.get("newTerms") or []) > limit:
                issues.append({"chapter": n, "type": "opening",
                               "detail": f"新名词 {len(c['newTerms'])} 个（{'、'.join(c['newTerms'])}），"
                                         + (f"第 1 章不超过 {limit} 个，设定留到后面用到再露" if n == start
                                            else f"开篇每章不超过 {limit} 个，读者记不住")})
        for name in c.get("cast") or []:
            if appear.get(name, 1) > n:
                issues.append({"chapter": n, "type": "early",
                               "detail": f"「{name}」设定第{appear[name]}章登场，但第{n}章出场了"})
        for r in c.get("foreshadow") or []:
            if r["key"] not in keys and not re.fullmatch(r"F\d+", r["key"], re.I):
                issues.append({"chapter": n, "type": "foreshadow", "detail": f"引用了没定义的伏笔 {r['key']}"})
    end = start + len(out["chapters"]) - 1
    for f in out["foreshadows"]:
        if not f["plantIn"]:
            issues.append({"type": "foreshadow", "detail": f"伏笔 {f['key']}「{f['text']}」没安排在哪章埋下"})
        elif f["payoffIn"] and f["payoffIn"] - f["plantIn"] < MIN_PAYOFF_GAP:
            issues.append({"type": "foreshadow",
                           "detail": f"伏笔 {f['key']} 第{f['plantIn']}章埋、第{f['payoffIn']}章就收，至少隔 {MIN_PAYOFF_GAP} 章"})
    if out["chapters"] and not any(f["payoffIn"] and f["payoffIn"] <= end for f in out["foreshadows"]):
        issues.append({"type": "foreshadow", "detail": f"这 {len(out['chapters'])} 章里没有任何伏笔回收，读者得不到兑现"})
    return issues


# ---------------------------------------------------------------- ④ 审稿

def review(req: dict) -> dict:
    """{novelId, premise, settings, outline, stage?, api|local} → {chapters[{index, problems, revised?}], overall[], usage, model}
    revised = 修正版 {title, goal, beats, hook}（作者在界面上逐章决定用不用）"""
    draft = req.get("settings") if isinstance(req.get("settings"), dict) else {}
    out = req.get("outline") if isinstance(req.get("outline"), dict) else {}
    chapters = out.get("chapters") or []
    if not chapters:
        raise InspireError("还没有大纲")
    start = chapters[0]["index"]
    opening = start == 1
    stage = _stage(req)
    lines = []
    for c in chapters:
        fs = "、".join(f"{r.get('key')}:{r.get('action')}" for r in c.get("foreshadow") or [])
        lines.append(f"第{c['index']}章《{c.get('title', '')}》：{c.get('goal', '')}\n  节拍：{'；'.join(c.get('beats') or [])}"
                     f"\n  出场：{'、'.join(c.get('cast') or [])}｜伏笔：{fs or '无'}｜钩子：{c.get('hook') or '无'}")
    fs_lines = [f"{f['key']}：{f['text']}（第{f.get('plantIn') or '?'}章埋，第{f.get('payoffIn') or '之后'}章收）"
                for f in out.get("foreshadows") or []]
    parts = [_premise(req), "【设定】\n" + _settings_text(draft)]
    situation = _situation(req)
    if situation:
        parts.append(f"【已写内容的局面】\n{situation}")
    sb, row = stage_block(clean_book(req.get("book")), start, len(chapters))
    if sb:
        parts.append(sb)
    st = inspire._stage_text({**stage, "chapter": start})
    if st:
        parts.append(st)
    if opening:
        parts.append(OPENING_RULES)
    parts.append(f"【大纲】{out.get('logline') or ''}\n" + "\n".join(lines) + "\n【伏笔计划】\n" + ("\n".join(fs_lines) or "（无）"))
    parts.append(
        "【任务】逐章审这份大纲：和设定 / 人物动机 / 阶段量级矛盾的地方、冲突不够或拖沓的章节、没有钩子、伏笔埋了不收或收得太突兀"
        + ("、违反【开篇规则】的地方" if opening else "")
        + ("、偏离【当前阶段】目标或写了「不能发生」的事" if row else "") + "。\n"
        "每章：problems 列具体问题（最多 3 条，每条 50 字内，没有就空）；只有问题严重的章才给 revised 修正版"
        "（全部最多 5 章；保留这章在全书里的作用，冲突保留甚至加强，人物不能早于设定的登场章节），其他章 revised 填 null。\n"
        "overall：整体问题（节奏、主线是否清楚、前 10 章结束时读者为什么会继续看）。\n"
        '输出 {"chapters": [{"index": 1, "problems": ["…"], "revised": {"title": "…", "goal": "…", "beats": ["…"], "hook": "…"}}],'
        ' "overall": ["…"]}')
    messages = [{"role": "system", "content": REVIEW_SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]
    cleaned = _clean_outline({**out, "chapters": chapters}, start, len(chapters))
    code = outline_issues(cleaned, draft, opening, start) + stage_issues(cleaned, row)
    try:
        data, usage, model = _call(req, messages, 8000, 0.3)   # 5000 时 4 次里 3 次被截断（10 章逐章 + 修正版）
    except InspireError as e:   # 审稿不是必须的：模型两次都坏了 → 只给代码检查
        return {"chapters": [], "overall": [], "codeIssues": code, "error": str(e), "usage": None, "model": ""}
    idx = {c["index"] for c in chapters}
    result = []
    for c in data.get("chapters") or []:
        if not isinstance(c, dict) or _int(c.get("index")) not in idx:
            continue
        rev = c.get("revised") if isinstance(c.get("revised"), dict) and _clip((c.get("revised") or {}).get("goal"), 2000) else None
        problems = _strs(c.get("problems"), 300, 6)
        result.append({"index": _int(c["index"]), "problems": problems,
                       "revised": {"title": _clip(rev.get("title"), 60), "goal": _clip(rev.get("goal"), 2000),
                                   "beats": _strs(rev.get("beats"), 200, 6), "hook": _clip(rev.get("hook"), 120)}
                       if rev and problems else None})
    return {"chapters": result, "overall": _strs(data.get("overall"), 300, 6), "codeIssues": code, "usage": usage, "model": model}


# ---------------------------------------------------------------- ⑤ 写进工作区（设定由前端写进设定编辑器后保存）

def apply(novel_id: str, req: dict) -> dict:
    """{outline{title?, logline, synopsis, chapters[{…, foreshadow[{key, action}], clocks[key]}], foreshadows[], clocks[]},
       setTitle?, book?, bookConfig?} → 计划伏笔 / 定时事件记进账本（planned），大纲里的 key 换成账本编号后保存为 novel.outline；
       book = 全书骨架（novel.book，续规划按它找当前阶段），bookConfig = 写作参数（novel.bookConfig，写正文进【作品定位】）"""
    out = req.get("outline") if isinstance(req.get("outline"), dict) else {}
    novel = store.get_novel(novel_id)
    extra = {}
    if clean_book(req.get("book")):
        extra["book"] = clean_book(req["book"])
    if spec_mod.clean_book_config(req.get("bookConfig")):
        extra["bookConfig"] = spec_mod.clean_book_config(req["bookConfig"])
    if not out.get("chapters"):
        # 故事优先现在到骨架为止：没有大纲，只存骨架 / 写作参数 / 书名（设定由前端写进设定编辑器）
        if not extra and not req.get("setTitle"):
            raise InspireError("没有可写入的内容")
        fields = dict(extra)
        title = _clip(req.get("title") or out.get("title"), 40)
        if req.get("setTitle") and title:
            fields["title"] = title
        if fields:
            store.update_novel(novel_id, **fields)
        return {"outline": None, "ids": {}, "planned": 0, "book": bool(extra.get("book"))}
    facts = store.get_facts(novel_id)
    ids = facts_mod.add_plan(facts, out.get("foreshadows") or [], out.get("clocks") or [])
    chapters = []
    for c in out["chapters"]:
        refs = []
        for r in c.get("foreshadow") or []:
            key = str(r.get("key") or r.get("id") or "")
            fid = ids.get(key) or (key.upper() if re.fullmatch(r"F\d+", key, re.I) else None)
            if fid:
                refs.append({"id": fid, "action": r.get("action")})
        clocks = [ids[k][2:] for k in c.get("clocks") or [] if str(ids.get(k, "")).startswith("C:")]
        chapters.append({**c, "foreshadow": refs, "clocks": clocks})
    old = novel.get("outline") or {}
    keep = [c for c in old.get("chapters") or [] if c["index"] < chapters[0]["index"]]   # 规划之前的章节大纲保留
    saved = ideas.validate_outline({"logline": out.get("logline") or old.get("logline") or "",
                                    "synopsis": out.get("synopsis") or old.get("synopsis") or "",
                                    "chapters": keep + chapters, "materials": old.get("materials") or []})
    facts_mod.sync_outline(facts, saved)
    store.save_facts(novel_id, facts)
    fields = {"outline": saved, **extra}
    if req.get("setTitle") and _clip(out.get("title"), 40):
        fields["title"] = _clip(out.get("title"), 40)
    store.update_novel(novel_id, **fields)
    return {"outline": saved, "ids": ids, "planned": sum(1 for f in facts["foreshadows"] if f["status"] == "planned"),
            "book": bool(extra.get("book"))}


# ---------------------------------------------------------------- 故事优先 ④ 素材点睛（可选）

ENRICH_FIELDS = {"character": ("tagline", "goal", "fear", "secret", "abilities", "background", "arc"),
                 **{k: tuple(v) for k, v in ELEMENT_FIELDS.items()}}
MAX_SUGGESTIONS = 8


def enrich_targets(draft: dict) -> list[dict]:
    """设定草案里可以「点睛」的对象：人物 + 元素 → [{key T1…, kind, index, name, text, fields}]（Java 也按这个顺序检索）"""
    out = []
    for i, c in enumerate(draft.get("characters") or []):
        if c.get("name"):
            text = "｜".join(x for x in (c.get("role"), c.get("tagline"), "、".join(c.get("abilities") or []), c.get("goal")) if x)
            out.append({"kind": "character", "index": i, "name": c["name"], "text": text, "fields": ENRICH_FIELDS["character"]})
    for i, e in enumerate(draft.get("elements") or []):
        if e.get("name") and e.get("category") in ENRICH_FIELDS:
            f = "；".join(v if isinstance(v, str) else "、".join(v) for v in (e.get("fields") or {}).values())
            out.append({"kind": e["category"], "index": i, "name": e["name"], "text": f[:200], "fields": ENRICH_FIELDS[e["category"]]})
    for n, t in enumerate(out, 1):
        t["key"] = f"T{n}"
    return out


def enrich(req: dict) -> dict:
    """{settings(draft), materials[]（Java 按每个对象检索到的）, links{materialId: [T…]}} → {suggestions[{target, kind, index, name,
    suggestion, fields{字段: 补充}, sources[素材 id], leaks[]}]}。只补细节，不改名、不推翻设定；作者逐条采用。"""
    draft = req.get("settings") if isinstance(req.get("settings"), dict) else {}
    materials = req.get("materials") or []
    targets = enrich_targets(draft)
    if not materials or not targets:
        return {"suggestions": [], "usage": None, "model": ""}
    block, refs = inspire._material_block(materials)
    by_id = {v: k for k, v in refs.items()}
    hints: dict[str, list[str]] = {}
    for mid, keys in (req.get("links") or {}).items():
        s = by_id.get(_int(mid))
        for k in keys if isinstance(keys, list) else [keys]:
            if s:
                hints.setdefault(str(k), []).append(s)
    lines = [f"[{t['key']}] {t['name']}（{ELEMENT_LABELS_ZH.get(t['kind'], t['kind'])}）：{t['text']}"
             f"｜可补的字段：{'、'.join(t['fields'])}" + (f"｜检索到的素材：{'、'.join(hints[t['key']])}" if hints.get(t["key"]) else "")
             for t in targets]
    parts = [_premise(req), "【设定】\n" + _settings_text(draft), "【可以点睛的对象】\n" + "\n".join(lines),
             "【素材】（从素材库检索到的）\n" + block,
             "【任务】这套设定已经能用。看看这些素材能不能给某个对象「点睛」：补一个更具体、更有意思的细节"
             "（能力的代价、怪物的弱点、势力的内部矛盾、人物的秘密、地点的特殊规则…）。\n"
             f"- 只在素材真的让设定更好时才给，宁缺毋滥，最多 {MAX_SUGGESTIONS} 条；不推翻原设定，不改名字\n"
             "- 素材里的人名、地名、组织名、功法名不能照搬，换成这本书里的说法\n"
             "- 每条：target 对象编号（T1…）；suggestion 给作者看的一句话：加什么 / 改什么（60 字内）；"
             "fields 要补进设定的内容 {字段名: 补充的文字}，字段名只能用这个对象「可补的字段」里的；sources 用到的素材编号\n"
             '输出 {"suggestions": [{"target": "T1", "suggestion": "…", "fields": {"secret": "…"}, "sources": ["S1"]}]}']
    messages = [{"role": "system", "content": STORY_SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]
    data, usage, model = _call(req, messages, 3000, 0.7)
    tmap = {t["key"]: t for t in targets}
    leaks = _leak_terms(materials)
    out = []
    for s in data.get("suggestions") or []:
        t = tmap.get(str((s or {}).get("target") or "").strip().upper()) if isinstance(s, dict) else None
        if not t:
            continue
        # 列表字段给成一句话时整句当一条（按逗号拆会拆成「但自创连线时精神反噬」这种碎片）
        fields = {k: ((_strs(v, 80, 6) if isinstance(v, list) else [_clip(v, 120)]) if k in ("abilities", "weakness")
                      else _clip(v, 400))
                  for k, v in (s.get("fields") or {}).items() if k in t["fields"] and v} if isinstance(s.get("fields"), dict) else {}
        if not fields:
            continue
        text = " ".join([_clip(s.get("suggestion"), 200)] + [v if isinstance(v, str) else "、".join(v) for v in fields.values()])
        out.append({"target": t["key"], "kind": t["kind"], "index": t["index"], "name": t["name"],
                    "suggestion": _clip(s.get("suggestion"), 200), "fields": fields,
                    "sources": inspire._refs(s.get("sources"), refs), "leaks": [k for k in leaks if k in text]})
    return {"suggestions": out[:MAX_SUGGESTIONS], "usage": usage, "model": model}


ELEMENT_LABELS_ZH = {"character": "人物", "faction": "势力", "location": "地点", "item": "物品", "monster": "怪物"}
