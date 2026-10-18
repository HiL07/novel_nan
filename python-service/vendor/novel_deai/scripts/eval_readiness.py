# -*- coding: utf-8 -*-
"""eval_readiness.py — 番茄推荐评估「就绪度」自检（宏观总览，非逐章清单）

在 eval_fix_check.py（逐章机械检测）之上，补一个**宏观就绪度总览**：
把「能否提交 8 万字推荐评估」拆成 5 个可直接从 .docx 算出的维度，
给出 0-100 综合就绪度分 + 各维度得分 + 最需补的短板清单。

维度与权重（对齐 references/tomato_80k_evaluation.md 硬性门槛）：
  1. 字数门槛   (30) 总汉字 ≥ 8 万（申请硬门槛），按达标比例给分
  2. 章节健康度 (20) 平均章字数落在 1500-3000 健康带的章节占比
  3. 开篇钩子   (20) 前三章无「世界观堆砌且无冲突」MUST 问题的章占比
  4. AI 味健康度(15) 全书平均 AI 味浓度分（硬×2+软×1）越低越高分
  5. 对话健康度 (15) 对话占比超标（>40%）章节占比越低越高分

诚实边界：日更稳定性（连续 3 天日更≥4000）、验证期留存率/小流量数据
**无法从文档判断**，报告单列「需后台自查」段提醒用户去平台后台确认。

输出：控制台摘要 + --out report.md（维度雷达 + 短板清单 + 后台自查项）

用法:
  python eval_readiness.py <src.docx> [--out 12_eval_readiness.md]
"""
from errkit import safe_main
import argparse
import sys
from collections import Counter
from docx import Document

# 复用 eval_fix_check 的章节切分与逐章检测（同一套机械规则，保证口径一致）
from eval_fix_check import (parse_chapters, check_chapter, check_opening_hook)
# 复用维基《AI 写作迹象》识别器的浓度分算法
from wiki_signs_scan import scan_paragraph, concentration_score

WORD_THRESHOLD = 80000          # 8 万字申请门槛
HEALTHY_LO, HEALTHY_HI = 1500, 3000
DIALOGUE_LIMIT = 0.40


def ai_concentration(doc):
    """全书 AI 味浓度分（硬信号×2 + 软信号×1）。"""
    hard = Counter()
    soft = Counter()
    for para in doc.paragraphs:
        t = para.text.strip()
        if not t or len(t) < 6:
            continue
        for (typ, reason, word, is_soft) in scan_paragraph(t):
            (soft if is_soft else hard)[typ] += 1
    return concentration_score(hard, soft)


def compute_readiness(src):
    doc = Document(str(src))
    chapters = parse_chapters(doc)
    if not chapters:
        return None  # 调用方处理「未检出章节」

    all_issues = []
    hans = []
    for num, title, paras in chapters:
        issues, han = check_chapter(num, title, paras)
        all_issues.append((num, title, issues, han))
        hans.append(han)

    total_han = sum(hans)
    avg = total_han / len(chapters)
    opening = check_opening_hook(chapters)
    score = ai_concentration(doc)

    # 1. 字数门槛 (30)
    word_score = 30.0 if total_han >= WORD_THRESHOLD else min(30.0, total_han / WORD_THRESHOLD * 30)

    # 2. 章节健康度 (20)
    healthy = sum(1 for h in hans if HEALTHY_LO <= h <= HEALTHY_HI)
    chapter_score = healthy / len(chapters) * 20

    # 3. 开篇钩子 (20)：前三章无 MUST 钩子问题
    op3 = opening[:3]
    op_pass = sum(1 for lv, _, _ in op3 if lv != "MUST")
    hook_score = (op_pass / len(op3) * 20) if op3 else 0.0

    # 4. AI 味健康度 (15)
    per_ch = score / len(chapters)
    if per_ch <= 1:
        ai_score = 15.0
    elif per_ch <= 3:
        ai_score = 10.0
    elif per_ch <= 6:
        ai_score = 5.0
    else:
        ai_score = 0.0

    # 5. 对话健康度 (15)
    dial_over = sum(1 for _, _, iss, _ in all_issues
                    if any(cat == "对话超标" for lv, cat, _ in iss))
    dial_score = 15.0 * (1 - dial_over / len(chapters))

    readiness = round(word_score + chapter_score + hook_score + ai_score + dial_score)

    if readiness >= 80:
        grade = "就绪（可直接提交评估）"
    elif readiness >= 60:
        grade = "基本就绪（建议先针对性优化短板）"
    else:
        grade = "差距较大（先补齐硬性门槛：字数 / 章节健康度）"

    return {
        "total_han": total_han,
        "nch": len(chapters),
        "avg": avg,
        "score": score,
        "word_score": word_score,
        "chapter_score": chapter_score,
        "hook_score": hook_score,
        "ai_score": ai_score,
        "dial_score": dial_score,
        "dial_over": dial_over,
        "healthy": healthy,
        "readiness": readiness,
        "grade": grade,
        "op_must": sum(1 for lv, _, _ in opening if lv == "MUST"),
    }


