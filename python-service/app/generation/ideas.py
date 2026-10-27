"""AI 构思：书名 / 全书大纲（分章计划）/ 下一章的标题与目标 / 构思方向建议（kind=direction），
「AI 填写设定」（kind=fill：设定编辑器里的单个字段 / 分组新增若干项 / 整个分类的未填项），
以及角色试聊（kind=chat：按角色卡扮演角色对话，类似 character.ai），结合工作区设定与素材库素材。

由 Java 的 /api/novel/gen/{id}/ideas 转发：Java 附带选中 / 自动匹配的素材（素材库在 Java 的数据库里），
以及所用模型：大模型（api，含 Key，只在本次调用中使用）或本地模型（local：基础模型 + 可选 LoRA 适配器，按需自动加载）。
结果只返回给前端，用户确认后才保存（大纲存为 novel.outline）。
"""
import json
import re

from .. import llm_client
from ..local import inference, jobs as local_jobs, registry
from . import chapter as chapter_mod, spec as spec_mod, store
from .backends import GenerationError, GenParams, LocalHFGenerator

KINDS = ("title", "outline", "chapter", "fill", "direction", "hint_polish", "chat")
CHAT_TURNS = 20             # 角色试聊带上最近多少条消息
CHAT_MESSAGE_CHARS = 1000
CHAT_SETTING_CHARS = 1500   # 试聊时附带的世界观 / 核心设定上限
FILL_MODES = ("field", "items", "category", "option")   # option：选择类字段的一个自定义选项
FILL_TYPES = ("text", "textarea", "tags", "single", "multi")   # 数字 / 滑块是参数，不让 AI 填
FILL_TYPE_HINTS = {
    "text": "字符串：简短的名称或短语（20 字内）",
    "textarea": "字符串：一段具体的描述（80~200 字）",
    "tags": "字符串数组：3~6 个简短标签",
    "single": "字符串：从可选项中选 1 个（输出选项文字；都不合适时可写一个新的简短选项）",
    "multi": "字符串数组：从可选项中选 1~3 个（输出选项文字；都不合适时可写新的简短选项）",
}
FILL_TOKEN_BUDGET = {"text": 40, "textarea": 300, "tags": 60, "single": 25, "multi": 40}   # 每个字段的输出 token 估算
MAX_MATERIALS = 20
MATERIAL_TEXT_CHARS = 260   # 单条素材写进提示词的上限，控制总长度
LOCAL_MAX_OUTLINE = 15     # 本地小模型一次规划太多章容易跑题 / 超时
HINT_CHARS = 3000          # 构思方向（可被 AI 润色扩写，较长）
CURRENT_TAIL_CHARS = 400   # 「当前章节」附带的正文结尾
MAX_CHOSEN = 10            # 选定的后续走向最多几条
CATEGORY_LABELS = {"world": "世界观", "faction": "势力", "character": "角色", "monster": "怪物", "location": "地点",
                   "item": "物品功法", "plot": "情节"}

SYSTEM = """你是资深网络小说策划编辑，擅长构思书名、搭建大纲、设计章节。只输出 JSON，不要任何多余文字。
原则：
1. 严格遵守【已确定的设定】，不得与之矛盾；设定没提到的可以发挥。
2. 【素材库素材】是作者挑选的创作素材：要有机地融入构思（可改写、组合、改名），不要照搬原作的专有名词和情节。
3. 构思要具体、有冲突和悬念，避免空泛套话。"""


FILL_SYSTEM = """你是资深网络小说策划编辑，正在帮作者补全小说设定。只输出 JSON，不要任何多余文字。
原则：
1. 与【已确定的设定】保持一致，不得矛盾；补全的内容要具体、有画面感、能直接用于写作。
2. 【素材库素材】是作者挑选的参考：可以借鉴、改写、组合，不要照搬原作的专有名词。
3. 选择类字段优先从给出的可选项里选。"""


CHAT_SYSTEM = """你正在扮演一部小说中的角色，和作者进行角色扮演对话（作者借此检验角色的性格与口吻）。
规则：
1. 始终以「{name}」的身份、语气、用词和价值观说话，不要跳出角色，不要提及自己是 AI 或模型，不要替对方说话。
2. 严格遵守下面的【角色卡】和【世界设定】；角色不知道的事情就表现得不知道，不要凭空给角色加设定之外的能力。
3. 回复用简体中文，1~4 小段，合计 200 字以内；动作、神态写在（）里，台词直接写。
4. 有来有往：可以反问、表露情绪、推进话题，让对话自然生动。"""


