# -*- coding: utf-8 -*-
"""semantic_scan.py — 深层语义风险扫描（去AI味流水线 辅助层，WARN-only）

与 L1/L2 的"机械查找替换"不同，本脚本面向**正则单点命不中的语义问题**，
尤其是用户反馈的痛点：「暗示性的多角关系 / 暧昧描写」「价值观 / 未成年负面导向」。

它**不做任何自动修改**（语义是否越界必须人 / LLM 拍板），而是把高风险段落
挖出来，附上原文 + 上下文 + 触发原因，交给 L3 按 references/semantic_risk_sop.md
（人工）或 references/agent_semantic_rewrite.md（agent 闭环）定向处理。

四类硬信号（A/B/C/D，多信号启发式，非单关键词，用"共现 / 聚类 / 结构"降低误报）：
  A. 亲密 / 身体暗示聚类：同一段落内出现 ≥2 个"亲密身体"token（贴近 / 耳畔 / 气息 /
     指尖 / 腰 / 压在 / 覆 / 缠绵 / 共枕 / 同榻 / 肌肤 / 体温 / 喘息 / 潮红 / 情动 /
     意乱 / 酥 / 凑近 / 鼻尖 / 唇 …），判为「疑似亲密暗示段落」。
  B. 情感边界模糊：出现"说不清的关系 / 介乎…之间 / 比恋人…比朋友 / 不只是朋友 /
     更像是家人 / 暧昧 / 纠缠不清 / 旧情 / 白月光 / 红颜 / 知心 / 共度良宵 / 心头朱砂"
     等，判为「情感边界模糊信号」。
  C. 多角结构（章节级强信号）：脚踏两条船 / 左拥右抱 / 众星捧月 / 周旋在…之间 /
     围着…转 / 他身边的女人 / 几房夫人 / 一妻多妾 / 三妻四妾 / 后宫 / 佳丽 / 红颜知己（们）
     等——直接 = 「潜在多角 / 暧昧结构」全书级告警。
  D. 未成年负面（价值观类，弱信号，仅提示核查）。

一类中置信软信号（E，交 LLM / agent 二次判定，不计入硬候选）：
  E. 暗示性留白：私密空间 token（闺房/深夜/独处/贴着…）+ 情感独占暗示 token
     （只对你/只有我们/除了你…）共现 → 疑似"只对你/只有我们"式暧昧独占。
     但历史/权谋小说里"深夜托付机密"也常命中，故标"中置信-待LLM判定"，
     由运行本 skill 的 agent（LLM）读上下文最终判断，不计入硬候选总数。

输出：控制台摘要 + --out report.md（按 章 → 候选段落 列出，A/B/C/D 为硬候选，E 单列待判定）。

用法:
  python semantic_scan.py <src.docx> [--out 语义风险报告.md]
"""
from errkit import safe_main
import argparse
import re
import sys
from collections import Counter, defaultdict

from docx import Document

try:
    from deai_deep_report import parse_chapters
except ImportError:  # 独立运行兜底
    from docx import Document as _D
    sys.path.insert(0, str(__file__).rsplit("\\", 1)[0].rsplit("/", 1)[0])
    from deai_deep_report import parse_chapters


# A. 亲密 / 身体暗示 token（分两类，聚类要求跨类 ≥2 个，降低单 token 误报）
TOUCH_A = ["贴近", "凑近", "耳畔", "耳侧", "鼻尖", "唇", "锁骨", "腰", "指尖",
           "气息", "体温", "压在", "覆", "缠绵", "缠绕", "共枕", "同榻", "肌肤",
           "依偎", "搂", "抱紧", "贴着", "抵在"]
TOUCH_B = ["喘息", "潮红", "情动", "意乱", "酥", "酥麻", "战栗", "轻颤", "微颤",
           "发烫", "灼热", "辗转", "耳语", "低喘", "闷哼"]

# B. 情感边界模糊
BOUNDARY = ["说不清的关系", "说不清道不明", "介乎", "比恋人", "比朋友", "不只是朋友",
            "更像是家人", "暧昧不清", "暧昧关系", "暧昧地", "纠缠不清", "纠缠在一起",
            "旧情", "白月光", "红颜", "知心", "共度良宵", "心头朱砂", "暧昧", "纠缠"]

