"""素材检索评测：召回（向量 / BM25 / RRF）、重排条数、MMR 多样性，各方案对比。

查询和标准答案由大模型自动生成（不用人工标注）：
  1. 从素材库按分类抽样，每条素材让模型写 3 种查询——desc（描述特点，不带名称）、need（作者需求口吻，更笼统）、
     kw（几个关键词）；另把 desc 加上设定位置路径（「角色 主要角色 …」）当 noisy，模拟素材选择弹窗拼出来的查询。
     这条素材就是该查询的「已知答案」→ 命中率 / MRR。
  2. need 查询往往有很多条都相关：把各方案前 5 条合在一起交给模型打 0 / 1 / 2 分（pooled judging）
     → 相关度、nDCG@5；同时算多样性（前 5 条两两余弦均值、细分类型数、来源书数）。
检索在本进程内完成（复用 app.local.embedding / lexical / reranker，和产品同一套代码，先逐条核对一致），
不占用 8021 / 8011；素材经 Java 测试实例读取（CLAUDE.md：只有 Java 打开数据库）。

用法（DATA_DIR 指向数据副本，向量缓存 / 评测结果都写在那里）：
  .venv/Scripts/python scripts/retrieval_eval.py --data-dir <副本> --java http://localhost:8012 [--per-cat 10]
  分阶段缓存在 <data-dir>/material-index/eval/：materials.json → queries.json → runs.json → judgments.json → report.md；
  删掉某个文件就重做那一步。大模型 key 读环境变量 DEEPSEEK_API_KEY 或 backend/application-secret.yml，不打印。
"""
import argparse
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CATEGORY_NAMES = {"world": "世界观", "faction": "势力", "character": "角色", "monster": "怪物",
                  "location": "地点", "item": "物品功法", "plot": "情节"}
# 素材选择弹窗的查询 = 设定位置路径 + 输入框文字（feedback.jsonl 里的实际样子：「角色 主要角色 法师」）
NOISE_PREFIX = {"character": "角色 主要角色", "plot": "情节推进 关键情节节点", "world": "世界观 世界观补充",
                "monster": "设定元素 怪物", "faction": "设定元素 势力", "location": "设定元素 地点", "item": "设定元素 物品"}
RERANK_MIN = 0.30          # = MaterialService.RERANK_MIN_SCORE / 100
PER_BOOK = 2               # = InspirationService.PER_BOOK
TAKE = 5                   # 每条需求取几条（灵感墙 count 默认 3，最多 6；这里取 5 便于看多样性）


# ---------------------------------------------------------------------------------------------- 素材

def vector_text(m: dict) -> str:
    """= MaterialService.vectorText（名称 / 子类 / 标签 / 概括 / 属性值）"""
    parts = [m.get("title"), m.get("subtype")]
    if m.get("tags"):
        parts.append("、".join(m["tags"]))
    parts.append(m.get("summary"))
    for v in (m.get("attributes") or {}).values():
        parts.append("、".join(map(str, v)) if isinstance(v, list) else (None if v is None else str(v)))
    return "\n".join(s.strip() for s in parts if isinstance(s, str) and s.strip())


def variant_text(master: dict, member: dict) -> str:
    """= MaterialService.variantText（主条目名称 + 版本名 + 独有设定 + 成员原文）"""
    v = next((x for x in (master.get("source") or {}).get("variants") or []
              if isinstance(x, dict) and x.get("id") == member["id"]), {})
    return "\n".join([master.get("title") or "", str(v.get("label") or ""), str(v.get("note") or ""),
                      vector_text(member)]).strip()


def fetch_materials(java: str) -> dict:
    import httpx
    mats, page = [], 1
    with httpx.Client(base_url=java, timeout=120, trust_env=False) as c:
        while True:
            d = c.get("/api/material/list", params={"page": page, "size": 100}).json()["data"]
            mats += d["records"]
            if page * 100 >= d["total"] or not d["records"]:
                break
            page += 1
        masters = [m for m in mats if (m.get("source") or {}).get("type") == "merge"]
        for m in masters:
            m["_members"] = (c.get(f"/api/material/{m['id']}").json().get("data") or {}).get("members") or []
        tags = [t["tag"] for t in c.get("/api/material/tags").json()["data"]]
    return {"materials": mats, "tags": tags}


