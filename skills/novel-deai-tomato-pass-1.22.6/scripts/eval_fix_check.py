#!/usr/bin/env python
"""eval_fix_check.py — 番茄推荐评估不过：机械层检测 + 逐章修改清单生成

按 references/tomato_eval_fix.md 的硬性基础规则扫描 .docx 小说：
  1. 章节字数 1500-3000（短章/长章标记）
  2. 单章对话占比 ≤40%（引号行汉字 / 全章汉字）
  3. 段落长度：超长段（>150 汉字，约 4+ 行）标记
  4. 章节长度稳定性：全书均值 ±60% 带宽外标记（节奏崩坏信号）
  5. 开篇钩子：第 1-3 章前 300 字含世界观堆砌词且无冲突标记时警告
  6. 标点规范：双逗号、省略号滥用（每章 >3 次）
  7. 红线低质词扫描（他想起/嘴角微微/似乎 等高频 AI 词）

输出：控制台报告 + 可选 --out report.md（逐章修改清单，可直接照着改）

用法:
  python eval_fix_check.py <src.docx> [--out report.md]
"""
from errkit import safe_main
import argparse
import re
import sys
from collections import Counter

from docx import Document

HAN = re.compile(r'[\u4e00-\u9fff]')

# 世界观堆砌信号词（开篇 300 字内出现即扣分）
WORLDBUILD_WORDS = ['大陆', '位面', '修炼等级', '等级体系', '修炼体系', '世界观', '设定',
                    '分为九', '分为三', '分为五', '九州', '王朝林立', '宗门林立']
# 冲突/钩子标记词（出现即视为有钩子）
HOOK_WORDS = ['死', '杀', '血', '退婚', '背叛', '危机', '追杀', '陷害', '重生', '穿越',
              '爆发', '怒', '崩溃', '秘密', '系统', '金手指', '当场', '逼', '债', '欺']

# 高频 AI 低质词（机械层）
AI_WORDS = ['他想起', '嘴角微微', '意味深长', '就在这时', '恍然大悟', '不禁', '一丝',
            '似乎', '仿佛', '顿时', '瞬间']

DIALOGUE_QUOTES = '\u201c\u201d\u300c\u300d\u2018\u2019"'

# 双逗号 / 省略号
DOUBLE_COMMA = re.compile(r'，，|,,')
ELLIPSIS = re.compile(r'……|\.\.\.')


