"""重排模型（交叉编码器，如 bge-reranker-v2-m3）：把「查询 + 候选文本」成对送进模型，给出 0–1 的相关度。

- 只用于检索的最后一步（向量 / 关键词召回 → 融合 → 重排前 N 条），不能生成文本
- 与生成模型、向量模型各自驻留：有 CUDA 时 fp16 跑在 GPU（bge-reranker-v2-m3 约 1.1 GB 显存）；
  本机训练任务占用 GPU 期间自动挪到 CPU。显存不够（OOM）时这一次放弃重排，由调用方注明「未重排」
- 相关度 = sigmoid(logit)：可以直接当阈值用（比余弦相似度好解释）
"""
import gc
import logging
import threading
import time
from datetime import datetime

from . import hardware, jobs, registry

log = logging.getLogger("local.reranker")

MAX_LENGTH = 512
MAX_TEXT_CHARS = 1500

_lock = threading.RLock()
_state: dict = {"status": "idle", "baseId": None, "name": None, "device": None,
                "error": None, "loadedAt": None, "loadSeconds": None}
_model = None
_tokenizer = None


class RerankError(RuntimeError):
    pass


def status() -> dict:
    with _lock:
        return dict(_state)


def models() -> list[dict]:
    return [m for m in registry.list_base() if m["task"] == "reranker"]


def default_model_id() -> str | None:
    """已加载的重排模型，否则第一个目录存在的重排模型；没有 → None（检索时跳过重排）。"""
    with _lock:
        if _state["status"] == "loaded":
            return _state["baseId"]
    return next((m["id"] for m in models() if m["exists"]), None)


def _want_device() -> str:
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
    """同步加载；已加载同一模型时直接返回。"""
    global _model, _tokenizer
    base_id = base_id or default_model_id()
    if not base_id:
        raise RerankError("还没有重排模型：请在「本地模型」页下载 BAAI/bge-reranker-v2-m3")
    base = registry.get_base(base_id)
    if base["task"] != "reranker":
        raise RerankError(f"「{base['name']}」不是重排模型")
    if not base["exists"]:
        raise RerankError(f"模型目录不存在：{base['path']}")
    if not hardware.deps_info()["torch"]["installed"]:
        raise RerankError("未安装 torch / transformers（见 requirements-local.txt），无法运行重排模型")
    with _lock:
        if _state["status"] == "loaded" and _state["baseId"] == base_id:
            return dict(_state)
        _free()
        _state.update(status="loading", baseId=base_id, name=base["name"], error=None, device=None)
        t0 = time.time()
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            _tokenizer = AutoTokenizer.from_pretrained(base["path"])
            _model = AutoModelForSequenceClassification.from_pretrained(base["path"]).eval()
            _move(_want_device())
        except Exception as e:  # noqa: BLE001
            _free()
            _state.update(status="error", error=f"加载失败：{e}")
            log.exception("重排模型加载失败 %s", base_id)
            raise RerankError(_state["error"]) from e
        _state.update(status="loaded", loadedAt=datetime.now().isoformat(timespec="seconds"),
                      loadSeconds=round(time.time() - t0, 1))
        log.info("重排模型已加载：%s（%s，%.1fs）", base["name"], _state["device"], _state["loadSeconds"])
        return dict(_state)


def _free() -> None:
    global _model, _tokenizer
    _model = _tokenizer = None
    gc.collect()
    if hardware.torch_info()["cuda"]:
        import torch

        torch.cuda.empty_cache()


def unload() -> dict:
    with _lock:
        _free()
        _state.update(status="idle", baseId=None, name=None, device=None, error=None, loadedAt=None, loadSeconds=None)
        return dict(_state)


def score(query: str, texts: list[str], base_id: str | None = None) -> dict:
    """→ {scores: [0–1], device, model, modelId, ms}。显存不够时抛 RerankError（调用方可退回未重排的结果）。"""
    import torch

    t0 = time.time()
    with _lock:
        load(base_id)
        want = _want_device()
        if want != _state["device"]:
            _move(want)
        batch = 16 if _state["device"] == "cuda" else 4
        out: list[float] = []
        try:
            with torch.inference_mode():
                for i in range(0, len(texts), batch):
                    pairs = [[query[:MAX_TEXT_CHARS], t[:MAX_TEXT_CHARS]] for t in texts[i:i + batch]]
                    enc = _tokenizer(pairs, padding=True, truncation=True, max_length=MAX_LENGTH, return_tensors="pt")
                    enc = {k: v.to(_state["device"]) for k, v in enc.items()}
                    logits = _model(**enc).logits.view(-1).float()
                    out.extend(torch.sigmoid(logits).cpu().tolist())
        except torch.cuda.OutOfMemoryError as e:
            torch.cuda.empty_cache()
            raise RerankError("显存不够，本次没有重排（可先卸载生成模型）") from e
        info = {"device": _state["device"], "model": _state["name"], "modelId": _state["baseId"]}
    return {"scores": [round(s, 4) for s in out], "ms": int((time.time() - t0) * 1000), **info}
