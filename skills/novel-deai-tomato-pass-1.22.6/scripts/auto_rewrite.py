# -*- coding: utf-8 -*-
"""auto_rewrite.py — 去 AI 味自动改写层（流水线 L2.5）

定位：在 L1 机械层(deai_humanizer) 跑完、L2 诊断层(deai_deep_report) 定位问题之后，
对诊断报告里【可安全自动修复】的模式做真实改写（不是删词，是改写句子），
把人工精修(L3) 的工作量降到最低。改写前后复用 deai_deep_report 的九项指标做量化对比，
让用户一眼看到"自动化到底修了多少"。

可自动修复（保证不丢语义、不破句、可 diff 复核）：
  A. 扩展填充词：覆盖 L1 漏掉的 AI 填充词（就在这时/顿时/瞬间/刹那间/恍然大悟/微微一笑/
     轻轻叹了口气/嘴角微微上扬/似乎/仿佛/不禁/不由得/下意识地/鬼使神差地/莫名地/那一刻/恍惚间/
     一丝+情绪/一股暖流涌上心头…）
  B. 情绪直陈→行为微描写（tell-not-show）：感到/觉得/涌起 + 情绪名词 → 具身动作
     （如 愤怒→攥紧了拳，指节发白；烦躁→揉了揉眉心），直接攻击 L2 第 2 项（情绪词库 40+）
  C. 对话标签去烂副词：淡淡地说/冷冷地道/微微一笑道 → 说/道（保说话人、去 AI 腔），
     攻击 L2 第 1 项的"机器腔"
  D. 陈词比喻替换：固定常见 AI 比喻 → 具体描写（字典 20+，仅精确匹配），攻击 L2 第 3 项
  E. 套路转场变化：与此同时/另一边/此时此刻 → 轮换候选池，破模板感，攻击 L2 第 5 项
  （五类规则互相独立且幂等，支持自迭代定点循环：一次调用反复跑直到无更多可修，
   把规则能覆盖的机械型 AI 味修到极限，再交给 L3 人工接手剩下的章）

不可自动修复（继续走 L3 人工，见 references/manual_fix_sop.md / llm_rewrite_sop.md）：
  - 跨角色口头禅趋同（L2 第 8 项，需给每人设语癖，语义级）
  - 段落同构 / 章尾套路（L2 第 6/7 项，影响节奏，需人判断）
  - 过度平滑 / 作者声纹缺失（L2 第 9 项，需注入口语毛刺/刻意卡壳/稳定语癖，见 llm_rewrite_sop 模式六）
  - 语义层多女信号 / 人物关系连贯 / 剧情删改 / 听感（manual_fix_sop 场景 A-D）

用法:
  python auto_rewrite.py <src.docx> <out.docx> [--dry-run]
  --dry-run  只打印每处改动的 old→new 与前后评分，不写文件
输出: 控制台 before/after AI 味评分（MUST/WARN 合计）+ 五类改写统计
"""
from errkit import safe_main
import argparse
import os
import re
import sys
from collections import Counter

from docx import Document

# ----------------------------------------------------------------------------
# A. 扩展填充词（L1 漏掉的 AI 痕迹；str 为精确子串，含正则的用 tuple(re, repl)）
# ----------------------------------------------------------------------------
EXTRA_FILLER = [
    ("就在这时，", ""),
    ("就在这时", ""),
    ("顿时", ""),
    ("瞬间", ""),
    ("刹那间", ""),
    ("恍然大悟", "明白过来"),
    ("微微一笑", "笑了笑"),
    ("轻轻叹了口气", "叹了口气"),
    ("嘴角微微上扬", "嘴角一扬"),
    ("似乎", ""),
    ("仿佛", ""),
    ("不禁", ""),
    ("禁不住", ""),
    ("不由得", ""),
    ("下意识地", ""),
    ("鬼使神差地", ""),
    ("不知不觉地", ""),
    ("莫名地", ""),
    ("莫名有种", "有种"),
    ("那一刻，", ""),
    ("那一刻", ""),
    ("恍惚间", ""),
    ("只觉得", "只觉"),
    (r"一丝(的)?(不安|犹豫|恐惧|落寞|无奈|酸楚|苦涩|凉意|寒意|伤感)", r"\2"),
    (r"一股(莫名的)?(暖流|寒意|酸涩|凉意)涌上(心头|心间)", r"胸口\2一热"),
]