def build_items(mats: list[dict]) -> list[dict]:
    """检索池：每条素材一条；合并主条目另加每个版本一条（id = 成员 id，mid = 主条目 id）"""
    items = [{"id": m["id"], "mid": m["id"], "text": vector_text(m)} for m in mats]
    for m in mats:
        for mem in m.get("_members") or []:
            items.append({"id": mem["id"], "mid": m["id"], "text": variant_text(m, mem)})
    return items


# ---------------------------------------------------------------------------------------------- 大模型

def model_cfg():
    from app.llm_client import ModelConfig
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        f = ROOT.parent / "backend" / "application-secret.yml"
        if f.exists():
            mt = re.search(r"api-key:\s*['\"]?([^'\"\s#]+)", f.read_text(encoding="utf-8"))
            key = mt.group(1) if mt else ""
    if not key:
        sys.exit("没有 DeepSeek key（DEEPSEEK_API_KEY 或 backend/application-secret.yml 的 ai.default.api-key）")
    return ModelConfig(baseUrl="https://api.deepseek.com", apiKey=key, model="deepseek-chat", concurrency=4)


def llm_json(cfg, system: str, user: str, usage: dict, max_tokens: int = 2000) -> dict | None:
    from app import llm_client
    try:
        text = llm_client.chat(cfg, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                               max_tokens, usage=usage)
        return json.loads(text)
    except Exception as e:  # noqa: BLE001 —— 一批失败只跳过这一批
        print(f"  ! 模型调用失败：{type(e).__name__}: {str(e)[:120]}")
        return None


def describe(m: dict, limit: int = 400) -> str:
    attrs = "；".join(f"{k}：{v}" for k, v in (m.get("attributes") or {}).items() if v)
    s = (f"名称：{m.get('title')}｜分类：{CATEGORY_NAMES.get(m.get('category'), m.get('category'))}｜类型：{m.get('subtype') or ''}"
         f"｜标签：{'、'.join(m.get('tags') or [])}｜概括：{m.get('summary') or ''}｜{attrs}")
    return s[:limit]


GEN_SYSTEM = "你在为一个网络小说素材库构建检索评测集。只输出 JSON。"
GEN_USER = """下面是 {n} 条素材。为每条写 3 个检索查询，模拟作者写小说时想找到这条素材会在搜索框里输入什么：
- desc：一句话描述它的特点，15–40 字。不许出现素材名称、别名、书名、人名地名等专有名词
- need：作者写作需求的口吻（如「需要一个内部分裂、表面团结的反派组织」），20–50 字，可以比素材更笼统；同样不许出现专有名词
- kw：2–4 个关键词，空格分隔，不许出现名称
输出 {{"items": [{{"id": 素材id, "desc": "...", "need": "...", "kw": "..."}}]}}

{materials}"""


def gen_queries(mats: list[dict], per_cat: int, cfg, usage: dict) -> list[dict]:
    rnd = random.Random(7)
    picked = []
    for cat in CATEGORY_NAMES:
        pool = [m for m in mats if m.get("category") == cat and len(m.get("summary") or "") >= 20]
        picked += rnd.sample(pool, min(per_cat, len(pool)))
    batches = [picked[i:i + 5] for i in range(0, len(picked), 5)]
    by_id = {m["id"]: m for m in picked}

    def one(batch):
        text = "\n".join(f"[id={m['id']}] {describe(m)}" for m in batch)
        return llm_json(cfg, GEN_SYSTEM, GEN_USER.format(n=len(batch), materials=text), usage)

    out = []
    with ThreadPoolExecutor(4) as ex:
        for res in ex.map(one, batches):
            for it in (res or {}).get("items") or []:
                m = by_id.get(it.get("id"))
                if not m:
                    continue
                for qtype in ("desc", "need", "kw"):
                    q = str(it.get(qtype) or "").strip()
                    if q:
                        out.append({"type": qtype, "query": q, "gold": m["id"], "category": m["category"]})
                if it.get("desc"):
                    out.append({"type": "noisy", "query": f"{NOISE_PREFIX[m['category']]} {it['desc']}",
                                "gold": m["id"], "category": m["category"]})
    return out


