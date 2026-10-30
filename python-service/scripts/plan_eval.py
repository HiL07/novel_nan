"""自动规划评测：同一句构思、同一批素材，比较「自动规划」（planner：设定草案 + 10 章大纲 + 伏笔计划 + 审稿修正）
和原来的「生成大纲」（AI 构思 kind=outline，构思方向 = 这句构思）。只评规划内容，不生成正文。

走测试端口的 HTTP 接口（Java 8012 → Python 8011，数据副本），每个构思新建一个空工作区（= 开篇）：
  新：needs → retrieve（过线的素材全用）→ settings → outline → review（全部采用修正）
  旧：同一批素材 id，generateIdeas kind=outline count=10
裁判 = DeepSeek（直接调，key 同 retrieval_eval）：每份规划打 合理 / 精彩 / 开篇 / 人物 / 伏笔 1–5，整份两两比较（位置随机）；
代码再数：开篇前 3 章每章新出场人物（新方案有 cast；旧方案从目标文字里数设定外的人名做不到，只比新方案自身）、章末钩子。

用法：.venv/Scripts/python scripts/plan_eval.py --out <目录> [--premise 法师喜欢冒险 --premise …]

--compare story：比较两条路线（docs/自动规划.md「故事优先」）——
  story   = 故事优先·零素材：idea（取第一个灵感）→ book → settings → outline → review（全部采用修正）
  enrich  = 同一份故事优先设定 + 素材点睛（全部采用）→ outline → review
  material= 素材优先（上面的「新」）
写作参数只给 目标字数 100 万 / 单章 3000（不给题材等，免得比素材优先多出信息）；裁判对三份分别打分，再两两比较。
"""
import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

J, P = "http://localhost:8012", "http://localhost:8011"
MODEL = {"source": "api"}
PREMISES = ["法师喜欢冒险", "废柴少年靠收破烂逆袭", "被退婚的大小姐开了家侦探社", "末世里开奶茶店的普通人"]
c = httpx.Client(timeout=400, trust_env=False)


def call(url, body=None):
    r = c.post(url, json=body) if body is not None else c.get(url)
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"{url} 失败：{r.status_code} {d.get('message')}")
    return d["data"]


def run_new(nid: str, premise: str) -> dict:
    t0 = time.time()
    needs = call(f"{J}/api/novel/plan/{nid}/needs", {"premise": premise, "model": MODEL})
    ret = call(f"{J}/api/novel/plan/{nid}/retrieve", {"needs": needs["needs"], "stage": needs["stage"]})
    items = [it for g in ret["groups"] for it in g["items"] if it.get("from") != "weak"]
    ids = [it["material"]["id"] for it in items][:20]
    variants = {str(it["material"]["id"]): it["variant"] for it in items if it.get("variant")}
    base = {"premise": premise, "stage": needs["stage"], "model": MODEL}
    st = call(f"{J}/api/novel/plan/{nid}/settings", {**base, "materialIds": ids, "materialVariants": variants})
    ol = call(f"{J}/api/novel/plan/{nid}/outline", {**base, "settings": st["draft"], "materialIds": ids})
    rv = call(f"{J}/api/novel/plan/{nid}/review", {**base, "settings": st["draft"], "outline": ol["outline"]})
    outline = json.loads(json.dumps(ol["outline"]))
    for r in rv["chapters"]:   # 全部采用修正（= 一键全自动）
        ch = next((x for x in outline["chapters"] if x["index"] == r["index"]), None)
        if ch and r.get("revised"):
            ch.update({k: v for k, v in r["revised"].items() if v})
    usage = [x.get("usage") or {} for x in (needs, st, ol, rv)]
    return {"ids": ids, "variants": variants, "settings": st, "outline": outline, "outlineIssues": ol["issues"],
            "review": rv, "seconds": round(time.time() - t0), "tokens": sum(u.get("promptTokens", 0) + u.get("completionTokens", 0) for u in usage)}


STORY_CONFIG = {"targetWords": "100万字", "chapterWords": "3000字"}