def main():
    ap = argparse.ArgumentParser(description="番茄推荐评估就绪度自检")
    ap.add_argument("src", help="源 .docx")
    ap.add_argument("--out", help="输出报告 .md")
    args = ap.parse_args()

    res = compute_readiness(args.src)
    if res is None:
        print("未检出任何章节（未找到 \"第N章\" 标题段），无法评估就绪度，退出。")
        sys.exit(1)

    print("=" * 56)
    print("番茄推荐评估 · 就绪度自检")
    print("=" * 56)
    print(f"综合就绪度: {res['readiness']}/100  →  {res['grade']}")
    print(f"总字数: {res['total_han']}（门槛 {WORD_THRESHOLD}）| 章节: {res['nch']} "
          f"| 均值: {res['avg']:.0f} 字/章")
    print(f"AI 味浓度分(全书): {res['score']} | 对话超标章: {res['dial_over']} "
          f"| 开篇钩子 MUST 问题: {res['op_must']}")
    print("-" * 56)
    print(f"  字数门槛    : {res['word_score']:.0f}/30")
    print(f"  章节健康度  : {res['chapter_score']:.0f}/20（{res['healthy']}/{res['nch']} 章在 1500-3000）")
    print(f"  开篇钩子    : {res['hook_score']:.0f}/20")
    print(f"  AI 味健康度 : {res['ai_score']:.0f}/15")
    print(f"  对话健康度  : {res['dial_score']:.0f}/15")
    print("=" * 56)

    if args.out:
        lines = ["# 番茄推荐评估 · 就绪度自检报告", "",
                 f"- 综合就绪度：**{res['readiness']}/100** → {res['grade']}",
                 f"- 总字数：{res['total_han']}（申请门槛 {WORD_THRESHOLD}）",
                 f"- 章节数：{res['nch']} | 平均章字数：{res['avg']:.0f}（健康带 {HEALTHY_LO}-{HEALTHY_HI}）",
                 f"- 全书 AI 味浓度分：{res['score']}",
                 "", "## 维度评分", "",
                 "| 维度 | 得分 | 说明 |",
                 "| --- | --- | --- |",
                 f"| 字数门槛 | {res['word_score']:.0f}/30 | 总字数达 8 万门槛的比例 |",
                 f"| 章节健康度 | {res['chapter_score']:.0f}/20 | {res['healthy']}/{res['nch']} 章落在 1500-3000 健康带 |",
                 f"| 开篇钩子 | {res['hook_score']:.0f}/20 | 前三章无「堆砌无冲突」MUST 问题的占比 |",
                 f"| AI 味健康度 | {res['ai_score']:.0f}/15 | 全书平均浓度分越低越高分 |",
                 f"| 对话健康度 | {res['dial_score']:.0f}/15 | 对话超标(>40%)章占比越低越高分 |",
                 "", "## 最需补的短板", ""]
        # 短板按得分/满分 比例排序
        dims = [("字数门槛", res['word_score'], 30, "补齐正文至 ≥8 万字（注意是有效正文，非灌水）"),
                ("章节健康度", res['chapter_score'], 20, "把过短(<1500)/过长(>3000)章调整到 1500-3000 字"),
                ("开篇钩子", res['hook_score'], 20, "重写前三章开篇：冲突/金手指前置到前300字，删世界观堆砌"),
                ("AI 味健康度", res['ai_score'], 15, "用 deai_humanizer + 11_wiki_signs 定向精修残留 AI 味信号"),
                ("对话健康度", res['dial_score'], 15, "砍掉对话超标章的无效对白，补充叙述/动作")]
        dims_sorted = sorted(dims, key=lambda d: d[1] / d[2])
        for name, sc, full, fix in dims_sorted:
            if sc < full:
                lines.append(f"- **{name}** {sc:.0f}/{full}：{fix}")
        if all(sc >= full for _, sc, full, _ in dims_sorted):
            lines.append("- ✅ 五个维度均达标，机械层无明显短板。")
        lines += ["", "## 需后台自查（无法从文档判断）", "",
                  "- 连续 3 天日更 ≥4000 字（申请资格门槛，断更/不足会重置资格）",
                  "- 验证期 7 天日更 ≥4000 字，且结束时满 10 万字（否则无法进入首秀）",
                  "- 留存率 / 小流量数据（平台后台查看，决定能否进正式首秀）",
                  "- 封面客观指标可用 `cover_check.py` 自动查；真人肖像/第三方IP/敏感地标仍需人确认",
                  "", "## 使用建议", "",
                  "- 就绪：可提交评估，**提交前再确认上方「需后台自查」项**（开启后不可撤回，仅 3 次机会）",
                  "- 基本就绪：先按「最需补的短板」针对性优化，再提交",
                  "- 差距较大：先补齐硬性门槛（字数 / 章节健康度）再谈优化", ""]
        open(args.out, "w", encoding="utf-8").write("\n".join(lines))
        print(f"就绪度报告已写出: {args.out}")


if __name__ == "__main__":
    safe_main(main)
