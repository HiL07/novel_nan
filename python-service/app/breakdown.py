"""拆书档案：由逐章章节卡用代码算出的节奏统计（不调用模型）。

口径参考 EasyWriting ``agent_breakdown.rs#summarize``（见 docs/素材提取改造方案.md 附录 A.4）：
密度类只算有章节卡的章；「最长无爽点区间」沿完整章节顺序走，没有章节卡的章会打断区间。
"""
from collections import Counter


def _count(items) -> list[dict]:
    return [{"type": t, "count": n} for t, n in sorted(Counter(i for i in items if i).items(), key=lambda x: (-x[1], x[0]))]


def _ratio(a: int | float, n: int) -> float:
    return round(a / n, 2) if n else 0.0


def pacing(cards: list[dict], threads: list[dict]) -> dict:
    """cards：result.chapterCards（每章一条，status done / failed）；threads：result.threads。"""
    carded = [c for c in cards if c.get("status") == "done" and c.get("oneLine")]
    n = len(carded)
    curve = []
    for c in cards:
        pays = c.get("payoffs") or []
        end = next((h for h in c.get("hooks") or [] if h.get("pos") == "end"), None)
        curve.append({"ci": c["ci"], "carded": c in carded, "payoffCount": len(pays),
                      "payoffPeak": max((p.get("strength") or 0 for p in pays), default=0),
                      "endHook": {"type": end["type"], "strength": end.get("strength")} if end else None,
                      "function": c.get("function") or ""})
    gap, run, start = (0, None, None), 0, None
    for p in curve:
        if p["carded"] and p["payoffCount"] == 0:
            if run == 0:
                start = p["ci"]
            run += 1
            if run > gap[0]:
                gap = (run, start, p["ci"])
        else:
            run = 0
    all_hooks = [h for c in carded for h in c.get("hooks") or []]
    end_hooks = [h for h in all_hooks if h.get("pos") == "end"]
    pays = [p for c in carded for p in c.get("payoffs") or []]
    paid = [t for t in threads if t.get("status") == "paid" and t.get("payoffCi") is not None]
    dist = [t["payoffCi"] - t["plantCi"] for t in paid]
    chars = sum((c.get("stats") or {}).get("chars", 0) for c in cards)
    dialog = sum((c.get("stats") or {}).get("dialogRatio", 0) * (c.get("stats") or {}).get("chars", 0) for c in cards)
    paras = [(c.get("stats") or {}).get("avgParagraph", 0) for c in cards if (c.get("stats") or {}).get("paragraphs")]
    lead_line = [{"ci": c["ci"], "field": ch.get("field"), "after": ch.get("after")}
                 for c in carded for ch in c.get("leadChanges") or []]
    return {
        "chapters": len(cards), "carded": n,
        "payoffsPerChapter": _ratio(len(pays), n),
        "endHookRate": _ratio(len({id(c) for c in carded if any(h.get("pos") == "end" for h in c.get("hooks") or [])}), n),
        "longestPayoffGap": {"length": gap[0], "from": gap[1], "to": gap[2]},
        "hookTypes": _count(h.get("type") for h in all_hooks),
        "endHookTypes": _count(h.get("type") for h in end_hooks),
        "payoffTypes": _count(p.get("type") for p in pays),
        "amplifiedRate": _ratio(sum(1 for p in pays if p.get("amplified")), len(pays)),
        "functions": _count(c.get("function") for c in carded),
        "threads": {"planted": len(threads), "paid": len(paid),
                    "avgDistance": round(sum(dist) / len(dist), 1) if dist else None},
        "opening": [{"ci": c["ci"], "title": c.get("title"), "oneLine": c.get("oneLine"),
                     "hooks": [h.get("type") for h in c.get("hooks") or []],
                     "payoffs": [p.get("type") for p in c.get("payoffs") or []]} for c in carded[:3]],
        "leadLine": lead_line[:300],
        "curve": curve,
        "style": {"avgParagraph": round(sum(paras) / len(paras), 1) if paras else 0,
                  "dialogRatio": round(dialog / chars, 3) if chars else 0},
    }
