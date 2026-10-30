"""走向引擎：基于世界书的局面，给作者「精彩又合理」的故事走向（设计见 docs/走向引擎.md）。

① 局面：worldbook.snapshot（人物想要什么 / 什么挡着 / 关系 / 知道什么、未回收伏笔、定时事件、阶段、大纲接下来、前情）。
   账本里还没有人物目标时（老工作区），先 refresh_situation 一次：按已写章节整理主要人物的局面，存进账本，以后不用再整理。
② 发散：按五种驱动各出 2 个候选（欲望碰撞 / 伏笔回收 / 信息差引爆 / 素材注入 / 反转），一次调用。
③ 审稿：一次调用对照局面逐条打 合理 / 精彩，列出硬伤，硬伤可修的给修正版（保留点子、去掉矛盾）；
   代码再查：引用了不存在或已回收的伏笔编号、尚未登场的设定正面出场。
④ 排序：去掉不合理的，按 合理 + 精彩 排，每种驱动最多 2 条，取 count 条。
本地小模型：③ 跳过（JSON 太长容易坏），按 ② 的顺序返回。
"""
import re

from . import facts as facts_mod, ideas, store, worldbook

DRIVERS = {
    "desire": ("欲望碰撞", "两个人物想要的东西互相冲突（A 想要的正好损害 B），逼出正面冲突或艰难选择"),
    "payoff": ("伏笔回收", "接上一条未回收的伏笔：推进、反转或兑现它（写明伏笔编号），或者顺势埋一个更大的"),
    "secret": ("信息差引爆", "某人知道而别人不知道的事被揭开 / 被利用 / 被误会，改变人物关系"),
    "material": ("素材注入", "用一条给出的素材（新人物、势力、怪物、地点、物品）打破现状"),
    "twist": ("反转", "违背读者预期、但不违背已写内容和设定的转折，事后回看有迹可循"),
}
PER_DRIVER = 2
MAX_PER_DRIVER_OUT = 2
MIN_REASONABLE = 3
SYSTEM = "你是资深网络小说主编，擅长在不违背已写内容的前提下设计让读者欲罢不能的后续走向。只输出 JSON，不要任何多余文字。"
CHECK_SYSTEM = "你是严格的网络小说审稿编辑，专门挑出后续走向和已写内容、人物、设定的矛盾。评分要拉开差距。只输出 JSON。"


class DirectionError(RuntimeError):
    pass


def _run(req: dict, messages: list[dict], max_tokens: int, temperature: float) -> tuple[dict, str]:
    local = req.get("local")
    try:
        if local and local.get("baseId"):
            return ideas._run_local(local, messages, max_tokens, temperature=temperature, use_adapter=False)
        if req.get("api"):
            return ideas._run_api(req["api"], messages, max_tokens, temperature=temperature)
    except ideas.IdeaError as e:
        raise DirectionError(str(e)) from e
    raise DirectionError("请选择大模型、GGUF 或本地模型")


