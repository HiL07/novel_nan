# -*- coding: utf-8 -*-
"""copyright_scan.py — 文本级版权风险扫描（WARN-only，辅助层）

封面 / 版权的"图片内容、跨库比对"脚本做不了（必须人确认，见
references/cover_copyright_checklist.md）。但**正文的文本侵权风险可以自动挖**——
本脚本扫出疑似侵权引用，交给用户 / 人工复核，把"完全帮不上忙"变成"至少把文本风险挖出来"。

五类信号（词库为示例性，非穷举；命中仅提示核查，不判定侵权）：
  1. 真人 / 明星 / 公众人物名（片段命中即 WARN）
  2. 知名 IP / 作品 / 游戏 / 动漫（王者荣耀 / 原神 / 火影 / 哈利波特 / 复联 / 迪士尼 / 甄嬛传 …）
  3. 歌词 / 诗文引用（显式标记"歌词/改编自/作词/原唱"，或长引含"演唱语境/现代歌词语气词"；
     普通古文/台词长引不误报）
  4. 同人 / 原作信号（同人 / 原作 / 番外·《X》/ crossover / 致敬《X》）
  5. 品牌商标（可口可乐 / 麦当劳 / 微信 / 抖音 …，片段命中提示核查）

输出：控制台摘要 + --out report.md（按 类别 → 候选 列出，附原文 + 原因，全部 WARN）。

用法:
  python copyright_scan.py <src.docx> [--out 版权风险报告.md]
"""
from errkit import safe_main
import argparse
import re
import sys
from collections import Counter

from docx import Document

try:
    from deai_deep_report import parse_chapters
except ImportError:
    sys.path.insert(0, str(__file__).rsplit("\\", 1)[0].rsplit("/", 1)[0])
    from deai_deep_report import parse_chapters


# 1. 真人 / 明星 / 公众人物（示例词库，按需扩充）
CELEBRITY = ["易烊千玺", "王一博", "肖战", "杨幂", "赵丽颖", "迪丽热巴", "刘亦菲",
             "周杰伦", "林俊杰", "陈奕迅", "成龙", "李连杰", "刘德华", "张学友",
             "特朗普", "拜登", "马斯克", "马云", "马化腾", "雷军", "董明珠"]

# 2. 知名 IP / 作品 / 游戏 / 动漫（示例词库）
IP = ["王者荣耀", "原神", "和平精英", "英雄联盟", "LOL", "火影忍者", "海贼王",
      "名侦探柯南", "哈利波特", " Harry Potter", "复仇者联盟", "复联", "漫威",
      "迪士尼", "皮克斯", "甄嬛传", "琅琊榜", "三体", "斗破苍穹", "盗墓笔记",
      "鬼吹灯", "庆余年", "诛仙", "仙剑奇侠传", "崩坏", "星穹铁道", "绝区零"]

# 4. 同人 / 原作信号
FAN_SIG = ["同人", "原作", "番外·", "crossover", "Crossover", "致敬《", "改编自《",
           "based on", "Based on"]

# 5. 品牌商标（示例词库；已剔除"小米/苹果/华为"等常见名词，避免谷物/水果/人名误报）
BRAND = ["可口可乐", "百事可乐", "麦当劳", "肯德基", "星巴克", "茅台", "微信",
         "抖音", "快手", "淘宝", "京东", "拼多多", "美团", "饿了么", "支付宝",
         "iPhone", "Nike", "Adidas", "路易威登", "LV"]

LYRIC_MARK = ["歌词", "作词", "作曲", "原唱", "改编自", "填词", "翻唱", "填词"]
# 长引被当歌词的约束：必须有显式引用标记，或现代歌词语气词（呀啊啦哟…）密集。
# 不用"哼/调子"等叙述词（"哼了一声""慢悠悠的调子"是普通叙述，非唱歌），
# 也不靠"演唱语境"——避免把古文的诗词/台词长引误炸。古典诗词用 兮/之乎者也，
# 不在下列语气词集，天然不命中（且本就多属公版，非版权关切）。
LYRIC_PARTICLE = set("呀啊啦哟哎呦喂咿喔嗬呐嘞喽喔呵")


