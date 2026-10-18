# -*- coding: utf-8 -*-
"""Mechanical de-AI pass (humanizer v3.1 fiction-safe subset) on a .docx.

Removes the most common AI-tell filler phrases, adverbial 地-fillers,
transition/connective filler, "仿佛/犹如/宛若/如同 + 一般/一样/似的" simile
connectors, vague openers ("随着…的发展"), and "一股+X" emotion-noun blobs.

额外产出「改写效果量化」：复用 wiki_signs_scan 的 AI 味浓度分算法，
在改写前后各算一次，输出**消除率**与仍残留的高频信号，
作为「输出准确性」的可验证证据（而非只报「改了 N 段」）。

Usage:
    python deai_humanizer.py <input.docx> <output.docx> [--report report.md]

Preserves paragraph style/alignment but collapses each edited paragraph to a
single run. For a plain-text novel manuscript this is acceptable; verify the
result visually afterwards.

The RULES list is the curated fiction-safe subset of the open-source
unclecheng/humanizer banned-words + structures rules.
"""
from errkit import safe_main
import argparse
import re
import sys
from collections import Counter
from docx import Document

# 复用维基《AI 写作迹象》识别器的浓度分算法（硬信号×2 + 软信号×1）
from wiki_signs_scan import scan_paragraph, concentration_score

RULES = [
    # --- most toxic filler phrases (delete) ---
    ("不禁", ""), ("忍不住", ""), ("下意识地", ""), ("下意识", ""),
    ("不由自主地", ""), ("不由自主", ""), ("情不自禁", ""),
    ("自然而然地", ""), ("自然而然", ""), ("说白了", ""),
    ("众所周知", ""), ("毫无疑问", ""), ("显而易见", ""),
    ("不容置疑", "就是"), ("不容置喙", ""), ("不易察觉", ""),
    ("深吸一口气", ""), ("心中涌起一股", ""), ("心头一震", ""),
    ("心中一动", ""), ("心下了然", ""), ("心底泛起", ""),
    ("不由得", ""), ("嘴角勾起一抹", ""), ("眉头微皱", "皱了皱眉"),
    ("眉眼低垂", "垂下眼"), ("瞳孔微缩", "瞳孔一缩"),
    ("眼中闪过一丝", ""), ("眼中闪过一抹", ""),
    # --- adverbial 地-fillers (safe: leaves the verb) ---
    ("微微地", ""), ("淡淡地", ""), ("缓缓地", ""), ("轻轻地", ""),
    # --- transition / connective filler ---
    ("此外", ""), ("值得注意的是", ""), ("需要指出的是", ""),
    ("不难发现", ""), ("综上所述", ""), ("总而言之", ""),
    ("不可否认", ""), ("毋庸置疑", ""), ("事实上", ""),
    ("不得不说", ""), ("坦率地说", ""), ("客观来讲", ""),
    ("从某种意义上说", ""), ("换言之", ""), ("由此可见", ""),
    ("进一步来说", ""), ("深入探讨", ""), ("至关重要", ""),
    ("在当今社会", ""), ("值得一提的是", ""),
    # --- simile connectors ---
    ("仿佛一般", ""), ("犹如一般", ""), ("宛若一般", ""), ("如同一般", ""),
    ("仿佛一样", ""), ("犹如一样", ""), ("宛若一样", ""), ("如同一样", ""),
    ("仿佛似的", ""), ("犹如似的", ""), ("宛若似的", ""), ("如同似的", ""),
    # --- vague openers ---
    (r"随着[^，。！？]{0,20}的发展", ""),
    (r"在[^，。！？]{0,20}的背景下", ""),
    # --- khazix high-risk tells ---
    ("本质上", ""), ("换句话说", ""),
    ("首先，", ""), ("其次，", ""), ("最后，", ""),
    ("一方面，", ""), ("另一方面，", ""),
    # --- tightened patterns (words between connector and simile tag) ---
    (r"仿佛[^，。！？]{0,10}(一般|一样|似的)", ""),
    (r"犹如[^，。！？]{0,10}(一般|一样|似的)", ""),
    (r"宛若[^，。！？]{0,10}(一般|一样|似的)", ""),
    (r"如同[^，。！？]{0,10}(一般|一样|似的)", ""),
    ("涌上心头", ""),
    (r"一股(暖流|寒意|凉意|力量|冲动|酸楚|苦涩|怒火|杀意|恐惧|悲伤|暖意|热流|冷汗|惆怅|落寞|凄凉|无奈|愤懑|酸涩)", ""),
]

