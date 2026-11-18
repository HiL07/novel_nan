"""故事账本：伏笔、角色状态、时间线（data/novels/<id>/facts.json，读写经 store.get_facts / save_facts）。

每章写完后由模型抽取「本章事实」（chapter._digest），merge() 合并进账本；每条记录都带来源章节：
- 删除最后一章 → drop_from(n) 回滚第 n 章及以后的记录
- 重新提取某章 → 先 drop_chapter(n) 去掉该章的旧记录再合并
- 一致性检查 / 规划只看「本章之前」的账本：view_before(n)
manual=True 的条目是作者手动新建 / 修改过的：AI 只追加历史，不改它的内容、状态。

角色除了 state，还记局面（世界书的动态部分，供走向引擎看清「谁想要什么、谁挡着谁、谁知道什么」）：
goal 当前目标 / obstacle 阻碍（取历史里最近一次写了的）、relations 关系（按对象合并，后写的覆盖）、
knows 知道的关键信息 / 秘密（历史并集，最近的 MAX_LIST 条）。都记在 history 里，删章 / 重提取时一起回滚。
clocks = 定时炸弹（「三天后宗门大比」「月圆之夜毒发」）：埋下的章节 + 期限，到点或兑现后 done。

本模块只做纯数据处理，不读写文件。
"""
import copy
import re

ACTIONS = ("plant", "advance", "resolve")
ACTION_LABEL = {"plant": "埋下", "advance": "推进", "resolve": "回收"}
MAX_FORESHADOWS, MAX_CHARACTERS, MAX_TIMELINE, MAX_CLOCKS = 300, 300, 2000, 100
MAX_TEXT = 300
MAX_LIST = 10          # 每个角色最多记几条关系 / 已知信息
DYN_KEYS = ("goal", "obstacle", "relations", "knows")


def empty() -> dict:
    return {"foreshadows": [], "characters": {}, "timeline": [], "clocks": []}


def _dyn(h: dict) -> dict:
    """一条角色记录里的局面字段（规范化；空的不写）"""
    out = {}
    for k in ("goal", "obstacle"):
        if _s(h.get(k), 120):
            out[k] = _s(h.get(k), 120)
    rels = [{"to": _s(r.get("to"), 40), "rel": _s(r.get("rel"), 60)} for r in (h.get("relations") or [])
            if isinstance(r, dict) and _s(r.get("to"), 40) and _s(r.get("rel"), 60)][:MAX_LIST]
    if rels:
        out["relations"] = rels
    knows = [_s(k, 120) for k in (h.get("knows") or []) if isinstance(k, str) and _s(k, 120)][:MAX_LIST]
    if knows:
        out["knows"] = knows
    return out


def _s(v, n: int = MAX_TEXT) -> str:
    return str(v or "").strip()[:n]


def _int(v) -> int:
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0


def _norm(text: str) -> str:
    return re.sub(r"[\s，。、！？!?,.：:；;“”\"'「」『』（）()]", "", text or "")


