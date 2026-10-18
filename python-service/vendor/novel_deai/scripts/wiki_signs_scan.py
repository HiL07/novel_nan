# -*- coding: utf-8 -*-
"""wiki_signs_scan.py — 维基《AI 写作迹象》识别扫描（去AI味流水线 辅助层，WARN-only）

把维基百科《Signs of AI writing》的"识别方法论"落成可机械执行的扫描器：
从 .docx 里挖出"疑似 AI 写作"的痕迹，按**高置信 / 中置信**分级，
输出 11_wiki_signs.md（章节 → 命中段落），**不自动改任何字**，交 L3 / agent 定向精修。

设计：面向网文场景做降噪——英文词汇黑名单罕见却高置信；中文对应词日常常用故不单独命中；
结构类信号（否定平行 / 说教免责 / 模糊归因 / 僵化结尾 / Markdown 残留 / Emoji / 破折号过量）
是鲁棒的主 detectors；"虚假范围 / 三段式排比 / 伪造来源"易误伤正常用法，标**中置信-待人工**。

信号分类（与 references/wiki_ai_writing_signs.md 一一对应）：
  【高置信·硬信号】
    V.英文词汇黑名单   delve/testament/landscape/underscore/highlight/pivotal/intricate/
                      nuanced/vibrant/bustling/showcase/foster/align with/enduring/lasting
    N.否定平行结构     不仅是X更是Y / not just X but Y
    D.说教式免责声明   值得注意的是/值得一提的是/需要指出的是/不可否认/毋庸置疑…
    A.模糊归因(黄鼠狼) 批评者认为/观察家指出/有人认为/专家表示…
    E.僵化结尾/升华     总结来说/整体来看/综上所述/尽管面临挑战但…
    M.Markdown残留      "## " / "# " / "**" / 反引号
    J.Emoji异常         🚀📘 等码位
    _.破折号过度使用     单段 "——" ≥ 3 处
  【中置信·软信号（待人工/L3 判定，不计入硬候选）】
    R.虚假范围          从X到Y（跨度可能风马牛不相及）
    T.三段式排比        单句 ≥3 个并列形容短语
    F.疑似伪造来源       ISBN/参考文献/据《》/第N页/来源：

输出：控制台摘要 + --out report.md（按 章 → 命中段落 列出，硬/软分级）。

用法:
  python wiki_signs_scan.py <src.docx> [--out 11_wiki_signs.md]
"""
from errkit import safe_main
import argparse
import re
import sys
from collections import Counter

from docx import Document

try:
    from deai_deep_report import parse_chapters
except ImportError:  # 独立运行兜底
    sys.path.insert(0, str(__file__).rsplit("\\", 1)[0].rsplit("/", 1)[0])
    from deai_deep_report import parse_chapters


# ---- 高置信：英文词汇黑名单（大小写不敏感整词匹配）----
EN_VOCAB = [
    "delve", "testament", "landscape", "underscore", "highlight", "pivotal",
    "intricate", "nuanced", "vibrant", "bustling", "showcase", "foster",
    "align with", "enduring", "lasting",
]
EN_VOCAB_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in EN_VOCAB) + r")\b",
                         re.IGNORECASE)

# ---- 高置信：否定平行结构 ----
NEG_PARALLEL_RE = re.compile(
    r"(?:不仅是|不只是|不止是|绝非仅仅)[^，。，]{0,15}(?:更是|还是|恰是|亦是)"
    r"|not\s+(?:just|only|merely)[^.]{0,40}but\s+(?:also|rather)",
    re.IGNORECASE)

# ---- 高置信：说教式免责声明 ----
DIDACTIC = ["值得注意的是", "重要的是", "值得一提的是", "需要指出的是", "不可否认",
            "毋庸置疑", "客观来讲", "有必要指出", "值得一提的是"]
DIDACTIC_RE = re.compile("|".join(re.escape(w) for w in DIDACTIC))

# ---- 高置信：模糊归因（黄鼠狼话术）----
VAGUE_ATTR = ["批评者认为", "观察家指出", "有人认为", "专家表示", "有分析认为",
              "据相关人士", "有学者指出", "外界认为", "有观点认为"]
VAGUE_ATTR_RE = re.compile("|".join(re.escape(w) for w in VAGUE_ATTR))

# ---- 高置信：僵化结尾 / 升华 ----
RIGID_ENDING = ["总结来说", "整体来看", "总的来说", "综上所述", "简而言之",
                "一言以蔽之", "尽管面临挑战", "虽然…但", "尽管…但",
                "in summary", "overall", "in conclusion"]
