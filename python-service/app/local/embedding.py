"""文本向量（embedding）模型：素材库「向量检索」用（bge-small-zh 等 BERT 类模型，CLS 池化 + L2 归一化）。

- 与 inference.py 的生成模型互不占用：各自驻留，bge-small fp16 显存不到 200 MB
- 有 CUDA 时跑在 GPU（fp16）；本机训练任务占用 GPU 期间自动挪到 CPU，训练结束后再挪回
- 向量缓存：data/material-index/<baseId>/（vectors.npy + keys.json + meta.json），键 = 文本的 SHA-1；
  每次只编码新增 / 改动的文本，删除的素材不再被请求即不参与。模型文件变化（configHash / 大小）时缓存作废。
  按模型 id 分目录：以后微调出的新 embedding 模型自带独立缓存
- feedback.jsonl：向量检索后作者勾选 / 没勾选的素材（query → 正例 / 负例），留作以后 embedding 微调的训练数据
"""
import gc
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from .. import config
from . import hardware, jobs, registry

log = logging.getLogger("local.embedding")

INDEX_DIR = config.DATA_DIR / "material-index"
MAX_LENGTH = 512
MAX_TEXT_CHARS = 2000
# bge 系列：短查询加检索指令，被检索的文本不加（见 BAAI/bge 说明）。EMBED_QUERY_INSTRUCTION 可覆盖
ZH_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
EN_INSTRUCTION = "Represent this sentence for searching relevant passages: "

_lock = threading.RLock()       # 保护 _state / 模型 / 缓存（编码也在锁内：单卡串行）
_state: dict = {"status": "idle", "baseId": None, "name": None, "device": None, "dim": None,
                "error": None, "loadedAt": None, "loadSeconds": None}
_model = None
_tokenizer = None
_instruction = ""
_caches: dict[str, dict] = {}   # baseId → {"keys": [...], "index": {key: row}, "mat": ndarray, "meta": {...}}
_feedback_lock = threading.Lock()


class EmbeddingError(RuntimeError):
    pass


def status() -> dict:
    with _lock:
        return dict(_state)


def models() -> list[dict]:
    return [m for m in registry.list_base() if m["task"] == "embedding"]


def default_model_id() -> str:
    """未指定模型时：已加载的向量模型，否则第一个目录存在的向量模型。"""
    with _lock:
        if _state["status"] == "loaded":
            return _state["baseId"]
    for m in models():
        if m["exists"]:
            return m["id"]
    raise EmbeddingError("还没有向量模型：请在「本地模型」页下载 BAAI/bge-small-zh-v1.5")


def _query_instruction(base: dict) -> str:
    env = os.getenv("EMBED_QUERY_INSTRUCTION")
    if env is not None:
        return env
    tag = f"{base.get('origin') or ''} {base.get('name') or ''} {base.get('path') or ''}".lower()
    if "bge" not in tag or "bge-m3" in tag:
        return ""
    return ZH_INSTRUCTION if "zh" in tag else EN_INSTRUCTION


def _want_device() -> str:
    """有 CUDA 且本机训练没占用 GPU → cuda，否则 cpu。"""
    if hardware.torch_info()["cuda"] and not jobs.gpu_busy():
        return "cuda"
    return "cpu"


def _move(device: str) -> None:
    import torch

    global _model
    if device == "cuda":
        _model = _model.half().to("cuda")
    else:
        _model = _model.float().to("cpu")
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    _state["device"] = device