def sanitize(data: dict | None) -> dict:
    """规范化账本（读取旧文件 / 作者手动保存时用）：补齐字段、截断长度、丢掉格式不对的条目。"""
    data = data if isinstance(data, dict) else {}
    out = empty()
    seen = set()
    for f in (data.get("foreshadows") or [])[:MAX_FORESHADOWS]:
        if not isinstance(f, dict) or not _s(f.get("text")):
            continue
        fid = _s(f.get("id"), 20) or _next_id(out)
        if fid in seen:
            fid = _next_id(out)
        seen.add(fid)
        hist = [{"chapter": _int(h.get("chapter")), "action": h.get("action") if h.get("action") in ACTIONS else "advance",
                 "note": _s(h.get("note"))} for h in (f.get("history") or []) if isinstance(h, dict)]
        status = f.get("status") if f.get("status") in ("resolved", "planned") else "open"
        entry = {"id": fid, "text": _s(f.get("text")), "status": status,
                 "plantedIn": _int(f.get("plantedIn")), "manual": bool(f.get("manual")),
                 "history": sorted(hist, key=lambda h: h["chapter"])}
        if f.get("planned") or status == "planned":
            entry.update(planned=True, plannedIn=_int(f.get("plannedIn")), payoffIn=_int(f.get("payoffIn")))
        out["foreshadows"].append(entry)
    chars = data.get("characters") or {}
    for name, c in list(chars.items())[:MAX_CHARACTERS] if isinstance(chars, dict) else []:
        name = _s(name, 40)
        if not name or not isinstance(c, dict):
            continue
        hist = [{"chapter": _int(h.get("chapter")), "change": _s(h.get("change")), "state": _s(h.get("state")), **_dyn(h)}
                for h in (c.get("history") or []) if isinstance(h, dict)]
        entry = {"state": _s(c.get("state")), "updatedIn": _int(c.get("updatedIn")), "manual": bool(c.get("manual")),
                 "history": sorted(hist, key=lambda h: h["chapter"])}
        entry.update({"goal": "", "obstacle": "", "relations": [], "knows": []} | _dyn(c))
        out["characters"][name] = entry
    for t in (data.get("timeline") or [])[-MAX_TIMELINE:]:
        if isinstance(t, dict) and _s(t.get("event")):
            out["timeline"].append({"chapter": _int(t.get("chapter")), "when": _s(t.get("when"), 60),
                                    "event": _s(t.get("event")), "manual": bool(t.get("manual"))})
    out["timeline"].sort(key=lambda t: t["chapter"])
    for k in (data.get("clocks") or [])[-MAX_CLOCKS:]:
        if isinstance(k, dict) and _s(k.get("text")):
            status = k.get("status") if k.get("status") in ("done", "planned") else "open"
            clock = {"chapter": _int(k.get("chapter")), "text": _s(k.get("text"), 120),
                     "due": _s(k.get("due"), 60), "status": status,
                     "doneIn": _int(k.get("doneIn")), "manual": bool(k.get("manual"))}
            if k.get("planned") or status == "planned":
                clock.update(planned=True, plannedIn=_int(k.get("plannedIn")), dueIn=_int(k.get("dueIn")))
            out["clocks"].append(clock)
    return out


def _next_id(facts: dict) -> str:
    nums = [int(m.group(1)) for f in facts["foreshadows"] if (m := re.fullmatch(r"F(\d+)", f["id"]))]
    return f"F{max(nums, default=0) + 1}"


def _refresh_foreshadow(f: dict) -> None:
    """按历史重算埋下章节与状态（manual 条目保持作者设定的状态）。"""
    f["history"].sort(key=lambda h: h["chapter"])
    if f["history"] and (not f["manual"] or not f["plantedIn"]):
        f["plantedIn"] = f["history"][0]["chapter"]
    if not f["manual"]:
        if any(h["action"] == "resolve" for h in f["history"]):
            f["status"] = "resolved"
        elif f["history"] or not f.get("planned"):
            f["status"] = "open"
        else:   # 规划里的伏笔还没写到：保持「计划中」（删章 / 重新提取回滚后也回到这里）
            f["status"], f["plantedIn"] = "planned", 0


def _refresh_character(c: dict) -> None:
    c["history"].sort(key=lambda h: h["chapter"])
    if c["history"]:
        c["updatedIn"] = c["history"][-1]["chapter"]
        if not c["manual"]:   # 只更新了目标 / 关系的那章不清空状态：取最近一条写了状态的
            c["state"] = next((h["state"] or h["change"] for h in reversed(c["history"]) if h["state"] or h["change"]), "")
    if c.get("manual"):
        for k, empty_v in (("goal", ""), ("obstacle", ""), ("relations", []), ("knows", [])):
            c.setdefault(k, empty_v)
        return
    goal = obstacle = ""
    rels: dict[str, str] = {}
    knows: list[str] = []
    for h in c["history"]:
        goal = h.get("goal") or goal
        obstacle = h.get("obstacle") or obstacle
        for r in h.get("relations") or []:
            rels.pop(r["to"], None)   # 后写的排到最后
            rels[r["to"]] = r["rel"]
        for k in h.get("knows") or []:
            if k not in knows:
                knows.append(k)
    c["goal"], c["obstacle"] = goal, obstacle
    c["relations"] = [{"to": t, "rel": r} for t, r in list(rels.items())[-MAX_LIST:]]
    c["knows"] = knows[-MAX_LIST:]


