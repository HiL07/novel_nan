"""基础模型与 LoRA 适配器登记（JSON 元数据与模型文件放在一起，见 settings.py 的目录说明）。

- 基础模型：登记本机已有的 Hugging Face 模型目录（只记路径，不复制大文件），或下载到 models/base/<id>/weights/
- 适配器：训练产出，meta.json 记录所用基础模型的「指纹」（config.json 的 sha256 + 路径 + 名称）和训练配置，
  加载时据此校验适配器与基础模型是否匹配
"""
import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from . import settings

WEIGHT_GLOBS = ("*.safetensors", "*.bin")
ARCH_KEYS = ("hidden_size", "num_hidden_layers", "num_attention_heads", "num_key_value_heads",
             "vocab_size", "max_position_embeddings", "torch_dtype")


class RegistryError(ValueError):
    pass


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_id(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()[:40] or "model"
    return f"{slug}-{uuid.uuid4().hex[:6]}"


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def config_hash(model_dir: Path) -> str:
    return hashlib.sha256((model_dir / "config.json").read_bytes()).hexdigest()[:16]


def inspect_model_dir(path: str) -> dict:
    """校验并读取 Hugging Face 模型目录：config.json + 权重 + 分词器。"""
    p = Path(path).expanduser()
    if not p.is_dir():
        raise RegistryError(f"目录不存在：{path}")
    cfg = _read_json(p / "config.json")
    if cfg is None:
        raise RegistryError("目录中没有 config.json，不是 Hugging Face 模型目录（GGUF 文件只能用于 llama.cpp）")
    weights = [f for g in WEIGHT_GLOBS for f in p.glob(g)]
    if not weights:
        if list(p.glob("*.gguf")):
            raise RegistryError("只找到 .gguf 文件：GGUF 无法用于 Transformers 训练，请使用 Hugging Face 格式（safetensors）")
        raise RegistryError("目录中没有 .safetensors / .bin 权重文件（下载可能不完整）")
    if not ((p / "tokenizer.json").exists() or (p / "tokenizer.model").exists() or (p / "vocab.json").exists()):
        raise RegistryError("目录中没有分词器文件（tokenizer.json / tokenizer.model / vocab.json）")
    sizes = [f.stat().st_size for f in weights]
    dtype = cfg.get("torch_dtype") or "bfloat16"
    bytes_per = {"float32": 4, "float16": 2, "bfloat16": 2}.get(dtype, 2)
    tok_cfg = _read_json(p / "tokenizer_config.json") or {}
    return {
        "path": str(p.resolve()),
        "modelType": cfg.get("model_type") or "unknown",
        "architecture": (cfg.get("architectures") or ["unknown"])[0],
        "arch": {k: cfg.get(k) for k in ARCH_KEYS},
        "sizeBytes": sum(sizes),
        "maxShardBytes": max(sizes),
        "numParams": int(sum(sizes) / bytes_per),
        "hasChatTemplate": bool(tok_cfg.get("chat_template")) or (p / "chat_template.jinja").exists(),
        "configHash": config_hash(p),
    }


# ---------------------------------------------------------------- 基础模型

def _base_record_path(model_id: str) -> Path:
    return settings.BASE_DIR / model_id / "model.json"


def register_base(name: str, path: str, *, source: str = "local", origin: str | None = None,
                  model_id: str | None = None) -> dict:
    info = inspect_model_dir(path)
    for m in list_base():
        if m["path"] == info["path"]:
            raise RegistryError(f"该目录已登记为「{m['name']}」")
    model_id = model_id or new_id(name)
    record = {"id": model_id, "name": name.strip() or Path(path).name, "source": source,
              "origin": origin, "createdAt": _now(), **info}
    (settings.BASE_DIR / model_id).mkdir(parents=True, exist_ok=True)
    _write_json(_base_record_path(model_id), record)
    return record


def get_base(model_id: str) -> dict:
    rec = _read_json(_base_record_path(model_id))
    if rec is None:
        raise RegistryError(f"基础模型不存在：{model_id}")
    rec["exists"] = Path(rec["path"]).is_dir()
    return rec


def list_base() -> list[dict]:
    out = []
    for f in sorted(settings.BASE_DIR.glob("*/model.json")):
        rec = _read_json(f)
        if rec:
            rec["exists"] = Path(rec["path"]).is_dir()
            out.append(rec)
    return sorted(out, key=lambda r: r.get("createdAt", ""), reverse=True)


def delete_base(model_id: str) -> None:
    """删除登记。只会删除 models/base/<id>/ 目录（含下载到这里的权重）；外部目录的模型文件不受影响。"""
    d = settings.BASE_DIR / model_id
    if not (d / "model.json").exists():
        raise RegistryError(f"基础模型不存在：{model_id}")
    shutil.rmtree(d)


def is_managed(rec: dict) -> bool:
    """权重是否存放在 models/ 下（下载的），删除登记会一并删除。"""
    try:
        Path(rec["path"]).resolve().relative_to(settings.BASE_DIR.resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- 适配器

def adapter_dir(adapter_id: str) -> Path:
    return settings.ADAPTER_DIR / adapter_id


def save_adapter_meta(adapter_id: str, meta: dict) -> None:
    save_adapter_meta_at(adapter_dir(adapter_id), meta)


def save_adapter_meta_at(directory: Path, meta: dict) -> None:
    meta = {k: v for k, v in meta.items() if k not in ("compat", "matchedBaseId")}
    _write_json(directory / "meta.json", meta)


def manifest_fingerprint(files: dict[str, str]) -> str:
    """权重文件指纹：{相对路径: sha256} 排序后整体 sha256（与官方下载清单 / 本地逐文件计算的结果可比）。"""
    return hashlib.sha256("\n".join(f"{k}:{v}" for k, v in sorted(files.items())).encode()).hexdigest()


def compute_weights_fingerprint(model_dir: Path) -> str:
    """逐个权重文件计算 sha256 后得到指纹（7B 约 15 GB，耗时分钟级，结果写入 model.json 缓存）。"""
    files = {}
    for f in sorted(p for g in WEIGHT_GLOBS for p in model_dir.glob(g)):
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 24), b""):
                h.update(chunk)
        files[f.name] = h.hexdigest()
    return manifest_fingerprint(files)


