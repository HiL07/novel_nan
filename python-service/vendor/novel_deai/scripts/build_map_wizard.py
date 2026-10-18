# -*- coding: utf-8 -*-
"""build_map_wizard.py — 新书映射生成向导：扫描 docx，自动生成草稿 map.json

解决「example_map.json 只适配《重生2026》，换书要人工从零建映射」的痛点。

做什么：
  1. 解析章节结构（复用 eval_fix_check.py 的 第N章 识别逻辑）。
  2. 识别书名（文档 core title / 首个非章节行），title_new 留空待用户填。
  3. 扫描硬伤触发词（多女/后宫/身体物化/去浪漫化），统计次数 + 抽样上下文句。
  4. 提取高频说话人姓名（对话归属 "Xxx说/道/问" 模式），辅助关系重构。
  5. 输出：
     - draft_map.json：可直接被 reframe_novel.py --map 消费的草稿。
       * bulk  = 通用安全替换（不依赖具体书，自动生效）
                 + 候选替换（脚本给出建议新词，标记 candidate:true 字段的旁注键，
                   reframe_novel.py 忽略未知键，确认后由人/模型并入 bulk）
     - 可选 --out report.md：人读的扫描报告（触发词统计、候选句、说话人清单）

用法:
  python build_map_wizard.py <input.docx> [--map draft_map.json] [--out report.md]

产出的 draft_map.json 结构:
  {
    "title_old": "...", "title_new": "",
    "bulk": [["旧", "新"], ...],              # 通用安全层，直接可用
    "candidates": [ {"old": "...", "suggest": "...",
                     "count": 3, "context": "..."}, ... ],  # 待确认后并入 bulk
    "chapter_swap_candidates": [ {"title": "...", "reason": "..."} ],
    "speakers": [ {"name": "苏晚晴", "lines": 120}, ... ]
  }
确认动线：人/模型把 candidates 里确认后的条目挪进 bulk（去掉建议词里的
「?」语气，改成定稿替换），整章违规的章写进 chapter_swaps，再跑 reframe_novel.py。
"""
from errkit import safe_main
import argparse
import json
import os
import re
import sys
from collections import Counter

from docx import Document

HAN = re.compile(r'[\u4e00-\u9fff]')