def _adopt(outline: dict, review: dict) -> dict:
    outline = json.loads(json.dumps(outline))
    for r in review["chapters"]:   # 全部采用修正（= 一键全自动）
        ch = next((x for x in outline["chapters"] if x["index"] == r["index"]), None)
        if ch and r.get("revised"):
            ch.update({k: v for k, v in r["revised"].items() if v})
    return outline


def run_story(nid: str, premise: str, enrich_nid: str | None) -> dict:
    """故事优先·零素材；enrich_nid 给了就在另一个工作区用同一份设定加素材点睛（全采用）再出大纲，作对照"""
    t0 = time.time()
    base = {"mode": "story", "premise": premise, "bookConfig": STORY_CONFIG, "model": MODEL}
    idea = call(f"{J}/api/novel/plan/{nid}/idea", {**base, "count": 3})
    base["idea"] = idea["ideas"][0]
    bk = call(f"{J}/api/novel/plan/{nid}/book", base)
    base["book"] = bk["book"]
    st = call(f"{J}/api/novel/plan/{nid}/settings", {**base, "materialIds": []})
    calls = [idea, bk, st]

    def finish(target_nid, draft, extra_calls, start):
        ol = call(f"{J}/api/novel/plan/{target_nid}/outline", {**base, "settings": draft, "materialIds": [], "count": 10})
        rv = call(f"{J}/api/novel/plan/{target_nid}/review", {**base, "settings": draft, "outline": ol["outline"]})
        usage = [x.get("usage") or {} for x in calls + extra_calls + [ol, rv]]
        return {"settings": {**st, "draft": draft}, "book": bk["book"], "outline": _adopt(ol["outline"], rv),
                "outlineIssues": ol["issues"], "review": rv, "seconds": round(time.time() - start),
                "tokens": sum(u.get("promptTokens", 0) + u.get("completionTokens", 0) for u in usage)}

    story = finish(nid, st["draft"], [], t0)
    out = {"story": story}
    if enrich_nid:
        t1 = time.time()
        en = call(f"{J}/api/novel/plan/{enrich_nid}/enrich", {**base, "settings": st["draft"]})
        draft = json.loads(json.dumps(st["draft"]))
        for s in en.get("suggestions") or []:
            obj = (draft["characters"] if s["kind"] == "character" else draft["elements"])[s["index"]]
            target = obj if s["kind"] == "character" else obj.setdefault("fields", {})
            for k, v in s["fields"].items():
                if isinstance(v, list) or isinstance(target.get(k), list):
                    target[k] = list(dict.fromkeys((target.get(k) or []) + (v if isinstance(v, list) else [v])))
                else:
                    target[k] = f"{target[k]}；{v}" if target.get(k) else v
        r = finish(enrich_nid, draft, [en], t1)
        r["seconds"] += story["seconds"]   # 点睛组 = 故事优先的前几步 + 点睛 + 大纲 / 审稿
        r["enriched"] = len(en.get("suggestions") or [])
        out["enrich"] = r
    return out


def render_story(x: dict) -> str:
    from app.generation import planner
    return "【全书骨架】\n" + planner.book_text(x["book"], detail=False) + "\n" + render_new(x)