HINT_POLISH_SYSTEM = """你是网络小说策划编辑，帮作者把粗略的构思扩写成完整、具体的故事构思。只输出 JSON，不要任何多余文字。
规则：
1. 只依据作者给出的这段构思，不要参考或假设任何其他设定、章节。
2. 保留作者的全部想法、人物和走向，不换题材、不推翻原有情节。
3. 大幅扩写：把每个要点展开——人物处境与动机、核心冲突、关键事件的前因后果、转折与悬念、情感线；
   可以补充为原有情节服务的细节，但不要另起与原文无关的主线。"""


FILL_PLAIN_SYSTEM = """你是资深网络小说策划编辑，正在帮作者补全小说设定。
与【已确定的设定】保持一致；【素材库素材】可借鉴、改写，不要照搬原作的专有名词。
只输出要求的内容本身，不要标题、引号、JSON 或任何解释。"""


class IdeaError(ValueError):
    pass


def _material_lines(materials: list[dict]) -> list[str]:
    lines = []
    for m in materials[:MAX_MATERIALS]:
        cat = CATEGORY_LABELS.get(m.get("category"), m.get("category") or "素材")
        head = f"- [{cat}] {m.get('title', '')}" + (f"（{m['subtype']}）" if m.get("subtype") else "")
        parts = [m.get("summary") or ""]
        attrs = m.get("attributes") or {}
        if attrs:
            parts.append("；".join(f"{k}：{'、'.join(v) if isinstance(v, list) else v}" for k, v in attrs.items()))
        if m.get("tags"):
            parts.append("标签：" + "、".join(m["tags"]))
        body = "；".join(p for p in parts if p)
        lines.append(f"{head}：{body[:MATERIAL_TEXT_CHARS]}")
    return lines