# C. 多角结构强信号
MULTI = ["脚踏两条船", "脚踏三条船", "脚踏四条船", "左拥右抱", "众星捧月", "周旋在",
         "围着", "身边的女人", "身边的几个女人", "几房夫人", "一妻多妾", "三妻四妾",
         "后宫", "佳丽", "红颜知己", "红颜知己们", "各怀心思的女人", "女人缘",
         "齐人之福", "坐拥", "环肥燕瘦"]

# 未成年负面（价值观类，弱信号，仅提示核查）
MINOR_NEG = ["高中生", "初中生", "未成年人", "未成年", "幼女", "萝莉", "初中生女友",
             "高中生女友", "校园恋", "师生恋"]

# E. 暗示性软信号（中置信度，交 LLM / agent 二次判定，不计入硬候选）
# 私密空间 + 情感独占暗示 共现 → 疑似"只对你/只有我们"式暧昧独占关系，
# 但需结合上下文判断（可能只是托付机密/兄弟情），故单列待判定。
IMPLICIT_SPACE = ["闺房", "内室", "床榻", "帷帐", "帐中", "耳畔", "夜里", "深夜",
                  "独处", "无人", "密室", "沐浴", "温泉", "贴着", "贴近", "无人之时",
                  "四下无人", "屏退左右"]
IMPLICIT_EXCLUSIVE = ["只对你", "只有我们", "谁都不能", "瞒着", "除了你", "只属于",
                      "我们的秘密", "旁人不知", "无人知晓", "只对我说", "怎可与他人",
                      "只与你说", "唯独你", "独独你", "只同你"]


def scan_paragraph(text):
    """返回该段命中的信号列表 [(类型, 原因, 命中词)]。"""
    hits = []

    # A：亲密身体聚类（跨两类计数）
    a = sum(1 for t in TOUCH_A if t in text)
    b = sum(1 for t in TOUCH_B if t in text)
    if a + b >= 2:
        matched = [t for t in (TOUCH_A + TOUCH_B) if t in text]
        hits.append(("A.亲密暗示聚类",
                     f"同段出现 {a + b} 个亲密/身体 token（{','.join(matched[:6])}），"
                     "疑似亲密/身体暗示描写，需人工判断是否越界",
                     ",".join(matched[:6])))

    # B：情感边界模糊
    for w in BOUNDARY:
        if w in text:
            hits.append(("B.情感边界模糊", f"出现情感边界模糊表达「{w}」，疑似暧昧/多角信号", w))
            break

    # C：多角结构强信号
    for w in MULTI:
        if w in text:
            hits.append(("C.多角结构", f"出现多角/多女围一人结构信号「{w}」", w))
            break

    # 未成年负面（价值观，弱提示）
    for w in MINOR_NEG:
        if w in text:
            hits.append(("D.未成年负面", f"出现未成年相关表达「{w}」，需核查是否涉未成年负面导向", w))
            break

    # E：暗示性软信号（中置信度，交 LLM / agent 二次判定，不计入硬候选）
    has_space = any(w in text for w in IMPLICIT_SPACE)
    has_excl = any(w in text for w in IMPLICIT_EXCLUSIVE)
    if has_space and has_excl:
        ms = [w for w in IMPLICIT_SPACE if w in text][:2] + [w for w in IMPLICIT_EXCLUSIVE if w in text][:2]
        hits.append(("E.暗示性(中置信-待LLM判定)",
                     f"私密空间({ms[0] if ms else ''}) + 情感独占暗示({ms[-1] if ms else ''}) 共现，"
                     "疑似'只对你/只有我们'式暧昧独占；但需结合上下文判断"
                     "（历史/权谋小说里'深夜托付机密'也常命中，可能非越界）",
                     ",".join(ms)))

    return hits