def load(base_id: str | None = None) -> dict:
    """同步加载（模型小，GPU 上几秒；首次导入 torch 稍慢）。已加载同一模型时直接返回。"""
    global _model, _tokenizer, _instruction
    base_id = base_id or default_model_id()
    base = registry.get_base(base_id)
    if base["task"] != "embedding":
        raise EmbeddingError(f"「{base['name']}」不是向量（embedding）模型")
    if not base["exists"]:
        raise EmbeddingError(f"模型目录不存在：{base['path']}")
    if not hardware.deps_info()["torch"]["installed"]:
        raise EmbeddingError("未安装 torch / transformers（见 requirements-local.txt），无法运行向量模型")
    with _lock:
        if _state["status"] == "loaded" and _state["baseId"] == base_id:
            return dict(_state)
        _free()
        _state.update(status="loading", baseId=base_id, name=base["name"], error=None, device=None, dim=None)
        t0 = time.time()
        try:
            from transformers import AutoModel, AutoTokenizer

            _tokenizer = AutoTokenizer.from_pretrained(base["path"])
            _model = AutoModel.from_pretrained(base["path"]).eval()
            _move(_want_device())
            _instruction = _query_instruction(base)
        except Exception as e:  # noqa: BLE001
            _free()
            _state.update(status="error", error=f"加载失败：{e}")
            log.exception("embedding 模型加载失败 %s", base_id)
            raise EmbeddingError(_state["error"]) from e
        _state.update(status="loaded", dim=int(_model.config.hidden_size),
                      loadedAt=datetime.now().isoformat(timespec="seconds"), loadSeconds=round(time.time() - t0, 1))
        log.info("embedding 模型已加载：%s（%s，%.1fs）", base["name"], _state["device"], _state["loadSeconds"])
        return dict(_state)


def _free() -> None:
    global _model, _tokenizer
    _model = _tokenizer = None
    _caches.clear()
    gc.collect()
    if hardware.torch_info()["cuda"]:
        import torch

        torch.cuda.empty_cache()


def unload() -> dict:
    with _lock:
        _free()
        _state.update(status="idle", baseId=None, name=None, device=None, dim=None, error=None,
                      loadedAt=None, loadSeconds=None)
        return dict(_state)


def _encode(texts: list[str], is_query: bool = False):
    """→ float32 ndarray (n, dim)，已 L2 归一化。调用方持有 _lock。"""
    import numpy as np
    import torch

    if _model is None:
        raise EmbeddingError("向量模型未加载")
    want = _want_device()
    if want != _state["device"]:
        _move(want)
    texts = [t[:MAX_TEXT_CHARS] for t in texts]
    if is_query and _instruction:
        texts = [_instruction + t for t in texts]
    batch = 64 if _state["device"] == "cuda" else 16
    out = []
    with torch.inference_mode():
        for i in range(0, len(texts), batch):
            enc = _tokenizer(texts[i:i + batch], padding=True, truncation=True, max_length=MAX_LENGTH,
                             return_tensors="pt")
            enc = {k: v.to(_state["device"]) for k, v in enc.items()}
            vec = _model(**enc).last_hidden_state[:, 0]
            out.append(torch.nn.functional.normalize(vec.float(), p=2, dim=-1).cpu().numpy())
    if not out:
        return np.zeros((0, _state["dim"]), dtype=np.float32)
    return np.concatenate(out).astype(np.float32)


# ---------------------------------------------------------------- 向量缓存

def _key(text: str) -> str:
    return hashlib.sha1(text[:MAX_TEXT_CHARS].encode("utf-8")).hexdigest()


def _cache_dir(base_id: str) -> Path:
    registry.adapter_dir(base_id)  # 复用 id 校验：只允许字母数字与 - _
    return INDEX_DIR / base_id


def _fingerprint(base_id: str) -> dict:
    base = registry.get_base(base_id)
    return {"baseId": base_id, "configHash": base.get("configHash"), "sizeBytes": base.get("sizeBytes"),
            "dim": _state["dim"]}


def _load_cache(base_id: str) -> dict:
    import numpy as np

    if base_id in _caches:
        return _caches[base_id]
    d = _cache_dir(base_id)
    fp = _fingerprint(base_id)
    cache = {"keys": [], "index": {}, "mat": np.zeros((0, fp["dim"]), dtype=np.float32), "meta": fp}
    try:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if meta == fp:
            keys = json.loads((d / "keys.json").read_text(encoding="utf-8"))
            mat = np.load(d / "vectors.npy")
            if mat.shape == (len(keys), fp["dim"]):
                cache.update(keys=keys, index={k: i for i, k in enumerate(keys)}, mat=mat)
        else:
            log.info("向量缓存与模型不符，重新编码：%s", base_id)
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("向量缓存读取失败，重新编码：%s（%s）", base_id, e)
    _caches[base_id] = cache
    return cache