JUDGE_SYSTEM = "你是网络小说写作助手的检索质量评审。只输出 JSON。"
JUDGE_USER = """作者的检索需求：「{query}」
下面是检索出来的素材。逐条判断它对这个需求有多大用：
2 = 很贴合，作者会直接用；1 = 部分相关，改改能用；0 = 不相关或基本用不上。
输出 {{"scores": {{"素材id": 分数}}}}

{materials}"""


def judge(tasks: list[dict], mat_by_id: dict, cfg, usage: dict) -> dict:
    """tasks = [{key, query, ids}] → {key: {id: 0|1|2}}"""
    def one(t):
        text = "\n".join(f"[id={i}] {describe(mat_by_id[i], 260)}" for i in t["ids"])
        res = llm_json(cfg, JUDGE_SYSTEM, JUDGE_USER.format(query=t["query"], materials=text), usage, 1200)
        sc = (res or {}).get("scores") or {}
        return t["key"], {int(k): int(v) for k, v in sc.items() if str(k).isdigit() and str(v) in ("0", "1", "2")}

    out = {}
    with ThreadPoolExecutor(4) as ex:
        for k, v in ex.map(one, tasks):
            out[k] = v
    return out


# ---------------------------------------------------------------------------------------------- 检索

class Engine:
    """和 embedding.search 同一套：向量 / BM25 各取前 RECALL，RRF，重排；一次重排前 100 条，再切成 30 / 60 / 100 三种方案
    （交叉编码器逐对打分，分数不受同批其他条目影响）。"""

    def __init__(self, items: list[dict], vocab: list[str]):
        from app.local import embedding, lexical
        self.emb, self.lex = embedding, lexical
        self.items = items
        self.texts = [(it["text"] or "")[:embedding.MAX_TEXT_CHARS] for it in items]
        self.keys = [embedding._key(t) for t in self.texts]
        t0 = time.time()
        self.mat, info = embedding.vectors(None, self.texts)
        print(f"  向量：{len(items)} 条（新编码 {info['encoded']}，{info['model']} / {info['device']}，{time.time() - t0:.0f}s）")
        lexical.add_vocab(vocab)

    def encode_queries(self, qs: list[str]):
        import numpy as np
        emb = self.emb
        out = []
        with emb._lock:
            for i in range(0, len(qs), 64):
                out.append(emb._encode(qs[i:i + 64], is_query=True))
        return np.concatenate(out) if out else np.zeros((0, self.mat.shape[1]))

    def retrieve(self, query: str, qvec, idx: list[int], rerank_top: int = 100) -> dict:
        """idx = 参与检索的条目下标（全库或某一分类）→ 各路名次 + 重排分（键都是全局下标）"""
        import numpy as np
        from app.local import reranker
        emb = self.emb
        sub = self.mat[idx]
        sims = sub @ qvec
        vec = [idx[int(i)] for i in np.argsort(-sims)[:emb.RECALL]]
        bm = np.asarray(self.lex.scores(query, [self.keys[i] for i in idx], [self.texts[i] for i in idx]))
        lex = [idx[int(i)] for i in np.argsort(-bm)[:emb.RECALL] if bm[i] > 0]
        fused: dict[int, float] = {}
        for order in (vec, lex):
            for r, i in enumerate(order):
                fused[i] = fused.get(i, 0.0) + 1.0 / (emb.RRF_K + r + 1)
        fused_order = sorted(fused, key=lambda i: -fused[i])
        cand = fused_order[:rerank_top]
        rr = dict(zip(cand, reranker.score(query, [self.texts[i] for i in cand])["scores"]))
        sim_of = {idx[j]: float(sims[j]) for j in range(len(idx))}
        return {"vec": vec, "lex": lex, "fused": fused_order, "rr": rr, "sim": {i: sim_of[i] for i in set(vec) | set(cand)}}

    def reranked(self, r: dict, top: int) -> list[int]:
        """= 产品：融合前 top 条按重排分排序（之后的丢弃）"""
        return sorted(r["fused"][:top], key=lambda i: -r["rr"][i])

    def masters(self, order: list[int]) -> list[int]:
        """条目下标 → 主条目 id，去重保留第一次出现（= Java 的版本映射）"""
        seen, out = set(), []
        for i in order:
            mid = self.items[i]["mid"]
            if mid not in seen:
                seen.add(mid)
                out.append(mid)
        return out


