"""灵感墙的 AI 部分：拆需求 → （Java 检索素材）→ 生成思路；细化、追问修改。

由 Java 的 /api/inspire/** 转发（素材库在 Java 的数据库里，检索也在 Java 做）。四个接口都不保存任何东西，
结果由 Java 存进构思记录 / 灵感墙。模型：大模型（api，Key 只在本次请求里）/ GGUF / 应用内本地模型，
调用、JSON 容错解析复用 ideas 模块。

素材在提示词里编号为 [S1] [S2]…，思路里的每一处借用都要写编号；代码检查编号，不在本次素材里的引用去掉，
一条有效引用都没有的思路标 uncited。
"""
import re

from . import ideas, store
from ..materials import CATEGORIES

TARGETS = {
    "adventure": "冒险路线", "plot": "剧情段", "location": "地点", "monster": "怪物", "faction": "势力",
    "character": "角色", "world": "世界设定", "item": "物品功法", "free": "自由构思",
}
# 不同「生成什么」的正文结构
TARGET_SHAPE = {
    "adventure": "sections 是冒险的若干站（3~6 站），heading 写「地点名」，text 写在这里遭遇什么、发生什么事件或转折",
    "plot": "sections 按 起因 / 冲突 / 转折 / 结果 四段写",
    "location": "sections 写这个地点的 外观与环境 / 危险 / 特殊规则 / 居民或势力 / 能发生的故事",
    "monster": "sections 写 外形 / 能力 / 弱点及原因 / 习性 / 与人类的关系 / 名场面设想",
    "faction": "sections 写 结构 / 目标 / 资源 / 内部矛盾 / 和主角的交集",
    "character": "sections 写 人设核心 / 反差 / 能力 / 动机 / 关系 / 名场面设想",
    "world": "sections 写 规则内容 / 代价 / 限制 / 谁能打破 / 对社会的影响",
    "item": "sections 写 作用 / 代价 / 获取方式 / 限制 / 名场面设想",
    "free": "sections 按内容需要自由分段（2~6 段）",
}
MAX_NEEDS = 8
MAX_COUNT = 5
CONTEXT_CHARS = 4000      # 关联工作区时带的设定 / 大纲 / 章节上限
REQUEST_CHARS = 1000
WALL_IDEAS = 12           # 墙上已有思路最多带几条（只带标题和卖点）

SYSTEM = """你是网络小说的创意策划，擅长把现成的素材组合成新的构思。只输出 JSON，不要任何多余文字。
原则：
1. 素材是从别的小说里提取的：可以借用设定、机制、结构，但要改名、改细节、重新组合，不要照搬原作的人名地名和具体情节。
2. 每次借用都要写清借的是哪条素材（编号）、改了什么。
3. 标着「共 N 种写法」的素材按它后面括号里的要求使用。
4. 构思要具体、有冲突、能直接往下写，避免空泛套话。"""


class InspireError(ValueError):
    pass


def _clip(text, limit: int) -> str:
    return str(text or "").strip()[:limit]


def _context(novel_id: str | None) -> str:
    """关联了工作区：设定（核心 + 卡片）、大纲、已写章节，截到 CONTEXT_CHARS。"""
    if not novel_id:
        return ""
    try:
        novel = store.get_novel(novel_id)
    except store.StoreError:
        return ""
    text, _ = ideas._context(novel)
    return text[:CONTEXT_CHARS]


def _request_text(req: dict) -> str:
    target = TARGETS.get(req.get("target") or "free", "自由构思")
    lines = [f"生成什么：{target}"]
    if _clip(req.get("request"), REQUEST_CHARS):
        lines.append(f"作者的需求：{_clip(req.get('request'), REQUEST_CHARS)}")
    if _clip(req.get("conditions"), REQUEST_CHARS):
        lines.append(f"补充条件（必须满足）：{_clip(req.get('conditions'), REQUEST_CHARS)}")
    return "\n".join(lines)


def _wall_text(req: dict) -> str:
    wall = [w for w in req.get("wallIdeas") or [] if isinstance(w, dict) and w.get("title")][:WALL_IDEAS]
    if not wall:
        return ""
    lines = "\n".join(f"- {_clip(w.get('title'), 40)}：{_clip(w.get('pitch'), 120)}" for w in wall)
    return f"【灵感墙上已收藏的思路】（新的思路不要和它们重复；可以基于它们延展）\n{lines}"


