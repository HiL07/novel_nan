# -*- coding: utf-8 -*-
"""deai_deep_report.py — 深层 AI 味逐章诊断（去AI味流水线 L2 层）

deai_humanizer.py（L1 机械层）跑完后，深层 AI 味（角色声纹趋同、节奏均匀、
tell 而非 show、安全比喻、套路转场）依然残留。本脚本把这些问题**定位到章**，
输出分数 + 修改清单，供 L3 逐章精修轮次定向重写，而不是盲改。

检测维度（每章打分，全书汇总排序）：
  1. 对话标签滥用：说话标签（X说/X道/问道/笑道）行 / 对话行占比，>30% 标记
  2. 情绪直陈密度（tell-not-show）：情绪名词直接命名（愤怒/悲伤/感动…）/ 千字
  3. 安全比喻密度：仿佛/犹如/宛若/如同/像…一样 / 千字
  4. AI 填充词密度：不禁/似乎/顿时/瞬间/嘴角微微… / 千字
  5. 套路转场：与此同时/另一边/此时此刻 出现次数
  6. 段落节奏均匀度：段长标准差 / 均值（变异系数 <0.4 = 同构严重，机器节奏信号）
  7. 章尾套路：以反问/感叹/省略号收尾（连续多章同款 = 模板感）
  8. 角色口头禅趋同：全书对话中重复 ≥5 次的 4-8 字台词片段（各角色共享 = 声纹趋同）
  9. 过度平滑 / 作者声纹缺失：对照平台"质量审查"维度——AI 文字往往"过度平滑"，
     缺作者口头禅、缺故意的"卡壳"。代理指标：毛刺密度（语气词+破折号+句内省略号+
     超短句）/千字 <1.0 → WARN；整章零语气词（han>300）→ 作者声纹缺失 WARN。

输出：控制台摘要 + --out report.md 逐章修改清单（MUST/WARN 两级）。

用法:
  python deai_deep_report.py <src.docx> [--out 深层AI味报告.md]
"""
from errkit import safe_main
import argparse
import re
import sys
from collections import Counter

from docx import Document

HAN = re.compile(r'[\u4e00-\u9fff]')

