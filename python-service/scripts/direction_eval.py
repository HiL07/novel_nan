"""故事走向评测：同一批「写到第 K 章」的工作区，比较不同出走向流程的合理性 / 精彩度 / 是否接近原作后续。

样本来自已有的小说提取结果（data/extract-results/<id>.json：每章摘要、人物、事件、伏笔）：
  前 K 章 → 测试工作区（章节 = 摘要，人物 = 设定里的角色卡，伏笔 / 事件 = 故事账本，更早章节 = 前情概要），
  第 K+1 ~ K+5 章的摘要 = 原作真实后续（只给裁判看，用来算「接近原作」，不是唯一正确答案）。
系统：old = AI 构思「后续走向」（ideas.generate kind=direction，无构思方向）；new = 走向引擎（P2 的 directions.generate）。
裁判 = DeepSeek，拿到的是完整前情（与被测系统看到的上下文无关）：
  每条走向打 合理 1–5（并列出矛盾）、精彩 1–5（冲突 / 意外 / 伏笔利用 / 主角主动 / 钩子）、是否用到未回收伏笔；
  另一调用对照原作后续打 接近 0 / 1 / 2；两个系统都有结果时再按样本做整组两两比较（顺序随机）。

用法（DATA_DIR 指向数据副本：测试工作区建在副本的 novels/ 下）：
  .venv/Scripts/python scripts/direction_eval.py --data-dir <副本> --system old [--runs 2]
  .venv/Scripts/python scripts/direction_eval.py --data-dir <副本> --system new   # P2 之后
  .venv/Scripts/python scripts/direction_eval.py --data-dir <副本> --report        # 只出报告
缓存在 <data-dir>/direction-eval/：fixtures.json、outputs-<system>.json、judge-<system>.json、pairwise.json、report.md。
"""
import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# (提取结果 id, 截到第 K 章)：长短、题材不同的几本
FIXTURES = [("2", 30), ("3", 30), ("3", 60), ("8", 40), ("8", 90), ("11", 40), ("11", 100)]
TRUTH_CHAPTERS = 5
ARC_KEEP = 8          # 和 chapter._merge_arc 一样：最近 8 章保留单章摘要，更早的合成前情概要
MAX_CAST = 8


def _cfg_dict(cfg) -> dict:
    return {"baseUrl": cfg.baseUrl, "apiKey": cfg.apiKey, "model": cfg.model, "concurrency": cfg.concurrency}


# ---------------------------------------------------------------------------------------------- 样本

def _spec(chars: list[dict], style: dict) -> list[dict]:
    """提取出的人物 / 文风 → 设定编辑器 spec（第一个 = 出场最多的 = 主角）"""
    cast = []
    for n, c in enumerate(chars):
        role = ("主角，" if n == 0 else "") + (c.get("role") or "")
        cast.append({"key": f"c{n}", "label": c["name"], "type": "groupItem", "name": c["name"], "children": [
            {"key": "role", "label": "角色定位", "type": "text", "value": role, "display": role}]})
    spec = [{"key": "characters", "label": "角色", "items": [
        {"key": "cast", "label": "主要角色", "type": "group", "children": cast}]}]
    tones = "、".join(dict.fromkeys(style.get("tones") or []))
    if tones or style.get("pace"):
        spec.append({"key": "style", "label": "文风", "items": [
            {"key": "tone", "label": "基调", "type": "text", "value": tones, "display": tones},
            {"key": "pace", "label": "节奏", "type": "text", "value": style.get("pace") or "", "display": style.get("pace") or ""}]})
    return spec