def _run(req: dict, messages: list[dict], max_tokens: int, temperature: float = 0.9) -> tuple[dict, str]:
    local = req.get("local")
    if local and local.get("baseId"):
        r, name = ideas._run_local(local, messages, max_tokens, temperature=temperature, use_adapter=False)
    elif req.get("api"):
        r, name = ideas._run_api(req["api"], messages, max_tokens, temperature=temperature)
    else:
        raise InspireError("请选择大模型、GGUF 或本地模型")
    return r, name


def _usage(r: dict) -> dict:
    return {"promptTokens": r["promptTokens"], "completionTokens": r["completionTokens"]}


def _parse(text: str, req: dict) -> dict:
    try:
        return ideas._parse(text, req.get("local"))
    except ideas.IdeaError as e:
        raise InspireError(str(e)) from e


# ---------------------------------------------------------------- ① 拆需求

def plan(req: dict) -> dict:
    """→ {summary, needs: [{category, query, count, why}], explore, usage, model}"""
    context = _context(req.get("novelId"))
    empty = not _clip(req.get("request"), 10) and not _clip(req.get("conditions"), 10)
    cats = "；".join(f"{k}={v[0]}" for k, v in CATEGORIES.items())
    if empty and not context:
        guide = ("作者什么都没给，也没有关联小说：请按「生成什么」列出宽泛而多样的检索方向，"
                 "让不同方向能组合出意想不到的构思。")
    elif empty:
        guide = "作者没写具体需求：请根据上面这部小说的设定、大纲和最近章节，判断接下来最需要什么素材。"
    else:
        guide = "根据作者的需求和条件，判断需要从素材库里找哪些素材。"
    parts = []
    if context:
        parts.append(f"【关联的小说】\n{context}")
    if _wall_text(req):
        parts.append(_wall_text(req))
    parts.append(f"【本次构思】\n{_request_text(req)}")
    parts.append(
        f"【任务】{guide}\n把需要的素材拆成 2~{MAX_NEEDS} 条检索需求，每条只对应一个分类（分类代码：{cats}）。"
        "query 写 3~10 个用空格隔开的检索词（具体名词、场景、特征，比如「冰原 雪山 极寒 暴风雪」），"
        "补充条件里的地理环境 / 限制要体现在相关需求的检索词里。count 是这条需要几条素材（1~6）。\n"
        '输出：{"summary":"一句话说明你理解的需求","needs":[{"category":"分类代码","query":"检索词","count":4,'
        '"why":"这条素材在构思里用来干什么，20 字内"}]}')
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]
    r, model = _run(req, messages, 900, temperature=0.6)
    data = _parse(r["text"], req)
    needs = []
    for n in data.get("needs") or []:
        if not isinstance(n, dict) or n.get("category") not in CATEGORIES or not _clip(n.get("query"), 200):
            continue
        try:
            count = max(1, min(6, int(n.get("count") or 3)))
        except (TypeError, ValueError):
            count = 3
        needs.append({"category": n["category"], "query": _clip(n.get("query"), 200), "count": count,
                      "why": _clip(n.get("why"), 60)})
    if not needs:
        raise InspireError("模型没有给出可用的检索需求，请重试或换个说法")
    return {"summary": _clip(data.get("summary"), 200), "needs": needs[:MAX_NEEDS], "explore": empty and not context,
            "usage": _usage(r), "model": model}


# ---------------------------------------------------------------- ③ 生成思路

def _material_block(materials: list[dict]) -> tuple[str, dict[str, int]]:
    """素材 → 带编号的提示词块（[S1]…，多版本写法沿用 ideas._material_lines）和 编号 → 素材 id。"""
    lines, refs = [], {}
    for i, m in enumerate(materials[:ideas.MAX_MATERIALS * 2], 1):
        line = ideas._material_lines([m])[0]
        book = f"（来自《{m['book']}》）" if m.get("book") else ""
        lines.append(f"[S{i}]{book} " + re.sub(r"^- ", "", line, count=1))
        refs[f"S{i}"] = m["id"]
    return "\n".join(lines), refs