def _atomic_write(path: Path, write) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        write(f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _save_cache(base_id: str, cache: dict) -> None:
    import numpy as np

    d = _cache_dir(base_id)
    d.mkdir(parents=True, exist_ok=True)
    try:
        _atomic_write(d / "vectors.npy", lambda f: np.save(f, cache["mat"]))
        _atomic_write(d / "keys.json", lambda f: f.write(json.dumps(cache["keys"]).encode("utf-8")))
        _atomic_write(d / "meta.json", lambda f: f.write(json.dumps(cache["meta"], ensure_ascii=False).encode("utf-8")))
    except OSError as e:
        log.warning("向量缓存写入失败：%s（%s）", base_id, e)


def _vectors_for(base_id: str, texts: list[str], encode: bool = True):
    """→ (ndarray (n, dim) | None, 新编码条数, 未缓存条数)；调用方持有 _lock。
    encode=False 只统计未缓存的条数。缓存里过期的条目在膨胀时清掉。"""
    import numpy as np

    cache = _load_cache(base_id)
    keys = [_key(t) for t in texts]
    missing = list(dict.fromkeys(k for k in keys if k not in cache["index"]))
    if not encode:
        return None, 0, len(missing)
    if missing:
        by_key = dict(zip(keys, texts))
        vecs = _encode([by_key[k] for k in missing])
        start = len(cache["keys"])
        cache["keys"].extend(missing)
        cache["index"].update({k: start + i for i, k in enumerate(missing)})
        cache["mat"] = np.concatenate([cache["mat"], vecs]) if start else vecs
        if len(cache["keys"]) > 2 * len(set(keys)) + 1000:  # 改动 / 删除积累的旧向量太多 → 只留本次用到的
            live = list(dict.fromkeys(keys))
            cache["mat"] = cache["mat"][[cache["index"][k] for k in live]]
            cache["keys"], cache["index"] = live, {k: i for i, k in enumerate(live)}
        _save_cache(base_id, cache)
    return cache["mat"][[cache["index"][k] for k in keys]], len(missing), 0


def index(base_id: str | None, items: list[dict], encode: bool = True) -> dict:
    """items = [{id, text}]：encode=True 编码所有未缓存的；False 只统计。→ {total, cached, encoded, …}"""
    t0 = time.time()
    with _lock:
        load(base_id)
        bid = _state["baseId"]
        _, encoded, pending = _vectors_for(bid, [it.get("text") or "" for it in items], encode)
        info = {"device": _state["device"], "model": _state["name"], "modelId": bid}
    total = len(items)
    return {"total": total, "cached": total - pending - encoded, "encoded": encoded, "pending": pending,
            "ms": int((time.time() - t0) * 1000), **info}


def vectors(base_id: str | None, texts: list[str]):
    """一批文本的向量（L2 归一化，未缓存的顺便编码）→ (ndarray (n, dim), info {model, modelId, device, encoded})。"""
    with _lock:
        load(base_id)
        bid = _state["baseId"]
        mat, encoded, _ = _vectors_for(bid, texts, True)
        return mat, {"model": _state["name"], "modelId": bid, "device": _state["device"], "encoded": encoded}


RECALL = 50        # 向量 / 关键词各取前 N 条进入融合
RRF_K = 60         # 倒数排名融合的平滑常数（常用默认值）
RERANK_TOP = 30    # 融合后送重排模型的条数


def search(base_id: str | None, query: str, items: list[dict], limit: int, *, mode: str = "hybrid",
           rerank: bool = True, rerank_model: str | None = None, vocab: list[str] | None = None) -> dict:
    """items = [{id, text}] → 最相关的前 limit 条。
    mode：vector = 只按余弦相似度；hybrid = 向量 + BM25（jieba）各召回前 RECALL 条，倒数排名融合（RRF）。
    vocab：领域词表（素材标签），加进 jieba 让「退婚」「扮猪吃虎」不被切碎。
    rerank：有重排模型时把融合后的前 RERANK_TOP 条交给交叉编码器重新打分（score = 0–1 相关度）；
    没有重排模型 / 显存不够时退回融合顺序（score = 余弦相似度），reranked = False 并给出 rerankSkipped 原因。
    每条结果：{id, score, similarity(余弦), lexRank / vecRank(各自召回里的名次，1 起；没进前 RECALL 为 None)}"""
    import numpy as np

    from . import lexical, reranker

    t0 = time.time()
    query = query.strip()
    with _lock:
        load(base_id)
        bid = _state["baseId"]
        texts = [(it.get("text") or "")[:MAX_TEXT_CHARS] for it in items]
        if texts:
            mat, encoded, _ = _vectors_for(bid, texts)
        else:
            mat, encoded = np.zeros((0, _state["dim"]), np.float32), 0
        q = _encode([query], is_query=True)[0]
        info = {"device": _state["device"], "model": _state["name"], "modelId": bid}
    base = {"encoded": encoded, "cached": len(texts) - encoded, "considered": len(texts), "mode": mode, **info}
    if not texts:
        return {"results": [], "reranked": False, "ms": int((time.time() - t0) * 1000), **base}

    sims = mat @ q
    vec_order = np.argsort(-sims)[:RECALL]
    vec_rank = {int(i): r + 1 for r, i in enumerate(vec_order)}
    lex_rank: dict[int, int] = {}
    if mode == "hybrid":
        if vocab:
            lexical.add_vocab(vocab)
        bm = np.asarray(lexical.scores(query, [_key(t) for t in texts], texts))
        lex_order = [int(i) for i in np.argsort(-bm)[:RECALL] if bm[i] > 0]
        lex_rank = {i: r + 1 for r, i in enumerate(lex_order)}
        fused: dict[int, float] = {}
        for ranks in (vec_rank, lex_rank):
            for i, r in ranks.items():
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r)
        order = sorted(fused, key=lambda i: -fused[i])
    else:
        order = [int(i) for i in vec_order]

    reranked, skipped, rr_info = False, None, {}
    if rerank:
        if not (rerank_model or reranker.default_model_id()):
            skipped = "没有重排模型"
        else:
            cand = order[:max(RERANK_TOP, limit)]
            try:
                r = reranker.score(query, [texts[i] for i in cand], rerank_model)
                rr = dict(zip(cand, r["scores"]))
                order = sorted(cand, key=lambda i: -rr[i])
                reranked = True
                rr_info = {"rerankModel": r["model"], "rerankDevice": r["device"], "rerankMs": r["ms"]}
            except (RuntimeError, ValueError) as e:  # RerankError / RegistryError
                skipped = str(e)
                log.warning("重排失败，退回融合顺序：%s", e)
    results = []
    for i in order[:max(1, limit)]:
        results.append({"id": items[i]["id"], "score": rr[i] if reranked else round(float(sims[i]), 4),
                        "similarity": round(float(sims[i]), 4), "vecRank": vec_rank.get(i), "lexRank": lex_rank.get(i)})
    return {"results": results, "reranked": reranked, "rerankSkipped": skipped, "queryTokens": lexical.tokens(query) if mode == "hybrid" else None,
            "ms": int((time.time() - t0) * 1000), **base, **rr_info}


def similarity(query: str, texts: list[str], base_id: str | None = None) -> dict:
    """主动调用 / 调试：query 与每段文本的余弦相似度（不走缓存）。"""
    t0 = time.time()
    with _lock:
        load(base_id)
        mat = _encode(texts)
        q = _encode([query.strip()], is_query=True)[0]
        info = {"device": _state["device"], "model": _state["name"], "modelId": _state["baseId"],
                "instruction": _instruction}
    return {"scores": [round(float(s), 4) for s in (mat @ q)], "ms": int((time.time() - t0) * 1000), **info}


def record_feedback(entry: dict) -> None:
    """追加一条检索反馈（query → 勾选的 / 展示了没勾选的素材），以后做 embedding 微调的训练数据。"""
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps({**entry, "at": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False)
    with _feedback_lock, open(INDEX_DIR / "feedback.jsonl", "a", encoding="utf-8") as f:
        f.write(line + "\n")