def mmr(head: list[int], rel: dict, mat, weight: float, norm: bool = False) -> list[int]:
    """weight × max cos 惩罚（= 原 embedding._mmr，2026-10-29 按本评测删除）；norm = 惩罚按池内两两余弦均值归零：(maxcos − μ) / (1 − μ)"""
    import numpy as np
    mu = 0.0
    if norm and len(head) > 2:
        sub = mat[head]
        s = sub @ sub.T
        mu = float((s.sum() - np.trace(s)) / (len(head) * (len(head) - 1)))
    picked, rest = [], list(head)
    while rest:
        if picked:
            sel = mat[picked]

            def pen(i):
                c = float((sel @ mat[i]).max())
                return max(0.0, (c - mu) / (1 - mu)) if norm else c
            best = max(rest, key=lambda i: rel[i] - weight * pen(i))
        else:
            best = max(rest, key=lambda i: rel[i])
        picked.append(best)
        rest.remove(best)
    return picked


def norm_subtype(s: str | None) -> str:
    return re.sub(r"[\s·・/（）()]", "", s or "")


# ---------------------------------------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--java", default="http://localhost:8012")
    ap.add_argument("--per-cat", type=int, default=10)
    args = ap.parse_args()
    os.environ["DATA_DIR"] = str(Path(args.data_dir).resolve())
    out_dir = Path(args.data_dir) / "material-index" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    usage: dict = {}

    def cached(name, make):
        f = out_dir / name
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
        data = make()
        f.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return data

    print("① 读取素材（Java 测试实例）")
    lib = cached("materials.json", lambda: fetch_materials(args.java))
    mats = lib["materials"]
    mat_by_id = {m["id"]: m for m in mats}
    items = build_items(mats)
    print(f"  素材 {len(mats)} 条（合并主条目 {sum(1 for m in mats if m.get('_members'))}），检索池 {len(items)} 条，标签 {len(lib['tags'])}")

    print("② 生成查询（DeepSeek）")
    cfg = None
    if not (out_dir / "queries.json").exists() or not (out_dir / "judgments.json").exists():
        cfg = model_cfg()
    queries = cached("queries.json", lambda: gen_queries(mats, args.per_cat, cfg, usage))
    print(f"  查询 {len(queries)} 条：" + "、".join(f"{t} {sum(q['type'] == t for q in queries)}"
                                              for t in ("desc", "need", "kw", "noisy")))

    print("③ 检索")
    eng = Engine(items, lib["tags"])
    qvecs = eng.encode_queries([q["query"] for q in queries])
    all_idx = list(range(len(items)))
    cat_idx = {c: [i for i, it in enumerate(items) if mat_by_id[it["mid"]].get("category") == c] for c in CATEGORY_NAMES}

    # 产品一致性核对：自己的 rr30 和 embedding.search 结果逐条相同
    from app.local import embedding
    pool = [{"id": it["id"], "text": it["text"]} for it in items]
    for q in queries[:3]:
        prod = [r["id"] for r in embedding.search(None, q["query"], pool, 30, vocab=lib["tags"])["results"]]
        mine_r = eng.retrieve(q["query"], qvecs[queries.index(q)], all_idx)
        mine = [items[i]["id"] for i in eng.reranked(mine_r, 30)]
        print(f"  核对「{q['query'][:16]}…」重排 {'一致' if prod == mine else '不一致'}")

    def make_runs():
        runs = []
        t0 = time.time()
        # 先跑全库（BM25 倒排统计按文档集合缓存），再按分类分组跑
        for scope in ("all", "cat"):
            order = sorted(range(len(queries)), key=lambda k: queries[k]["category"]) if scope == "cat" else range(len(queries))
            for k in order:
                q = queries[k]
                if scope == "cat" and q["type"] != "need":
                    continue        # 分类内只看 need（模拟灵感墙：按需求的分类过滤后检索）
                idx = all_idx if scope == "all" else cat_idx[q["category"]]
                r = eng.retrieve(q["query"], qvecs[k], idx)
                row = {"q": k, "scope": scope,
                       "vec": eng.masters(r["vec"])[:30], "lex": eng.masters(r["lex"])[:30], "rrf": eng.masters(r["fused"])[:100]}
                for top in (30, 60, 100):
                    row[f"rr{top}"] = eng.masters(eng.reranked(r, top))[:30]
                head = eng.reranked(r, 30)
                row["rrScores"] = [round(r["rr"][i], 4) for i in head]
                sub = eng.mat[head]
                s = sub @ sub.T
                n = len(head)
                row["headCos"] = round(float((s.sum() - s.trace()) / max(1, n * (n - 1))), 4)
                if scope == "cat":
                    # 灵感墙式取用：重排 → (MMR) → 主条目去重 → 相关度 ≥ 0.30 → 每本书 ≤ 2 → 取 TAKE 条
                    variants = {"base": head,
                                "mmr0.3": mmr(head, r["rr"], eng.mat, 0.3), "mmr0.5": mmr(head, r["rr"], eng.mat, 0.5),
                                "mmr0.7": mmr(head, r["rr"], eng.mat, 0.7),
                                "norm0.3": mmr(head, r["rr"], eng.mat, 0.3, True), "norm0.5": mmr(head, r["rr"], eng.mat, 0.5, True)}
                    best_rr: dict[int, float] = {}
                    for i in head:
                        best_rr[items[i]["mid"]] = max(best_rr.get(items[i]["mid"], 0.0), r["rr"][i])
                    picks = {}
                    for name, order_v in variants.items():
                        picks[name] = take(eng.masters(order_v), best_rr, mat_by_id)
                    # 细分类型上限：按重排顺序，同一细分类型最多 1 条（不够再补）
                    ms = take(eng.masters(head), best_rr, mat_by_id, limit=len(head))
                    first, rest, seen = [], [], set()
                    for mid in ms:
                        st = norm_subtype(mat_by_id[mid].get("subtype"))
                        (rest if st and st in seen else first).append(mid)
                        seen.add(st)
                    picks["subtype1"] = (first + rest)[:TAKE]
                    row["picks"] = picks
                runs.append(row)
            print(f"  {scope} 完成（{time.time() - t0:.0f}s）")
        return runs

    runs = cached("runs.json", make_runs)

    print("④ 相关度打分（DeepSeek，pooled）")

    def make_judgments():
        tasks = []
        for row in runs:
            q = queries[row["q"]]
            if q["type"] != "need":
                continue
            ids = set()
            if row["scope"] == "all":
                for k in ("rrf", "rr30", "rr60", "rr100", "vec"):
                    ids |= set(row[k][:5])
            else:
                for v in row["picks"].values():
                    ids |= set(v)
            tasks.append({"key": f"{row['scope']}:{row['q']}", "query": q["query"], "ids": sorted(ids)})
        return judge(tasks, mat_by_id, cfg, usage)

    judgments = cached("judgments.json", make_judgments)
    if usage:
        print(f"  本次 token：{usage}")

    report = build_report(queries, runs, judgments, eng, mat_by_id, items, lib)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"\n报告：{out_dir / 'report.md'}")