IDEA_FIELDS = ('{"title":"思路标题，不超过 16 字","pitch":"一句话卖点，不超过 60 字",'
               '"sections":[{"heading":"小标题","text":"具体内容，80~200 字","sources":["S1"]}],'
               '"elements":[{"category":"分类代码","name":"新名字","desc":"它在这个构思里是什么，60 字内",'
               '"sources":["S2"],"change":"相对素材改了什么，40 字内"}],'
               '"twist":"至少一处素材里没有的反转 / 新东西，60 字内","questions":["待作者决定的问题"]}')


def _refs(value, refs: dict[str, int]) -> list[int]:
    out = []
    for s in value if isinstance(value, list) else [value]:
        m = re.search(r"S\s*(\d+)", str(s or ""), re.I)
        mid = refs.get(f"S{m.group(1)}") if m else None
        if mid is not None and mid not in out:
            out.append(mid)
    return out


def _clean_idea(d: dict, refs: dict[str, int]) -> dict | None:
    """模型的思路 → 统一结构；素材编号换成素材 id，不在本次素材里的引用去掉。"""
    if not isinstance(d, dict) or not _clip(d.get("title"), 40):
        return None
    sections = []
    for s in d.get("sections") or []:
        if isinstance(s, dict) and _clip(s.get("text"), 1200):
            sections.append({"heading": _clip(s.get("heading"), 40), "text": _clip(s.get("text"), 1200),
                             "sources": _refs(s.get("sources"), refs)})
    elements = []
    for e in d.get("elements") or []:
        if isinstance(e, dict) and _clip(e.get("name"), 40):
            elements.append({"category": e.get("category") if e.get("category") in CATEGORIES else "",
                             "name": _clip(e.get("name"), 40), "desc": _clip(e.get("desc"), 300),
                             "sources": _refs(e.get("sources"), refs), "change": _clip(e.get("change"), 200)})
    used = []
    for x in sections + elements:
        used += [i for i in x["sources"] if i not in used]
    return {"title": _clip(d.get("title"), 40), "pitch": _clip(d.get("pitch"), 200), "sections": sections,
            "elements": elements, "twist": _clip(d.get("twist"), 300),
            "questions": [_clip(q, 120) for q in d.get("questions") or [] if _clip(q, 120)][:3],
            "sources": used, "uncited": not used}


def _base_parts(req: dict, block: str) -> list[str]:
    parts = []
    context = _context(req.get("novelId"))
    if context:
        parts.append(f"【关联的小说】（构思要和它的设定、已写内容相容）\n{context}")
    if _wall_text(req):
        parts.append(_wall_text(req))
    parts.append(f"【本次构思】\n{_request_text(req)}")
    parts.append(f"【可用的素材】（方括号里是编号）\n{block}" if block else "【可用的素材】（没有）")
    return parts


def generate(req: dict) -> dict:
    """→ {ideas: [思路], usage, model}；materials = Java 检索 / 用户勾选后的素材条目（含多版本）"""
    materials = [m for m in req.get("materials") or [] if isinstance(m, dict) and m.get("id") is not None]
    if not materials:
        raise InspireError("没有可用的素材：换个需求，或者在素材库里多存一些素材")
    count = max(1, min(MAX_COUNT, int(req.get("count") or 3)))
    target = req.get("target") if req.get("target") in TARGETS else "free"
    block, refs = _material_block(materials)
    parts = _base_parts(req, block)
    parts.append(
        f"【任务】用上面的素材组合出 {count} 个彼此差异明显的思路。要求：每个思路至少借用 2 条素材，"
        "再加至少一处素材里没有的反转；不同思路尽量用不同的素材；借用时改名、改细节，不照搬原作；"
        f"补充条件必须满足。{TARGET_SHAPE[target]}。sources 写借用的素材编号。\n"
        f'输出：{{"ideas":[{IDEA_FIELDS}]}}')
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]
    local = bool((req.get("local") or {}).get("baseId"))
    r, model = _run(req, messages, min(8000, (700 if local else 1100) * count + 400))
    if r["finishReason"] == "length":
        raise InspireError("模型输出被截断，请减少思路数量后重试")
    data = _parse(r["text"], req)
    raw = data.get("ideas") or data.get("items") or []
    out = [i for i in (_clean_idea(d, refs) for d in raw) if i]
    if not out:
        raise InspireError("模型没有给出可用的思路，请重试")
    return {"ideas": out[:count], "usage": _usage(r), "model": model}


# ---------------------------------------------------------------- 细化 / 追问修改

