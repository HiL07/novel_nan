"""世界书：一个工作区的全部故事知识，编译成统一的条目（设计见 docs/世界书.md）。

不单独存储，每次从现有数据编译（P1：只读视图）：
- 设定编辑器的 spec（spec.build_for：核心 → pinned 条目，卡片 → 按名字触发的条目，未到登场章节的 → notYet）
- 角色卡快照 novel.personas（人物内核 brief 并进同名角色条目）
- 故事账本 facts.json（角色的 状态 / 目标 / 阻碍 / 关系 / 已知信息 → 条目的 state；伏笔 → threads；定时事件 → clocks）
- 故事阶段（inspire.stage_of）、大纲里接下来的章节、前情（前情概要 + 最近章节摘要）

snapshot() 把它压成「此刻的局面」给走向引擎：谁想要什么、谁挡着谁、未回收的伏笔、谁知道什么、什么快到期。
"""
import re

from . import facts as facts_mod, spec as spec_mod, store

RECENT_SUMMARIES = 8
SNAPSHOT_CHARACTERS = 10
SNAPSHOT_THREADS = 12
KIND_OF_CATEGORY = {"characters": "character", "world": "world", "plot": "event", "style": "style"}


def _names(cons) -> dict[str, str]:
    """角色名单「名（定位）」→ {名: 定位}"""
    out = {}
    for r in cons.roster:
        m = re.match(r"(.+?)（(.*)）$", r)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def compile(novel_id: str, chapter: int | None = None, spec: list | None = None) -> dict:
    """→ {chapter, entries[], threads[], clocks[], timeline[], stage, outlineNext[], story, open[]}；
    chapter = 为第几章编译（默认下一章：账本只看这之前的、登场条件按这一章算）。"""
    from . import inspire   # inspire 依赖 ideas / spec，延迟导入避免循环
    novel = store.get_novel(novel_id)
    chapters = store.list_chapters(novel_id)
    n = chapter or ((chapters[-1]["index"] + 1) if chapters else 1)
    cons = spec_mod.build_for(novel, spec, chapter=n)
    facts = facts_mod.view_before(store.get_facts(novel_id), n)
    roles = _names(cons)
    protagonists = {name for name, role in roles.items() if any(w in role for w in spec_mod.PROTAGONIST_WORDS)}

    entries: list[dict] = []
    by_name: dict[str, dict] = {}

    def add(e: dict) -> dict:
        entries.append(e)
        for k in [e["name"], *e["aliases"]]:
            if k:
                by_name.setdefault(k, e)
        return e

    for i, text in enumerate(cons.core):
        head = re.match(r"【(.+?)】(.*)", text)
        label, rest = (head.group(1), head.group(2).strip()) if head else (f"核心设定 {i + 1}", "")
        if label == "主角" or label.startswith("人物内核·"):
            name = label.split("·", 1)[1] if "·" in label else (rest.splitlines()[0].strip() if rest else "主角")
            e = by_name.get(name)
            if e:
                e["text"] += "\n" + text
                e["pinned"] = True
                continue
            add({"id": f"core.{i}", "kind": "character", "category": "角色", "name": name, "aliases": [],
                 "role": roles.get(name, "主角"), "text": text, "pinned": True, "since": None, "notYet": False,
                 "source": {"type": "persona" if "·" in label else "settings"}, "state": None})
        else:
            add({"id": f"core.{i}", "kind": "rule", "category": label, "name": label, "aliases": [], "role": "",
                 "text": text, "pinned": True, "since": None, "notYet": False, "source": {"type": "settings"}, "state": None})

    for c, not_yet in [(c, False) for c in cons.cards] + [(c, True) for c in cons.not_yet]:
        cat = c.id.split(".", 1)[0]
        is_persona = cat == "persona"
        kind = "character" if is_persona else KIND_OF_CATEGORY.get(cat, "element")
        name = c.title.split("：", 1)[-1] if "：" in c.title else c.title
        e = by_name.get(name) if kind == "character" else None
        if e:   # 同一个角色的人物内核卡 / 设定卡并成一条
            e["text"] += "\n" + c.text
            e["aliases"] = sorted(set(e["aliases"]) | (c.keywords - {e["name"]}))
            continue
        add({"id": c.id, "kind": kind, "category": c.title.split("：", 1)[0] if "：" in c.title else c.title,
             "name": name, "aliases": sorted(c.keywords - {name}), "role": roles.get(name, ""), "text": c.text,
             "pinned": False, "since": (c.appear or {}).get("from"), "notYet": not_yet,
             "source": {"type": "persona" if is_persona else "settings", "ref": c.id}, "state": None})

    for name, ch in facts["characters"].items():
        e = by_name.get(name)
        if e is None:
            e = add({"id": f"ledger.{name}", "kind": "character", "category": "角色", "name": name, "aliases": [],
                     "role": roles.get(name, ""), "text": "", "pinned": False, "since": None, "notYet": False,
                     "source": {"type": "ledger"}, "state": None})
        e["state"] = {k: ch.get(k) for k in ("state", "updatedIn", "goal", "obstacle", "relations", "knows", "manual")}
    for e in entries:
        if e["kind"] == "character" and e["name"] in protagonists:
            e["pinned"] = True
            e["protagonist"] = True

    recent = [c for c in chapters if c["index"] < n and c.get("summary")][-RECENT_SUMMARIES:]
    outline = (novel.get("outline") or {}).get("chapters") or []
    return {
        "novelId": novel_id, "title": novel.get("title"), "chapter": n,
        "entries": entries,
        "threads": [{"id": f["id"], "text": f["text"], "status": f["status"], "plantedIn": f["plantedIn"],
                     "lastChapter": f["history"][-1]["chapter"] if f["history"] else f["plantedIn"], "manual": f["manual"],
                     "planned": bool(f.get("planned")), "plannedIn": f.get("plannedIn") or 0, "payoffIn": f.get("payoffIn") or 0}
                    for f in facts["foreshadows"]],
        # 大纲和账本对不上 / 计划伏笔超期（自动规划写进来的计划，见 planner.py）
        "checks": facts_mod.check_outline(facts, novel.get("outline"), n - 1),
        "clocks": facts.get("clocks") or [],
        "timeline": facts["timeline"][-30:],
        "stage": inspire.stage_of({"novelId": novel_id}),
        "outlineNext": [c for c in outline if c.get("index", 0) >= n][:5],
        "story": {"arcSummary": novel.get("arcSummary") or "", "arcUpTo": novel.get("arcUpTo") or 0,
                  "recent": [{"index": c["index"], "title": c.get("title") or "", "summary": c["summary"]} for c in recent]},
        "open": cons.open,
    }