def build_fixtures(cfg, usage: dict) -> list[dict]:
    from app.generation import facts as facts_mod, store
    from retrieval_eval import llm_json
    out = []
    for book, k in FIXTURES:
        d = json.loads((ROOT.parent / "data" / "extract-results" / f"{book}.json").read_text(encoding="utf-8"))
        chs = d["chapters"]
        title_idx = {c.get("title"): i + 1 for i, c in enumerate(chs)}
        chars = [c for c in sorted(d.get("characters") or [], key=lambda c: -(c.get("chapterCount") or 0))
                 if title_idx.get(c.get("firstAppear"), 1) <= k][:MAX_CAST]
        novel = store.create_novel(f"评测样本 {book}-{k}", {"source": "api", "apiName": "DeepSeek"}, 32768)
        nid = novel["id"]
        facts = {"foreshadows": [], "characters": {}, "timeline": []}
        for i, c in enumerate(chs[:k], 1):
            s = (c.get("summary") or "").strip()
            store.save_chapter(nid, {"index": i, "title": c.get("title") or f"第{i}章", "goal": "", "text": s,
                                     "summary": s, "status": "done", "createdAt": store.now()})
            facts_mod.merge(facts, i, {
                "foreshadow": [{"text": f, "action": "plant"} for f in (c.get("foreshadowing") or [])[:4]],
                "timeline": [{"when": e.get("time") or "", "event": e.get("summary") or ""} for e in (c.get("events") or [])[:3]]})
        store.save_facts(nid, facts)
        # 前情概要：模拟 _merge_arc（K − 8 章之前的合成一段）
        upto = max(0, k - ARC_KEEP)
        arc = ""
        if upto:
            text = "\n".join(f"第{i}章：{(c.get('summary') or '')[:200]}" for i, c in enumerate(chs[:upto], 1))[:12000]
            res = llm_json(cfg, "你是小说编辑。只输出 JSON。",
                           f"把下面这些章节摘要合成一段前情概要（600 字以内，保留主线、人物关系变化和未解决的悬念）。\n"
                           f'输出 {{"summary": "..."}}\n\n{text}', usage, 1200)
            arc = str((res or {}).get("summary") or "")[:1200]
        store.update_novel(nid, settings={"config": None, "spec": _spec(chars, d.get("style") or {}), "savedAt": store.now()},
                           arcSummary=arc, arcUpTo=upto)
        truth = [f"第{i}章：{(c.get('summary') or '').strip()}" for i, c in enumerate(chs[k:k + TRUTH_CHAPTERS], k + 1)]
        recap = (f"【前情概要（至第{upto}章）】{arc}\n" if arc else "") + "\n".join(
            f"第{i}章：{(c.get('summary') or '')[:220]}" for i, c in enumerate(chs[upto:k], upto + 1))
        opens = [f["text"] for f in facts_mod.open_foreshadows(facts)][-20:]
        out.append({"book": book, "k": k, "novelId": nid, "recap": recap,
                    "cast": [f"{c['name']}：{c.get('role') or ''}" for c in chars], "openForeshadows": opens, "truth": truth})
        print(f"  样本 {book}-{k}：{nid}，人物 {len(chars)}，未回收伏笔 {len(facts_mod.open_foreshadows(facts))}")
    return out


# ---------------------------------------------------------------------------------------------- 被测系统

