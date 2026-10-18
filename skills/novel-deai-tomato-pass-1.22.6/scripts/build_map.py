# -*- coding: utf-8 -*-
"""Build references/example_map.json from the proven reframe scripts.

Reads the three original reframe_*.py files, extracts their REPL / REPL2
lists via AST (exact strings, no transcription error), merges them into a
single bulk map, drops no-op placeholders, and writes example_map.json with
the title pair + the Ch40 full-chapter swap.
"""
import ast
import json
import os

BASE = r"C:\Users\quany\WorkBuddy\2026-08-03-11-36-43"
OUT = os.path.join(os.path.dirname(__file__), "..", "references", "example_map.json")


def extract_list(path, name):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(node.value)
    return []


# --- collect bulk replacements ---
bulk = []
bulk += extract_list(os.path.join(BASE, "reframe_foundation.py"), "REPL")
bulk += extract_list(os.path.join(BASE, "reframe_final.py"), "REPL")

# REPL2 from reframe_chapters.py: all anchor-based, EXCEPT the Ch40 full swap
repl2 = extract_list(os.path.join(BASE, "reframe_chapters.py"), "REPL2")
# The Ch40 rewrite is handled via chapter_swaps, not bulk.
ch40_anchors = set()
bulk += repl2  # REPL2 entries are all anchor->new; include them all

# drop pure no-op placeholders (old == new)
bulk = [list(p) for p in bulk if p[0] != p[1]]

# de-dup while preserving order
seen = set()
dedup = []
for old, new in bulk:
    if old in seen:
        continue
    seen.add(old)
    dedup.append([old, new])