def take(order: list[int], best_rr: dict, mat_by_id: dict, limit: int = TAKE) -> list[int]:
    """= InspirationService.retrieve 的取用：相关度 ≥ 0.30、每本书 ≤ 2"""
    per_book, out = {}, []
    for mid in order:
        if best_rr.get(mid, 0) < RERANK_MIN:
            continue
        book = mat_by_id[mid].get("sourceBook") or ""
        if book and per_book.get(book, 0) >= PER_BOOK:
            continue
        per_book[book] = per_book.get(book, 0) + 1
        out.append(mid)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------------------------- 报告

def build_report(queries, runs, judgments, eng, mat_by_id, items, lib) -> str:
    import numpy as np
    vec_of = {it["mid"]: eng.mat[i] for i, it in reversed(list(enumerate(items))) if it["id"] == it["mid"]}
    L = [f"# 素材检索评测报告（{time.strftime('%Y-%m-%d %H:%M')}）", "",
         f"素材 {len(mat_by_id)} 条，检索池 {len(items)} 条；查询 {len(queries)} 条（大模型按抽样素材生成）。", ""]

    def rank(lst, gold):
        return lst.index(gold) + 1 if gold in lst else None

    # 1. 已知答案
    L += ["## 1. 已知答案命中（全库检索，答案 = 生成查询的那条素材）", "",
          "| 查询类型 | 方案 | Hit@1 | Hit@5 | Hit@10 | Hit@30 | MRR |", "|---|---|---|---|---|---|---|"]
    all_runs = [r for r in runs if r["scope"] == "all"]
    for qt in ("desc", "need", "kw", "noisy"):
        rs = [r for r in all_runs if queries[r["q"]]["type"] == qt]
        if not rs:
            continue
        for k in ("vec", "lex", "rrf", "rr30", "rr60", "rr100"):
            ranks = [rank(r[k][:30], queries[r["q"]]["gold"]) for r in rs]
            hit = lambda n: sum(1 for x in ranks if x and x <= n) / len(ranks)  # noqa: E731
            mrr_v = sum(1 / x for x in ranks if x) / len(ranks)
            L.append(f"| {qt} | {k} | {hit(1):.0%} | {hit(5):.0%} | {hit(10):.0%} | {hit(30):.0%} | {mrr_v:.3f} |")
    L += ["", "> vec / lex = 单路召回；rrf = 融合不重排；rrN = 融合前 N 条交给重排（产品现在是 rr30）。", ""]

    # 召回天花板：答案在融合前 N 条里的比例（重排救不回融合阶段漏掉的）
    L += ["### 召回天花板：答案进了融合前 N 条的比例", "", "| 查询类型 | 前 30 | 前 60 | 前 100 |", "|---|---|---|---|"]
    for qt in ("desc", "need", "kw", "noisy"):
        rs = [r for r in all_runs if queries[r["q"]]["type"] == qt]
        if rs:
            cells = [f"{sum(1 for r in rs if queries[r['q']]['gold'] in r['rrf'][:n]) / len(rs):.0%}" for n in (30, 60, 100)]
            L.append(f"| {qt} | " + " | ".join(cells) + " |")
    L.append("")

    # 2. 需求类查询的相关度
    def ndcg(lst, sc, n=5):
        gains = [sc.get(i, 0) for i in lst[:n]]
        dcg = sum((2 ** g - 1) / np.log2(k + 2) for k, g in enumerate(gains))
        ideal = sorted(sc.values(), reverse=True)[:n]
        idcg = sum((2 ** g - 1) / np.log2(k + 2) for k, g in enumerate(ideal))
        return dcg / idcg if idcg else 0.0

    L += ["## 2. 需求类查询（need）：前 5 条的相关度（大模型打分 0 / 1 / 2）", "",
          "| 方案 | 平均分 | 前 5 里 ≥1 分的条数 | nDCG@5 |", "|---|---|---|---|"]
    for k in ("vec", "rrf", "rr30", "rr60", "rr100"):
        vals = []
        for r in all_runs:
            sc = judgments.get(f"all:{r['q']}")
            if sc is None or queries[r["q"]]["type"] != "need":
                continue
            top = r[k][:5]
            vals.append((np.mean([sc.get(i, 0) for i in top]) if top else 0, sum(sc.get(i, 0) >= 1 for i in top), ndcg(top, sc)))
        if vals:
            a = np.array(vals)
            L.append(f"| {k} | {a[:, 0].mean():.2f} | {a[:, 1].mean():.2f} | {a[:, 2].mean():.3f} |")
    L.append("")

    # 3. 重排分分布 / 池内相似度（MMR 的前提）
    rr_all = np.array([s for r in all_runs for s in r["rrScores"]])
    cos_all = np.array([r["headCos"] for r in runs])
    L += ["## 3. MMR 的前提：重排分分布、候选之间的相似度", "",
          f"- 重排前 30 条的重排分：<0.1 占 {np.mean(rr_all < 0.1):.0%}，0.1–0.3 占 {np.mean((rr_all >= 0.1) & (rr_all < 0.3)):.0%}，"
          f"0.3–0.7 占 {np.mean((rr_all >= 0.3) & (rr_all < 0.7)):.0%}，≥0.7 占 {np.mean(rr_all >= 0.7):.0%}",
          f"- 前 30 条两两余弦均值：中位 {np.median(cos_all):.3f}（10%–90%：{np.percentile(cos_all, 10):.3f}–{np.percentile(cos_all, 90):.3f}）",
          f"- 0.3 × 余弦的惩罚：和池内平均一样像的一条被罚 ≈ {0.3 * np.median(cos_all):.3f}，"
          f"几乎一模一样（余弦 0.95）被罚 ≈ 0.285，差 {0.285 - 0.3 * np.median(cos_all):.3f}——重排分差距超过这个数时 MMR 不会改变顺序", ""]

    # 4. MMR 方案对比（分类内，灵感墙式取用）
    cat_runs = [r for r in runs if r["scope"] == "cat"]
    L += ["## 4. 灵感墙式取用（按需求分类过滤 → 重排 → 方案 → 主条目去重 → ≥0.30 → 每书 ≤2 → 取 5）", "",
          "| 方案 | 和不用 MMR 的结果不同 | 条数 | 平均分 | ≥1 分条数 | 两两余弦（越低越分散） | 细分类型数 | 来源书数 |",
          "|---|---|---|---|---|---|---|---|"]
    for name in ("base", "mmr0.3", "mmr0.5", "mmr0.7", "norm0.3", "norm0.5", "subtype1"):
        rows = []
        for r in cat_runs:
            p, base = r["picks"][name], r["picks"]["base"]
            sc = judgments.get(f"cat:{r['q']}", {})
            vs = [vec_of[i] for i in p if i in vec_of]
            ils = np.mean([float(a @ b) for x, a in enumerate(vs) for b in vs[x + 1:]]) if len(vs) > 1 else np.nan
            rows.append((set(p) != set(base), len(p), np.mean([sc.get(i, 0) for i in p]) if p else np.nan,
                         sum(sc.get(i, 0) >= 1 for i in p), ils,
                         len({norm_subtype(mat_by_id[i].get("subtype")) for i in p}),
                         len({mat_by_id[i].get("sourceBook") or "" for i in p})))
        a = np.array(rows, dtype=float)
        L.append(f"| {name} | {np.nanmean(a[:, 0]):.0%} | {np.nanmean(a[:, 1]):.1f} | {np.nanmean(a[:, 2]):.2f} | "
                 f"{np.nanmean(a[:, 3]):.2f} | {np.nanmean(a[:, 4]):.3f} | {np.nanmean(a[:, 5]):.2f} | {np.nanmean(a[:, 6]):.2f} |")
    L += ["", "> base = 产品现在的做法（不做 MMR）；mmr0.3 = 灵感墙原来的设置（已删除）；normX = 惩罚按池内平均相似度归零；"
          "subtype1 = 同一细分类型最多 1 条（规则化多样性）。", ""]

    # 5. 真实反馈
    fb = Path(os.environ["DATA_DIR"]) / "material-index" / "feedback.jsonl"
    if fb.exists():
        lines = [json.loads(x) for x in fb.read_text(encoding="utf-8").splitlines() if x.strip()]
        L += [f"## 5. 真实使用反馈（feedback.jsonl，{len(lines)} 条）", ""]
        for e in lines:
            shown, picked = e.get("shownIds") or [], e.get("pickedIds") or []
            pos = [shown.index(p) + 1 for p in picked if p in shown]
            L.append(f"- 「{e.get('query')}」：展示 {len(shown)} 条，勾了 {len(picked)} 条，名次 {pos}")
        L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    main()