def _drop(facts: dict, keep) -> None:
    """只保留 keep(chapter) 为真的 AI 记录；没有任何历史、也不是手动建的条目随之删除。"""
    kept = []
    for f in facts["foreshadows"]:
        f["history"] = [h for h in f["history"] if keep(h["chapter"])]
        if f["history"] or f["manual"] or f.get("planned"):
            _refresh_foreshadow(f)
            kept.append(f)
    facts["foreshadows"] = kept
    for name in list(facts["characters"]):
        c = facts["characters"][name]
        c["history"] = [h for h in c["history"] if keep(h["chapter"])]
        if c["history"] or c["manual"]:
            _refresh_character(c)
        else:
            del facts["characters"][name]
    facts["timeline"] = [t for t in facts["timeline"] if t.get("manual") or keep(t["chapter"])]
    clocks = []
    for k in facts.setdefault("clocks", []):
        if k.get("planned") and k["chapter"] and not keep(k["chapter"]) and not k.get("manual"):
            k.update(status="planned", chapter=0, doneIn=0)   # 规划的定时事件：定下它的那章没了 → 回到计划中
            clocks.append(k)
            continue
        if not (k.get("manual") or keep(k["chapter"]) or (k.get("planned") and not k["chapter"])):
            continue
        if k.get("doneIn") and not keep(k["doneIn"]) and not k.get("manual"):
            k["status"], k["doneIn"] = "open", 0
        clocks.append(k)
    facts["clocks"] = clocks


def drop_chapter(facts: dict, index: int) -> None:
    _drop(facts, lambda ch: ch != index)


def drop_from(facts: dict, index: int) -> None:
    """删除第 index 章（及以后）时回滚。"""
    _drop(facts, lambda ch: ch < index)


def view_before(facts: dict, index: int) -> dict:
    """第 index 章之前的账本（副本）。"""
    f = copy.deepcopy(facts)
    drop_from(f, index)
    return f


def _find_foreshadow(facts: dict, fid: str, text: str) -> dict | None:
    if fid:
        hit = next((f for f in facts["foreshadows"] if f["id"].upper() == fid.upper()), None)
        if hit:
            return hit
    key = _norm(text)
    if len(key) < 4:
        return None
    return next((f for f in facts["foreshadows"]
                 if (k := _norm(f["text"])) and (key in k or k in key)), None)


def merge(facts: dict, index: int, data: dict) -> dict:
    """把第 index 章抽取出的事实合并进账本（先去掉该章的旧记录，可重复执行）。
    data: {foreshadow:[{id?, text, action, note?}], characters:[{name, change, state?}], timeline:[{when, event}]}
    返回规范化后的「本章事实变化」（新伏笔已分配 id），存在章节的 facts 字段上供界面展示。"""
    drop_chapter(facts, index)
    applied = {"foreshadow": [], "characters": [], "timeline": []}
    for it in (data.get("foreshadow") or [])[:20]:
        if not isinstance(it, dict):
            continue
        action = it.get("action") if it.get("action") in ACTIONS else "advance"
        text, note = _s(it.get("text")), _s(it.get("note"))
        hit = _find_foreshadow(facts, _s(it.get("id"), 20), text)
        if hit is None:
            if action == "resolve" or not text or len(facts["foreshadows"]) >= MAX_FORESHADOWS:
                continue  # 回收一个账本里没有的伏笔：无从对应，跳过
            hit = {"id": _next_id(facts), "text": text, "status": "open", "plantedIn": index, "manual": False,
                   "history": []}
            facts["foreshadows"].append(hit)
            action = "plant"
        hit["history"].append({"chapter": index, "action": action, "note": note or text})
        _refresh_foreshadow(hit)
        applied["foreshadow"].append({"id": hit["id"], "text": hit["text"], "action": action, "note": note})
    for it in (data.get("characters") or [])[:30]:
        if not isinstance(it, dict):
            continue
        name, change, dyn = _s(it.get("name"), 40), _s(it.get("change")), _dyn(it)
        if not name or not (change or dyn):
            continue
        c = facts["characters"].get(name)
        if c is None:
            if len(facts["characters"]) >= MAX_CHARACTERS:
                continue
            c = facts["characters"][name] = {"state": "", "updatedIn": index, "manual": False, "history": []}
        c["history"].append({"chapter": index, "change": change, "state": _s(it.get("state")), **dyn})
        _refresh_character(c)
        applied["characters"].append({"name": name, "change": change, "state": c["state"], **dyn})
    applied["clocks"] = []
    clocks = facts.setdefault("clocks", [])
    for it in (data.get("clocks") or [])[:5]:
        if not isinstance(it, dict) or not _s(it.get("text"), 120):
            continue
        text, key = _s(it.get("text"), 120), _norm(it.get("text"))
        hit = next((k for k in clocks if k["status"] in ("open", "planned") and (n := _norm(k["text"])) and (key in n or n in key)),
                   None)
        if it.get("action") == "done":
            if hit and not hit.get("manual"):
                if hit["status"] == "planned":
                    hit["chapter"] = index
                hit["status"], hit["doneIn"] = "done", index
                applied["clocks"].append({"text": hit["text"], "action": "done"})
            continue
        if hit is not None and hit["status"] == "planned":   # 规划里的定时事件这章定下了
            hit["status"], hit["chapter"] = "open", index
            hit["due"] = hit["due"] or _s(it.get("due"), 60)
            applied["clocks"].append({"text": hit["text"], "due": hit["due"], "action": "set"})
        elif hit is None and len(clocks) < MAX_CLOCKS:
            clocks.append({"chapter": index, "text": text, "due": _s(it.get("due"), 60), "status": "open",
                           "doneIn": 0, "manual": False})
            applied["clocks"].append({"text": text, "due": _s(it.get("due"), 60), "action": "set"})
    for it in (data.get("timeline") or [])[:20]:
        if isinstance(it, dict) and _s(it.get("event")):
            t = {"chapter": index, "when": _s(it.get("when"), 60), "event": _s(it.get("event")), "manual": False}
            facts["timeline"].append(t)
            applied["timeline"].append({"when": t["when"], "event": t["event"]})
    facts["timeline"].sort(key=lambda t: t["chapter"])
    del facts["timeline"][:-MAX_TIMELINE]
    return applied


