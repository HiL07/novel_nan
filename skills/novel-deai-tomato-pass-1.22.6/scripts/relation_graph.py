# -*- coding: utf-8 -*-
"""relation_graph.py — 人物亲密/情感关系图（自动定位多角关系，降低"人物关系需人判断"）

为什么有这个脚本：
  v1.10.0 的 agent 语义闭环虽让 agent 亲自改写，但"人物关系是否多角"仍靠 agent 通读全书的
  人工理解。本书有几十个角色时，人/agent 容易漏看某条暗线。本脚本把"谁和谁在亲密/暧昧语境里
  频繁共现"用**可枚举的信号**自动画成关系图，直接标出"≥2 个亲密对象"的多角高置信预警，
  让 agent 拿到图就能定向改写，不必自己从头梳理关系——把"人物关系处理"从纯人工降到"看图改"。

机制（WARN-only，绝不自动改字）：
  1. 角色名：优先用 --names 显式给（如从 build_map_wizard 的高频说话人取）；
     未给时做轻量自动探测（高频 2-3 字、且常作说话人/主语的 token）。
  2. 亲密/暧昧信号词库（INTIMATE）：出现即标记该段为"亲密语境"。
  3. 章节内上下文窗口：同一章里，若角色 A、B 都出现在亲密语境段（或相邻段），
     给边 (A,B) 加权重，并记录章节。
  4. 预警：任一角色亲密对象 ≥2 → 标记"多角关系高置信预警"（角色级 C 类），
     这类是审核最在意的"多女共侍/脚踏两条船"结构的直接证据。

注意：历史人物/群像小说里"君臣/战友/亲族"也会被共现，脚本**只报共现、不判越界**，
  最终是否越界、怎么改，由 agent 结合上下文（见 references/agent_semantic_rewrite.md）拍板。

用法:
  python relation_graph.py <src.docx> [--names 甲,乙,丙] [--out 09_relation.md]
"""
from errkit import safe_main
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

# 亲密/暧昧语境信号词（出现即标记该段为"亲密语境"）
INTIMATE = [
    "贴近", "气息", "耳畔", "耳旁", "唇", "腰", "腰间", "拥抱", "拥入", "挽", "挽住",
    "牵手", "牵起", "贴着", "贴了贴", "心跳", "意乱情迷", "暧昧", "脸颊", "红晕", "羞红",
    "酥", "吻", "轻吻", "柔情", "缠绵", "依偎", "相拥", "情愫", "倾心", "爱慕",
    "心动", "含情", "脉脉", "耳语", "额头相抵", "十指相扣", "环住", "搂", "搂住",
    "抚上", "指尖划过", "呼吸交错", "双眸含水",
]
INTIMATE_RE = re.compile("|".join(re.escape(w) for w in INTIMATE))

CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百千零0-9]+[章回卷节]")
# 轻量人名自动探测：仅接受 2-3 个纯汉字、且常作说话人/主语的 token；
# 用 [一-鿿]{2,3} 杜绝把引号/句号/代词碎片（如 "你 / 。"他）误当名字。
SPEAKER_TAIL = re.compile(r"([一-鿿]{2,3})(?:说道|说|道|问|笑|想|看|低声|轻声|沉声|喝道|怒道|回道|应道)")
# 单列字代词/常见虚词，避免被当作人名
NAME_DENY = {"他们", "她们", "我们", "你们", "自己", "此人", "其人", "此人", "将军", "主公",
             "陛下", "大人", "兄长", "兄弟", "手下", "众人", "将士", "士兵", "百姓", "使者"}
# 含这些字符的 2-3 字片段几乎都是动词/虚词（不知/回头/在旁/夏傲没…），排除掉
# 含这些字符的 2-3 字片段几乎都是动词/代词/虚词（或者/抬头/有人/他抬头/你知/夏傲没…），排除掉。
# 注意：刻意不含 大/小/多/少/新/旧/老/太/史/乔/黄 等可能作为真实人名首字的字符。
NAME_DENY_CHARS = set("或不没了的道说问道笑想看回在原本忽突渐显当自其如应沉轻低怒喝旁边长前中上下来去起出进对给让把被从向往到与和跟为因所能会要可该已正都也还又再却竟究知得着过头有他她我你们这那什怎后然便就才")


def parse_chapters(paras):
    """返回 [(章节标题, [段文本...])]，无标题段归到 '未分章'。"""
    chapters = []
    cur_title = "未分章"
    cur_paras = []
    for t in paras:
        t = t.strip()
        if not t:
            continue
        if CHAPTER_RE.match(t) and len(t) < 25:
            chapters.append((cur_title, cur_paras))
            cur_title = t
            cur_paras = []
        else:
            cur_paras.append(t)
    chapters.append((cur_title, cur_paras))
    return [c for c in chapters if c[1]]