def _json(req: dict, system: str, user: str, max_tokens: int, temperature: float, usage: dict) -> dict:
    r, name = _run(req, [{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens, temperature)
    usage["promptTokens"] += r["promptTokens"]
    usage["completionTokens"] += r["completionTokens"]
    usage["calls"] += 1
    usage["model"] = name
    if r["finishReason"] == "length":
        raise DirectionError("模型输出被截断，请重试")
    try:
        return ideas._parse(r["text"], req.get("local"))
    except ideas.IdeaError as e:
        raise DirectionError(str(e)) from e


# ---------------------------------------------------------------------------------------------- ① 局面

SITUATION_USER = """{snapshot}

【任务】根据上面的已写内容，整理此刻主要人物（最多 8 个，主角必须有）的局面。只写已写内容里看得出来的，不要编：
- goal：他现在最想要什么（≤30 字）；obstacle：什么挡着他（≤30 字）
- relations：和其他主要人物现在的关系（每条 ≤15 字，如「表面效忠、暗中提防」）
- knows：他知道而别人不知道、会影响剧情的信息或秘密（每条 ≤30 字，没有就空）
另外列出 clocks：已写内容里定了期限、还没到的事（如「三个月后的地下拍卖会」），没有就空。
输出 {{"characters": [{{"name": "…", "goal": "…", "obstacle": "…", "relations": [{{"to": "…", "rel": "…"}}], "knows": ["…"]}}],
"clocks": [{{"text": "…", "due": "…"}}]}}"""


def needs_situation(wb: dict) -> bool:
    chars = [e for e in wb["entries"] if e["kind"] == "character"]
    return wb["chapter"] > 3 and bool(chars) and not any((e.get("state") or {}).get("goal") for e in chars)


def refresh_situation(novel_id: str, req: dict, usage: dict | None = None) -> dict:
    """按已写章节整理主要人物的局面，记进账本（算作最后一章的 AI 记录：删掉那章或重新提取那章时一起去掉）。"""
    usage = usage if usage is not None else {"promptTokens": 0, "completionTokens": 0, "calls": 0}
    wb = worldbook.compile(novel_id)
    last = wb["chapter"] - 1
    if last < 1:
        raise DirectionError("还没有写完的章节，没有局面可整理")
    data = _json(req, SYSTEM, SITUATION_USER.format(snapshot=worldbook.snapshot(wb)), 2000, 0.3, usage)
    facts = store.get_facts(novel_id)
    applied = facts_mod.add_situation(facts, last, data)
    store.save_facts(novel_id, facts)
    return {"applied": applied, "chapter": last, "usage": usage}


# ---------------------------------------------------------------------------------------------- ② 发散

def _diverge_user(snapshot: str, req: dict, mat: list[str]) -> str:
    hint = (req.get("hint") or "").strip()[:ideas.HINT_CHARS]
    tone = (req.get("tone") or "").strip()[:200]
    rejected = [str(r).strip()[:200] for r in req.get("rejected") or [] if str(r).strip()][:30]
    # 没选素材时不要「素材注入」：评测里凭空引入的新因素合理性最低（93% 有矛盾，见 docs/走向引擎.md）
    drivers = "\n".join(f"- {k}（{v[0]}）：{v[1]}" for k, v in DRIVERS.items() if k != "material" or mat)
    parts = [snapshot]
    parts.append("【素材库素材】\n" + "\n".join(mat) if mat else "【素材库素材】（未选择）")
    if tone:
        parts.append(f"【基调】{tone}（走向要贴合这个基调）")
    if hint:
        parts.append(f"【作者的构思方向】{hint}\n所有走向都在这个构思之内展开，不要偏离成别的故事。")
    if rejected:
        parts.append("【已经给过或被作者否定的走向，不要再给相同或相似的】\n" + "\n".join(f"- {r}" for r in rejected))
    parts.append(
        f"【任务】为第 {{n}} 章起的后续，按下面每种驱动各给 {PER_DRIVER} 个走向：\n{drivers}\n"
        "要求：\n"
        "- 必须从【人物局面】出发：写清楚谁为了什么做了什么、撞上了谁的什么，不要空泛的「危机降临」「实力大涨」\n"
        "- 不要保守：每个走向都要有让读者想追下一章的强冲突或强悬念（有人付出代价、关系破裂、计划败露、局势失控），"
        "合理不等于平淡，只是不能和已写内容矛盾\n"
        "- 不能和【前情】【核心设定】矛盾；死去 / 离开的人物不能无故回来；尚未登场的设定只能作传闻 / 伏笔\n"
        "- 遵守【故事阶段】的量级：主角现在打不过的东西不能被他解决\n"
        "- 每个走向 60~150 字，写清楚接下来发生什么、冲突在哪、留下什么钩子；彼此差异要明显\n"
        "- uses 写用到的伏笔编号（如 F12）和人物名\n"
        '输出 {"directions": [{"driver": "desire", "label": "4~8 字短标题", "direction": "…", "uses": ["F12", "人物名"]}]}')
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------------------------- ③ 审稿

def _check_user(snapshot: str, cands: list[dict]) -> str:
    lst = "\n".join(f"[{i}] {c['direction']}" for i, c in enumerate(cands))
    return (f"{snapshot}\n\n【待审的后续走向】\n{lst}\n\n"
            "逐条审：\n"
            "- reasonable 合理 1–5：和前情、人物性格动机、设定、阶段量级是否一致（5 = 完全自洽，1 = 明显矛盾）\n"
            "- problems：具体的硬伤（和哪段已写内容 / 哪个设定冲突），没有就空\n"
            "- revised：有硬伤但点子值得保留时，给一个改掉硬伤的版本（60~150 字）：冲突和悬念保留甚至加强，"
            "不要改成平淡、稳妥的版本；没有硬伤或救不了就空字符串\n"
            "- exciting 精彩 1–5：冲突强度、意外但合理、利用已有伏笔 / 人物关系、主角主动、给后面留钩子\n"
            '输出 {"items": [{"i": 0, "reasonable": 4, "problems": [], "revised": "", "exciting": 4}]}')


def _code_checks(c: dict, wb: dict) -> list[str]:
    """代码能确定的硬伤：伏笔编号不存在 / 已回收，尚未登场的设定被正面写出"""
    probs = []
    threads = {t["id"].upper(): t for t in wb["threads"]}
    for fid in re.findall(r"F\d+", " ".join([c["direction"], *c.get("uses", [])]), flags=re.I):
        t = threads.get(fid.upper())
        if t is None:
            probs.append(f"伏笔 {fid} 不存在")
        elif t["status"] != "open":
            probs.append(f"伏笔 {fid} 已经回收过了")
    for e in wb["entries"]:
        if e["notYet"] and len(e["name"]) >= 2 and e["name"] in c["direction"]:
            probs.append(f"「{e['name']}」第 {e.get('since') or '?'} 章才登场，现在只能作传闻 / 伏笔")
    return probs


# ---------------------------------------------------------------------------------------------- 入口

def generate(novel_id: str, req: dict) -> dict:
    """req: {api? | local?, hint?, tone?, rejected?[], count?, materials?[], situation?: true（先整理局面）}
    → {kind: direction, nextIndex, result: {directions[{label, direction, driver, driverLabel, uses, scores, problems, revised}]},
       usage, model, situation?}"""
    usage = {"promptTokens": 0, "completionTokens": 0, "calls": 0, "model": ""}
    wb = worldbook.compile(novel_id)
    situation = None
    if req.get("situation") is not False and needs_situation(wb):
        try:
            situation = refresh_situation(novel_id, req, usage)
            wb = worldbook.compile(novel_id)
        except DirectionError as e:   # 整理失败不挡出走向
            situation = {"error": str(e)}
    snap = worldbook.snapshot(wb, max_chars=7000 if not req.get("local") else 3500)
    count = max(1, min(int(req.get("count") or 5), 8))
    mat = ideas._material_lines(req.get("materials") or [])
    data = _json(req, SYSTEM, _diverge_user(snap, req, mat).replace("{n}", str(wb["chapter"])), 3500, 0.95, usage)
    cands = []
    for d in data.get("directions") or data.get("items") or []:
        if isinstance(d, dict) and str(d.get("direction") or "").strip():
            drv = d.get("driver") if d.get("driver") in DRIVERS else "twist"
            cands.append({"label": str(d.get("label") or "").strip()[:20], "direction": str(d["direction"]).strip()[:400],
                          "driver": drv, "driverLabel": DRIVERS[drv][0],
                          "uses": [str(u).strip()[:40] for u in d.get("uses") or [] if str(u).strip()][:8]})
    if not cands:
        raise DirectionError("模型没有给出走向，请重试")

    checked = False
    if not req.get("local"):
        try:
            items = _json(req, CHECK_SYSTEM, _check_user(snap, cands), 3000, 0.2, usage).get("items") or []
            for it in items:
                i = it.get("i")
                if not isinstance(i, int) or not 0 <= i < len(cands):
                    continue
                c = cands[i]
                c["scores"] = {"reasonable": _score(it.get("reasonable")), "exciting": _score(it.get("exciting"))}
                c["problems"] = [str(p).strip()[:200] for p in it.get("problems") or [] if str(p).strip()][:5]
                rev = str(it.get("revised") or "").strip()
                if rev and c["problems"]:
                    c["original"], c["direction"], c["revised"] = c["direction"], rev[:400], True
            checked = True
        except DirectionError:
            checked = False
    for c in cands:
        code = _code_checks(c, wb)
        if code:
            c["problems"] = c.get("problems", []) + code
            if c.get("scores"):
                c["scores"]["reasonable"] = min(c["scores"]["reasonable"], 2)
    return {"kind": "direction", "nextIndex": wb["chapter"], "result": {"directions": _rank(cands, count, checked)},
            "usage": {k: usage[k] for k in ("promptTokens", "completionTokens", "calls")}, "model": usage["model"],
            "situation": situation, "checked": checked}


def _score(v) -> int:
    try:
        return max(1, min(5, int(v)))
    except (TypeError, ValueError):
        return 3


def _rank(cands: list[dict], count: int, checked: bool) -> list[dict]:
    if not checked:
        pool = [c for c in cands if not c.get("problems")] or cands
        return _per_driver(pool, count)
    def key(c):
        s = c.get("scores") or {"reasonable": 3, "exciting": 3}
        # 修正过的视为合理（硬伤已改掉），但比原本就没毛病的略靠后
        r = 4 if c.get("revised") else s["reasonable"]
        return -(r + s["exciting"] * 1.3)   # 过了合理门槛（MIN_REASONABLE）之后，精彩更重要
    good = [c for c in cands if c.get("revised") or (c.get("scores") or {}).get("reasonable", 3) >= MIN_REASONABLE]
    out = _per_driver(sorted(good, key=key), count)
    return out + sorted([c for c in cands if c not in good], key=key)[:count - len(out)]   # 合格的不够才用不合格的补


def _per_driver(pool: list[dict], count: int) -> list[dict]:
    """按排序取，每种驱动最多 MAX_PER_DRIVER_OUT 条，不够再不限。
    （不强制每种各 1 条：评测里那样会把合理性最低的驱动顶进前 5，见 docs/走向引擎.md）"""
    out = []
    for cap in (MAX_PER_DRIVER_OUT, len(pool)):
        per: dict[str, int] = {}
        for c in out:
            per[c["driver"]] = per.get(c["driver"], 0) + 1
        for c in pool:
            if len(out) >= count:
                return out
            if c not in out and per.get(c["driver"], 0) < cap:
                out.append(c)
                per[c["driver"]] = per.get(c["driver"], 0) + 1
    return out