def scan_paragraph(text):
    hits = []
    for w in CELEBRITY:
        if w in text:
            hits.append(("1.真人/明星名", f"出现公众人物名「{w}」，需核查是否未授权使用真人形象/姓名", w))
            break
    for w in IP:
        if w in text:
            hits.append(("2.知名IP/作品", f"出现知名 IP/作品名「{w}」，需核查是否侵权使用他人世界观/专有名词", w))
            break
    for w in BRAND:
        if w in text:
            hits.append(("5.品牌商标", f"出现品牌商标「{w}」，需核查是否未授权商业使用", w))
            break
    for w in FAN_SIG:
        if w in text:
            hits.append(("4.同人/原作信号", f"出现同人/原作信号「{w}」，需核查是否涉他人 IP", w))
            break
    # 3. 歌词 / 诗文引用
    flagged_lyric = False
    for mk in LYRIC_MARK:
        if mk in text:
            hits.append(("3.歌词/诗文引用", f"出现引用标记「{mk}」，疑似引用他人歌词/诗文，需核查授权与合理使用", mk))
            flagged_lyric = True
            break
    if not flagged_lyric:
        # 仅当长引含"现代歌词语气词密集"时才报，规避古文/台词长引误炸
        quotes = re.findall(r'[“"]([^”"]{30,})[”"]', text)
        if quotes:
            particles = sum(1 for q in quotes for ch in q if ch in LYRIC_PARTICLE)
            if particles >= 3:
                hits.append(("3.歌词/诗文引用",
                             f"出现疑似歌词长引用（{len(quotes)} 处，含歌词语气词），需核查授权",
                             quotes[0][:20] + "…"))
    return hits


def scan_docx(path, max_per_chapter=20):
    doc = Document(str(path))
    chapters = parse_chapters(doc)
    results = []
    type_counter = Counter()
    for ch in chapters:
        ch_hits = []
        for para in ch["paras"]:
            if len(para.strip()) < 4:
                continue
            for (typ, reason, word) in scan_paragraph(para):
                snippet = para if len(para) <= 80 else para[:80] + "…"
                ch_hits.append((typ, reason, word, snippet))
                type_counter[typ] += 1
                if len(ch_hits) >= max_per_chapter:
                    break
        if ch_hits:
            results.append((ch["title"], ch_hits))
    return results, type_counter, len(chapters)


def main():
    ap = argparse.ArgumentParser(description="文本级版权风险扫描（WARN-only）")
    ap.add_argument("src", help="源 .docx")
    ap.add_argument("--out", help="输出报告 .md")
    args = ap.parse_args()

    results, type_counter, nch = scan_docx(args.src)
    total = sum(type_counter.values())

    print("=" * 56)
    print("文本级版权风险扫描（WARN-only，仅挖候选，不判定侵权）")
    print("=" * 56)
    print(f"扫描章节: {nch}  | 命中候选: {total}")
    if type_counter:
        for typ, c in type_counter.most_common():
            print(f"  [{typ}] {c}")
    print("-" * 56)
    print("⚠ 封面图内容 / 跨库比对仍须人工确认（脚本做不到）。")

    if args.out:
        lines = ["# 文本级版权风险报告（WARN-only · 仅候选，需人工核查）", ""]
        lines.append("> 本扫描**不判定侵权**，只把正文里「疑似侵权引用」的片段挖出来供你核查。"
                     "封面图内容、跨库比对、授权确认等仍需人工（见 `references/cover_copyright_checklist.md`）。")
        lines.append("")
        lines.append(f"- 扫描章节：{nch}")
        lines.append(f"- 命中候选合计：{total}")
        if type_counter:
            lines.append("- 信号分布：" + "，".join(f"{t}={c}" for t, c in type_counter.most_common()))
        lines.append("")
        if not results:
            lines.append("✅ 未扫出明显文本版权风险候选（词库为示例，建议人工再抽读）。")
        for title, hits in results:
            lines.append(f"## {title}")
            lines.append("")
            for (typ, reason, word, snippet) in hits:
                lines.append(f"- **[{typ}]** {reason}")
                lines.append(f"  > 原文：{snippet}")
            lines.append("")
        open(args.out, "w", encoding="utf-8").write("\n".join(lines))
        print(f"报告已写出: {args.out}")
    else:
        for title, hits in results[:20]:
            print(f"· {title}（{len(hits)} 处）")
            for (typ, reason, word, snippet) in hits[:3]:
                print(f"    - [{typ}] {snippet[:40]}")


if __name__ == "__main__":
    safe_main(main)