# ----------------------------------------------------------------------------
# B. 情绪直陈 → 行为微描写（tell-not-show 自动化）
# ----------------------------------------------------------------------------
EMO_MAP = {
    "愤怒": "攥紧了拳，指节发白",
    "生气": "皱起眉",
    "悲伤": "垂下眼，半晌没作声",
    "难过": "别开脸",
    "开心": "眉眼松了下来",
    "高兴": "嘴角动了动",
    "惊讶": "瞳孔一缩",
    "震惊": "僵在原地",
    "害怕": "往后退了半步",
    "恐惧": "呼吸一滞",
    "紧张": "喉头发紧",
    "尴尬": "摸了摸鼻尖",
    "温柔": "声音放轻了些",
    "失落": "肩头塌了下去",
    "感动": "鼻尖一酸",
    "委屈": "咬住下唇",
    "无奈": "摇了摇头",
    "绝望": "整个人像被抽空了力气",
    "痛苦": "闷哼一声",
    "幸福": "眼底软了下来",
    "喜悦": "眼睛亮了一瞬",
    "兴奋": "手心发热",
    "激动": "声音发颤",
    "羞愧": "耳根烧了起来",
    "懊悔": "攥紧了衣角",
    "孤独": "抱紧了膝盖",
    "寂寞": "望着窗外出神",
    "心酸": "喉头哽住",
    "释然": "长长舒了口气",
    "欣慰": "眼底软了下来",
    "迷茫": "眼前一阵发空",
    "烦躁": "揉了揉眉心",
    "释怀": "呼出一口浊气",
    "满足": "眯起眼",
    "嫉妒": "别开视线",
    "羡慕": "多看了两眼",
    "不安": "指尖无意识敲着桌沿",
    "期待": "身子微微前倾",
    "后悔": "抿紧了唇",
    "心疼": "指尖颤了颤",
    "愧疚": "垂下眼",
    "释然": "长长舒了口气",
    "恼火": "眉头拧成结",
    "困惑": "眉头微蹙",
    "好奇": "凑近了些",
    "疲惫": "揉了揉太阳穴",
    "松了口气": "肩膀松了下来",
    "不甘": "咬了咬牙",
    "酸涩": "喉头哽了哽",
}
_EMO_ALT = "|".join(re.escape(e) for e in sorted(EMO_MAP, key=len, reverse=True))
_EMO_RE = re.compile(
    r"(?<![\u4e00-\u9fff])"  # 主语不能以汉字紧邻开头，避免吃进前句
    r"(?P<subj>(?:他|她|我|你|[\u4e00-\u9fff]{1,4})?)"
    r"(?P<pre>(?:心中|心里|心头|心底|内心里)?)"
    r"(?P<verb>感到|感觉到|觉得|觉着|涌起(?:一丝|一阵|一股)?|泛起(?:一丝|一阵)?)"
    r"(?P<opt>很|非常|十分|格外|有些|有点|一阵)?"
    r"(?P<emo>" + _EMO_ALT + r")"
)

# ----------------------------------------------------------------------------
# C. 对话标签去烂副词（保说话人、去 AI 腔）
# ----------------------------------------------------------------------------
_TAG_ADV = (r"淡淡|冷冷|微微|轻轻|缓缓|深深|无奈|苦笑|无声|默默|失笑|木然|"
            r"淡淡地|冷冷地|微微地|轻轻地|缓缓地|深深地|无声地|木然地")
_TAG_RE = re.compile(
    r"(?P<subj>[\u4e00-\u9fff]{1,4})"
    r"(?P<adv>" + _TAG_ADV + r")"
    r"(?P<v>地说|地道|说道|道|一笑道|应道|回道|喊道)"
)