def auto_detect_names(paras, top=12):
    """轻量人名探测：只取 2-3 纯汉字、且作为说话人高频出现、不在禁用名单里的 token。"""
    cnt = defaultdict(int)
    for t in paras:
        for m in SPEAKER_TAIL.finditer(t):
            nm = m.group(1)
            if (2 <= len(nm) <= 3 and nm not in NAME_DENY
                    and not any(ch in NAME_DENY_CHARS for ch in nm)):
                cnt[nm] += 1
    # 频率门槛：至少出现 3 次，避免偶发误抓
    return [n for n, c in sorted(cnt.items(), key=lambda x: -x[1]) if c >= 3][:top]


def build_graph(paras, names):
    chapters = parse_chapters(paras)
    edges = defaultdict(lambda: {"weight": 0, "chapters": set()})
    partner_of = defaultdict(set)  # name -> set(亲密对象)

    for title, cparas in chapters:
        # 标出本章每段是否亲密语境
        intimate_idx = {i for i, t in enumerate(cparas) if INTIMATE_RE.search(t)}
        # 角色出现位置
        appear = defaultdict(list)
        for i, t in enumerate(cparas):
            for nm in names:
                if nm and nm in t:
                    appear[nm].append(i)
        # 对每对角色，检查是否在同一亲密语境段或相邻段共现
        for a in names:
            for b in names:
                if a >= b:
                    continue
                ai = appear.get(a, [])
                bi = appear.get(b, [])
                hit = False
                for i in ai:
                    # a 在亲密段，且 b 在同段或邻近(±1)段
                    if i in intimate_idx:
                        if any(abs(j - i) <= 1 for j in bi):
                            hit = True
                            break
                    # 或 b 在亲密段且 a 邻近
                    elif any(j in intimate_idx and abs(j - i) <= 1 for j in bi):
                        hit = True
                        break
                if hit:
                    key = (a, b)
                    edges[key]["weight"] += 1
                    edges[key]["chapters"].add(title)
                    partner_of[a].add(b)
                    partner_of[b].add(a)

    return edges, partner_of, len(chapters)


def check(src, names=None, out_md=None):
    from docx import Document
    d = Document(src)
    paras = [p.text for p in d.paragraphs]
    if not names:
        names = auto_detect_names(paras)
    names = [n for n in names if n]

    edges, partner_of, nch = build_graph(paras, names)

    # 多角预警：亲密对象 ≥2
    flagged = {n: sorted(ps) for n, ps in partner_of.items() if len(ps) >= 2}

    lines = ["# 人物亲密关系图（自动检测 · WARN-only）", ""]
    lines.append(f"- 角色来源: {'显式给定' if names else '自动探测(前若干高频说话人)'}")
    lines.append(f"- 检测角色数: {len(names)} ｜ 章节数: {nch}")
    lines.append(f"- 亲密语境边(共现)数: {len(edges)}")
    lines.append("")
    lines.append("> 本图只报「谁和谁在亲密/暧昧语境里频繁共现」，**不判越界、不改字**。")
    lines.append("> 历史人物/群像里君臣、战友、亲族也会共现，是否构成审核意义上的多角关系，")
    lines.append("> 由 agent 结合上下文（见 references/agent_semantic_rewrite.md）拍板。")
    lines.append("")

    if flagged:
        lines.append("## 🔴 多角关系高置信预警（亲密对象 ≥2）")
        lines.append("")
        for n, ps in sorted(flagged.items(), key=lambda x: -len(x[1])):
            lines.append(f"- **{n}**：亲密对象 {len(ps)} 人 → {', '.join(ps)}")
        lines.append("")
        lines.append("> 这类是审核最在意的「多女共侍 / 脚踏两条船」结构的直接证据，")
        lines.append("> agent 应优先据此收束为单配偶 + 合伙人（见 agent_semantic_rewrite.md 原则三/四）。")
        lines.append("")
    else:
        lines.append("## ✅ 未检出多角关系高置信预警")
        lines.append("")
        lines.append("> 没有角色同时与 ≥2 人落入亲密语境。但软信号（暗示性留白）仍需 agent 读上下文兜底。")
        lines.append("")

    if edges:
        lines.append("## 亲密共现边明细")
        lines.append("")
        lines.append("| 角色A | 角色B | 共现强度 | 涉及章节 |")
        lines.append("|---|---|---|---|")
        for (a, b), info in sorted(edges.items(), key=lambda x: -x[1]["weight"]):
            chs = "、".join(sorted(info["chapters"]))[:80]
            lines.append(f"| {a} | {b} | {info['weight']} | {chs} |")
        lines.append("")

    text = "\n".join(lines)
    if out_md:
        Path(out_md).write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[summary] 角色={len(names)} 边={len(edges)} 多角预警={len(flagged)}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="人物亲密关系图自动检测")
    ap.add_argument("src", help="源 .docx")
    ap.add_argument("--names", help="角色名列表，逗号分隔（如 甲,乙,丙）。不填则自动探测")
    ap.add_argument("--out", help="报告输出 .md 路径")
    args = ap.parse_args()
    names = [n.strip() for n in args.names.split(",")] if args.names else None
    check(args.src, names, args.out)


if __name__ == "__main__":
    safe_main(main)