RIGID_ENDING_RE = re.compile("|".join(re.escape(w) for w in RIGID_ENDING),
                             re.IGNORECASE)

# ---- 高置信：Markdown 残留 ----
MD_RESIDUE_RE = re.compile(r"(^|\n)\s{0,3}#{1,6}\s|##\s|\*\*|```")

# ---- 高置信：Emoji 异常（常见 emoji 码位区间）----
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F]")

# ---- 高置信：破折号过度使用（单段 ≥3 处）----
EM_DASH_THRESHOLD = 3

# ---- 中置信：虚假范围（从X到Y，易误伤正常用法）----
FALSE_RANGE_RE = re.compile(r"从[^，。，]{1,14}到[^，。，]{1,14}[，。，]")

# ---- 中置信：三段式排比（单句 ≥3 个"的"结尾并列短语）----
# 以 、或， 分隔、且多数以"的"结尾的形容词短语 ≥3 个
RULE_OF_THREE_RE = re.compile(r"([一-龥]{1,6}的[，、]){2,}[一-龥]{1,6}的?")

# ---- 中置信：疑似伪造来源 / 引用幻觉 ----
FAKE_REF_RE = re.compile(r"ISBN|参考文献|据《[^》]{1,15}》|第\s*\d+\s*页|来源\s*[:：]")


def scan_paragraph(text):
    """返回该段命中的信号列表 [(类型, 原因, 命中词, 是否软信号)]。"""
    hits = []

    # V. 英文词汇黑名单（高置信）
    for m in EN_VOCAB_RE.finditer(text):
        hits.append(("V.英文词汇黑名单", f"出现 AI 高频英文词「{m.group(1)}」", m.group(1), False))
        break

    # N. 否定平行结构（高置信）
    if NEG_PARALLEL_RE.search(text):
        hits.append(("N.否定平行结构",
                     "出现「不仅是X更是Y」式否定平行，赋予平凡事物深刻意义", "不仅是…更是", False))

    # D. 说教式免责声明（高置信）
    dm = DIDACTIC_RE.search(text)
    if dm:
        hits.append(("D.说教式免责声明", f"出现教科书式指导读者「{dm.group(0)}」", dm.group(0), False))

    # A. 模糊归因（高置信）
    am = VAGUE_ATTR_RE.search(text)
    if am:
        hits.append(("A.模糊归因(黄鼠狼话术)", f"出现不指名来源的「{am.group(0)}」", am.group(0), False))

    # E. 僵化结尾 / 升华（高置信）
    em = RIGID_ENDING_RE.search(text)
    if em:
        hits.append(("E.僵化结尾/升华", f"出现套路化总结/升华语「{em.group(0)}」", em.group(0), False))

    # M. Markdown 残留（高置信）
    if MD_RESIDUE_RE.search(text):
        hits.append(("M.Markdown残留", "文本含未清除的 Markdown 标记（##/**/```）", "##/**", False))

    # J. Emoji 异常（高置信）
    jm = EMOJI_RE.search(text)
    if jm:
        hits.append(("J.Emoji异常", f"正文出现异常 Emoji「{jm.group(0)}」", jm.group(0), False))

    # _. 破折号过度使用（高置信，按单段计数）
    dash = text.count("——")
    if dash >= EM_DASH_THRESHOLD:
        hits.append(("_.破折号过度使用", f"单段出现 {dash} 处破折号（≥{EM_DASH_THRESHOLD}），过量", "——", False))

    # R. 虚假范围（中置信-待人工）
    if FALSE_RANGE_RE.search(text):
        hits.append(("R.虚假范围(中置信-待人工)",
                     "出现「从X到Y」跨段表述，可能风马牛不相及、用华丽辞藻掩盖空洞；需结合语境判断",
                     "从…到…", True))

    # T. 三段式排比（中置信-待人工）
    if RULE_OF_THREE_RE.search(text):
        hits.append(("T.三段式排比(中置信-待人工)",
                     "单句含 ≥3 个并列形容短语，疑似 AI 式排比；需结合语境判断（正常排比不误杀）",
                     "的、的、的", True))

    # F. 疑似伪造来源（中置信-待人工）
    if FAKE_REF_RE.search(text):
        hits.append(("F.疑似伪造来源(中置信-待人工)",
                     "正文出现 ISBN/参考文献/据《》/第N页/来源：等引用痕迹，网文本不应有；需人工核查真伪",
                     "引用痕迹", True))

    return hits