# ----------------------------------------------------------------------------
# D. 陈词比喻替换（仅精确匹配，避免误伤；攻击 L2 第 3 项）
# ----------------------------------------------------------------------------
SIMILE_FIX = {
    "像一潭死水": "了无生气",
    "像一潭死水般沉默": "一片死寂",
    "像一潭死水般闷热": "闷得人发慌",
    "像一只温顺的小猫": "乖巧地蜷着",
    "像一只受惊的小鹿": "惊得往后一缩",
    "像一朵栀子花": "素净得像栀子",
    "像一尊雕塑": "僵在原地",
    "像一只斗败的公鸡": "蔫了下去",
    "像踩了尾巴的猫": "炸了毛",
    "像吞了苍蝇": "脸色一僵",
    "像被雷劈": "整个人僵住",
    "像见了鬼": "猛地一哆嗦",
    "像一头发怒的狮子": "吼了一声",
    "像一只饿狼": "眸光一沉",
    "像块木头": "僵着没动",
    "像根木头": "愣在原地",
    "像霜打的茄子": "蔫了下去",
    "像热锅上的蚂蚁": "来回踱步",
    "像只鸵鸟": "把头埋得更低",
    "像中了邪": "愣了半晌",
    "像团棉花": "软绵绵提不起劲",
    "像一尊佛": "一动不动",
    "像只斗败的公鸡": "蔫了下去",
    "像踩了尾巴的猫": "炸了毛",
    "像吞了苍蝇": "脸色一僵",
}

# ----------------------------------------------------------------------------
# E. 套路转场变化（轮换候选池，破模板感；攻击 L2 第 5 项）
# ----------------------------------------------------------------------------
TRANS_FIX = {
    "与此同时": ["同一时刻，", "那时，", "就在此刻，", "这头，"],
    "另一边": ["同一时间，", "话分两头，", "那厢，"],
    "此时此刻": ["此刻，", "这时，", "当下，"],
}
_TRANS_RE = re.compile(r"(?:" + "|".join(re.escape(k) for k in TRANS_FIX) + r")[，,]?")
_trans_counters = {k: 0 for k in TRANS_FIX}


def _emo_repl(m):
    subj = m.group("subj")
    return (subj if subj else "") + EMO_MAP[m.group("emo")]


def _tag_repl(m):
    return m.group("subj") + "说"


def _trans_repl(m):
    key = m.group(0).rstrip("，,")
    pool = TRANS_FIX[key]
    idx = _trans_counters[key] % len(pool)
    _trans_counters[key] += 1
    return pool[idx]


def rewrite_paragraph(text, stats):
    """对单段应用五类改写，累计统计。返回新文本。"""
    new = text
    # C. 对话标签去烂副词（先于 A，避免"微微一笑道"先被拆成"笑了笑道"）
    new, n = _TAG_RE.subn(_tag_repl, new)
    if n:
        stats["C_tag_deadv"] += n
    # A. 扩展填充词（模式均为中文/无正则元字符，直接作正则子串即可）
    for pat, rep in EXTRA_FILLER:
        new, n = re.subn(pat, rep, new)
        if n:
            stats["A_ext_filler"] += n
    # B. 情绪直陈 → 行为
    new, n = _EMO_RE.subn(_emo_repl, new)
    if n:
        stats["B_tell_to_show"] += n
    # D. 陈词比喻替换（长匹配优先，避免短词截断长词）
    for sim in sorted(SIMILE_FIX, key=len, reverse=True):
        rep = SIMILE_FIX[sim]
        if sim in new:
            new = new.replace(sim, rep)
            stats["D_simile"] += 1
    # E. 套路转场轮换
    new, n = _TRANS_RE.subn(_trans_repl, new)
    if n:
        stats["E_transition"] += n
    return new


