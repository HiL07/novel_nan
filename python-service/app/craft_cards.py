"""写法卡（卡片整理，2026-11-03）：把提取得到的写法统计总结成可借用的写法规律。

数字和例子由代码从章节卡 / 伏笔表里算、挑（有依据），模型只把它们写成规律，每条规律必须引用给出的例子章节；
代码再核对一遍：引用不在例子里的章号去掉，没有合法引用的规律丢掉。依据不够（快速档没有钩子 / 爽点 / 伏笔，
已读太少）就不调模型，记在 skipped 里给界面看。

输入（Java 从提取结果或暂停时的断点组装）：cards = 章节卡 [{ci, title, oneLine, events, hooks, payoffs, function,
leadChanges, golden?}]（ci = 范围内序号），threads = 伏笔表，base = 范围起点前的章数（显示 / 引用用全书章号 = base + ci + 1），
fromStart = 范围是否从第 1 章开始（开篇卡要求）。
"""
from __future__ import annotations

import logging
import threading
from collections import Counter
from typing import Callable

from . import breakdown
from . import material_facts as mf

log = logging.getLogger(__name__)

TYPES = {"pacing": "节奏", "endhook": "章末钩子", "payoff": "爽点套路", "thread": "伏笔", "opening": "开篇", "lead": "主角成长线"}
MIN_CHAPTERS = 5
MAX_EXAMPLES = 6
CARD_TOKENS = 1400

SYSTEM = "你是网文写作教练，只输出 JSON，不要任何多余文字。"
PROMPT_TAIL = """
请把上面的统计和例子总结成「{label}」方面可以借用到别的小说里的写法规律，输出 JSON：
{{"title":"这张写法卡的标题（不超过20字）","summary":"一句话概括这本书在{label}上的做法（不超过60字）",
"rules":[{{"text":"一条具体可操作的写法规律（不超过80字）","chapters":[引用的例子章号，整数]}}],
"when":"适用场景（不超过60字）","borrowTip":"借用时要注意 / 要改什么（不超过80字）"}}
要求：rules 3–5 条；每条规律只能依据上面给出的统计和例子，chapters 只能填上面例子里出现过的章号，至少引用 1 个；
不要编造例子里没有的情节，不要空泛的套话（如「要吸引读者」）。"""


def _n(base: int, ci: int) -> int:
    return base + ci + 1


def _pct(v) -> str:
    return f"{round((v or 0) * 100)}%"


def _top(items: list[dict], k: int = 5) -> str:
    return "、".join(f"{x['type']} {x['count']}" for x in (items or [])[:k]) or "无"