def _clip(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "…"


def snapshot(wb: dict, max_chars: int = 6000) -> str:
    """此刻的局面（走向引擎的输入）：主角、人物局面、未回收伏笔、定时事件、阶段、大纲接下来、前情、其他设定。"""
    from . import inspire
    chars = [e for e in wb["entries"] if e["kind"] == "character"]
    chars.sort(key=lambda e: (not e.get("protagonist"), -((e.get("state") or {}).get("updatedIn") or 0)))
    parts = [f"【书名】{wb.get('title') or ''}（下一章是第 {wb['chapter']} 章）"]

    lines = []
    for e in chars[:SNAPSHOT_CHARACTERS]:
        tag = "主角" if e.get("protagonist") else (e.get("role") or "")
        head = f"{e['name']}" + (f"（{_clip(tag, 30)}）" if tag else "")
        st = e.get("state")
        if st:
            lines.append("- " + facts_mod.character_line(head, st))
        else:
            body = _clip(_body(e["text"]), 120)
            lines.append(f"- {head}" + (f"：{body}" if body else ""))
    if lines:
        parts.append("【人物局面】（想要什么 / 什么挡着 / 关系 / 知道什么）\n" + "\n".join(lines))

    opens = sorted((t for t in wb["threads"] if t["status"] == "open"), key=lambda t: -t["lastChapter"])
    if opens:
        parts.append("【未回收的伏笔】（最近有动静的在前）\n" + "\n".join(
            f"- {t['id']}：{t['text']}（第{t['plantedIn']}章埋下）" for t in opens[:SNAPSHOT_THREADS]))
    planned = sorted((t for t in wb["threads"] if t["status"] == "planned"), key=lambda t: t["plannedIn"] or 999)
    if planned:
        n = wb["chapter"]
        parts.append("【计划中的伏笔】（规划里定好、还没写出来的）\n" + "\n".join(
            f"- {t['id']}：{t['text']}（计划第{t['plannedIn'] or '?'}章埋" + (f"，第{t['payoffIn']}章收" if t["payoffIn"] else "") + "）"
            + ("【本章该埋】" if t["plannedIn"] == n else "【已超期】" if t["plannedIn"] and t["plannedIn"] < n else "")
            for t in planned[:10]))
    due = [t for t in wb["threads"] if t["status"] == "open" and t["planned"] and t["payoffIn"] and t["payoffIn"] <= wb["chapter"]]
    if due:
        parts.append("【计划该回收的伏笔】\n" + "\n".join(f"- {t['id']}：{t['text']}（计划第{t['payoffIn']}章收）" for t in due))
    clocks = [k for k in wb["clocks"] if k["status"] == "open"]
    if clocks:
        parts.append("【未到期的定时事件】\n" + "\n".join(f"- {facts_mod._clock_line(k)}" for k in clocks[-6:]))
    planned_clocks = [k for k in wb["clocks"] if k["status"] == "planned"]
    if planned_clocks:
        parts.append("【计划中的定时事件】\n" + "\n".join(
            f"- {k['text']}（计划第{k.get('plannedIn') or '?'}章定下" + (f"，第{k['dueIn']}章到期" if k.get("dueIn") else "") + "）"
            for k in planned_clocks[:6]))
    st = inspire._stage_text({**(wb.get("stage") or {}), "chapter": wb["chapter"]})
    if st:
        parts.append(st)
    if wb["outlineNext"]:
        parts.append("【大纲里接下来的章节】\n" + "\n".join(
            f"第{c['index']}章《{c.get('title', '')}》：{c.get('goal', '')}" for c in wb["outlineNext"]))
    story = wb["story"]
    recap = []
    if story["arcSummary"]:
        recap.append(f"（至第{story['arcUpTo']}章）{story['arcSummary']}")
    recap += [f"第{c['index']}章《{c['title']}》：{c['summary']}" for c in story["recent"]]
    if recap:
        parts.append("【前情】\n" + "\n".join(recap))
    rules = [e for e in wb["entries"] if e["kind"] != "character" and e["pinned"]]
    if rules:
        parts.append("【核心设定】\n" + "\n".join(_clip(e["text"], 400) for e in rules))
    others = [e for e in wb["entries"] if e["kind"] != "character" and not e["pinned"]]
    if others:
        parts.append("【其他设定】" + "；".join(
            f"{e['name']}" + ("（尚未登场，只能作传闻 / 伏笔）" if e["notYet"] else "") for e in others[:40]))
    text = "\n\n".join(parts)
    return text if len(text) <= max_chars else _shrink(parts, max_chars)


def _body(text: str) -> str:
    """去掉条目原文的【标题】行和「角色定位」（已经写在名字后面），留内容"""
    return "；".join(l.strip(" -") for l in (text or "").splitlines()
                    if l.strip() and not l.lstrip().startswith("【") and not l.strip(" -").startswith("角色定位："))


def _shrink(parts: list[str], max_chars: int) -> str:
    """超长时：前情先只留最近几章，再截断其他设定 / 核心设定"""
    out = list(parts)
    for i, p in enumerate(out):
        if p.startswith("【前情】"):
            lines = p.splitlines()
            out[i] = "\n".join([lines[0]] + lines[-5:])
    text = "\n\n".join(out)
    return text[:max_chars]
