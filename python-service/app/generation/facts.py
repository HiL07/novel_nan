"""故事账本：伏笔、角色状态、时间线（data/novels/<id>/facts.json，读写经 store.get_facts / save_facts）。

每章写完后由模型抽取「本章事实」（chapter._digest），merge() 合并进账本；每条记录都带来源章节：
- 删除最后一章 → drop_from(n) 回滚第 n 章及以后的记录
- 重新提取某章 → 先 drop_chapter(n) 去掉该章的旧记录再合并
- 一致性检查 / 规划只看「本章之前」的账本：view_before(n)
manual=True 的条目是作者手动新建 / 修改过的：AI 只追加历史，不改它的内容、状态。

本模块只做纯数据处理，不读写文件。
"""
import copy
import re

ACTIONS = ("plant", "advance", "resolve")
ACTION_LABEL = {"plant": "埋下", "advance": "推进", "resolve": "回收"}
MAX_FORESHADOWS, MAX_CHARACTERS, MAX_TIMELINE = 300, 300, 2000
MAX_TEXT = 300


def empty() -> dict:
    return {"foreshadows": [], "characters": {}, "timeline": []}


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
        out["foreshadows"].append({"id": fid, "text": _s(f.get("text")),
                                   "status": "resolved" if f.get("status") == "resolved" else "open",
                                   "plantedIn": _int(f.get("plantedIn")), "manual": bool(f.get("manual")),
                                   "history": sorted(hist, key=lambda h: h["chapter"])})
    chars = data.get("characters") or {}
    for name, c in list(chars.items())[:MAX_CHARACTERS] if isinstance(chars, dict) else []:
        name = _s(name, 40)
        if not name or not isinstance(c, dict):
            continue
        hist = [{"chapter": _int(h.get("chapter")), "change": _s(h.get("change")), "state": _s(h.get("state"))}
                for h in (c.get("history") or []) if isinstance(h, dict)]
        out["characters"][name] = {"state": _s(c.get("state")), "updatedIn": _int(c.get("updatedIn")),
                                   "manual": bool(c.get("manual")),
                                   "history": sorted(hist, key=lambda h: h["chapter"])}
    for t in (data.get("timeline") or [])[-MAX_TIMELINE:]:
        if isinstance(t, dict) and _s(t.get("event")):
            out["timeline"].append({"chapter": _int(t.get("chapter")), "when": _s(t.get("when"), 60),
                                    "event": _s(t.get("event")), "manual": bool(t.get("manual"))})
    out["timeline"].sort(key=lambda t: t["chapter"])
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
        f["status"] = "resolved" if any(h["action"] == "resolve" for h in f["history"]) else "open"


def _refresh_character(c: dict) -> None:
    c["history"].sort(key=lambda h: h["chapter"])
    if c["history"]:
        last = c["history"][-1]
        c["updatedIn"] = last["chapter"]
        if not c["manual"]:
            c["state"] = last["state"] or last["change"]


def _drop(facts: dict, keep) -> None:
    """只保留 keep(chapter) 为真的 AI 记录；没有任何历史、也不是手动建的条目随之删除。"""
    kept = []
    for f in facts["foreshadows"]:
        f["history"] = [h for h in f["history"] if keep(h["chapter"])]
        if f["history"] or f["manual"]:
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
        name, change = _s(it.get("name"), 40), _s(it.get("change"))
        if not name or not change:
            continue
        c = facts["characters"].get(name)
        if c is None:
            if len(facts["characters"]) >= MAX_CHARACTERS:
                continue
            c = facts["characters"][name] = {"state": "", "updatedIn": index, "manual": False, "history": []}
        c["history"].append({"chapter": index, "change": change, "state": _s(it.get("state"))})
        _refresh_character(c)
        applied["characters"].append({"name": name, "change": change, "state": c["state"]})
    for it in (data.get("timeline") or [])[:20]:
        if isinstance(it, dict) and _s(it.get("event")):
            t = {"chapter": index, "when": _s(it.get("when"), 60), "event": _s(it.get("event")), "manual": False}
            facts["timeline"].append(t)
            applied["timeline"].append({"when": t["when"], "event": t["event"]})
    facts["timeline"].sort(key=lambda t: t["chapter"])
    del facts["timeline"][:-MAX_TIMELINE]
    return applied


def open_foreshadows(facts: dict) -> list[dict]:
    return [f for f in facts["foreshadows"] if f["status"] == "open"]


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
    chars = sorted(facts["characters"].items(), key=lambda kv: -kv[1]["updatedIn"])[:max_characters]
    if chars:
        parts.append("角色当前状态：\n" + "\n".join(f"- {n}：{c['state'] or '（未记录）'}" for n, c in chars))
    return "\n\n".join(parts)


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
                     + "\n".join(f"- {n}（第{c['updatedIn']}章）：{c['state']}" for n, c in present[:max_characters]))
    if facts["timeline"]:
        parts.append("最近的时间线：\n" + "\n".join(
            f"- 第{t['chapter']}章{('·' + t['when']) if t['when'] else ''}：{t['event']}"
            for t in facts["timeline"][-max_timeline:]))
    return "\n".join(parts)