def compare_story(premises: list[str], out: Path) -> None:
    from retrieval_eval import model_cfg
    cfg = model_cfg()
    usage: dict = {}
    runs_f = out / "story-runs.json"
    runs = json.loads(runs_f.read_text(encoding="utf-8")) if runs_f.exists() else {}
    novel = lambda tag, p: call(f"{P}/api/gen/novels", {"title": f"规划评测 {tag} {p}",  # noqa: E731
                                                       "model": {"source": "api", "apiName": "DeepSeek"}, "contextWindow": 32768})["id"]

    def one(p):
        if p in runs:
            return p, runs[p]
        try:
            r = run_story(novel("故事", p), p, novel("点睛", p))
            r["material"] = run_new(novel("素材", p), p)
            print(f"  {p}：故事 {r['story']['seconds']}s / {r['story']['tokens']} token；点睛 {r['enrich']['enriched']} 条；"
                  f"素材 {r['material']['seconds']}s / {r['material']['tokens']} token / {len(r['material']['ids'])} 条素材")
            return p, r
        except Exception as e:  # noqa: BLE001 —— 一个构思失败不影响其他的
            print(f"  ! {p} 失败：{e}")
            return p, None

    with ThreadPoolExecutor(2) as ex:
        for p, r in ex.map(one, premises):
            if r:
                runs[p] = r
                runs_f.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    if not runs:
        raise SystemExit("没有成功的构思")

    systems = {"story": ("故事优先·零素材", render_story), "enrich": ("故事优先 + 点睛", render_story),
               "material": ("素材优先", render_new)}
    scores = {s: [] for s in systems}
    texts = {p: {s: fn(r[s]) for s, (_, fn) in systems.items()} for p, r in runs.items()}
    for p in runs:
        for s in systems:
            scores[s].append(judge_one(p, texts[p][s], cfg, usage))
    rnd = random.Random(7)
    pairs = {("story", "material"): [], ("enrich", "story"): []}
    for (a, b), lst in pairs.items():
        for p in runs:
            flip = rnd.random() < 0.5
            res = judge_pair(p, texts[p][b] if flip else texts[p][a], texts[p][a] if flip else texts[p][b], cfg, usage)
            win = lambda v: {"A": b, "B": a}.get(v, "tie") if flip else {"A": a, "B": b}.get(v, "tie")  # noqa: E731
            lst.append({"premise": p, **{k: win(res.get(k)) for k in ("reasonable", "exciting", "opening", "overall")},
                        "why": res.get("why")})

    keys = ("reasonable", "exciting", "opening", "characters", "foreshadow", "usable")
    L = [f"# 故事优先 vs 素材优先（{time.strftime('%Y-%m-%d %H:%M')}，{len(runs)} 个构思）", "",
         "| 方案 | 自洽 | 精彩 | 开篇 | 人物 | 伏笔 | 可用 | 平均耗时 | 平均 token |", "|---|" + "---|" * 8]
    for s, (label, _) in systems.items():
        rows = scores[s]
        mean = lambda k: sum(float(x.get(k) or 0) for x in rows) / max(1, len(rows))  # noqa: E731
        sec = sum(r[s]["seconds"] for r in runs.values()) / len(runs)
        tok = sum(r[s]["tokens"] for r in runs.values()) / len(runs)
        L.append(f"| {label} | " + " | ".join(f"{mean(k):.2f}" for k in keys) + f" | {sec:.0f}s | {tok:.0f} |")
    for (a, b), lst in pairs.items():
        L += ["", f"| {systems[a][0]} vs {systems[b][0]} | {systems[a][0]}胜 | {systems[b][0]}胜 | 平 |", "|---|---|---|---|"]
        for k, lab in (("reasonable", "自洽"), ("exciting", "精彩"), ("opening", "开篇"), ("overall", "总体")):
            L.append(f"| {lab} | {sum(x[k] == a for x in lst)} | {sum(x[k] == b for x in lst)} | {sum(x[k] == 'tie' for x in lst)} |")
    L += ["", "## 裁判评语"]
    for i, p in enumerate(runs):
        L.append(f"- {p}｜" + "｜".join(f"{systems[s][0]}：{scores[s][i].get('comment')}" for s in systems))
        for (a, b), lst in pairs.items():
            L.append(f"  - {systems[a][0]} vs {systems[b][0]}：{lst[i]['overall']}，{lst[i].get('why')}")
    report = "\n".join(L)
    (out / "story-report.md").write_text(report, encoding="utf-8")
    print(report)
    print("裁判 token：", usage)


def run_old(nid: str, premise: str, ids: list[int], variants: dict) -> dict:
    t0 = time.time()
    d = call(f"{J}/api/novel/gen/{nid}/ideas", {"kind": "outline", "source": "api", "hint": premise, "count": 10,
                                               "materialIds": ids, "materialVariants": variants, "autoMaterials": False})
    u = d.get("usage") or {}
    return {"outline": d["result"], "seconds": round(time.time() - t0), "tokens": u.get("promptTokens", 0) + u.get("completionTokens", 0)}