def add_situation(facts: dict, index: int, data: dict) -> dict:
    """「整理局面」的结果（主要人物的 目标 / 阻碍 / 关系 / 已知信息 + 定时事件）记成第 index 章的 AI 记录，
    不动该章已有的记录（不像 merge 那样先清掉本章）。"""
    applied = {"characters": [], "clocks": []}
    for it in (data.get("characters") or [])[:12]:
        if not isinstance(it, dict):
            continue
        name, dyn = _s(it.get("name"), 40), _dyn(it)
        if not name or not dyn:
            continue
        c = facts["characters"].get(name)
        if c is None:
            if len(facts["characters"]) >= MAX_CHARACTERS:
                continue
            c = facts["characters"][name] = {"state": "", "updatedIn": index, "manual": False, "history": []}
        c["history"].append({"chapter": index, "change": "", "state": "", **dyn})
        _refresh_character(c)
        applied["characters"].append({"name": name, **dyn})
    clocks = facts.setdefault("clocks", [])
    for it in (data.get("clocks") or [])[:6]:
        text = _s((it or {}).get("text"), 120) if isinstance(it, dict) else ""
        if text and len(clocks) < MAX_CLOCKS and not any(_norm(k["text"]) == _norm(text) for k in clocks):
            clocks.append({"chapter": index, "text": text, "due": _s(it.get("due"), 60), "status": "open",
                           "doneIn": 0, "manual": False})
            applied["clocks"].append({"text": text, "due": _s(it.get("due"), 60)})
    return applied


def open_foreshadows(facts: dict) -> list[dict]:
    return [f for f in facts["foreshadows"] if f["status"] == "open"]


def planned_foreshadows(facts: dict) -> list[dict]:
    return sorted((f for f in facts["foreshadows"] if f["status"] == "planned"), key=lambda f: f.get("plannedIn") or 999)


# ---------------------------------------------------------------- 规划（自动规划写进来的计划，见 planner.py）