# --- Ch40 full-chapter swap body (from reframe_chapters.py new_body) ---
ch40_body = [
    "紫建国七十岁了，身体硬朗，每天下棋、遛鸟、带孙子孙女，享尽天伦之乐。王秀芳六十八岁，身体也很好，每天跳广场舞、买菜、做饭，一大家子的饭都是她做，她乐在其中。苏晚晴的父母和沈知夏的父母也经常来上海小住，一大家人聚在一起，热闹得不行。",
    "2038年春天，紫日做了一个决定。",
    "他要和赵晓棠补办一场真正的婚礼——法律意义上的、只属于他们两个人的婚礼。这些年公司一路狂奔，他们一直没顾上。赵晓棠是明媒正娶的妻子，可连张像样的婚纱照都没有，紫日觉得亏欠了她太久。",
    "婚礼定在马尔代夫的一个私人小岛上。苏晚晴、沈知夏、陈梦瑶这三个一路陪他们走过来的合伙人，主动揽下了所有筹备的活：场地、流程、宾客名单，连请柬都是沈知夏亲手设计的。她们说，晓棠嫁人，她们得当好伴娘。",
    "那天天气很好，碧海蓝天，白沙椰影。赵晓棠穿着大红色的中式嫁衣，绣着金凤的缎面剪裁合身，衬得她170的身段挺拔利落。小麦色的肌肤在红嫁衣映衬下健康又明艳，大眼睛画了眼线更显泼辣，高鼻梁下饱满的嘴唇涂着正红色口红，头发高高盘起戴着凤冠，整个人泼辣又美丽，像一朵开得最盛的山茶花。",
    "苏晚晴穿着淡紫色的伴娘裙，收腰大裙摆衬出她176的高挑身段。皮肤白得在阳光下像发光的瓷，鹅蛋脸上柳叶眉弯着，桃花眼含着笑意，头发盘起戴着珍珠头冠，温柔又端庄。沈知夏穿着淡蓝色的礼服，简洁的A字裙衬得她165的身姿匀称美好，素颜的脸白得发光，齐肩的黑发柔柔地披在肩头，杏眼清澈明亮，清纯脱俗。三个女人站在一起，美得让所有人都看呆了。",
    "紫日穿着一身白色的西装，站在赵晓棠面前，眼眶湿润。",
    "“晓棠，”他说，“我不是一个完美的男人，我甚至是一个很自私的男人。但我会用余生，好好爱你，好好守这个家，也好好珍惜一路陪我们走过的每一个人。”",
    "赵晓棠哭了，苏晚晴和沈知夏也红了眼眶。陈梦瑶站在台下，笑着抹了抹眼角，对身边的朋友说：“看，我最好的搭档，找了个好归宿吧。”",
    "紫念深带着弟弟妹妹站在最前面，拍着小手喊：“爸爸加油！妈妈加油！”",
    "所有的亲朋好友都鼓掌欢呼。紫建国和王秀芳笑得合不拢嘴，苏父苏母在擦眼泪，沈父沈母也在抹眼泪。他们知道自己是一家人，这就够了。",
    "那天晚上的婚礼，是紫日这辈子最幸福的时刻。赵晓棠穿着最美的嫁衣，成了他名正言顺的妻子。这份承诺，比任何文书都更有分量。",
    "婚礼后的晚宴上，陈梦瑶喝了不少酒。她平时很注意形象，但今晚她不想再伪装了。她端着酒杯走到紫日面前，眼眶红红的。",
    "“紫日，”她笑着说，“你欠我一杯喜酒。”",
    "“我知道。”紫日也有些哽咽，“你和老陈的喜酒，我一定到。”",
    "“不用。”陈梦瑶摇了摇头，“看到你幸福，我就高兴了。”她举起酒杯，一饮而尽，然后转身走进了人群，继续笑着、闹着，好像什么都没发生过。",
    "但赵晓棠看到了她转身时眼角的泪光。那天晚上，赵晓棠找到紫日。",
    "“紫日，”她说，“梦瑶也是我们的家人。她一个人在外头飘了太久，该有个落脚的地方了。以后她的难处，咱们一起扛。”",
    "紫日看着赵晓棠，说不出话来。",
    "“别感动。”赵晓棠笑了笑，“我不是为了你，我是为了她。她太苦了，该有个家了。”",
    "陈梦瑶的落寞，赵晓棠看在了眼里。第二天早上，她找到紫日，说了一句让他意外的话。",
    "“等梦瑶想通了，咱们把她的股份和合伙人身份正式定下来，让她名正言顺地回来。”",
    "紫日看着赵晓棠，眼眶有点红。",
    "晚饭后，大家坐在沙滩上。赵晓棠靠在他肩头，苏晚晴和沈知夏坐在对面，陈梦瑶在不远处的沙滩上，一个人喝着酒，看着大海。",
    "“在想什么？”赵晓棠问。",
    "“在想，我何德何能。”紫日轻声说。",
    "“知道就好。”赵晓棠笑了，“所以你这辈子都不许辜负我们这些家人。”",
    "“绝不。”",
    "苏晚晴没说话，只是笑了笑。沈知夏轻轻拍了拍他的手背，眼睛亮晶晶的。远处传来陈梦瑶的笑声，她在和朋友们跳舞，红色的裙摆随风飘动，像一团火焰。",
    "紫日看着星空，看着大海，看着身边的家人，心里暗暗发誓：他要用余生去爱赵晓棠、守护这个家、和伙伴们一起走下去。这是他重生以来最大的心愿。",
    "紫日坐在不远处的沙滩上，看着他们，觉得自己是全世界最幸福的男人。他给了赵晓棠一场名正言顺的婚礼，也给了伙伴们毫无保留的信任和一个真正的家。而她们，回报给他的是毫无保留的陪伴。",
    "夜风吹过，带着海水的咸味。远处传来婚礼宾客们的笑闹声，天上的星星亮得像钻石。这一刻，紫日希望时间能够停止。",
]

result = {
    "title_old": "重生2026：开局四个绝色老婆，我靠AI赢麻了",
    "title_new": "重生2026：我靠AI赢麻了",
    "bulk": dedup,
    "chapter_swaps": {
        "第四十章 三驾马车": {
            "next": "第四十一章",
            "body": ch40_body,
        }
    },
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f"wrote {OUT}")
print(f"bulk entries: {len(dedup)} | chapter_swaps: {list(result['chapter_swaps'].keys())}")