def render_new(x: dict) -> str:
    from app.generation import planner
    o = x["outline"]
    lines = ["【设定】", planner._settings_text(x["settings"]["draft"]), f"【一句话】{o['logline']}", f"【梗概】{o['synopsis']}"]
    for ch in o["chapters"]:
        lines.append(f"第{ch['index']}章《{ch['title']}》：{ch['goal']}（节拍：{'；'.join(ch.get('beats') or [])}｜钩子：{ch.get('hook') or ''}）")
    lines.append("【伏笔计划】" + "；".join(f"{f['text']}（第{f['plantIn']}章埋，第{f['payoffIn'] or '之后'}章收）" for f in o["foreshadows"]))
    return "\n".join(lines)


def render_old(x: dict) -> str:
    o = x["outline"]
    lines = [f"【一句话】{o.get('logline', '')}", f"【梗概】{o.get('synopsis', '')}"]
    lines += [f"第{ch['index']}章《{ch.get('title', '')}》：{ch.get('goal', '')}" for ch in o.get("chapters", [])]
    return "\n".join(lines)


JUDGE_SYSTEM = "你是资深网络小说主编，评审新书的开书规划（设定 + 前 10 章大纲）。评分要严格、拉开差距。只输出 JSON。"


def judge_one(premise: str, text: str, cfg, usage) -> dict:
    from retrieval_eval import llm_json
    user = (f"作者的构思：{premise}\n\n【规划】\n{text}\n\n按 1–5 分评审（5 最好）：\n"
            "- reasonable 自洽：人物动机、世界规则、情节因果是否成立，前后不矛盾\n"
            "- exciting 精彩：冲突强度、悬念、爽点 / 情绪点，读者会不会追\n"
            "- opening 开篇：第 1 章是否开场就有冲突、主角欲望和缺陷是否清楚、前 3 章是否确立核心卖点、信息量是否压得住\n"
            "- characters 人物：主要人物是否鲜明、各有所求\n"
            "- foreshadow 伏笔：长线悬念的埋设与回收是否有设计\n"
            "- usable 可用性：作者拿着这份规划能不能直接开写\n"
            '输出 {"reasonable": 3, "exciting": 3, "opening": 3, "characters": 3, "foreshadow": 3, "usable": 3, "comment": "一句话"}')
    return llm_json(cfg, JUDGE_SYSTEM, user, usage, 600) or {}


