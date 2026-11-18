"""入库前比对（书库，2026-11-04）：卡片存进素材库之前，先在这本书已有的素材里找「可能是同一条」的。

三步：
- 名称 / 别名：规范化后相等或互相包含（≥2 个字），跨分类也算——「夏风」和「路西恩·伊文斯（夏风）」；
- 向量召回：bge 余弦相似度（`local.embedding.vectors`，带缓存，不调大模型），只在同分类里取前 RECALL 条；
- 重排：交叉编码器（bge-reranker，`local.reranker.score`）给「卡片 ↔ 候选」重新打分。实测（《奥术神座》，2026-11-04）
  向量分在 0.6–0.75 里分不开「同一个东西的另一种写法」和「描述相似的另一个东西」（两个不同的音乐家 0.67、
  骑士制度 ↔ 骑士体系 0.69），重排分能分开：同一东西 0.58–0.999，不同的人 ≈0.003，一部分 ↔ 整体 ≈0.03。
每张卡取最像的 top 条（名称命中排前面）。score = 重排分（reranked=True）或余弦分（重排不可用时）；
向量模型不可用时只做名称比对，vector=False + 原因。建议动作由 Java 按分数定。
"""
from __future__ import annotations

import logging

from .materials import _norm_title

log = logging.getLogger(__name__)

MIN_NAME = 2
RECALL = 5          # 每张卡向量召回几条送重排


def _names(x: dict) -> set[str]:
    out = {_norm_title(x.get("title") or "")}
    out |= {_norm_title(a) for a in x.get("aliases") or [] if a}
    return {n for n in out if len(n) >= MIN_NAME}


def _name_hit(a: set[str], b: set[str]) -> str | None:
    """→ name（相等）/ alias（一方包含另一方）/ None"""
    if a & b:
        return "name"
    for x in a:
        for y in b:
            if len(x) >= MIN_NAME and len(y) >= MIN_NAME and (x in y or y in x):
                return "alias"
    return None


def match(queries: list[dict], items: list[dict], top: int = 3, model_id: str | None = None) -> dict:
    """queries = 卡片 [{id, category, title, aliases?, text}]；items = 已有素材 [{id, category, title, aliases?, text}]。
    → {matches: {卡片id: [{id, score, reason: name|alias|vector}]}, vector: bool, message?}"""
    result: dict = {str(q["id"]): [] for q in queries}
    if not queries or not items:
        return {"matches": result, "vector": False}
    item_names = [_names(i) for i in items]
    hits: dict[str, dict] = {str(q["id"]): {} for q in queries}
    for q in queries:
        qn = _names(q)
        for i, it in enumerate(items):
            r = _name_hit(qn, item_names[i])
            if r:
                same_cat = it.get("category") == q.get("category")
                hits[str(q["id"])][it["id"]] = {"id": it["id"], "score": 1.0 if r == "name" else 0.95, "reason": r,
                                                "sameCategory": same_cat}

    vector, reranked, message = False, False, ""
    text_of = lambda x: x.get("text") or x.get("title") or ""  # noqa: E731
    try:
        from .local import embedding

        texts = [text_of(q) for q in queries] + [text_of(i) for i in items]
        mat, _ = embedding.vectors(model_id, texts)
        qv, iv = mat[:len(queries)], mat[len(queries):]
        sims = qv @ iv.T
        by_id = {it["id"]: k for k, it in enumerate(items)}
        for qi, q in enumerate(queries):
            same = [k for k, it in enumerate(items) if it.get("category") == q.get("category")]
            same.sort(key=lambda k: -float(sims[qi, k]))
            h = hits[str(q["id"])]
            for k in same[:RECALL]:
                it = items[k]
                if it["id"] not in h:
                    h[it["id"]] = {"id": it["id"], "score": round(float(sims[qi, k]), 3), "reason": "vector"}
            for x in h.values():
                x["vector"] = round(float(sims[qi, by_id[x["id"]]]), 3)
        vector = True
    except Exception as e:  # 向量模型没装 / 没加载 / 显存不够：只做名称比对
        message = f"向量比对不可用，只按名称比对：{e}"[:200]
        log.warning("入库比对：%s", message)

    if vector:
        try:
            from .local import reranker

            if reranker.default_model_id():
                item_text = {it["id"]: text_of(it) for it in items}
                for q in queries:
                    h = hits[str(q["id"])]
                    if not h:
                        continue
                    ids = list(h)
                    r = reranker.score(text_of(q), [item_text[i] for i in ids])
                    for i, sc in zip(ids, r["scores"]):
                        h[i]["rerank"] = round(float(sc), 3)
                        if h[i]["reason"] != "name":  # 名称包含也看重排分：「冥想」⊂「冥想与精神力体系」是一部分，不是同一个
                            h[i]["score"] = h[i]["rerank"]
                reranked = True
        except Exception as e:  # 没有重排模型 / 显存不够：退回余弦分
            message = f"重排不可用，按向量相似度比对（建议更保守）：{e}"[:200]
            log.warning("入库比对：%s", message)

    for qid, h in hits.items():
        result[qid] = sorted(h.values(), key=lambda x: (x["reason"] != "name", -x["score"]))[:top]
    out = {"matches": result, "vector": vector, "reranked": reranked}
    if message:
        out["message"] = message
    return out