def run_system(system: str, fixtures: list[dict], runs: int, cfg) -> list[dict]:
    from app.generation import ideas
    out = []
    if system == "new":
        # 先按顺序整理局面（结果存进样本的账本，和真实使用时「第一次出走向」一样只做一次），免得两次运行并发写账本
        from app.generation import directions, worldbook
        for fx in fixtures:
            if directions.needs_situation(worldbook.compile(fx["novelId"])):
                r = directions.refresh_situation(fx["novelId"], {"api": _cfg_dict(cfg)})
                print(f"  整理局面 {fx['book']}-{fx['k']}：{len(r['applied']['characters'])} 个人物、"
                      f"{len(r['applied']['clocks'])} 个定时事件，{r['usage']['promptTokens']}+{r['usage']['completionTokens']} token")

    def one(job):
        fx, r = job
        req = {"kind": "direction", "api": _cfg_dict(cfg), "count": 5, "materials": [],
               "chapterContext": {"current": True, "past": True}}
        t0 = time.time()
        try:
            if system == "old":
                res = ideas.generate(fx["novelId"], req)
                dirs = res["result"]["directions"]
            else:
                from app.generation import directions   # P2
                res = directions.generate(fx["novelId"], req)
                dirs = res["result"]["directions"]
            return {"fixture": f"{fx['book']}-{fx['k']}", "run": r, "directions": dirs, "usage": res.get("usage"),
                    "seconds": round(time.time() - t0, 1)}
        except Exception as e:  # noqa: BLE001
            print(f"  ! {fx['book']}-{fx['k']} 第 {r} 次失败：{e}")
            return {"fixture": f"{fx['book']}-{fx['k']}", "run": r, "directions": [], "error": str(e)}

    with ThreadPoolExecutor(4) as ex:
        out = list(ex.map(one, [(fx, r) for fx in fixtures for r in range(runs)]))
    return out


# ---------------------------------------------------------------------------------------------- 裁判

JUDGE_SYSTEM = "你是资深网络小说编辑，负责评审 AI 给作者提出的故事后续走向。评分要严格、拉开差距。只输出 JSON。"


def _story(fx: dict) -> str:
    return (f"【人物】\n" + "\n".join(fx["cast"]) + f"\n\n【已写内容（至第{fx['k']}章）】\n{fx['recap']}\n\n"
            "【尚未回收的伏笔（最近的）】\n" + "\n".join(f"- {f}" for f in fx["openForeshadows"]))


def judge_quality(fx: dict, dirs: list[dict], cfg, usage: dict) -> list[dict]:
    from retrieval_eval import llm_json
    lst = "\n".join(f"[{i}] {d.get('label', '')}：{d['direction']}" for i, d in enumerate(dirs))
    user = (f"{_story(fx)}\n\n【AI 提出的后续走向】\n{lst}\n\n逐条评审：\n"
            "- reasonable 合理性 1–5：和已写内容、人物性格动机、世界规则是否一致（5 = 完全自洽，1 = 明显矛盾）；contradictions 列出具体矛盾（没有就空）\n"
            "- exciting 精彩度 1–5，以及分项 1–5：conflict 冲突强度、surprise 意外但合理、payoff 利用已有伏笔 / 人物关系、agency 主角主动、hook 给后面留钩子\n"
            "- usesForeshadow：是否明确接上了上面某条未回收的伏笔（true / false）\n"
            "- generic：是否空泛套路、换一本书也能用（true / false）\n"
            '输出 {"items": [{"i": 0, "reasonable": 4, "contradictions": [], "exciting": 3, "conflict": 3, "surprise": 3, '
            '"payoff": 3, "agency": 3, "hook": 3, "usesForeshadow": false, "generic": false}]}')
    res = llm_json(cfg, JUDGE_SYSTEM, user, usage, 2500)
    return (res or {}).get("items") or []


def judge_truth(fx: dict, dirs: list[dict], cfg, usage: dict) -> list[dict]:
    from retrieval_eval import llm_json
    lst = "\n".join(f"[{i}] {d['direction']}" for i, d in enumerate(dirs))
    user = (f"【已写内容（至第{fx['k']}章）】\n{fx['recap'][-3000:]}\n\n【原作实际的后续 {TRUTH_CHAPTERS} 章】\n"
            + "\n".join(fx["truth"]) + f"\n\n【AI 提出的走向】\n{lst}\n\n"
            "逐条判断走向和原作实际后续有多接近：2 = 抓住了原作接下来的核心发展，1 = 部分方向一致，0 = 基本无关。\n"
            '输出 {"items": [{"i": 0, "close": 0}]}')
    res = llm_json(cfg, JUDGE_SYSTEM, user, usage, 600)
    return (res or {}).get("items") or []