CN_NUM = {'零': 0, '〇': 0, '一': 1, '两': 2, '二': 2, '三': 3, '四': 4,
          '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}


def cn_to_int(s: str) -> int:
    """中文数字（支持到百位，如 十二/二十三/一百零八）转 int。"""
    total, num = 0, 0
    for ch in s:
        if ch in CN_NUM:
            num = CN_NUM[ch]
        elif ch == '十':
            num = 1 if num == 0 else num
            total += num * 10
            num = 0
        elif ch == '百':
            num = 1 if num == 0 else num
            total += num * 100
            num = 0
    return total + num


def parse_chapter_heading(text: str):
    """识别 '第N章' 标题（阿拉伯数字或中文数字），返回 (章号, 标题) 或 None。"""
    m = re.match(r'^第\s*(\d+)\s*章\s*(.*)', text)
    if m:
        return int(m.group(1)), text
    m = re.match(r'^第\s*([零〇一二两三四五六七八九十百]+)\s*章\s*(.*)', text)
    if m:
        return cn_to_int(m.group(1)), text
    return None


def han_count(text: str) -> int:
    return len(HAN.findall(text))


def parse_chapters(doc):
    """按段落切章：以 '第N章' 开头的段落视为章标题（支持中文数字）。"""
    chapters = []
    cur_num, cur_title, cur_paras = None, None, []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        head = parse_chapter_heading(text)
        if head:
            if cur_num is not None:
                chapters.append((cur_num, cur_title, cur_paras))
            cur_num, cur_title, cur_paras = head[0], head[1], [text]
        elif cur_num is not None:
            cur_paras.append(text)
    if cur_num is not None:
        chapters.append((cur_num, cur_title, cur_paras))
    return chapters


def check_chapter(num, title, paras):
    """返回该章问题列表（每条：级别、类别、描述）。"""
    issues = []
    body = paras[1:] if len(paras) > 1 else []
    full_text = ''.join(paras)
    han = han_count(full_text)

    # 1. 字数
    if han < 1500:
        issues.append(('MUST', '字数不足', f'纯汉字 {han} < 1500，需扩写补冲突（非补描写）'))
    elif han > 3000:
        issues.append(('MUST', '字数超标', f'纯汉字 {han} > 3000，需砍灌水或拆章'))

    # 2. 对话占比
    dial_han = 0
    for p in body:
        if any(q in p for q in DIALOGUE_QUOTES):
            dial_han += han_count(p)
    if han > 0:
        ratio = dial_han / han
        if ratio > 0.40:
            issues.append(('MUST', '对话超标', f'对话占比 {ratio:.0%} > 40%，砍无效对白'))

    # 3. 超长段
    long_paras = [p for p in body if han_count(p) > 150]
    if long_paras:
        issues.append(('WARN', '超长段落', f'{len(long_paras)} 段超过 150 汉字（约4行+），切分为 2-3 段'))

    # 6. 标点
    double_comma = len(DOUBLE_COMMA.findall(full_text))
    ellipsis = len(ELLIPSIS.findall(full_text))
    if double_comma:
        issues.append(('MUST', '标点错误', f'双逗号 {double_comma} 处'))
    if ellipsis > 3:
        issues.append(('WARN', '省略号滥用', f'省略号 {ellipsis} 次（建议每章 ≤3）'))

    # 7. AI 低质词
    hits = {w: full_text.count(w) for w in AI_WORDS if w in full_text}
    if hits:
        detail = '、'.join(f'{w}×{c}' for w, c in sorted(hits.items(), key=lambda x: -x[1]))
        issues.append(('MUST', 'AI低质词', detail))

    return issues, han


def check_opening_hook(chapters):
    """前三章开篇 300 字钩子检查，返回问题列表。"""
    issues = []
    for num, title, paras in chapters[:3]:
        body = ''.join(paras[1:4])[:300]  # 前3段、前300字
        if not body:
            issues.append(('MUST', '开篇钩子', f'第{num}章正文为空'))
            continue
        has_worldbuild = any(w in body for w in WORLDBUILD_WORDS)
        has_hook = any(w in body for w in HOOK_WORDS)
        if has_worldbuild and not has_hook:
            issues.append(('MUST', '开篇钩子',
                           f'第{num}章前300字疑似世界观堆砌（{[w for w in WORLDBUILD_WORDS if w in body]}）且无冲突标记——设定改为事件中展示'))
        elif not has_hook:
            issues.append(('WARN', '开篇钩子',
                           f'第{num}章前300字未检出冲突/金手指标记，人工确认是否够抓人'))
    return issues


def main():
    ap = argparse.ArgumentParser(description='番茄推荐评估机械层检测')
    ap.add_argument('src', help='源 .docx 文件')
    ap.add_argument('--out', help='输出修改清单 markdown 路径（可选）')
    args = ap.parse_args()

    doc = Document(args.src)
    chapters = parse_chapters(doc)
    if not chapters:
        print('未检出任何章节（未找到 "第N章" 标题段），退出。')
        sys.exit(1)

    # 全书统计
    hans = []
    all_issues = []  # (章号, 标题, [(级别,类别,描述), ...])
    for num, title, paras in chapters:
        issues, han = check_chapter(num, title, paras)
        hans.append(han)
        all_issues.append((num, title, issues, han))

    avg = sum(hans) / len(hans)
    opening_issues = check_opening_hook(chapters)

    # 4. 章节长度稳定性
    for (num, title, issues, han) in all_issues:
        if han < avg * 0.4:
            issues.append(('WARN', '节奏崩坏', f'章节 {han} 字 vs 全书均值 {avg:.0f} 字（<40%），忽短信号'))
        elif han > avg * 1.6:
            issues.append(('WARN', '节奏崩坏', f'章节 {han} 字 vs 全书均值 {avg:.0f} 字（>160%），忽长信号'))

    # ---- 控制台摘要 ----
    must_cnt = sum(1 for _, _, iss, _ in all_issues for lv, _, _ in iss if lv == 'MUST')
    warn_cnt = sum(1 for _, _, iss, _ in all_issues for lv, _, _ in iss if lv == 'WARN')
    op_must = sum(1 for lv, _, _ in opening_issues if lv == 'MUST')
    print(f'章节总数: {len(chapters)} | 全书均值: {avg:.0f} 汉字/章')
    print(f'开篇钩子问题: {len(opening_issues)} | 章内必修: {must_cnt} | 章内建议: {warn_cnt}')
    print(f'必修项合计: {must_cnt + op_must} | 建议项合计: {warn_cnt + len(opening_issues) - op_must}')
    print()

    cat_counter = Counter()
    for _, _, iss, _ in all_issues:
        for lv, cat, _ in iss:
            cat_counter[f'{lv}:{cat}'] += 1
    for lv, cat, _ in opening_issues:
        cat_counter[f'{lv}:{cat}'] += 1
    print('问题分布:')
    for key, cnt in cat_counter.most_common():
        print(f'  {key}: {cnt}')
    print()

    # ---- 修改清单 ----
    lines = ['# 番茄推荐评估 修改清单', '',
             f'> 源文件: `{args.src}`',
             f'> 章节: {len(chapters)} | 均值: {avg:.0f} 汉字/章 | 必修: {must_cnt + op_must} | 建议: {warn_cnt + len(opening_issues) - op_must}',
             '', '## 一、开篇钩子（前三章，最优先）', '']
    for lv, cat, desc in opening_issues:
        lines.append(f'- **[{lv}] {cat}**：{desc}')
    if not opening_issues:
        lines.append('- ✓ 前三章开篇未检出机械层问题（人工再确认冲突是否前置）')

    lines += ['', '## 二、逐章问题清单（按章节顺序）', '']
    for num, title, iss, han in all_issues:
        if not iss:
            continue
        lines.append(f'### {title} （{han} 汉字）')
        for lv, cat, desc in iss:
            lines.append(f'- **[{lv}] {cat}**：{desc}')
        lines.append('')

    lines += ['', '## 三、修改动线（照此执行）', '',
              '1. 先修 MUST 项（格式+安全+AI词）——机械层可自动处理',
              '2. 重写前三章开篇钩子（冲突/金手指前置到前300字）',
              '3. 砍对话超标章的无效对白，补短章核心冲突',
              '4. 对照避坑雷区复查：低质AI文/结构空洞/节奏崩坏/可读性差',
              '5. 详见 references/tomato_eval_fix.md']

    report = '\n'.join(lines)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f'修改清单已写入: {args.out}')
    else:
        print('--- 修改清单 ---')
        print(report)


if __name__ == "__main__":
    safe_main(main)