CN_NUM = {'零': 0, '〇': 0, '一': 1, '两': 2, '二': 2, '三': 3, '四': 4,
          '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}

# ---------- 通用安全替换（不依赖具体书，语境无关，直接并入 draft bulk） ----------
AUTO_SAFE = [
    # 身体物化中性化
    ["饱满的胸部", "胸口"],
    ["胸部曲线", "身形曲线"],
    ["丰满的胸部", "胸口"],
    ["翘臀", "挺拔的身姿"],
    ["事业线", "领口"],
    ["深V", "V领"],
    # 多女信号词的通用安全替换（对话语境下语义不变）
    ["三妻四妾", "三心二意"],
    ["脚踏两条船", "摇摆不定"],
    ["脚踏三条船", "摇摆不定"],
    ["脚踏四条船", "摇摆不定"],
]

# ---------- 触发词分类（需人工/模型定稿替换的候选层） ----------
TRIGGER_GROUPS = {
    '明示亲密': ['上床', '情人', '新娘', '洞房', '床笫', '缠绵', '包养', '一夜情'],
    '多女结构': ['后宫', '种马', '名分', '白月光', '暧昧', '姨太太', '妾',
                '共侍一夫', '左拥右抱', '齐人之福', '三宫六院'],
    '关系密度': ['四个女人', '三个女人', '几个女人', '四个妈妈', '几个老婆',
                '老婆们', '女人们', '众女'],
    '比喻多女': ['皇帝', '后宫佳丽'],
    '身体物化': ['妩媚勾人', '妖娆', '酥胸', '玉体', '曼妙身材', '胸前沟'],
}

# 对话归属模式：“苏晚晴说道：” / “林薇冷冷道”（姓名惰性匹配限2-3字，
# 避免"苏晚晴说"这类把动词吃进姓名的贪婪误匹配；动词在捕获组外）
SPEAKER_RE = re.compile(r'([\u4e00-\u9fff]{2,3}?)(?:也|又|才|便|就|再)?'
                        r'(?:冷冷|淡淡|微微|轻轻|缓缓|哈哈|苦笑|自嘲)?'
                        r'(?:说|道|问|答|喊|叫|吼|笑|叹|嘀咕|嘟囔|回应|开口)')

SENT_SPLIT = re.compile(r'[。！？!?；;\n]')


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


def guess_title(doc, chapters):
    # 1) core property; 2) 首个非章节、非空段落（不少导出稿首行是书名）
    try:
        t = (doc.core_properties.title or '').strip()
        if t:
            return t
    except Exception:
        pass
    for para in doc.paragraphs[:10]:
        text = para.text.strip()
        if not text or parse_chapter_heading(text):
            continue
        if len(text) <= 40 and not text.startswith('作者') and '笔名' not in text:
            return text
    return ''


def sample_contexts(all_text, word, limit=3):
    """取含触发词的完整句（按句切）作为上下文样本。"""
    ctx = []
    for sent in SENT_SPLIT.split(all_text):
        sent = sent.strip()
        if word in sent and 8 <= len(sent) <= 80:
            ctx.append(sent)
            if len(ctx) >= limit:
                break
    return ctx


def scan_triggers(all_text):
    """返回 {组名: [ {word, count, contexts}, ... ]}，按次数降序。"""
    result = {}
    for group, words in TRIGGER_GROUPS.items():
        hits = []
        for w in words:
            c = all_text.count(w)
            if c > 0:
                hits.append({'word': w, 'count': c,
                             'contexts': sample_contexts(all_text, w)})
        if hits:
            hits.sort(key=lambda x: -x['count'])
            result[group] = hits
    return result


def extract_speakers(all_text, chapters):
    """从对话归属提取说话人姓名及台词数。"""
    counter = Counter()
    for para_text in (p for ch in chapters for p in ch['paras']):
        m = SPEAKER_RE.search(para_text[:30])
        if m and any(q in para_text for q in '“”"「'):
            counter[m.group(1)] += 1
    # 过滤非人名噪音（动词误匹配，如“他说”“她道”）
    stop = {'他说', '她说', '他道', '她道', '两人', '我们', '他们', '她们', '对方'}
    return [{'name': n, 'lines': c} for n, c in counter.most_common(30)
             if n not in stop and c >= 3]


def suggest_for(group, word):
    """按组给出候选建议词（仅是建议，必须人工/模型确认语境后再定稿）。"""
    table = {
        '明示亲密': {'上床': '越界', '情人': '旧情人?', '新娘': '女主角?', '洞房': '新婚之夜?',
                   '缠绵': '相拥', '包养': '金主关系?'},
        '多女结构': {'后宫': '团队', '种马': '风流成性', '名分': '身份',
                   '白月光': '初恋', '暧昧': '关系微妙', '妾': '旧式侧室?'},
        '关系密度': {'四个女人': '四位合伙人', '三个女人': '三位合伙人',
                   '老婆们': '合伙人们', '女人们': '女同事们'},
        '比喻多女': {'皇帝': '大老板'},
        '身体物化': {'妩媚勾人': '笑容亲切', '妖娆': '动人', '酥胸': '胸口'},
    }
    return table.get(group, {}).get(word, '待定')


def chapter_swap_candidates(triggers, chapters):
    """触发词密度最高的章 → 建议整章重写候选。"""
    cands = []
    for ch in chapters:
        text = ''.join(ch['paras'])
        score = sum(text.count(w) for group in triggers.values()
                    for w in [h['word'] for h in group])
        if score >= 5:
            cands.append({'title': ch['title'], 'reason': f'触发词命中 {score} 次，疑似整章违规'})
    return cands


def main():
    ap = argparse.ArgumentParser(description='新书映射生成向导')
    ap.add_argument('src', help='源 .docx 文件')
    ap.add_argument('--map', default='draft_map.json', help='输出草稿 map 路径')
    ap.add_argument('--out', default=None, help='输出人读报告 markdown（可选）')
    args = ap.parse_args()

    doc = Document(args.src)
    chapters = parse_chapters(doc)
    if not chapters:
        print('未检出任何章节（未找到 "第N章" 标题段），退出。')
        sys.exit(1)

    all_text = '\n'.join(p for ch in chapters for p in ch['paras'])
    title_old = guess_title(doc, chapters)
    triggers = scan_triggers(all_text)
    speakers = extract_speakers(all_text, chapters)
    swaps = chapter_swap_candidates(triggers, chapters)

    # 草稿 map：通用安全层直接进 bulk；候选层等确认
    draft = {
        '_说明': '草稿映射。candidates 条目经人工/模型确认语境后，改写为定稿替换并挪入 bulk；'
                 '整章违规的章按 reframe_map.md 补 chapter_swaps。reframe_novel.py 只读 '
                 'title_*/bulk/chapter_swaps，其余键会被忽略。',
        'title_old': title_old,
        'title_new': '',
        'bulk': [list(pair) for pair in AUTO_SAFE if pair[0] in all_text],
        'candidates': [
            {'group': g, 'old': h['word'], 'suggest': suggest_for(g, h['word']),
             'count': h['count'], 'context': h['contexts'][:2]}
            for g, group in triggers.items() for h in group
        ],
        'chapter_swap_candidates': swaps,
        'speakers': speakers,
    }
    with open(args.map, 'w', encoding='utf-8') as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)
    print(f'草稿映射已写入: {args.map}')
    print(f'  书名(旧): {title_old or "(未识别，请手填)"}')
    print(f'  通用安全替换: {len(draft["bulk"])} 条')
    print(f'  待确认候选: {len(draft["candidates"])} 条')
    print(f'  整章违规候选: {len(swaps)} 章')
    print(f'  说话人: {", ".join(s["name"] for s in speakers[:8])}')

    if args.out:
        lines = ['# 新书映射扫描报告', '',
                 f'> 源文件: `{args.src}`',
                 f'> 章节: {len(chapters)} | 书名(旧): {title_old or "未识别"}',
                 '', '## 一、高频说话人（关系重构的人物清单）', '']
        for s in speakers:
            lines.append(f'- {s["name"]}（台词归属 {s["lines"]} 次）')
        lines += ['', '## 二、触发词统计（按组）', '']
        for g, group in triggers.items():
            lines.append(f'### {g}')
            for h in group:
                lines.append(f'- **{h["word"]}** ×{h["count"]}，建议替换: `{suggest_for(g, h["word"])}`')
                for c in h['contexts'][:2]:
                    lines.append(f'  - 例：{c}')
            lines.append('')
        lines += ['', '## 三、整章违规候选', '']
        if swaps:
            for s in swaps:
                lines.append(f'- {s["title"]} —— {s["reason"]}')
        else:
            lines.append('- 无（无单章触发词密度 ≥5 的章）')
        lines += ['', '## 四、下一步', '',
                  '1. 按重构方向（单配偶+合伙人 推荐）确认 candidates 的替换词',
                  '2. 整章违规的写 chapter_swaps（见 references/reframe_map.md）',
                  '3. 运行 `reframe_novel.py in.docx out.docx --map 定稿map.json`']
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        print(f'扫描报告已写入: {args.out}')


if __name__ == "__main__":
    safe_main(main)