def judge_all(outputs: list[dict], fx_by: dict, cfg, usage: dict) -> list[dict]:
    def one(o):
        fx = fx_by[o["fixture"]]
        if not o["directions"]:
            return {**o, "quality": [], "truth": []}
        return {**o, "quality": judge_quality(fx, o["directions"], cfg, usage), "truth": judge_truth(fx, o["directions"], cfg, usage)}

    with ThreadPoolExecutor(4) as ex:
        return list(ex.map(one, outputs))


def pairwise(a: list[dict], b: list[dict], fx_by: dict, cfg, usage: dict) -> list[dict]:
    """同一样本同一次 run：两组走向整组比较（A / B 位置随机），裁判不知道哪组是哪个系统"""
    from retrieval_eval import llm_json
    rnd = random.Random(11)
    pairs = [(x, y) for x in a for y in b if x["fixture"] == y["fixture"] and x["run"] == y["run"]
             and x["directions"] and y["directions"]]

    def one(p):
        x, y = p
        flip = rnd.random() < 0.5
        first, second = (y, x) if flip else (x, y)
        fmt = lambda o: "\n".join(f"- {d['direction']}" for d in o["directions"])  # noqa: E731
        user = (f"{_story(fx_by[x['fixture']])}\n\n【方案 A】\n{fmt(first)}\n\n【方案 B】\n{fmt(second)}\n\n"
                "作为作者，你更想拿哪一组走向继续写？分别比较：reasonable 哪组更自洽、exciting 哪组更精彩、overall 总体更想用哪组。"
                '每项填 "A"、"B" 或 "tie"。输出 {"reasonable": "A", "exciting": "B", "overall": "A", "why": "一句话理由"}')
        res = llm_json(cfg, JUDGE_SYSTEM, user, usage, 400) or {}
        unflip = lambda v: {"A": "B", "B": "A"}.get(v, "tie") if flip else (v if v in ("A", "B") else "tie")  # noqa: E731
        # 统一成：A = 第一个系统（a），B = 第二个系统（b）
        return {"fixture": x["fixture"], "run": x["run"], **{k: unflip(res.get(k)) for k in ("reasonable", "exciting", "overall")},
                "why": res.get("why")}

    with ThreadPoolExecutor(4) as ex:
        return list(ex.map(one, pairs))


# ---------------------------------------------------------------------------------------------- 报告