COMPILED = [(re.compile(p), r) for p, r in RULES]


def clean(text):
    for rx, rep in COMPILED:
        text = rx.sub(rep, text)
    text = re.sub(r"  +", " ", text)
    text = re.sub(r"\s+([，。！？、])", r"\1", text)
    text = text.replace("（）", "")
    return text


def doc_concentration(doc):
    """遍历 doc 全部段落，汇总 AI 味浓度分与硬/软信号计数。

    返回 (浓度分, hard_counter, soft_counter)。
    """
    hard = Counter()
    soft = Counter()
    for para in doc.paragraphs:
        t = para.text.strip()
        if not t or len(t) < 6:
            continue
        for (typ, reason, word, is_soft) in scan_paragraph(t):
            (soft if is_soft else hard)[typ] += 1
    return concentration_score(hard, soft), hard, soft


def main():
    ap = argparse.ArgumentParser(description="去AI味机械层改写（含改写效果量化）")
    ap.add_argument("src", help="源 .docx")
    ap.add_argument("dst", help="输出 .docx")
    ap.add_argument("--report", help="写出改写效果报告 .md（含消除率与残留信号）")
    args = ap.parse_args()
    src, dst = args.src, args.dst

    doc = Document(src)
    score_before, _, _ = doc_concentration(doc)

    total = 0
    for para in doc.paragraphs:
        if not para.text.strip():
            continue
        new = clean(para.text)
        if new != para.text:
            style = para.style
            align = para.alignment
            para.clear()
            para.add_run(new)
            para.style = style
            para.alignment = align
            total += 1
    doc.save(dst)

    score_after, after_hard, after_soft = doc_concentration(doc)
    delta = score_after - score_before
    if score_before > 0:
        rate = (score_before - score_after) / score_before * 100
        rate_text = f"{rate:.0f}%"
    else:
        # 改写前本就没有 AI 味信号：报「0%」会误导成没效果，故明确区分
        rate = 0.0
        rate_text = "N/A（改写前未检出 AI 味信号，本层无需消除）"

    print(f"paragraphs edited: {total} -> {dst}")
    line = f"AI 味浓度分: {score_before} → {score_after}（消除率 {rate_text}）"
    if delta > 0:
        line += f"  ⚠️ 未降反升 {delta}，建议人工/L3 精修"
    print(line)

    if args.report:
        lines = ["# 去AI味机械层改写报告", "",
                 f"- 改写段落数：{total}",
                 f"- AI 味浓度分（改写前 → 改写后）：{score_before} → {score_after}",
                 f"- 消除率：{rate_text}", ""]
        if delta > 0:
            lines.append("> ⚠️ 浓度分未降反升，说明机械层改写可能引入或未能消除某些信号，"
                         "建议结合 11_wiki_signs.md 做 L3/agent 定向精修。")
            lines.append("")
        resid = Counter()
        resid.update(after_hard)
        resid.update(after_soft)
        if resid:
            lines.append("改写后仍残留的高频信号（建议 L3/agent 定向精修）：")
            for typ, c in resid.most_common(3):
                lines.append(f"- [{typ}] ×{c}")
        else:
            lines.append("✅ 改写后未检出 AI 写作迹象信号（仍建议人工抽读确认语义层）。")
        open(args.report, "w", encoding="utf-8").write("\n".join(lines))
        print(f"改写报告已写出: {args.report}")


if __name__ == "__main__":
    safe_main(main)
