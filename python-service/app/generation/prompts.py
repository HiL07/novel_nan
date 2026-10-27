"""提示词模板（中文）。核心规则放在 system 中，每次调用都会带上且不会被裁剪。"""

SYSTEM_RULES = """你是一位中文长篇小说作者，正在连载一部小说。写作规则：
1. 只输出小说正文，不要输出标题、提纲、说明、总结或任何与正文无关的话。
2. 严格遵守【核心设定】；按需提供的【相关设定】同样必须遵守。
3. 设定中没有提到的内容尚未确定：可以合理发挥，但不得与已有设定和前文冲突，也不要把临时发挥写成与设定矛盾的“定论”。
4. 保持叙事视角、人物性格和文风前后一致；不要重复已经写过的内容。"""


def system(core: list[str], open_: list[str], roster: list[str]) -> str:
    parts = [SYSTEM_RULES, "", "【核心设定】"]
    parts.append("\n\n".join(core) if core else "（用户尚未确定任何核心设定，请根据本章目标自行把握，并保持前后一致）")
    if roster:
        parts += ["", "【已设定的角色】" + "、".join(roster)]
    if open_:
        parts += ["", "【尚未设定】" + "、".join(open_) + "（可合理发挥，不得与已有内容冲突）"]
    return "\n".join(parts)


def beat_at(plan: dict | None, written_chars: int, target_chars: int) -> int:
    """按已写字数占比估计当前应写到第几个节拍（0 起）；没有规划时为 -1。"""
    beats = (plan or {}).get("beats") or []
    if not beats:
        return -1
    return min(len(beats) - 1, int(written_chars / max(target_chars, 1) * len(beats)))


def task(*, chapter_index: int, title: str, goal: str, target_chars: int, written_chars: int,
         segment_chars: int, is_first: bool, is_last: bool, plan: dict | None = None) -> str:
    head = f"第{chapter_index}章" + (f"《{title}》" if title else "")
    lines = [f"本章：{head}", f"本章目标：{goal}", f"本章计划约 {target_chars} 字，已写约 {written_chars} 字。"]
    beats = (plan or {}).get("beats") or []
    if beats:
        lines.append("本章节拍：" + "；".join(f"{i + 1}. {b}" for i, b in enumerate(beats)))
        k = beat_at(plan, written_chars, target_chars)
        if is_last:
            lines.append(f"本段写完第 {k + 1} 个及之后剩余的节拍。")
        else:
            lines.append(f"本段主要写第 {k + 1} 个节拍：{beats[k]}（按节拍顺序推进，不要跳到后面的节拍）。")
        if is_last and plan.get("hook"):
            lines.append(f"章末钩子：{plan['hook']}")
    if is_first:
        lines.append(f"现在开始写本章正文，本次写约 {segment_chars} 字。")
    else:
        lines.append(f"紧接【本章此前内容】的最后一句继续往下写，不要重复、不要重新开头，本次写约 {segment_chars} 字。")
    if is_last:
        lines.append("这是本章的最后一部分：请推进并完成本章目标，在一个自然的位置收束本章。")
    else:
        lines.append("本章尚未结束：不要在这一部分收尾，保持情节继续发展。")
    return "\n".join(lines)


# ---------------------------------------------------------------- 章节规划 / 事实抽取 / 一致性检查（JSON 输出）

PLAN_SYSTEM = "你是连载小说的策划编辑，负责在动笔前把一章拆成节拍。只输出 JSON，不要任何解释。"


def plan_user(*, chapter_index: int, title: str, goal: str, target_chars: int, core: str, facts: str,
              prev_summary: str, next_outline: str) -> str:
    parts = []
    if core:
        parts.append("【核心设定】\n" + core)
    if facts:
        parts.append("【故事账本】\n" + facts)
    if prev_summary:
        parts.append("【上一章摘要】\n" + prev_summary)
    if next_outline:
        parts.append("【下一章预告（大纲）】\n" + next_outline)
    head = f"第{chapter_index}章" + (f"《{title}》" if title else "")
    parts.append(f"【本章】{head}，约 {target_chars} 字\n本章目标：{goal}")
    parts.append(
        "请为本章规划 3~6 个按顺序推进的节拍，每个节拍一句话（≤40 字），写清发生什么、谁参与、结果如何；"
        "节拍要完成本章目标，并与前情和故事账本衔接。foreshadow 写本章打算怎么处理伏笔："
        "推进或回收【故事账本】里已有的伏笔时写它的编号（如「F1 推进：…」，只能用账本里出现过的编号，不要编造），"
        "打算新埋的写「新埋：…」；没有就留空数组。"
        "最后给出一个章末钩子（为下一章留悬念；有下一章预告时向它铺垫）。\n"
        '输出格式：{"beats": ["…", "…"], "foreshadow": ["F1 推进：…", "新埋：…"], "hook": "…"}')
    return "\n\n".join(parts)


DIGEST_SYSTEM = "你是连载小说的编辑，负责为每章写摘要并整理故事事实账本。只输出 JSON，不要任何解释。"