def add_plan(facts: dict, foreshadows: list[dict], clocks: list[dict]) -> dict[str, str]:
    """把规划里的伏笔 / 定时事件记成「计划中」：foreshadows [{key, text, plantIn, payoffIn}]、clocks [{key, text, due, setIn, dueIn}]
    → {规划里的 key: 账本编号}（伏笔 F<n>；定时事件用 C:<文字>）。同文的已有条目不重复建。"""
    ids: dict[str, str] = {}
    for p in foreshadows[:40]:
        text, key = _s(p.get("text")), _s(p.get("key"), 20)
        if not text:
            continue
        hit = _find_foreshadow(facts, "", text)
        if hit is None and len(facts["foreshadows"]) < MAX_FORESHADOWS:
            hit = {"id": _next_id(facts), "text": text, "status": "planned", "plantedIn": 0, "manual": False,
                   "history": [], "planned": True}
            facts["foreshadows"].append(hit)
        if hit is None:
            continue
        if hit["status"] == "planned":
            hit.update(planned=True, plannedIn=_int(p.get("plantIn")), payoffIn=_int(p.get("payoffIn")))
        if key:
            ids[key] = hit["id"]
    clocks_list = facts.setdefault("clocks", [])
    for p in clocks[:20]:
        text, key = _s(p.get("text"), 120), _s(p.get("key"), 20)
        if not text:
            continue
        hit = next((k for k in clocks_list if _norm(k["text"]) == _norm(text)), None)
        if hit is None and len(clocks_list) < MAX_CLOCKS:
            hit = {"chapter": 0, "text": text, "due": _s(p.get("due"), 60), "status": "planned", "doneIn": 0,
                   "manual": False, "planned": True}
            clocks_list.append(hit)
        if hit is not None and hit["status"] == "planned":
            hit.update(plannedIn=_int(p.get("setIn")), dueIn=_int(p.get("dueIn")))
        if hit is not None and key:
            ids[key] = "C:" + hit["text"]
    return ids


def sync_outline(facts: dict, outline: dict | None) -> None:
    """大纲里改了计划章节 = 改账本：还没写到的（planned）伏笔按大纲每章的引用重算 plannedIn（第一次 plant）/ payoffIn（resolve）。"""
    plant, payoff = {}, {}
    for c in (outline or {}).get("chapters") or []:
        for r in c.get("foreshadow") or []:
            fid = str(r.get("id") or "").upper()
            if r.get("action") == "plant":
                plant.setdefault(fid, c["index"])
            elif r.get("action") == "resolve":
                payoff[fid] = c["index"]
    for f in facts["foreshadows"]:
        fid = f["id"].upper()
        if f["status"] == "planned" and (fid in plant or fid in payoff):
            f["plannedIn"] = plant.get(fid, f.get("plannedIn") or 0)
            f["payoffIn"] = payoff.get(fid, f.get("payoffIn") or 0)


def check_outline(facts: dict, outline: dict | None, written: int) -> list[str]:
    """大纲和账本对不上的地方（世界书页提示）：引用了不存在的伏笔、计划章节两边不一致、过了预计章节还没埋 / 没收。"""
    by_id = {f["id"].upper(): f for f in facts["foreshadows"]}
    out, plant = [], {}
    for c in (outline or {}).get("chapters") or []:
        for r in c.get("foreshadow") or []:
            fid = str(r.get("id") or "").upper()
            if fid and fid not in by_id:
                out.append(f"大纲第{c['index']}章引用的伏笔 {fid} 在账本里不存在")
            elif r.get("action") == "plant":
                plant.setdefault(fid, c["index"])
    for fid, ch in plant.items():
        f = by_id.get(fid)
        if f and f["status"] == "planned" and f.get("plannedIn") and f["plannedIn"] != ch:
            out.append(f"{fid}：大纲计划第{ch}章埋，账本记的是第{f['plannedIn']}章")
    for f in facts["foreshadows"]:
        if f["status"] == "planned" and f.get("plannedIn") and f["plannedIn"] <= written:
            out.append(f"{f['id']}「{_s(f['text'], 30)}」计划第{f['plannedIn']}章埋，已写到第{written}章还没埋")
        if f.get("planned") and f["status"] == "open" and f.get("payoffIn") and f["payoffIn"] <= written:
            out.append(f"{f['id']}「{_s(f['text'], 30)}」预计第{f['payoffIn']}章回收，已写到第{written}章还没收")
    return out[:30]


def _foreshadow_line(f: dict) -> str:
    moves = [f"第{h['chapter']}章{ACTION_LABEL[h['action']]}" for h in f["history"]][-3:]
    where = "，".join(moves) or "第{}章埋下".format(f["plantedIn"])
    return f"{f['id']}：{f['text']}（{where}）"