def evidence(cards: list[dict], threads: list[dict], base: int, from_start: bool) -> tuple[list[dict], list[dict]]:
    """→ (jobs [{type, label, stats{…}, statsText, examples[{n, title, text}]}], skipped [{type, label, reason}])。"""
    for c in cards:
        c.setdefault("status", "done")
    carded = [c for c in cards if c.get("oneLine")]
    skipped: list[dict] = []
    jobs: list[dict] = []

    def skip(t: str, reason: str) -> None:
        skipped.append({"type": t, "label": TYPES[t], "reason": reason})

    if len(carded) < MIN_CHAPTERS:
        for t in TYPES:
            skip(t, f"已读的章太少（{len(carded)} 章，至少 {MIN_CHAPTERS} 章）")
        return jobs, skipped
    p = breakdown.pacing(cards, threads)
    by_ci = {c["ci"]: c for c in carded}
    title = lambda ci: (by_ci.get(ci) or {}).get("title") or ""
    rich = any("hooks" in c or "payoffs" in c for c in carded)  # 快速档只有一句话 + 事件

    def ex(ci: int, text: str) -> dict:
        return {"n": _n(base, ci), "title": title(ci), "text": text[:160]}

    # ---- 节奏
    if not rich:
        skip("pacing", "快速档没有记录爽点，无法总结节奏")
    else:
        dense = sorted(carded, key=lambda c: -len(c.get("payoffs") or []))[:3]
        exs = [ex(c["ci"], f"{c['oneLine']}（爽点：{'、'.join(x['type'] for x in c.get('payoffs') or []) or '无'}）") for c in dense]
        gap = p["longestPayoffGap"]
        if gap["length"] and gap["from"] is not None:
            for ci in (gap["from"] - 1, gap["to"] + 1):
                if ci in by_ci:
                    exs.append(ex(ci, f"{'低谷前' if ci < gap['from'] else '低谷后接回'}：{by_ci[ci]['oneLine']}"))
        stats = {"chapters": p["carded"], "payoffsPerChapter": p["payoffsPerChapter"], "longestGap": gap["length"],
                 "functions": p["functions"][:6]}
        text = (f"已读 {p['carded']} 章；平均每章爽点 {p['payoffsPerChapter']} 个；最长连续无爽点 {gap['length']} 章"
                + (f"（第 {_n(base, gap['from'])}–{_n(base, gap['to'])} 章）" if gap["length"] else "")
                + f"；章节功能分布：{_top(p['functions'], 6)}")
        jobs.append({"type": "pacing", "stats": stats, "statsText": text, "examples": exs[:MAX_EXAMPLES]})

    # ---- 章末钩子
    ends = [(c["ci"], h) for c in carded for h in c.get("hooks") or [] if h.get("pos") == "end"]
    if not rich or not ends:
        skip("endhook", "没有记录章末钩子（快速档或这些章没有钩子）")
    else:
        ends.sort(key=lambda x: -(x[1].get("strength") or 0))
        exs = [ex(ci, f"[{h['type']}] {h.get('text') or ''}" + (f"「{h['quote']}」" if h.get("quote") else "")) for ci, h in ends[:MAX_EXAMPLES]]
        text = f"章末钩子率 {_pct(p['endHookRate'])}；章末钩子类型：{_top(p['endHookTypes'])}；全部钩子类型：{_top(p['hookTypes'])}"
        jobs.append({"type": "endhook", "stats": {"endHookRate": p["endHookRate"], "endHookTypes": p["endHookTypes"][:6]},
                     "statsText": text, "examples": exs})

    # ---- 爽点套路
    pays = [(c["ci"], x) for c in carded for x in c.get("payoffs") or []]
    if not rich or not pays:
        skip("payoff", "没有记录爽点（快速档或这些章没有爽点）")
    else:
        pays.sort(key=lambda x: (-(x[1].get("strength") or 0), -int(bool(x[1].get("amplified")))))
        exs = [ex(ci, f"[{x['type']}{'·有旁观反应' if x.get('amplified') else ''}] {x.get('setup') or ''}"
                      + (f" →「{x['quote']}」" if x.get("quote") else "")) for ci, x in pays[:MAX_EXAMPLES]]
        text = f"共 {len(pays)} 个爽点；类型：{_top(p['payoffTypes'], 6)}；带旁观反应（放大）的占 {_pct(p['amplifiedRate'])}"
        jobs.append({"type": "payoff", "stats": {"payoffs": len(pays), "payoffTypes": p["payoffTypes"][:6],
                                                 "amplifiedRate": p["amplifiedRate"]}, "statsText": text, "examples": exs})

    # ---- 伏笔
    paid = [t for t in threads or [] if t.get("status") == "paid" and t.get("payoffCi") is not None]
    if not threads or not paid:
        skip("thread", "没有已回收的伏笔（快速档没有伏笔表，或读的章还不够回收）")
    else:
        paid.sort(key=lambda t: -(t["payoffCi"] - t["plantCi"]))
        exs = []
        for t in paid[:MAX_EXAMPLES]:
            e = ex(t["plantCi"], f"[{t.get('kind') or '伏笔'}] {t.get('text') or ''}：第 {_n(base, t['plantCi'])} 章埋下，"
                                 f"第 {_n(base, t['payoffCi'])} 章回收（隔 {t['payoffCi'] - t['plantCi']} 章）")
            e["also"] = [_n(base, t["payoffCi"])]
            exs.append(e)
        th = p["threads"]
        text = f"埋下 {th['planted']} 条，已回收 {th['paid']} 条，平均隔 {th['avgDistance']} 章回收"
        jobs.append({"type": "thread", "stats": th, "statsText": text, "examples": exs})

    # ---- 开篇
    if not from_start:
        skip("opening", "这次提取不是从第 1 章开始读的")
    else:
        first = carded[:3]
        exs = []
        for c in first:
            bits = [c["oneLine"]]
            if c.get("function"):
                bits.append(f"功能：{c['function']}")
            if c.get("hooks"):
                bits.append("钩子：" + "、".join(h["type"] for h in c["hooks"]))
            if c.get("payoffs"):
                bits.append("爽点：" + "、".join(x["type"] for x in c["payoffs"]))
            g = c.get("golden") or {}
            if g.get("hook300"):
                bits.append(f"开头钩子：{g['hook300']}")
            if g.get("establish"):
                bits.append(f"人设：{g['establish']}")
            if g.get("dilemma"):
                bits.append(f"核心困境：{g['dilemma']}")
            exs.append(ex(c["ci"], "；".join(bits)))
        jobs.append({"type": "opening", "stats": {"chapters": len(first)}, "statsText": "前 3 章（黄金三章）的做法如下",
                     "examples": exs})

    # ---- 主角成长线
    line = p.get("leadLine") or []
    if len(line) < 3:
        skip("lead", "主角状态变化太少（快速档没有记录，或读的章还不够）")
    else:
        step = max(1, len(line) // MAX_EXAMPLES)
        picked = line[::step][:MAX_EXAMPLES]
        exs = [ex(x["ci"], f"{x.get('field') or ''}：{x.get('after') or ''}") for x in picked]
        fields = Counter(x.get("field") for x in line)
        text = f"主角状态变化 {len(line)} 次；变化的方面：" + "、".join(f"{k} {v}" for k, v in fields.most_common(6))
        jobs.append({"type": "lead", "stats": {"changes": len(line), "fields": dict(fields)}, "statsText": text, "examples": exs})

    for j in jobs:
        j["label"] = TYPES[j["type"]]
    return jobs, skipped


def prompt(job: dict) -> str:
    lines = [f"【统计】{job['statsText']}", "【例子】"]
    for e in job["examples"]:
        lines.append(f"第{e['n']}章《{e['title']}》：{e['text']}")
    return "\n".join(lines) + PROMPT_TAIL.format(label=job["label"])


def to_card(data: dict, job: dict) -> dict | None:
    """模型输出 → 卡片项（核对章号：只认例子里出现过的章）；没有一条合法规律返回 None。"""
    if not isinstance(data, dict):
        return None
    allowed = {e["n"] for e in job["examples"]} | {n for e in job["examples"] for n in e.get("also") or []}
    titles = {e["n"]: e["title"] for e in job["examples"]}
    rules = []
    for r in data.get("rules") or []:
        if not isinstance(r, dict) or not mf._text(r.get("text"), 120):
            continue
        chs = []
        for x in r.get("chapters") or []:
            try:
                n = int(x)
            except (TypeError, ValueError):
                continue
            if n in allowed and n not in chs:
                chs.append(n)
        if chs:
            rules.append({"text": mf._text(r.get("text"), 120), "chapters": chs[:4]})
    if not rules:
        return None
    label = job["label"]
    cited = sorted({n for r in rules for n in r["chapters"]})
    attrs = {"规律": "；".join(r["text"] for r in rules)[:300],
             "适用场景": mf._text(data.get("when"), 120),
             "示例章节": "、".join(f"第{n}章《{titles.get(n, '')}》" for n in cited)[:300],
             "数据": job["statsText"][:300],
             "借用提示": mf._text(data.get("borrowTip"), 160)}
    attrs = {k: v for k, v in attrs.items() if v and not mf._EMPTY_VALUE.match(v)}
    return {
        "candidateId": f"craft:{job['type']}",
        "kind": "craft",
        "category": "craft",
        "subtype": label,
        "title": mf._text(data.get("title"), 40) or f"{label}写法",
        "summary": mf._text(data.get("summary"), 120),
        "detail": "\n".join(f"{i}. {r['text']}（第 {'、'.join(map(str, r['chapters']))} 章）" for i, r in enumerate(rules, 1)),
        "attributes": attrs,
        "tags": [label, "写法"],
        "excerpt": "",
        "chapters": [f"第{n}章《{titles.get(n, '')}》" for n in cited],
        "facts": [],
        "rules": rules,
        "stats": job["stats"],
        "examples": job["examples"],
        "craftType": job["type"],
    }


def compile_craft(craft: dict, call: Callable[[list[dict], int], str], concurrency: int, ckpt,
                  on_progress: Callable[[int, str], None], stop: threading.Event | None) -> dict:
    """→ {materials: [写法卡], stats: {cards, skipped[], failedCards}}。断点阶段 craft（按类型）。"""
    jobs, skipped = evidence(list(craft.get("cards") or []), list(craft.get("threads") or []),
                             int(craft.get("base") or 0), bool(craft.get("fromStart", True)))
    stats = {"entities": 0, "cards": 0, "notUseful": 0, "systems": 0, "arcs": 0, "failedCards": 0,
             "craftCards": 0, "skipped": skipped}
    lock = threading.Lock()
    done = ckpt.done("craft")
    by_type = {j["type"]: j for j in jobs}

    def make(t: str) -> None:
        text = call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt(by_type[t])}], CARD_TOKENS)
        with lock:
            ckpt.append("craft", t, mf._parse(text))

    mf._parallel([t for t in by_type if t not in done], make, workers=concurrency, stop=stop, lock=lock,
                 on_progress=on_progress, label="整理写法卡", base=0, span=98, total=len(by_type),
                 failed=stats, fail_key="failedCards")
    out = []
    for t, job in by_type.items():
        card = to_card(ckpt.done("craft").get(t), job)
        if card:
            out.append(card)
        else:
            stats["notUseful"] += 1
    stats["craftCards"] = stats["cards"] = len(out)
    return {"materials": out, "stats": stats}