def judge_pair(premise: str, a: str, b: str, cfg, usage) -> dict:
    from retrieval_eval import llm_json
    user = (f"作者的构思：{premise}\n\n【规划 A】\n{a}\n\n【规划 B】\n{b}\n\n作为作者，你更想拿哪一份开写？"
            "分别比较 reasonable 自洽、exciting 精彩、opening 开篇、overall 总体，每项填 \"A\"、\"B\" 或 \"tie\"。"
            '输出 {"reasonable": "A", "exciting": "B", "opening": "A", "overall": "A", "why": "一句话"}')
    return llm_json(cfg, JUDGE_SYSTEM, user, usage, 400) or {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--premise", action="append")
    ap.add_argument("--compare", choices=["old", "story"], default="old",
                    help="old = 自动规划 vs 旧的生成大纲（默认）；story = 故事优先 vs 素材优先")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    premises = args.premise or PREMISES
    if args.compare == "story":
        compare_story(premises, out)
        return
    from retrieval_eval import model_cfg
    cfg = model_cfg()
    usage: dict = {}

    runs_f = out / "plan-runs.json"
    runs = json.loads(runs_f.read_text(encoding="utf-8")) if runs_f.exists() else {}

    def one(premise):
        if premise in runs:
            return premise, runs[premise]
        try:
            return premise, plan_both(premise)
        except Exception as e:  # noqa: BLE001 —— 一个构思失败不影响其他的
            print(f"  ! {premise} 失败：{e}")
            return premise, None

    def plan_both(premise):
        nid_new = call(f"{P}/api/gen/novels", {"title": f"规划评测 新 {premise}", "model": {"source": "api", "apiName": "DeepSeek"},
                                               "contextWindow": 32768})["id"]
        nid_old = call(f"{P}/api/gen/novels", {"title": f"规划评测 旧 {premise}", "model": {"source": "api", "apiName": "DeepSeek"},
                                               "contextWindow": 32768})["id"]
        new = run_new(nid_new, premise)
        old = run_old(nid_old, premise, new["ids"], new["variants"])
        print(f"  {premise}：新 {new['seconds']}s / {new['tokens']} token，旧 {old['seconds']}s / {old['tokens']} token，素材 {len(new['ids'])} 条"
              + ("（审稿失败：" + new["review"]["error"] + "）" if new["review"].get("error") else ""))
        return {"new": new, "old": old}

    with ThreadPoolExecutor(2) as ex:   # 检索在本机 GPU 上，别开太多
        for p, r in ex.map(one, premises):
            if r:
                runs[p] = r
                runs_f.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    if not runs:
        raise SystemExit("没有成功的构思")

    rnd = random.Random(5)
    scores = {"new": [], "old": []}
    pairs = []
    for p, r in runs.items():
        tn, to = render_new(r["new"]), render_old(r["old"])
        scores["new"].append(judge_one(p, tn, cfg, usage))
        scores["old"].append(judge_one(p, to, cfg, usage))
        flip = rnd.random() < 0.5
        res = judge_pair(p, to if flip else tn, tn if flip else to, cfg, usage)
        un = lambda v: ({"A": "B", "B": "A"}.get(v, "tie") if flip else (v if v in ("A", "B") else "tie"))  # noqa: E731
        pairs.append({"premise": p, **{k: ("new" if un(res.get(k)) == "A" else "old" if un(res.get(k)) == "B" else "tie")
                                         for k in ("reasonable", "exciting", "opening", "overall")}, "why": res.get("why")})

    keys = ("reasonable", "exciting", "opening", "characters", "foreshadow", "usable")
    L = [f"# 自动规划评测（{time.strftime('%Y-%m-%d %H:%M')}，{len(runs)} 个构思）", "",
         "| 方案 | " + " | ".join(["自洽", "精彩", "开篇", "人物", "伏笔", "可用"]) + " | 平均耗时 | 平均 token |", "|---|" + "---|" * 8]
    for s in ("new", "old"):
        rows = scores[s]
        mean = lambda k: sum(float(x.get(k) or 0) for x in rows) / max(1, len(rows))  # noqa: E731
        sec = sum(r[s]["seconds"] for r in runs.values()) / len(runs)
        tok = sum(r[s]["tokens"] for r in runs.values()) / len(runs)
        L.append(f"| {'自动规划' if s == 'new' else '生成大纲（旧）'} | " + " | ".join(f"{mean(k):.2f}" for k in keys) + f" | {sec:.0f}s | {tok:.0f} |")
    L += ["", "| 两两比较 | 自动规划胜 | 旧胜 | 平 |", "|---|---|---|---|"]
    for k, lab in (("reasonable", "自洽"), ("exciting", "精彩"), ("opening", "开篇"), ("overall", "总体")):
        L.append(f"| {lab} | {sum(x[k] == 'new' for x in pairs)} | {sum(x[k] == 'old' for x in pairs)} | {sum(x[k] == 'tie' for x in pairs)} |")
    L += ["", "## 代码检查（自动规划，修正后）"]
    from app.generation import planner
    for p, r in runs.items():
        iss = planner.outline_issues(r["new"]["outline"], r["new"]["settings"]["draft"], True, 1)
        L.append(f"- {p}：设定问题 {len(r['new']['settings']['issues'])} 条（{'、'.join(sorted({i['type'] for i in r['new']['settings']['issues']})) or '无'}），"
                 f"大纲问题 {len(iss)} 条（{'、'.join(sorted({i['type'] for i in iss})) or '无'}）")
    L += ["", "## 裁判评语"]
    for p, sn, so, pr in zip(runs, scores["new"], scores["old"], pairs):
        L.append(f"- {p}｜新：{sn.get('comment')}｜旧：{so.get('comment')}｜比较：{pr['overall']}，{pr.get('why')}")
    report = "\n".join(L)
    (out / "plan-report.md").write_text(report, encoding="utf-8")
    print(report)
    print("裁判 token：", usage)


if __name__ == "__main__":
    main()