def report(judged: dict[str, list[dict]], pw: list[dict] | None) -> str:
    import statistics as st
    L = [f"# 故事走向评测报告（{time.strftime('%Y-%m-%d %H:%M')}）", ""]
    keys = ("reasonable", "exciting", "conflict", "surprise", "payoff", "agency", "hook")
    L += ["## 1. 逐条打分（均值，1–5）", "", "| 系统 | 走向数 | " + " | ".join(
        ["合理", "精彩", "冲突", "意外", "伏笔利用", "主角主动", "钩子"]) + " | 有矛盾 | 用到伏笔 | 空泛 | 接近原作(0–2) | 失败次数 |",
          "|---|---|" + "---|" * 12]
    for sysname, rows in judged.items():
        qs = [q for r in rows for q in r.get("quality") or []]
        ts = [t.get("close", 0) for r in rows for t in r.get("truth") or [] if isinstance(t.get("close"), int)]
        if not qs:
            continue
        mean = lambda k: st.mean(float(q.get(k) or 0) for q in qs)  # noqa: E731
        share = lambda f: sum(1 for q in qs if f(q)) / len(qs)  # noqa: E731
        L.append(f"| {sysname} | {len(qs)} | " + " | ".join(f"{mean(k):.2f}" for k in keys)
                 + f" | {share(lambda q: q.get('contradictions')):.0%} | {share(lambda q: q.get('usesForeshadow') is True):.0%}"
                 f" | {share(lambda q: q.get('generic') is True):.0%} | {st.mean(ts) if ts else 0:.2f}"
                 f" | {sum(1 for r in rows if r.get('error'))} |")
    L.append("")
    L += ["## 2. 按样本（合理 / 精彩 / 接近原作）", "", "| 样本 | " + " | ".join(judged) + " |", "|---|" + "---|" * len(judged)]
    fixtures = sorted({r["fixture"] for rows in judged.values() for r in rows}, key=lambda s: (s.split("-")[0], int(s.split("-")[1])))
    for f in fixtures:
        cells = []
        for rows in judged.values():
            qs = [q for r in rows if r["fixture"] == f for q in r.get("quality") or []]
            ts = [t.get("close", 0) for r in rows if r["fixture"] == f for t in r.get("truth") or []]
            cells.append(f"{st.mean(float(q.get('reasonable') or 0) for q in qs):.1f} / {st.mean(float(q.get('exciting') or 0) for q in qs):.1f}"
                         f" / {st.mean(ts) if ts else 0:.1f}" if qs else "—")
        L.append(f"| {f} | " + " | ".join(cells) + " |")
    L.append("")
    if pw:
        names = list(judged)
        L += [f"## 3. 整组两两比较：{names[0]}（A） vs {names[1]}（B），{len(pw)} 组", "", "| 维度 | A 胜 | B 胜 | 平 |", "|---|---|---|---|"]
        for k, lab in (("reasonable", "自洽"), ("exciting", "精彩"), ("overall", "总体")):
            L.append(f"| {lab} | {sum(p[k] == 'A' for p in pw)} | {sum(p[k] == 'B' for p in pw)} | {sum(p[k] == 'tie' for p in pw)} |")
        L.append("")
    # 例子：每个系统得分最高 / 最低的各两条
    for sysname, rows in judged.items():
        flat = [(q, r["directions"][q["i"]]["direction"], r["fixture"]) for r in rows for q in r.get("quality") or []
                if isinstance(q.get("i"), int) and q["i"] < len(r["directions"])]
        flat.sort(key=lambda x: -(float(x[0].get("reasonable") or 0) + float(x[0].get("exciting") or 0)))
        if flat:
            L += [f"## 例子：{sysname}", ""]
            for q, text, f in flat[:2] + flat[-2:]:
                L.append(f"- [{f}] 合理 {q.get('reasonable')} / 精彩 {q.get('exciting')}：{text}"
                         + (f"（矛盾：{'；'.join(q['contradictions'])}）" if q.get("contradictions") else ""))
            L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--system", choices=("old", "new"))
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    os.environ["DATA_DIR"] = str(Path(args.data_dir).resolve())
    out_dir = Path(args.data_dir) / "direction-eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    from retrieval_eval import model_cfg
    cfg = model_cfg()
    usage: dict = {}

    def cached(name, make):
        f = out_dir / name
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
        data = make()
        f.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return data

    print("① 样本")
    fixtures = cached("fixtures.json", lambda: build_fixtures(cfg, usage))
    fx_by = {f"{fx['book']}-{fx['k']}": fx for fx in fixtures}
    if args.system:
        print(f"② 被测系统 {args.system}（{len(fixtures)} 个样本 × {args.runs} 次）")
        outputs = cached(f"outputs-{args.system}.json", lambda: run_system(args.system, fixtures, args.runs, cfg))
        print(f"③ 裁判 {args.system}")
        cached(f"judge-{args.system}.json", lambda: judge_all(outputs, fx_by, cfg, usage))
    judged = {s: json.loads((out_dir / f"judge-{s}.json").read_text(encoding="utf-8"))
              for s in ("old", "new") if (out_dir / f"judge-{s}.json").exists()}
    pw = None
    if len(judged) == 2:
        pw = cached("pairwise.json", lambda: pairwise(judged["old"], judged["new"], fx_by, cfg, usage))
    if usage:
        print(f"  本次 token：{usage}")
    text = report(judged, pw)
    (out_dir / "report.md").write_text(text, encoding="utf-8")
    print("\n" + text)


if __name__ == "__main__":
    main()