def _idea_text(idea: dict, refs_back: dict[int, str]) -> str:
    """已有思路 → 提示词文本（素材 id 换回本次的编号）"""
    def tag(ids):
        names = [refs_back[i] for i in ids or [] if i in refs_back]
        return f"（借用 {'、'.join(names)}）" if names else ""

    lines = [f"标题：{idea.get('title', '')}", f"卖点：{idea.get('pitch', '')}"]
    for s in idea.get("sections") or []:
        lines.append(f"- {s.get('heading', '')}：{s.get('text', '')}{tag(s.get('sources'))}")
    for e in idea.get("elements") or []:
        lines.append(f"- 元素「{e.get('name', '')}」：{e.get('desc', '')}；改动：{e.get('change', '')}{tag(e.get('sources'))}")
    if idea.get("twist"):
        lines.append(f"反转：{idea['twist']}")
    if idea.get("detail"):
        lines.append("细化内容：\n" + "\n".join(f"{s.get('heading', '')}：{s.get('text', '')}"
                                             for s in idea["detail"].get("sections") or []))
    return "\n".join(lines)


def refine(req: dict) -> dict:
    """思路 → 详细内容 {detail: {sections: [{heading, text, sources}]}}，800~1500 字"""
    idea = req.get("idea") or {}
    if not idea.get("title"):
        raise InspireError("缺少要细化的思路")
    materials = [m for m in req.get("materials") or [] if isinstance(m, dict) and m.get("id") is not None]
    block, refs = _material_block(materials)
    back = {v: k for k, v in refs.items()}
    parts = _base_parts(req, block)
    parts.append(f"【要细化的思路】\n{_idea_text(idea, back)}")
    ask = _clip(req.get("instruction"), 300)
    parts.append(
        "【任务】把这个思路写成详细内容，800~1500 字，分 3~8 段，每段有小标题：写清环境、人物的行动和选择、冲突怎么升级、"
        "伏笔和钩子。" + (f"作者的要求：{ask}。" if ask else "") +
        "借用素材的地方写编号。\n"
        '输出：{"sections":[{"heading":"小标题","text":"内容","sources":["S1"]}]}')
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]
    r, model = _run(req, messages, 3000, temperature=0.8)
    if r["finishReason"] == "length":
        raise InspireError("模型输出被截断，请缩小细化范围后重试")
    data = _parse(r["text"], req)
    sections = [{"heading": _clip(s.get("heading"), 40), "text": _clip(s.get("text"), 2000), "sources": _refs(s.get("sources"), refs)}
                for s in data.get("sections") or [] if isinstance(s, dict) and _clip(s.get("text"), 2000)]
    if not sections:
        raise InspireError("模型没有给出细化内容，请重试")
    return {"detail": {"sections": sections, "instruction": ask}, "usage": _usage(r), "model": model}


def revise(req: dict) -> dict:
    """按作者的指令修改思路，返回同结构的新版本"""
    idea = req.get("idea") or {}
    ask = _clip(req.get("instruction"), 500)
    if not idea.get("title") or not ask:
        raise InspireError("缺少思路或修改要求")
    materials = [m for m in req.get("materials") or [] if isinstance(m, dict) and m.get("id") is not None]
    block, refs = _material_block(materials)
    back = {v: k for k, v in refs.items()}
    parts = _base_parts(req, block)
    history = [h for h in req.get("history") or [] if isinstance(h, str) and h.strip()][-6:]
    if history:
        parts.append("【之前的修改要求】\n" + "\n".join(f"- {_clip(h, 200)}" for h in history))
    parts.append(f"【当前思路】\n{_idea_text(idea, back)}")
    target = req.get("target") if req.get("target") in TARGETS else "free"
    parts.append(
        f"【任务】按作者的要求修改这个思路：{ask}\n只改要求涉及的部分，其余保持不变；改动后仍要自洽，"
        f"借用素材写编号。{TARGET_SHAPE[target]}。\n输出：{IDEA_FIELDS}")
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]
    r, model = _run(req, messages, 2500, temperature=0.7)
    if r["finishReason"] == "length":
        raise InspireError("模型输出被截断，请重试")
    data = _parse(r["text"], req)
    out = _clean_idea(data.get("idea") if isinstance(data.get("idea"), dict) else data, refs)
    if not out:
        raise InspireError("模型没有给出修改后的思路，请重试")
    return {"idea": out, "usage": _usage(r), "model": model}