def scan_docx(path, max_per_chapter=25):
    doc = Document(str(path))
    chapters = parse_chapters(doc)
    results = []  # (ch_title, hits_in_chapter)
    hard_counter = Counter()      # A/B/C/D 硬候选
    soft_counter = Counter()      # E 中置信软信号（不计入硬候选）
    for ch in chapters:
        body = "\n".join(ch["paras"])
        ch_hits = []
        for para in ch["paras"]:
            if not para.strip():
                continue
            for (typ, reason, word) in scan_paragraph(para):
                # 仅保留有意义的段落（避免整章标题误报）
                if len(para) < 6:
                    continue
                snippet = para if len(para) <= 80 else para[:80] + "…"
                is_soft = typ.startswith("E.")
                if is_soft:
                    soft_counter[typ] += 1
                else:
                    hard_counter[typ] += 1
                ch_hits.append((typ, reason, word, snippet, is_soft))
                if len(ch_hits) >= max_per_chapter:
                    break
        if ch_hits:
            results.append((ch["title"], ch_hits))
    return results, hard_counter, soft_counter, len(chapters)


def main():
    ap = argparse.ArgumentParser(description="深层语义风险扫描（WARN-only）")
    ap.add_argument("src", help="源 .docx")
    ap.add_argument("--out", help="输出报告 .md")
    args = ap.parse_args()

    results, hard_counter, soft_counter, nch = scan_docx(args.src)
    hard_total = sum(hard_counter.values())
    soft_total = sum(soft_counter.values())

    print("=" * 56)
    print("深层语义风险扫描（WARN-only，仅挖候选，不自动修改）")
    print("=" * 56)
    print(f"扫描章节: {nch}")
    print(f"硬候选(A/B/C/D): {hard_total}  | 中置信软信号(E,待LLM判定): {soft_total}")
    if hard_counter:
        print("  [硬候选]")
        for typ, c in hard_counter.most_common():
            print(f"    [{typ}] {c}")
    if soft_counter:
        print("  [中置信-待LLM判定]")
        for typ, c in soft_counter.most_common():
            print(f"    [{typ}] {c}")
    print("-" * 56)

    if args.out:
        lines = ["# 深层语义风险报告（WARN-only · 仅候选，需人工/L3 判定）", ""]
        lines.append("> 本扫描**不替你改任何字**。它把「暗示性多角关系/暧昧/亲密暗示/未成年负面」等"
                     "正则单点命不中的语义风险段落挖出来，供你按 `references/semantic_risk_sop.md`（人工）"
                     "或 `references/agent_semantic_rewrite.md`（agent 闭环）定向精修。是否越界由人工/LLM 判断。")
        lines.append("")
        lines.append(f"- 扫描章节：{nch}")
        lines.append(f"- 硬候选合计（A/B/C/D）：{hard_total}")
        lines.append(f"- 中置信软信号（E，待 LLM 判定，不计入硬候选）：{soft_total}")
        if hard_counter:
            lines.append("- 硬候选分布：" + "，".join(f"{t}={c}" for t, c in hard_counter.most_common()))
        if soft_counter:
            lines.append("- 中置信软信号分布：" + "，".join(f"{t}={c}" for t, c in soft_counter.most_common()))
        lines.append("")
        if not results:
            lines.append("✅ 未扫出明显语义风险候选（不代表绝对安全，仍建议人工抽读）。")
        for title, hits in results:
            lines.append(f"## {title}")
            lines.append("")
            for (typ, reason, word, snippet, is_soft) in hits:
                tag = "【中置信·待LLM判定】" if is_soft else "【硬候选】"
                lines.append(f"- **[{typ}]** {tag} {reason}")
                lines.append(f"  > 原文：{snippet}")
            lines.append("")
        open(args.out, "w", encoding="utf-8").write("\n".join(lines))
        print(f"报告已写出: {args.out}")
    else:
        # 控制台简要列出每章前几条
        for title, hits in results[:20]:
            soft_n = sum(1 for h in hits if h[4])
            print(f"· {title}（{len(hits)} 处，其中中置信 {soft_n}）")
            for (typ, reason, word, snippet, is_soft) in hits[:3]:
                print(f"    - [{typ}] {snippet[:40]}")


if __name__ == "__main__":
    safe_main(main)