def digest_user(chapter_index: int, title: str, text: str, known: str) -> str:
    head = f"第{chapter_index}章" + (f"《{title}》" if title else "")
    known_part = f"【已有账本】\n{known}\n\n" if known else ""
    return (
        f"{known_part}【{head} 正文】\n{text}\n\n"
        "请完成两件事：\n"
        "1. summary：不超过 150 字，概括本章关键情节、人物状态变化和留下的悬念，供后续章节衔接。\n"
        "2. 抽取本章的故事事实（只写本章正文中实际发生的，不要推测）：\n"
        "   - foreshadow：伏笔只记会影响后续多章的长线悬念（隐藏的身世 / 秘密、神秘物品或力量、未兑现的约定或威胁、"
        "未解的谜团）；本章内就解决的困境、普通冲突、人物恩怨本身都不算。本章新埋的（action=plant，不填 id）最多 2 个，"
        "宁缺毋滥；【已有账本】里的伏笔本章有新进展填 advance，谜底揭开 / 困境已解除 / 约定已兑现填 resolve（都要填编号）。\n"
        "   - characters：状态有变化的角色（受伤、突破、身份暴露、立场或关系改变、获得 / 失去重要物品、死亡等），"
        "change 写本章的变化，state 写变化后的完整当前状态（≤60 字）；没变化的角色不要列。\n"
        "   - timeline：本章 1~3 个推动主线的关键事件（when 写故事内的时间，如「入门第三天」，不确定就留空）；"
        "琐碎动作不要列。\n"
        '输出格式：{"summary": "…", "foreshadow": [{"id": "", "text": "…", "action": "plant", "note": "…"}], '
        '"characters": [{"name": "…", "change": "…", "state": "…"}], "timeline": [{"when": "…", "event": "…"}]}')


REVIEW_SYSTEM = ("你是严格的连载小说责任编辑，负责检查新写的一章与已有设定、前文是否矛盾。只输出 JSON，不要任何解释。"
                 "只报告确实存在的问题，不要吹毛求疵，不要评价文笔。")
REVIEW_TYPES = {"setting": "设定冲突", "character": "人物不符", "timeline": "时间线", "foreshadow": "伏笔",
                "logic": "逻辑漏洞"}


def review_user(*, chapter_index: int, title: str, goal: str, text: str, core: str, facts: str, story: str,
                plan: str) -> str:
    parts = []
    if core:
        parts.append("【核心设定】\n" + core)
    if facts:
        parts.append("【故事账本（本章之前）】\n" + facts)
    if story:
        parts.append("【前情提要】\n" + story)
    head = f"第{chapter_index}章" + (f"《{title}》" if title else "")
    parts.append(f"【本章目标】{goal}" + (f"\n【本章规划】{plan}" if plan else ""))
    parts.append(f"【{head} 正文】\n{text}")
    parts.append(
        "请检查本章正文是否存在以下问题：setting（与核心设定冲突，如力量体系、世界规则、地名势力）、"
        "character（人物言行、能力、关系与设定或前文不符，或角色状态如伤势、生死被忽略）、"
        "timeline（时间顺序、时长、季节等前后矛盾）、foreshadow（与已埋伏笔矛盾，或回收方式与伏笔不符）、"
        "logic（情节因果不通、前后自相矛盾）。\n"
        "每个问题：quote 摘录正文中出问题的原句（必须是正文里原样存在的连续文字，≤60 字），detail 说明与什么冲突，"
        "fix 给出具体修改建议。只报告读者会察觉的真正矛盾；用词、细节描写、可以合理脑补的小处不算问题。"
        "没有问题就输出空数组。最多 5 个问题，按严重程度排序。\n"
        '输出格式：{"issues": [{"type": "character", "quote": "…", "detail": "…", "fix": "…"}]}')
    return "\n\n".join(parts)


SUMMARY_SYSTEM = "你是小说编辑，负责为连载小说写简洁准确的章节摘要。只输出摘要本身。"


def summary_user(chapter_index: int, title: str, text: str) -> str:
    return (f"请用不超过 150 字概括第{chapter_index}章{('《' + title + '》') if title else ''}的关键情节、"
            f"人物状态变化和留下的悬念，供后续章节衔接使用：\n\n{text}")


def arc_user(previous_arc: str, summaries: list[str]) -> str:
    joined = "\n".join(summaries)
    prev = f"已有的前情概要：\n{previous_arc}\n\n" if previous_arc else ""
    return f"{prev}请把以下章节摘要与已有概要合并为一段不超过 300 字的前情概要，保留主线、人物关系和未解悬念：\n{joined}"


POLISH_SYSTEM = "你是小说润色编辑。只输出润色后的正文，不要标题、说明或任何多余的话。"


def polish_user(text: str) -> str:
    return ("润色下面这段小说正文：情节、人物、对话含义、叙述视角和段落顺序保持不变，不增删情节，不续写；"
            "只改进用词、句式和节奏，让文字更自然、更有文学性。直接输出润色后的这段正文：\n\n" + text)