# ----------------------------------------------------------------------------
# 评分：复用 deai_deep_report 的章节解析 + 九项检测
# ----------------------------------------------------------------------------
def _score_doc(target):
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from deai_deep_report import parse_chapters, check_chapter  # noqa
    except Exception as e:  # 评分是锦上添花，失败不阻断改写
        return None, None, str(e)
    doc = Document(target) if isinstance(target, str) else target
    chs = parse_chapters(doc)
    if not chs:
        return 0, 0, {}
    cat = Counter()
    for ch in chs:
        iss, _ = check_chapter(ch)
        for lv, c, _ in iss:
            cat[f"{lv}:{c}"] += 1
    return sum(cat.values()), len(chs), cat


def main():
    ap = argparse.ArgumentParser(description="去 AI 味自动改写层（L2.5）")
    ap.add_argument("src", help="源 .docx")
    ap.add_argument("dst", nargs="?", help="输出 .docx（省略则仅 --dry-run 打印）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印改动 diff 与前后评分，不写文件")
    ap.add_argument("--max-pass", type=int, default=2,
                    help="自迭代定点循环最大轮数（默认 2：首轮改写+一轮收尾，抓住规则间相互触发）")
    ap.add_argument("--no-iter", action="store_true",
                    help="关闭自迭代，只跑一轮（结果确定、易断言，测试用）")
    args = ap.parse_args()

    doc = Document(args.src)
    before_total, before_ch, before_cat = _score_doc(args.src)

    stats = Counter()
    # 记录原文；doc.paragraphs 每次访问返回新 wrapper，故只取一次并复用同一批对象，
    # 保证 id() 稳定、diff 配对准确
    paras = list(doc.paragraphs)
    originals = {}
    for para in paras:
        if para.text.strip():
            originals[id(para)] = para.text

    max_pass = 1 if args.no_iter else max(1, args.max_pass)
    for _pass in range(max_pass):
        changed_any = False
        for para in paras:
            if not para.text.strip():
                continue
            new = rewrite_paragraph(para.text, stats)
            if new != para.text:
                changed_any = True
                style = para.style
                align = para.alignment
                para.clear()
                para.add_run(new)
                para.style = style
                para.alignment = align
        if not changed_any:
            break

    diffs = [(originals[id(p)], p.text)
             for p in paras if id(p) in originals and p.text != originals[id(p)]]

    after_total, after_ch, after_cat = _score_doc(doc)

    # 控制台摘要
    print("=" * 56)
    print("自动改写层（L2.5）执行结果")
    print("=" * 56)
    print(f"改动段落数 : {len(diffs)}")
    print("五类改写统计:")
    labels = {
        "A_ext_filler": "A 扩展填充词",
        "B_tell_to_show": "B 情绪直陈→行为",
        "C_tag_deadv": "C 对话标签去烂副词",
        "D_simile": "D 陈词比喻替换",
        "E_transition": "E 套路转场轮换",
    }
    for k, lab in labels.items():
        if stats[k]:
            print(f"  - {lab}: {stats[k]} 处")
    if before_total is not None:
        delta = after_total - before_total
        print("-" * 56)
        print(f"AI 味评分(九项 MUST+WARN 合计): {before_total} → {after_total} "
              f"({'减少' if delta < 0 else '增加' if delta > 0 else '持平'} {abs(delta)})")
        if delta > 0:
            print("  ⚠ 评分上升：可能触发了未覆盖的模式，请人工复核 diff。")
    else:
        print("-" * 56)
        print(f"（评分不可用：{after_ch}）")

    if args.dry_run or not args.dst:
        print("-" * 56)
        print(f"DIFF（原文 → 终稿，共 {len(diffs)} 处，--dry-run 不写文件）:")
        for old, new in diffs[:40]:
            print(f"  - {old}\n  + {new}")
        if len(diffs) > 40:
            print(f"  …（其余 {len(diffs) - 40} 处省略）")
        return

    doc.save(args.dst)
    print(f"\n已写出: {args.dst}")


if __name__ == "__main__":
    safe_main(main)