def scan_docx(path, max_per_chapter=25):
    doc = Document(str(path))
    chapters = parse_chapters(doc)
    results = []
    hard_counter = Counter()
    soft_counter = Counter()
    for ch in chapters:
        ch_hits = []
        for para in ch["paras"]:
            if not para.strip() or len(para) < 6:
                continue
            for (typ, reason, word, is_soft) in scan_paragraph(para):
                if is_soft:
                    soft_counter[typ] += 1
                else:
                    hard_counter[typ] += 1
                snippet = para if len(para) <= 80 else para[:80] + "…"
                ch_hits.append((typ, reason, word, snippet, is_soft))
                if len(ch_hits) >= max_per_chapter:
                    break
        if ch_hits:
            results.append((ch["title"], ch_hits))
    return results, hard_counter, soft_counter, len(chapters)


def concentration_score(hard_counter, soft_counter):
    """AI 味浓度分：硬信号 +2 / 软信号 +1。"""
    return sum(hard_counter.values()) * 2 + sum(soft_counter.values())


def main():
    ap = argparse.ArgumentParser(description="维基《AI 写作迹象》识别扫描（WARN-only）")
    ap.add_argument("src", help="源 .docx")
    ap.add_argument("--out", help="输出报告 .md")
    args = ap.parse_args()

    results, hard_counter, soft_counter, nch = scan_docx(args.src)
    hard_total = sum(hard_counter.values())
    soft_total = sum(soft_counter.values())
    score = concentration_score(hard_counter, soft_counter)

    print("=" * 56)
    print("维基《AI 写作迹象》识别扫描（WARN-only，仅挖候选，不自动修改）")
    print("=" * 56)
    print(f"扫描章节: {nch}")
    print(f"硬信号(高置信): {hard_total}  | 中置信软信号(待人工): {soft_total}")
    print(f"AI 味浓度分: {score}")
    if hard_counter:
        print("  [硬信号]")
        for typ, c in hard_counter.most_common():
            print(f"    [{typ}] {c}")
    if soft_counter:
        print("  [中置信-待人工]")
        for typ, c in soft_counter.most_common():
            print(f"    [{typ}] {c}")
    print("-" * 56)

    if args.out:
        lines = ["# 维基《AI 写作迹象》识别报告（WARN-only · 仅候选，需人工/L3 判定）", ""]
        lines.append("> 本扫描**不替你改任何字**。它把维基百科《Signs of AI writing》列出的 AI 写作迹象"
                     "在本书里挖出来，供你按 `references/wiki_ai_writing_signs.md`（知识库）"
                     "或 `references/llm_rewrite_sop.md` / `references/agent_semantic_rewrite.md`（改写）定向精修。"
                     "**高置信**信号建议直接按 humanizer 规则改写；**中置信**信号需读上下文二次判定，勿误杀正常排比/合理范围。")
        lines.append("")
        lines.append(f"- 扫描章节：{nch}")
        lines.append(f"- 硬信号合计（高置信）：{hard_total}")
        lines.append(f"- 中置信软信号合计（待人工/L3 判定，不计入硬候选）：{soft_total}")
        lines.append(f"- **AI 味浓度分**：{score}（硬信号×2 + 软信号×1；越高越集中，优先处理高分章节）")
        if hard_counter:
            lines.append("- 硬信号分布：" + "，".join(f"{t}={c}" for t, c in hard_counter.most_common()))
        if soft_counter:
            lines.append("- 中置信软信号分布：" + "，".join(f"{t}={c}" for t, c in soft_counter.most_common()))
        lines.append("")
        if not results:
            lines.append("✅ 未扫出明显 AI 写作迹象（不代表绝对无 AI 味，仍建议人工抽读）。")
        for title, hits in results:
            lines.append(f"## {title}")
            lines.append("")
            for (typ, reason, word, snippet, is_soft) in hits:
                tag = "【中置信·待人工】" if is_soft else "【高置信·硬信号】"
                lines.append(f"- **[{typ}]** {tag} {reason}")
                lines.append(f"  > 原文：{snippet}")
            lines.append("")
        open(args.out, "w", encoding="utf-8").write("\n".join(lines))
        print(f"报告已写出: {args.out}")
    else:
        for title, hits in results[:20]:
            soft_n = sum(1 for h in hits if h[4])
            print(f"· {title}（{len(hits)} 处，其中中置信 {soft_n}）")
            for (typ, reason, word, snippet, is_soft) in hits[:3]:
                print(f"    - [{typ}] {snippet[:40]}")


if __name__ == "__main__":
    safe_main(main)