CN_NUM = {'零': 0, '〇': 0, '一': 1, '两': 2, '二': 2, '三': 3, '四': 4,
          '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}

# 情绪直陈（tell-not-show）：作者直接命名情绪而非用行为体现
EMOTION_WORDS = ['愤怒', '悲伤', '开心', '高兴', '惊讶', '震惊', '恐惧', '害怕', '紧张',
                 '尴尬', '温柔', '失落', '感动', '委屈', '无奈', '绝望', '痛苦', '幸福',
                 '喜悦', '兴奋', '激动', '羞愧', '懊悔', '孤独', '寂寞', '心酸', '释然']

# 安全比喻连接词
SIMILE_WORDS = ['仿佛', '犹如', '宛若', '如同', '一样', '似的']

# AI 填充/低质词（与 eval_fix_check.py / humanizer_banned.md 对齐的子集）
AI_FILLER = ['不禁', '忍不住', '下意识', '不由自主', '情不自禁', '深吸一口气',
             '心中涌起', '心头一震', '不由得', '嘴角微微', '意味深长', '似乎',
             '顿时', '瞬间', '一丝', '恍然大悟', '就在这时']

# 套路转场
TRANSITION = ['与此同时', '另一边', '此时此刻', '与此同时']

# 说话标签（用于对话标签滥用统计）
TAG_RE = re.compile(r'[\u4e00-\u9fff]{1,4}(?:冷冷|淡淡|微微|轻轻|缓缓)?'
                    r'(?:说|道|问|答|喊|叫|吼|笑|叹)\s*[：:]')
DIALOGUE_QUOTES = '“”「"'

# 语气词（"毛刺"代理指标之一，衡量文本是否过度平滑、缺口语特征）
TONE_CHARS = '啊呢吧嘛呗嘁切哼哎哟哦啦噶诶额嘞喏哈喂嗯'

# 情绪反问/感叹章尾
ENDING_RE = re.compile(r'[？！…]$|[？]$|吗[？！]$')

SENT_SPLIT = re.compile(r'[。！？!?]')


def cn_to_int(s: str) -> int:
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
    m = re.match(r'^第\s*(\d+)\s*章\s*(.*)', text)
    if m:
        return int(m.group(1)), text
    m = re.match(r'^第\s*([零〇一二两三四五六七八九十百]+)\s*章\s*(.*)', text)
    if m:
        return cn_to_int(m.group(1)), text
    return None


def parse_chapters(doc):
    chapters = []
    cur = None
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        head = parse_chapter_heading(text)
        if head:
            if cur is not None:
                chapters.append(cur)
            cur = {'num': head[0], 'title': head[1], 'paras': [text]}
        elif cur is not None:
            cur['paras'].append(text)
    if cur is not None:
        chapters.append(cur)
    return chapters


def han_count(text: str) -> int:
    return len(HAN.findall(text))


def catchphrases(all_dialogues, min_len=4, max_len=10, min_repeat=5):
    """跨角色重复的台词片段 = 声纹趋同信号。"""
    counter = Counter()
    for d in all_dialogues:
        # 抽取引号内台词
        for seg in re.findall(r'[“「]([^”」]+)[”」]', d):
            seg = seg.strip()
            if len(seg) < min_len:
                continue
            counter[seg[:max_len]] += 1
    return [(p, c) for p, c in counter.most_common(30) if c >= min_repeat]


def check_chapter(ch):
    issues = []
    paras = ch['paras']
    body = paras[1:] if len(paras) > 1 else []
    full = ''.join(paras)
    han = han_count(full)
    if han < 50:
        return issues, han  # 太短的章跳过
    per_k = 1000.0 / han

    # 1. 对话标签滥用
    dial_paras = [p for p in body if any(q in p for q in DIALOGUE_QUOTES)]
    if dial_paras:
        tagged = sum(1 for p in dial_paras if TAG_RE.search(p))
        ratio = tagged / len(dial_paras)
        if ratio > 0.30:
            issues.append(('MUST', '对话标签滥用',
                          f'带说话标签的对话行 {ratio:.0%} > 30%（{tagged}/{len(dial_paras)}），'
                          f'改用动作/语气替代「X说/道」'))

    # 2. 情绪直陈密度
    emo = sum(full.count(w) for w in EMOTION_WORDS)
    emo_k = emo * per_k
    if emo_k > 8:
        issues.append(('MUST', '情绪直陈(tell-not-show)',
                      f'情绪名词直陈 {emo} 处（{emo_k:.1f}/千字），改写为行为/生理反应体现'))

    # 3. 安全比喻密度
    sim = sum(full.count(w) for w in SIMILE_WORDS)
    sim_k = sim * per_k
    if sim_k > 5:
        issues.append(('WARN', '安全比喻密度',
                      f'比喻连接词 {sim} 处（{sim_k:.1f}/千字），替换为具体感官描写'))

    # 4. AI 填充词
    filler = sum(full.count(w) for w in AI_FILLER)
    fill_k = filler * per_k
    if fill_k > 6:
        issues.append(('MUST', 'AI填充词',
                      f'填充词 {filler} 处（{fill_k:.1f}/千字），'
                      f'L1 未清干净的残留，逐处删/换'))

    # 5. 套路转场
    trans = sum(full.count(w) for w in TRANSITION)
    if trans >= 3:
        issues.append(('WARN', '套路转场',
                      f'「与此同时/另一边」类转场 {trans} 次，改为场景内衔接'))

    # 6. 段落节奏均匀度（变异系数）
    lens = [han_count(p) for p in body if han_count(p) > 0]
    if len(lens) >= 8:
        mean = sum(lens) / len(lens)
        std = (sum((x - mean) ** 2 for x in lens) / len(lens)) ** 0.5
        cv = std / mean if mean else 0
        if cv < 0.4:
            issues.append(('WARN', '段落同构',
                          f'段长变异系数 {cv:.2f} < 0.4，段落长度过于均匀（机器节奏），'
                          f'长短段交错重排'))

    # 7. 章尾套路
    last_para = body[-1] if body else ''
    if ENDING_RE.search(last_para.strip()):
        issues.append(('WARN', '章尾套路',
                      f'章尾为反问/感叹/省略号收尾：…{last_para[-25:]}，'
                      f'若多章同款需换钩子形式'))

    # 9. 过度平滑 / 作者声纹缺失（对照平台"质量审查"维度：AI 文字"过度平滑"，
    #    缺乏作者口头禅、故意的"卡壳"）。代理指标：毛刺密度 = (语气词 + 破折号 +
    #    句内省略号 + 超短句(≤5字,非对话)) / 千字；过低 → 文本过于规整像机器产出。
    tone_n = sum(full.count(c) for c in TONE_CHARS)
    dash_n = full.count('——') + full.count('—')
    inner_ell = full.count('…')
    frag_n = sum(1 for p in body
                 if 0 < han_count(p) <= 5 and not any(q in p for q in DIALOGUE_QUOTES))
    burr = tone_n + dash_n + inner_ell + frag_n
    burr_k = burr * per_k
    if burr_k < 1.0:
        issues.append(('WARN', '过度平滑/缺口语毛刺',
                      f'语气词/破折号/碎片等"毛刺"仅 {burr} 处（{burr_k:.1f}/千字），'
                      f'文本过于平滑规整，建议加口语词/刻意卡壳提升人味'))
    if tone_n == 0 and han > 300:
        issues.append(('WARN', '作者声纹缺失',
                      f'整章零语气词（啊/呢/吧/嘛…），缺作者口头禅特征，'
                      f'建议给叙述者/角色设定稳定语癖'))

    return issues, han


def main():
    ap = argparse.ArgumentParser(description='深层 AI 味逐章诊断（L2）')
    ap.add_argument('src', help='源 .docx 文件')
    ap.add_argument('--out', help='输出报告 markdown 路径（可选）')
    args = ap.parse_args()

    doc = Document(args.src)
    chapters = parse_chapters(doc)
    if not chapters:
        print('未检出任何章节（未找到 "第N章" 标题段），退出。')
        sys.exit(1)

    all_text = '\n'.join(p for ch in chapters for p in ch['paras'])
    all_dialogues = [p for ch in chapters for p in ch['paras']
                    if any(q in p for q in DIALOGUE_QUOTES)]
    phrases = catchphrases(all_dialogues)

    results = []  # (title, han, issues)
    for ch in chapters:
        issues, han = check_chapter(ch)
        results.append((ch['title'], han, issues))

    must_cnt = sum(1 for _, _, iss in results for lv, _, _ in iss if lv == 'MUST')
    warn_cnt = sum(1 for _, _, iss in results for lv, _, _ in iss if lv == 'WARN')
    worst = sorted(results, key=lambda r: -len(r[2]))[:10]

    print(f'章节总数: {len(chapters)} | MUST: {must_cnt} | WARN: {warn_cnt}')
    print(f'跨角色口头禅（声纹趋同信号）: {len(phrases)} 条')
    for p, c in phrases[:10]:
        print(f'  "{p}" ×{c}')
    print()

    cat_counter = Counter()
    for _, _, iss in results:
        for lv, cat, _ in iss:
            cat_counter[f'{lv}:{cat}'] += 1
    print('问题分布:')
    for key, cnt in cat_counter.most_common():
        print(f'  {key}: {cnt}')
    print()
    print('最严重的 10 章:')
    for title, han, iss in worst:
        if iss:
            print(f'  {title}（{han}字，{len(iss)} 项）')

    lines = ['# 深层 AI 味逐章诊断报告（L2）', '',
             f'> 源文件: `{args.src}`',
             f'> 章节: {len(chapters)} | MUST: {must_cnt} | WARN: {warn_cnt}',
             '> 用途：L1（deai_humanizer.py）跑完后仍残留的深层 AI 味，本报告定位到章，',
             '> 供 L3 逐章精修轮次定向重写。人工只需抽查，不必逐章重写。', '']

    lines += ['## 一、跨角色口头禅（全书声纹趋同）', '']
    if phrases:
        lines.append('以下台词片段在全书对话中重复出现——各角色说话没区分度，精修时给每个角色')
        lines.append('单独的语癖/句式/口头禅，这些通用片段要打散重写：')
        lines.append('')
        for p, c in phrases:
            lines.append(f'- "{p}" ×{c}')
    else:
        lines.append('- ✓ 未检出高频重复台词片段')
    lines.append('')

    lines += ['## 二、逐章问题清单（按严重度排序）', '']
    for title, han, iss in sorted(results, key=lambda r: -len(r[2])):
        if not iss:
            continue
        lines.append(f'### {title} （{han} 汉字）')
        for lv, cat, desc in iss:
            lines.append(f'- **[{lv}] {cat}**：{desc}')
        lines.append('')

    lines += ['## 三、L3 精修轮次 SOP（照此执行）', '',
              '1. 按 MUST 章优先、每次对话处理 3-5 章，按本报告定向重写（不要盲改全书）',
              '2. 每章重写完成后复跑 eval_fix_check.py 确认字数/对话占比/红线未回退',
              '3. 全书 MUST 清零后，人工抽查 3 章听感（读对话是否分得出谁在说话）',
              '4. 重写规则见 references/humanizer_banned.md 第五节']

    report = '\n'.join(lines)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f'报告已写入: {args.out}')
    else:
        print('--- 报告 ---')
        print(report)


if __name__ == "__main__":
    safe_main(main)