def _context(novel: dict, spec: list | None = None, current: bool = True, past: bool = True) -> tuple[str, list[dict]]:
    """工作区已有内容：书名、设定（核心 + 卡片；spec 为编辑器中尚未保存的当前设定时优先用它）、大纲，
    以及已写章节：past = 前情概要 + 更早章节的摘要，current = 最近写完的一章（摘要 + 结尾）。"""
    cons = spec_mod.build(spec if spec is not None else novel["settings"].get("spec"))
    parts = [f"【当前书名】{novel['title']}"]
    settings = cons.core + [c.text for c in cons.cards]
    parts.append("【已确定的设定】\n" + ("\n\n".join(settings) if settings else "（尚未设定，可自由构思）"))
    if cons.open:
        parts.append("【尚未设定】" + "、".join(cons.open))
    outline = novel.get("outline") or {}
    if outline.get("chapters"):
        plan = "\n".join(f"第{c['index']}章《{c.get('title', '')}》：{c.get('goal', '')}" for c in outline["chapters"])
        parts.append(f"【已采用的大纲】\n一句话：{outline.get('logline', '')}\n{outline.get('synopsis', '')}\n{plan}")
    chapters = store.list_chapters(novel["id"])
    last = chapters[-1] if chapters else None
    if past:
        if novel.get("arcSummary"):
            parts.append(f"【前情概要（至第{novel['arcUpTo']}章）】{novel['arcSummary']}")
        older = [c for c in chapters if c["index"] > novel.get("arcUpTo", 0) and c.get("summary")
                 and c is not last][-10:]
        if older:
            parts.append("【过去章节】\n" + "\n".join(f"第{c['index']}章《{c.get('title') or ''}》：{c['summary']}" for c in older))
    if current and last:
        text = (store.get_chapter(novel["id"], last["index"]).get("text") or "").strip()
        lines = [f"【当前章节：第{last['index']}章《{last.get('title') or ''}》（最近写完的一章）】"]
        if last.get("summary"):
            lines.append(f"摘要：{last['summary']}")
        if text:
            lines.append(f"结尾：…{text[-CURRENT_TAIL_CHARS:]}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts), chapters


def _task(kind: str, hint: str, count: int, next_index: int, purpose: str = "", tone: str = "",
          rejected: list[str] | None = None, chosen: list[str] | None = None) -> tuple[str, int]:
    tone_line = f"作者定下的基调：{tone}（必须贴合这个基调）\n" if tone else ""
    hint_line = tone_line + (f"作者的构思方向：{hint}\n" if hint else "")
    if chosen:
        hint_line += "作者选定的后续走向（必须沿着这些走向展开）：\n" + "\n".join(f"- {c}" for c in chosen) + "\n"
    if kind == "direction":
        use = f"这些走向用于：{purpose}。\n" if purpose else ""
        if hint:
            base = (f"作者的构思方向：「{hint}」\n围绕这个构思，结合上面提供的设定和章节（如果有），"
                    "构思故事接下来可能的发展走向——每个走向是一条不同的发展路线。\n")
        elif tone:
            base = "围绕这个基调，结合上面提供的设定和章节（如果有），从不同角度给出故事可能的发展走向。\n"
        else:
            base = "作者还没有想法，请结合上面提供的内容主动给出灵感。\n"
        avoid = ("以下走向已经给过或被作者否定，不要给出相同或相似的：\n" + "\n".join(f"- {r}" for r in rejected) + "\n"
                 if rejected else "")
        return (f"{tone_line}{base}{avoid}{use}给出 {count} 个彼此差异明显的走向（可以从核心冲突、主角处境、反转、情感主线、"
                "势力博弈、名场面等角度切入），每个 40~120 字，写清楚接下来发生什么、带来什么冲突或悬念。\n"
                '输出：{"directions":[{"label":"4~8 字的短标题","direction":"走向描述"}]}'), 1500
    if kind == "title":
        return (f"{hint_line}为这部小说构思 {count} 个书名候选，风格各异，贴合设定和素材。\n"
                '输出：{"titles":[{"title":"书名","pitch":"一句话卖点（30字内）","materials":["用到的素材标题"]}]}'), 1200
    if kind == "outline":
        return (f"{hint_line}为这部小说写大纲，并规划从第{next_index}章开始的 {count} 章（已写的章节不要重写，接着往下规划）。\n"
                "每章给出标题和本章目标（这一章具体发生什么、推进什么冲突、留下什么悬念，60~120字）。\n"
                '输出：{"title":"建议书名（沿用当前书名也可）","logline":"一句话故事（40字内）",'
                '"synopsis":"故事梗概（200~400字：主线、主要人物与关系、核心冲突、走向）",'
                '"chapters":[{"index":章号,"title":"章节标题","goal":"本章目标","materials":["本章用到的素材标题"]}],'
                '"materials":["整体用到的素材标题"]}'), min(8000, 1200 + count * 220)
    return (f"{hint_line}设计第{next_index}章：给出 {count} 个不同方向的方案（若已有大纲，第一个方案应与大纲一致），"
            "要承接已写章节、推进主线。\n"
            '输出：{"options":[{"title":"章节标题","goal":"本章目标（60~150字，具体写发生什么）","materials":["用到的素材标题"]}]}'), 1500


def generate(novel_id: str, req: dict) -> dict:
    """req: {kind, hint?, tone?, rejected?[], count?, materials: [...], api?: ModelConfig dict, local?: {baseId, adapterId}}"""
    kind = req.get("kind")
    if kind not in KINDS:
        raise IdeaError(f"kind 只能是 {KINDS}")
    local = req.get("local")
    if not req.get("api") and not (local and local.get("baseId")):
        raise IdeaError("AI 构思需要通过 Java 后端发起，并选择大模型或本地模型")
    novel = store.get_novel(novel_id)
    if kind == "fill":
        return _fill(novel, req, local)
    if kind == "chat":
        return _chat(novel, req, local)
    hint = (req.get("hint") or "").strip()[:HINT_CHARS]
    if kind == "hint_polish":
        return _polish_hint(hint, req, local)
    spec = req.get("spec") if isinstance(req.get("spec"), list) else None
    # 章节上下文：未指定时都带（AI 填写设定等旧调用）；章节题目必须承接已写章节，总是带
    ctx = req.get("chapterContext") if isinstance(req.get("chapterContext"), dict) else {}
    current = kind == "chapter" or ctx.get("current", True) is not False
    past = kind == "chapter" or ctx.get("past", True) is not False
    context, chapters = _context(novel, spec, current, past)
    next_index = (chapters[-1]["index"] + 1) if chapters else 1
    default_count = {"title": 5, "outline": 10, "chapter": 3, "direction": 5}[kind]
    max_count = (LOCAL_MAX_OUTLINE if local else 40) if kind == "outline" else 8
    count = max(1, min(int(req.get("count") or default_count), max_count))
    materials = req.get("materials") or []
    mat = _material_lines(materials)
    rejected = [str(r).strip()[:200] for r in req.get("rejected") or [] if str(r).strip()][:30]
    chosen = ([str(c).strip()[:300] for c in req.get("chosenDirections") or [] if str(c).strip()][:MAX_CHOSEN]
              if kind != "direction" else [])
    task, max_tokens = _task(kind, hint, count, next_index, (req.get("purpose") or "").strip()[:60],
                             (req.get("tone") or "").strip()[:200], rejected, chosen)
    user = context + ("\n\n【素材库素材】\n" + "\n".join(mat) if mat else "\n\n【素材库素材】（未选择）") + "\n\n【任务】\n" + task
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    r, model_name = _run_local(local, messages, max_tokens) if local else _run_api(req["api"], messages, max_tokens)
    if r["finishReason"] == "length":
        raise IdeaError("模型输出被截断，请减少章节数后重试")
    data = _parse(r["text"], local)
    return {"kind": kind, "nextIndex": next_index, "result": _normalize(kind, data, next_index),
            "usage": {"promptTokens": r["promptTokens"], "completionTokens": r["completionTokens"]},
            "model": model_name}


def _polish_hint(hint: str, req: dict, local: dict | None) -> dict:
    """AI 润色构思方向：只看这段文字本身（不带设定 / 章节 / 素材 / 基调），保留原意大幅扩写。"""
    if not hint:
        raise IdeaError("请先在构思方向里写下大致情节再润色")
    messages = [{"role": "system", "content": HINT_POLISH_SYSTEM},
                {"role": "user", "content": f"作者的构思：\n{hint}\n\n把它扩写成 300~1200 字的完整构思"
                                            '（原文越长扩写越多，最多 1500 字）。\n输出：{"text":"扩写后的构思",'
                                            '"changes":"主要扩写了哪些方面（40 字内）"}'}]
    r, model_name = _run_local(local, messages, 2500) if local else _run_api(req["api"], messages, 2500)
    if r["finishReason"] == "length":
        raise IdeaError("模型输出被截断，请缩短构思后重试")
    return {"kind": "hint_polish", "result": _normalize("hint_polish", _parse(r["text"], local), 0),
            "usage": {"promptTokens": r["promptTokens"], "completionTokens": r["completionTokens"]},
            "model": model_name}


_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _parse(text: str, local: dict | None) -> dict:
    """容错解析模型输出的 JSON：去掉 ```json 包裹和多余的尾逗号；顶层是数组时视为 {"items": [...]}。"""
    body = re.sub(r"^```\w*\s*|\s*```$", "", text.strip())
    body = _TRAILING_COMMA.sub(r"\1", body)
    starts = [i for i in (body.find("{"), body.find("[")) if i >= 0]
    if starts:
        try:
            data = json.loads(body[min(starts):])
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            return {"items": data}
        if isinstance(data, dict):
            return data
    try:
        return llm_client.parse_json(body)
    except llm_client.LLMError as e:
        hint = "；本地小模型不擅长按格式输出，可重试或换用大模型" if local else ""
        raise IdeaError(f"{e}{hint}") from e


def _run_api(api: dict, messages: list[dict], max_tokens: int, temperature: float = 0.9,
             json_mode: bool = True) -> tuple[dict, str]:
    cfg = llm_client.ModelConfig(**api)
    try:
        return llm_client.complete(cfg, messages, max_tokens=max_tokens, temperature=temperature, top_p=0.95,
                                   json_mode=json_mode, timeout=170), cfg.model
    except llm_client.LLMError as e:
        raise IdeaError(f"大模型调用失败：{e}") from e


def _run_local(local: dict, messages: list[dict], max_tokens: int, temperature: float = 0.8,
               use_adapter: bool = True) -> tuple[dict, str]:
    """本地模型（+ 适配器）：未加载 / 加载的不一致时先加载（同一基础模型只切换适配器）。
    use_adapter=False：本次调用停用适配器（文风适配器会削弱按格式输出的能力，JSON 类请求用基础模型）。"""
    if chapter_mod.active_job():
        raise IdeaError("有章节正在生成或润色，完成后再用本地模型构思")
    if local_jobs.gpu_busy():
        raise IdeaError("有训练任务正在使用 GPU，请等待训练完成或换用大模型")
    if inference.extract_busy():
        raise IdeaError("小说提取正在使用本地模型，请等待提取完成或换用大模型")
    base_id, adapter_id = local["baseId"], local.get("adapterId") or None
    try:
        if adapter_id:
            inference.check_adapter(adapter_id, base_id)
        loaded = inference.loaded_model()
        if not loaded or loaded["baseId"] != base_id or loaded["adapterId"] != adapter_id:
            inference.load(base_id, adapter_id, "auto")
            inference.wait_loaded(timeout=300)
        gen = LocalHFGenerator(base_id, adapter_id)
        g = gen.generate(messages, GenParams(max_new_tokens=min(max_tokens, 3000), temperature=temperature, top_p=0.9,
                                             top_k=40, repetition_penalty=1.05, use_adapter=use_adapter))
    except (RuntimeError, registry.RegistryError, GenerationError) as e:
        raise IdeaError(f"本地模型构思失败：{e}") from e
    return ({"text": g.text, "promptTokens": g.prompt_tokens, "completionTokens": g.completion_tokens,
             "finishReason": g.finish_reason}, gen.name)


# ---------------------------------------------------------------- 角色试聊（character.ai 式）

def _chat(novel: dict, req: dict, local: dict | None) -> dict:
    """req.chat: {character: {name, card: {字段名: 值}}, messages: [{role: user|assistant, content}], scene?, userRole?}
    → result.reply：角色的下一句回复（纯文本）。"""
    chat = req.get("chat") or {}
    character = chat.get("character") or {}
    name = str(character.get("name") or "").strip()[:40]
    if not name:
        raise IdeaError("角色还没有名字，先填写姓名再试聊")
    card_lines = []
    for k, v in (character.get("card") or {}).items():
        if v in (None, "", []):
            continue
        text = "、".join(map(str, v)) if isinstance(v, list) else str(v)
        card_lines.append(f"- {k}：{text[:600]}")
    spec = req.get("spec") if isinstance(req.get("spec"), list) else None
    cons = spec_mod.build(spec if spec is not None else novel["settings"].get("spec"))
    world = "\n".join(cons.core)[:CHAT_SETTING_CHARS]
    system = CHAT_SYSTEM.format(name=name) + "\n\n【角色卡】\n" + ("\n".join(card_lines) or f"- 姓名：{name}")
    if world:
        system += f"\n\n【世界设定】（小说《{novel['title']}》）\n{world}"
    if chat.get("scene"):
        system += f"\n\n【当前场景】{str(chat['scene'])[:300]}"
    if chat.get("userRole"):
        system += f"\n\n【对方身份】作者扮演：{str(chat['userRole'])[:100]}"
    history = []
    for m in (chat.get("messages") or [])[-CHAT_TURNS:]:
        role = m.get("role") if isinstance(m, dict) else None
        content = str(m.get("content") or "").strip()[:CHAT_MESSAGE_CHARS] if role else ""
        if role in ("user", "assistant") and content:
            history.append({"role": role, "content": content})
    if not history or history[-1]["role"] != "user":
        raise IdeaError("请先输入要对角色说的话")
    messages = [{"role": "system", "content": system}, *history]
    if local:
        r, model_name = _run_local(local, messages, 500, temperature=0.85)
    else:
        cfg = llm_client.ModelConfig(**req["api"])
        try:
            r = llm_client.complete(cfg, messages, max_tokens=600, temperature=0.85, top_p=0.95, timeout=120)
        except llm_client.LLMError as e:
            raise IdeaError(f"大模型调用失败：{e}") from e
        model_name = cfg.model
    reply = re.sub(rf"^\s*{re.escape(name)}\s*[：:]\s*", "", r["text"].strip())  # 小模型常带「名字：」前缀
    if r["finishReason"] == "length":
        cut = max(reply.rfind(ch) for ch in _SENTENCE_END)
        reply = reply[:cut + 1] if cut > 0 else reply
    if not reply:
        raise IdeaError("模型没有给出回复，请重试")
    return {"kind": "chat", "result": {"reply": reply}, "model": model_name,
            "usage": {"promptTokens": r["promptTokens"], "completionTokens": r["completionTokens"]}}


# ---------------------------------------------------------------- AI 填写设定

def _field_line(f: dict) -> str:
    line = f"- {f['key']}「{f.get('label', '')}」：{FILL_TYPE_HINTS[f['type']]}"
    if f.get("options"):
        line += "；可选项：" + "、".join(str(o) for o in f["options"][:40])
    if f.get("desc") or f.get("placeholder"):
        line += f"（{f.get('desc') or f.get('placeholder')}）"
    return line


def _fill(novel: dict, req: dict, local: dict | None) -> dict:
    """req.fill: {mode: field|items|category, path: [位置], fields: [{key, label, type, options?, desc?, placeholder?}],
    current?: {标签: 已有内容}, itemLabel?, count?, existing?: [已有项名称],
    action?: polish|generate, seed?: 框内文字（只用于单个文本字段）}；req.spec：编辑器当前设定（可选）。"""
    fill = req.get("fill") or {}
    mode = fill.get("mode")
    if mode not in FILL_MODES:
        raise IdeaError(f"fill.mode 只能是 {FILL_MODES}")
    fields = [f for f in fill.get("fields") or [] if isinstance(f, dict) and f.get("key") and f.get("type") in FILL_TYPES]
    if not fields:
        raise IdeaError("没有可以由 AI 填写的字段（数字 / 滑块等参数请手动设置）")
    spec = req.get("spec") if isinstance(req.get("spec"), list) else None
    context, _ = _context(novel, spec)
    mat = _material_lines(req.get("materials") or [])
    hint = (req.get("hint") or "").strip()[:500]
    path = " › ".join(str(p) for p in fill.get("path") or [])
    current = {k: v for k, v in (fill.get("current") or {}).items() if v not in (None, "", [])}
    lines = [f"位置：{path}" if path else ""]
    if current:
        lines.append("同一位置已填写的内容（要与之配合，不要重复）：\n" +
                     "\n".join(f"- {k}：{'、'.join(v) if isinstance(v, list) else v}" for k, v in current.items()))
    if hint:
        lines.append(f"作者的要求：{hint}")
    if mode == "option":
        return _custom_option(fields[0], fill, context, mat, lines, req, local)
    # 单个文本字段：polish = 在框内已写内容上扩写；generate = 框内文字只是大致方向（可为空）
    single_text = mode == "field" and len(fields) == 1 and fields[0]["type"] in ("text", "textarea")
    seed = str(fill.get("seed") or "").strip()[:2000] if single_text else ""
    polish = single_text and fill.get("action") == "polish"
    if polish and not seed:
        raise IdeaError("框里还没有内容，无法润色；可以用「AI 生成」")
    long_text = single_text and fields[0]["type"] == "textarea"
    if polish:
        lines.append(f"作者已写的内容：「{seed}」\n在保留全部已写内容和原意的基础上润色扩写：补充具体细节、理顺语句，不改变设定、"
                     + ("篇幅约为原文的 2~3 倍（不超过 400 字）。" if long_text else "仍是简短的名称或短语（20 字内）。"))
    elif seed:
        lines.append(f"作者给的大致方向：「{seed}」——按这个方向来写，可以大幅展开。")
    field_lines = "\n".join(_field_line(f) for f in fields)
    if polish and long_text:  # 润色扩写的篇幅以上面的要求为准，不受字段说明的 80~200 字限制
        field_lines = field_lines.replace("（80~200 字）", "（约为原文的 2~3 倍，不超过 400 字）")
    plain_text = False
    if mode == "items":
        count = max(1, min(int(fill.get("count") or 3), 5 if local else 10))
        label = fill.get("itemLabel") or "项"
        existing = [str(x) for x in fill.get("existing") or [] if x][:50]
        if existing:
            lines.append(f"已有的{label}（不要重复）：" + "、".join(existing))
        lines.append(f"新设计 {count} 个{label}，彼此不同、贴合设定与素材。每个{label}包含以下字段：\n{field_lines}\n"
                     '输出：{"items":[{"字段key":值}]}')
        # 角色卡这类字段多的分组：按字段类型估算每项输出长度，避免截断
        per_item = sum(FILL_TOKEN_BUDGET[f["type"]] for f in fields) + 60
        max_tokens = min(8000, max(350, per_item) * count + 300)
    elif plain_text := ((local or req.get("gguf")) and mode == "field" and len(fields) == 1
                        and fields[0]["type"] in ("text", "textarea")):
        # 本地小模型（含 GGUF）按 JSON 输出很不稳定（实测会原样返回字段名）：单个文本字段直接要正文
        f = fields[0]
        size = ("一个简短的名称或短语（20 字内）" if f["type"] == "text"
                else "润色扩写后的完整内容" if polish else "一段 80~200 字的具体描述")
        lines.append(f"写出「{f.get('label', f['key'])}」：{size}。直接输出内容本身，不要 JSON、标题、引号或任何解释。")
        # 约 200 字（润色最多 400 字）；小模型容易越写越长、开始重复
        max_tokens = 80 if f["type"] == "text" else 520 if polish else 280
    else:
        lines.append(f"为以下字段生成内容：\n{field_lines}\n" + '输出：{"values":{"字段key":值}}')
        # 本地模型约 10~16 token/秒，且小模型写完 JSON 常不停：按字段类型估算上限，避免一直写到超时
        max_tokens = (max(300, sum(FILL_TOKEN_BUDGET[f["type"]] for f in fields) + 200) if local
                      else 300 * len(fields) + 300)
    user = (context + ("\n\n【素材库素材】\n" + "\n".join(mat) if mat else "") + "\n\n【任务：补全设定】\n" +
            "\n".join(x for x in lines if x))
    messages = [{"role": "system", "content": FILL_PLAIN_SYSTEM if plain_text else FILL_SYSTEM},
                {"role": "user", "content": user}]
    # 本地：JSON 输出用基础模型（文风适配器常写完 JSON 不停、格式出错）；单个文本字段直接要正文，保留适配器的文风
    r, model_name = (_run_local(local, messages, max_tokens, temperature=0.5, use_adapter=bool(plain_text)) if local
                     else _run_api(req["api"], messages, max_tokens, temperature=0.5, json_mode=False) if plain_text
                     else _run_api(req["api"], messages, max_tokens))
    if plain_text:
        value = _plain_value(r["text"], fields[0]["type"], truncated=r["finishReason"] == "length")
        if not value:
            raise IdeaError("模型没有给出可用的内容，请重试")
        return {"kind": "fill", "mode": mode, "result": {"values": {fields[0]["key"]: value}}, "model": model_name,
                "usage": {"promptTokens": r["promptTokens"], "completionTokens": r["completionTokens"]}}
    if r["finishReason"] == "length":
        raise IdeaError("模型输出被截断，请减少数量后重试")
    try:
        data = _parse(r["text"], local)
    except IdeaError:
        data = _salvage(r["text"], fields, mode)  # 小模型的 JSON 常有小毛病：按字段名把值抠出来
        if data is None:
            raise
    if mode == "items":
        result = {"items": [_coerce(fields, it) for it in data.get("items") or [] if isinstance(it, dict)]}
        result["items"] = [it for it in result["items"] if it]
    else:
        values = data.get("values") if isinstance(data.get("values"), dict) else data
        result = {"values": _coerce(fields, values)}
    if not (result.get("items") or result.get("values")):
        raise IdeaError("模型没有给出可用的内容，请重试")
    return {"kind": "fill", "mode": mode, "result": result, "model": model_name,
            "usage": {"promptTokens": r["promptTokens"], "completionTokens": r["completionTokens"]}}


def _custom_option(field: dict, fill: dict, context: str, mat: list[str], lines: list[str], req: dict,
                   local: dict | None) -> dict:
    """选择类字段「自定义」：polish = 把作者写的整理成一个选项；generate = 按作者的方向 / 素材设计一个新选项。
    素材只来自这个自定义框里选的（Java 按本次 materialIds 取）。→ {option: {label, desc}}"""
    if field["type"] not in ("single", "multi"):
        raise IdeaError("自定义选项只用于单选 / 多选字段")
    seed = str(fill.get("seed") or "").strip()[:500]
    if not seed and not mat:
        raise IdeaError("先在自定义框里写点内容，或选择素材")
    label = field.get("label") or field["key"]
    existing = "、".join(str(o) for o in (field.get("options") or [])[:40])
    if existing:
        lines.append(f"「{label}」已有的选项：{existing}")
    if fill.get("action") == "polish":
        lines.append((f"作者为「{label}」写的自定义选项：「{seed}」——把它润色成一个可直接使用的选项：保留原意，"
                      if seed else f"根据【素材库素材】为「{label}」整理出一个选项：")
                     + "选项名简洁（12 字内），再写一句说明它具体是什么（60 字内）"
                     + ("，说明可参考素材补充细节。" if mat and seed else "。"))
    else:
        lines.append(f"为「{label}」设计一个新的自定义选项，不要与已有选项重复"
                     + (f"；按作者给的方向：「{seed}」" if seed else "")
                     + ("；从【素材库素材】中提炼" if mat else "")
                     + "。选项名简洁（12 字内），说明写清楚它具体是什么（60 字内）。")
    lines.append('这里是新建选项，不要照搬已有选项。输出：{"label":"选项名","desc":"一句话说明"}')
    user = (context + ("\n\n【素材库素材】\n" + "\n".join(mat) if mat else "") + "\n\n【任务：自定义选项】\n" +
            "\n".join(x for x in lines if x))
    messages = [{"role": "system", "content": FILL_SYSTEM}, {"role": "user", "content": user}]
    r, model_name = (_run_local(local, messages, 250, temperature=0.6, use_adapter=False) if local
                     else _run_api(req["api"], messages, 400))
    data = _parse(r["text"], local)
    name = str(data.get("label") or data.get("name") or data.get("option") or "").strip().strip("「」\"")[:30]
    if not name:
        raise IdeaError("模型没有给出选项，请重试")
    return {"kind": "fill", "mode": "option", "result": {"option": {"label": name, "desc": str(data.get("desc") or "").strip()[:120]}},
            "model": model_name, "usage": {"promptTokens": r["promptTokens"], "completionTokens": r["completionTokens"]}}


_SENTENCE_END ="。！？!?…」”"


def _plain_value(text: str, ftype: str, truncated: bool) -> str:
    """整理本地模型直接写出的字段内容：去掉代码块 / 引号 / 「情节描述：」之类的前缀；
    名称只取第一行；被截断时回退到最后一个句末标点。"""
    t = re.sub(r"^```\w*|```$", "", text.strip()).strip()
    t = re.sub(r"^[^\n：:]{1,12}[：:]\s*", "", t, count=1) if len(t) > 15 else t
    t = re.sub(r"^【[^】\n]{1,12}】\s*", "", t)  # 开头的「【情节描述】」之类的标题
    echo = t.find("【", 1)  # 小模型常在后面复述「【情节描述】…」：从那里截断
    t = (t[:echo] if echo > 0 else t).strip().strip('"“”「」')
    if ftype == "text":
        return t.splitlines()[0].strip().strip('"“”「」《》')[:40] if t else ""
    if truncated:
        cut = max(t.rfind(ch) for ch in _SENTENCE_END)
        t = t[:cut + 1] if cut > 0 else t
    return t.strip()


def _salvage(text: str, fields: list[dict], mode: str) -> dict | None:
    """JSON 解析失败时的兜底：在每个 {...} 片段里按字段 key 找 "key": "值" / "key": ["a","b"]。
    只填一个文本字段且模型直接写了正文时，把正文当作该字段的值。"""
    blocks = re.findall(r"\{[^{}]*\}", text) or [text]
    found = []
    for b in blocks:
        item = {}
        for f in fields:
            k = re.escape(f["key"])
            m = re.search(rf'"{k}"\s*:\s*"((?:[^"\\]|\\.)*)"', b, re.S)
            if m:
                item[f["key"]] = m.group(1).replace("\\n", "\n").replace('\\"', '"').strip()
                continue
            m = re.search(rf'"{k}"\s*:\s*\[([^\]]*)\]', b, re.S)
            if m:
                item[f["key"]] = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
        if item:
            found.append(item)
    if not found and mode == "field" and len(fields) == 1 and fields[0]["type"] in ("text", "textarea"):
        plain = re.sub(r"^```\w*|```$", "", text.strip()).strip().strip('"')
        if plain and "{" not in plain:
            found = [{fields[0]["key"]: plain}]
    if not found:
        return None
    return {"items": found} if mode == "items" else {"values": found[0]}


def _coerce(fields: list[dict], values: dict) -> dict:
    """按字段类型整理模型输出，只保留请求的字段；空值丢弃。"""
    out = {}
    for f in fields:
        v = values.get(f["key"])
        if v is None:
            v = values.get(f.get("label"))  # 模型偶尔用中文名当键
        if v is None:
            continue
        if f["type"] in ("tags", "multi"):
            v = [str(x).strip() for x in (v if isinstance(v, list) else str(v).replace("，", "、").split("、")) if str(x).strip()]
            v = v[:3] if f["type"] == "multi" else v[:12]
        elif f["type"] == "single":
            v = str(v[0] if isinstance(v, list) and v else v).strip()
        else:
            v = "、".join(map(str, v)) if isinstance(v, list) else str(v).strip()
        if v:
            out[f["key"]] = v
    return out


def _strs(v) -> list[str]:
    return [str(x) for x in v] if isinstance(v, list) else []


def _normalize(kind: str, data: dict, next_index: int) -> dict:
    """整理成固定结构，丢掉模型多给 / 少给的字段。"""
    if kind == "direction":
        items = data.get("directions") or data.get("items") or []
        out = []
        for d in items:
            if isinstance(d, str) and d.strip():
                out.append({"label": "", "direction": d.strip()})
            elif isinstance(d, dict) and str(d.get("direction") or "").strip():
                out.append({"label": str(d.get("label") or "").strip()[:20], "direction": str(d["direction"]).strip()})
        return {"directions": out}
    if kind == "hint_polish":
        text = str(data.get("text") or data.get("direction") or "").strip()[:3000]
        if not text:
            raise IdeaError("模型没有给出润色结果，请重试")
        return {"text": text, "changes": str(data.get("changes") or "").strip()[:80]}
    if kind == "title":
        return {"titles": [{"title": str(t.get("title", "")).strip(), "pitch": str(t.get("pitch", "")),
                            "materials": _strs(t.get("materials"))}
                           for t in data.get("titles", []) if isinstance(t, dict) and t.get("title")]}
    if kind == "chapter":
        return {"options": [{"title": str(o.get("title", "")).strip(), "goal": str(o.get("goal", "")).strip(),
                             "materials": _strs(o.get("materials"))}
                            for o in data.get("options", []) if isinstance(o, dict) and o.get("goal")]}
    chapters = []
    for i, c in enumerate(x for x in data.get("chapters", []) if isinstance(x, dict) and x.get("goal")):
        chapters.append({"index": next_index + i, "title": str(c.get("title", "")).strip(),
                         "goal": str(c.get("goal", "")).strip(), "materials": _strs(c.get("materials"))})
    return {"title": str(data.get("title", "")).strip(), "logline": str(data.get("logline", "")).strip(),
            "synopsis": str(data.get("synopsis", "")).strip(), "chapters": chapters,
            "materials": _strs(data.get("materials"))}


def validate_outline(outline: dict | None) -> dict | None:
    """保存用户确认 / 编辑后的大纲：{logline, synopsis, chapters:[{index, title, goal, materials?}], materials?}"""
    if outline is None:
        return None
    chapters = [{"index": int(c["index"]), "title": str(c.get("title", ""))[:60], "goal": str(c.get("goal", ""))[:2000],
                 "materials": _strs(c.get("materials"))[:20]}
                for c in outline.get("chapters", []) if isinstance(c, dict) and c.get("index") and c.get("goal")]
    return {"logline": str(outline.get("logline", ""))[:200], "synopsis": str(outline.get("synopsis", ""))[:3000],
            "chapters": sorted(chapters, key=lambda c: c["index"])[:200],
            "materials": _strs(outline.get("materials"))[:50], "savedAt": store.now()}

