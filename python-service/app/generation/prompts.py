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


def task(*, chapter_index: int, title: str, goal: str, target_chars: int, written_chars: int,
         segment_chars: int, is_first: bool, is_last: bool) -> str:
    head = f"第{chapter_index}章" + (f"《{title}》" if title else "")
    lines = [f"本章：{head}", f"本章目标：{goal}", f"本章计划约 {target_chars} 字，已写约 {written_chars} 字。"]
    if is_first:
        lines.append(f"现在开始写本章正文，本次写约 {segment_chars} 字。")
    else:
        lines.append(f"紧接【本章此前内容】的最后一句继续往下写，不要重复、不要重新开头，本次写约 {segment_chars} 字。")
    if is_last:
        lines.append("这是本章的最后一部分：请推进并完成本章目标，在一个自然的位置收束本章。")
    else:
        lines.append("本章尚未结束：不要在这一部分收尾，保持情节继续发展。")
    return "\n".join(lines)


SUMMARY_SYSTEM = "你是小说编辑，负责为连载小说写简洁准确的章节摘要。只输出摘要本身。"


def summary_user(chapter_index: int, title: str, text: str) -> str:
    return (f"请用不超过 150 字概括第{chapter_index}章{('《' + title + '》') if title else ''}的关键情节、"
            f"人物状态变化和留下的悬念，供后续章节衔接使用：\n\n{text}")


def arc_user(previous_arc: str, summaries: list[str]) -> str:
    joined = "\n".join(summaries)
    prev = f"已有的前情概要：\n{previous_arc}\n\n" if previous_arc else ""
    return f"{prev}请把以下章节摘要与已有概要合并为一段不超过 300 字的前情概要，保留主线、人物关系和未解悬念：\n{joined}"