def verify_base_weights(model_id: str) -> dict:
    """计算并缓存本地基础模型的权重指纹（用于与远程训练所用模型比对）。"""
    rec = get_base(model_id)
    if not rec["exists"]:
        raise RegistryError(f"模型目录不存在：{rec['path']}")
    rec.pop("exists", None)
    rec["weightsFingerprint"] = compute_weights_fingerprint(Path(rec["path"]))
    rec["weightsVerifiedAt"] = _now()
    _write_json(_base_record_path(model_id), rec)
    return get_base(model_id)


def _with_compat(meta: dict) -> dict:
    """附加与本地基础模型的匹配状态与可加载的本地基础模型 matchedBaseId。

    - 本地训练的适配器：按基础模型 id 匹配；config.json 变了 → changed，基础模型不在 → missing
    - 远程训练的适配器（baseModel.source == "remote"）：本地须有 configHash 与权重指纹（官方清单 sha256）都一致的模型
      → ok；只有 configHash 一致、权重指纹未计算 → unverified（不允许加载，需先校验权重）；都没有 → remote-only
    """
    base = meta.get("baseModel") or {}
    meta["matchedBaseId"] = None
    if base.get("source") == "remote":
        same_cfg = [b for b in list_base() if b["exists"] and b.get("configHash") == base.get("configHash")]
        verified = [b for b in same_cfg if b.get("weightsFingerprint")
                    and b["weightsFingerprint"] == base.get("weightsFingerprint")]
        if verified:
            meta["compat"], meta["matchedBaseId"] = "ok", verified[0]["id"]
        elif any(b.get("weightsFingerprint") for b in same_cfg):
            meta["compat"] = "changed"  # 配置相同但权重不同
        elif same_cfg:
            meta["compat"], meta["matchedBaseId"] = "unverified", same_cfg[0]["id"]
        else:
            meta["compat"] = "remote-only"
        return meta
    try:
        cur = get_base(base.get("id", ""))
        if not cur["exists"]:
            meta["compat"] = "missing"
        else:
            meta["compat"] = "ok" if config_hash(Path(cur["path"])) == base.get("configHash") else "changed"
            meta["matchedBaseId"] = cur["id"] if meta["compat"] == "ok" else None
    except (RegistryError, OSError):
        meta["compat"] = "missing"
    return meta


def get_adapter(adapter_id: str) -> dict:
    meta = _read_json(adapter_dir(adapter_id) / "meta.json")
    if meta is None or not (adapter_dir(adapter_id) / "adapter_config.json").exists():
        raise RegistryError(f"适配器不存在或不完整：{adapter_id}")
    return _with_compat(meta)


def list_adapters() -> list[dict]:
    out = []
    for f in settings.ADAPTER_DIR.glob("*/meta.json"):
        if f.parent.name.endswith(".partial"):  # 下载 / 保存中途的目录，不可用
            continue
        meta = _read_json(f)
        if meta and (f.parent / "adapter_config.json").exists():
            out.append(_with_compat(meta))
    return sorted(out, key=lambda r: r.get("createdAt", ""), reverse=True)


def delete_adapter(adapter_id: str) -> None:
    d = adapter_dir(adapter_id)
    if not d.is_dir():
        raise RegistryError(f"适配器不存在：{adapter_id}")
    shutil.rmtree(d)


def rename_adapter(adapter_id: str, name: str) -> dict:
    meta = get_adapter(adapter_id)
    meta["name"] = name.strip() or meta["name"]
    save_adapter_meta(adapter_id, meta)
    return _with_compat(meta)