def known_lines(facts: dict, max_foreshadows: int = 30, max_characters: int = 30) -> str:
    """供「抽取本章事实」参考的已有账本（让模型引用已有伏笔 id、沿用角色名）。"""
    parts = []
    opens = open_foreshadows(facts)[-max_foreshadows:]
    if opens:
        parts.append("未回收的伏笔：\n" + "\n".join(f"- {f['id']}：{f['text']}" for f in opens))
    planned = planned_foreshadows(facts)[:15]
    if planned:   # 规划里的伏笔：本章写出来了就用 action=plant 并填这个编号，转成已埋下
        parts.append("规划中、还没写出来的伏笔（本章埋下了就填这个编号，action=plant）：\n"
                     + "\n".join(f"- {f['id']}：{f['text']}" + (f"（计划第{f['plannedIn']}章埋）" if f.get("plannedIn") else "")
                                 for f in planned))
    chars = sorted(facts["characters"].items(), key=lambda kv: -kv[1]["updatedIn"])[:max_characters]
    if chars:
        parts.append("角色当前状态：\n" + "\n".join(f"- {n}：{c['state'] or '（未记录）'}"
                                              + (f"；目标：{c['goal']}" if c.get("goal") else "") for n, c in chars))
    clocks = open_clocks(facts)
    if clocks:
        parts.append("未到期的定时事件：\n" + "\n".join(f"- {_clock_line(k)}" for k in clocks[-10:]))
    return "\n\n".join(parts)


def open_clocks(facts: dict) -> list[dict]:
    return [k for k in facts.get("clocks") or [] if k["status"] == "open"]


def _clock_line(k: dict) -> str:
    return f"{k['text']}" + (f"（期限：{k['due']}）" if k.get("due") else "") + f"（第{k['chapter']}章定下）"


def character_line(name: str, c: dict) -> str:
    """角色的局面一行：状态 + 目标 / 阻碍 + 关系 + 知道的秘密（世界书 / 走向引擎用）"""
    bits = [c.get("state") or "（状态未记录）"]
    if c.get("goal"):
        bits.append(f"想要：{c['goal']}")
    if c.get("obstacle"):
        bits.append(f"阻碍：{c['obstacle']}")
    if c.get("relations"):
        bits.append("关系：" + "，".join(f"{r['to']}（{r['rel']}）" for r in c["relations"][-5:]))
    if c.get("knows"):
        bits.append("知道：" + "；".join(c["knows"][-4:]))
    return f"{name}：" + "｜".join(bits)


def context_text(facts: dict, haystack: str, *, max_foreshadows: int = 10, max_characters: int = 8,
                 max_timeline: int = 5) -> str:
    """写作时注入上下文的账本：未回收伏笔（最近活动的优先）+ 本章出场角色的最新状态 + 最近的时间线。"""
    parts = []
    opens = sorted(open_foreshadows(facts), key=lambda f: -(f["history"][-1]["chapter"] if f["history"] else 0))
    if opens:
        parts.append("未回收的伏笔（后文要照应，不要遗忘或写出矛盾）：\n"
                     + "\n".join("- " + _foreshadow_line(f) for f in opens[:max_foreshadows]))
    present = [(n, c) for n, c in facts["characters"].items() if c["state"] and n in haystack]
    present.sort(key=lambda nc: -nc[1]["updatedIn"])
    if present:
        parts.append("本章相关角色的当前状态：\n"
                     + "\n".join(f"- {n}（第{c['updatedIn']}章）：{c['state']}"
                                 + (f"；目标：{c['goal']}" if c.get("goal") else "")
                                 + (f"；阻碍：{c['obstacle']}" if c.get("obstacle") else "")
                                 for n, c in present[:max_characters]))
    clocks = open_clocks(facts)
    if clocks:
        parts.append("未到期的定时事件（到期前要照应）：\n" + "\n".join(f"- {_clock_line(k)}" for k in clocks[-5:]))
    if facts["timeline"]:
        parts.append("最近的时间线：\n" + "\n".join(
            f"- 第{t['chapter']}章{('·' + t['when']) if t['when'] else ''}：{t['event']}"
            for t in facts["timeline"][-max_timeline:]))
    return "\n".join(parts)
