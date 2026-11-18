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
# 向量（embedding）模型的 model_type：只用于素材向量检索，不能生成 / 训练 LoRA（带 ForSequenceClassification 头的是重排模型）
EMBEDDING_TYPES = {"bert", "xlm-roberta", "roberta", "nomic_bert", "new"}
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


def canonical_config_hash(data: bytes) -> str:
    """config.json 的内容指纹（解析后排序键）：与换行符 / 缩进无关（Windows git 检出会把 LF 改成 CRLF）。"""
    return hashlib.sha256(json.dumps(json.loads(data), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _same_config(rec: dict, base: dict) -> bool:
    if rec.get("configHash") == base.get("configHash"):
        return True
    if not base.get("configCanonicalHash"):
        return False
    try:
        return canonical_config_hash((Path(rec["path"]) / "config.json").read_bytes()) == base["configCanonicalHash"]
    except (OSError, ValueError):
        return False


def inspect_model_dir(path: str) -> dict:
    """校验并读取 Hugging Face 模型目录：config.json + 权重 + 分词器。"""
    p = Path(path).expanduser()
    if not p.is_dir():
        raise RegistryError(f"目录不存在：{path}")
    cfg = _read_json(p / "config.json")
    if cfg is None:
        raise RegistryError("目录中没有 config.json，不是 Hugging Face 模型目录")
    weights = [f for g in WEIGHT_GLOBS for f in p.glob(g)]
    if not weights:
        raise RegistryError("目录中没有 .safetensors / .bin 权重文件（下载可能不完整）")
    if not any((p / f).exists() for f in ("tokenizer.json", "tokenizer.model", "vocab.json", "vocab.txt")):
        raise RegistryError("目录中没有分词器文件（tokenizer.json / tokenizer.model / vocab.json / vocab.txt）")
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
        "task": model_task(cfg.get("model_type"), (cfg.get("architectures") or [""])[0]),
        "quantMethod": _quant_method(cfg),
    }


def _quant_method(cfg: dict) -> str | None:
    """预量化的 HF 模型（GPTQ / AWQ / bitsandbytes / fp8 …）：config.json 的 quantization_config.quant_method。"""
    q = cfg.get("quantization_config")
    return str(q.get("quant_method") or "unknown") if isinstance(q, dict) else None


# ---------------------------------------------------------------- GGUF（llama.cpp 格式，只登记展示）

_GGUF_SHARD = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.I)
# llama.cpp 的 llama_ftype（general.file_type）
_GGUF_FTYPES = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K",
                11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M",
                18: "Q6_K", 19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S", 22: "IQ3_XS", 23: "IQ3_XXS", 24: "IQ1_S",
                25: "IQ4_NL", 26: "IQ3_S", 27: "IQ3_M", 28: "IQ2_S", 29: "IQ2_M", 30: "IQ4_XS", 31: "IQ1_M",
                32: "BF16"}
_GGUF_QUANT_NAME = re.compile(r"(?<![A-Za-z0-9])(I?Q\d(?:_[A-Z0-9]+)*|BF16|F16|F32)(?![A-Za-z0-9])", re.I)
# GGUF 值类型 → struct 格式（8 = 字符串、9 = 数组单独处理）
_GGUF_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}


def is_gguf_path(path: str) -> bool:
    """路径是 .gguf 文件，或是没有 config.json、但有 .gguf 文件的目录。"""
    p = Path(path).expanduser()
    if p.is_file():
        return p.suffix.lower() == ".gguf"
    return p.is_dir() and not (p / "config.json").exists() and any(p.glob("*.gguf"))


def _gguf_main_file(path: str) -> Path:
    p = Path(path).expanduser()
    if p.is_dir():
        files = [f for f in p.glob("*.gguf") if not f.name.lower().startswith("mmproj")]
        main = sorted({f for f in files if not _GGUF_SHARD.search(f.name)}
                      | {f for f in files if (m := _GGUF_SHARD.search(f.name)) and int(m.group(1)) == 1})
        if not main:
            raise RegistryError("目录中没有可用的 .gguf 模型文件（mmproj 是视觉投影文件，不是模型）")
        if len(main) > 1:
            raise RegistryError("目录中有多个 GGUF 模型，请填写具体的 .gguf 文件路径：" + "、".join(f.name for f in main[:8]))
        p = main[0]
    m = _GGUF_SHARD.search(p.name)
    if m and int(m.group(1)) != 1:  # 填的是第 N 个分片：换成第 1 个
        p = p.with_name(_GGUF_SHARD.sub(f"-00001-of-{m.group(2)}.gguf", p.name))
        if not p.is_file():
            raise RegistryError(f"找不到第 1 个分片：{p.name}")
    return p


def _gguf_metadata(f, wanted_prefixes: tuple[str, ...] = ("general.",)) -> dict:
    """读 GGUF 文件头的 KV 元数据（只读开头，遇到 tokenizer.* 就停：后面是几十万个词表项）。"""
    import struct

    def read(fmt: str):
        size = struct.calcsize(fmt)
        data = f.read(size)
        if len(data) < size:
            raise RegistryError("GGUF 文件头不完整（文件可能还没下载完）")
        return struct.unpack(fmt, data)[0]

    def read_str() -> str:
        n = read("<Q")
        if n > 1 << 20:
            raise RegistryError("GGUF 文件头损坏（字符串长度异常）")
        return f.read(n).decode("utf-8", "replace")

    def read_value(t: int):
        if t in _GGUF_SCALARS:
            return read(_GGUF_SCALARS[t])
        if t == 8:
            return read_str()
        if t == 9:
            item_type, n = read("<I"), read("<Q")
            if item_type in _GGUF_SCALARS:
                f.seek(struct.calcsize(_GGUF_SCALARS[item_type]) * n, 1)
            else:
                for _ in range(n):
                    read_value(item_type)
            return None
        raise RegistryError(f"GGUF 文件头损坏（未知值类型 {t}）")

    if f.read(4) != b"GGUF":
        raise RegistryError("不是 GGUF 文件（文件头没有 GGUF 标记）")
    version = read("<I")
    if version < 2:
        raise RegistryError(f"GGUF 版本 {version} 太旧，请用新版 llama.cpp 重新转换")
    read("<Q")  # tensor_count
    kv_count = read("<Q")
    meta: dict = {"version": version}
    for _ in range(kv_count):
        key = read_str()
        if key.startswith("tokenizer."):
            break
        value = read_value(read("<I"))
        if value is not None and (key.startswith(wanted_prefixes) or key.endswith(".context_length")):
            meta[key] = value
    return meta


def _size_label_params(label: str | None) -> int:
    """general.size_label（如 7B、1.5B、8x7B、500M）→ 参数量；认不出返回 0。"""
    m = re.fullmatch(r"(?:(\d+)x)?(\d+(?:\.\d+)?)([KMBT])", (label or "").strip(), re.I)
    if not m:
        return 0
    scale = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[m.group(3).upper()]
    return int(float(m.group(2)) * scale * int(m.group(1) or 1))


def inspect_gguf(path: str) -> dict:
    """读取 GGUF 模型（llama.cpp 格式）的元数据：架构、量化级别、上下文长度、大小。只用于登记展示，不能在本服务推理 / 训练。"""
    p = _gguf_main_file(path)
    try:
        with p.open("rb") as f:
            meta = _gguf_metadata(f)
    except OSError as e:
        raise RegistryError(f"无法读取 GGUF 文件：{e}") from e
    m = _GGUF_SHARD.search(p.name)
    shards = [p.with_name(_GGUF_SHARD.sub(f"-{i:05d}-of-{m.group(2)}.gguf", p.name))
              for i in range(1, int(m.group(2)) + 1)] if m else [p]
    sizes = [s.stat().st_size for s in shards if s.is_file()]
    arch = str(meta.get("general.architecture") or "unknown")
    quant = _GGUF_FTYPES.get(meta.get("general.file_type"))
    if not quant:
        q = _GGUF_QUANT_NAME.search(p.stem)
        quant = q.group(1).upper() if q else None
    return {
        "path": str(p.resolve()),
        "modelType": arch,
        "architecture": "GGUF",
        "task": "gguf",
        "ggufName": meta.get("general.name"),
        "quant": quant,
        "contextLength": meta.get(f"{arch}.context_length"),
        "sizeBytes": sum(sizes),
        "numParams": _size_label_params(meta.get("general.size_label")),
        "shards": len(shards),
        "shardsMissing": len(shards) - len(sizes),
        "ggufVersion": meta["version"],
    }


def task_label(task: str) -> str:
    return {"embedding": "向量模型", "reranker": "重排模型", "gguf": "GGUF 模型"}.get(task, "生成模型")


def not_generation_reason(rec: dict, action: str) -> str:
    """非生成模型被拿去推理 / 训练 / 提取时的提示。"""
    if rec.get("task") == "gguf":
        return (f"「{rec['name']}」是 GGUF 模型，只能用 llama.cpp 运行，不能{action}：到「llama.cpp」页启动它后，"
                "各处选模型时选「GGUF」即可用于提取 / 构思 / 写作")
    return f"「{rec['name']}」是{task_label(rec.get('task', ''))}，只能用于素材检索，不能{action}"


def model_task(model_type: str | None, architecture: str | None) -> str:
    """causal-lm = 生成模型（推理 / 训练 / 小说生成）；embedding = 向量模型（素材向量检索）；
    reranker = 重排模型（交叉编码器，如 bge-reranker-v2-m3，给「查询 + 候选」打相关度分）。"""
    if re.search(r"(ForCausalLM|LMHeadModel|ForConditionalGeneration)$", architecture or ""):
        return "causal-lm"
    if (architecture or "").endswith("ForSequenceClassification"):
        return "reranker"
    return "embedding" if (model_type or "").lower() in EMBEDDING_TYPES else "causal-lm"


def _with_task(rec: dict) -> dict:
    """旧登记没有 task / quantMethod 字段：按已记录的 modelType / architecture、config.json 补出。"""
    rec.setdefault("task", model_task(rec.get("modelType"), rec.get("architecture")))
    if rec["task"] == "gguf":
        rec["exists"] = Path(rec["path"]).is_file()
    elif "quantMethod" not in rec:
        cfg = _read_json(Path(rec["path"]) / "config.json") if rec.get("exists") else None
        rec["quantMethod"] = _quant_method(cfg) if cfg else None
    return rec


# ---------------------------------------------------------------- 基础模型

def _base_record_path(model_id: str) -> Path:
    return settings.BASE_DIR / model_id / "model.json"


def register_base(name: str, path: str, *, source: str = "local", origin: str | None = None,
                  model_id: str | None = None, owns_files: bool = False) -> dict:
    """owns_files：权重是本服务下载到外部目录的（删除登记时一并删除）；手动登记的目录永远不删。
    path 是 .gguf 文件（或只有 .gguf 的目录）时登记为 GGUF 模型（task = gguf，只展示，用 llama.cpp 运行）。"""
    info = inspect_gguf(path) if is_gguf_path(path) else inspect_model_dir(path)
    for m in list_base():
        if m["path"] == info["path"]:
            raise RegistryError(f"该目录已登记为「{m['name']}」")
    model_id = model_id or new_id(name)
    record = {"id": model_id, "name": name.strip() or Path(path).name, "source": source,
              "origin": origin, "createdAt": _now(), **info}
    if owns_files:
        record["ownsFiles"] = True
    (settings.BASE_DIR / model_id).mkdir(parents=True, exist_ok=True)
    _write_json(_base_record_path(model_id), record)
    return record


def get_base(model_id: str) -> dict:
    rec = _read_json(_base_record_path(model_id))
    if rec is None:
        raise RegistryError(f"基础模型不存在：{model_id}")
    rec["exists"] = Path(rec["path"]).is_dir()
    return _with_task(rec)


def list_base() -> list[dict]:
    out = []
    for f in sorted(settings.BASE_DIR.glob("*/model.json")):
        rec = _read_json(f)
        if rec:
            rec["exists"] = Path(rec["path"]).is_dir()
            out.append(_with_task(rec))
    return sorted(out, key=lambda r: r.get("createdAt", ""), reverse=True)


def delete_base(model_id: str) -> None:
    """删除登记与 models/base/<id>/ 目录（含下载到这里的权重）；本服务下载到外部目录的权重（ownsFiles）也一并删除。
    手动登记的外部目录不受影响。"""
    d = settings.BASE_DIR / model_id
    if not (d / "model.json").exists():
        raise RegistryError(f"基础模型不存在：{model_id}")
    rec = _read_json(_base_record_path(model_id)) or {}
    if rec.get("ownsFiles") and rec.get("path") and Path(rec["path"]).is_dir():
        shutil.rmtree(rec["path"])
    shutil.rmtree(d)


def is_managed(rec: dict) -> bool:
    """权重是否由本服务管理（下载到 models/ 下，或下载到自选目录），删除登记会一并删除。"""
    if rec.get("ownsFiles"):
        return True
    try:
        Path(rec["path"]).resolve().relative_to(settings.BASE_DIR.resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- 适配器

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")


def adapter_dir(adapter_id: str) -> Path:
    """只接受登记生成的 id 形式（字母数字与 - _），拒绝「..」、路径分隔符等，前端不能借此访问任意目录。"""
    if not isinstance(adapter_id, str) or not _ID_RE.fullmatch(adapter_id):
        raise RegistryError(f"非法的适配器 id：{adapter_id!r}")
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


def _causal_bases() -> list[dict]:
    """可挂 LoRA 适配器的基础模型：存在的 HF 生成模型（向量 / 重排 / GGUF 都不算）。"""
    return [b for b in list_base() if b["exists"] and b["task"] == "causal-lm"]


def _with_compat(meta: dict) -> dict:
    """附加与本地基础模型的匹配状态与可加载的本地基础模型 matchedBaseId。

    - 本地训练的适配器：按基础模型 id 匹配；config.json 变了 → changed，基础模型不在 → missing
    - 远程训练的适配器（baseModel.source == "remote"）：本地须有 config 一致（原始字节或内容指纹 configCanonicalHash）
      且权重指纹（官方清单 sha256）一致的模型 → ok；config 一致、权重指纹未计算 → unverified（不允许加载，需先校验权重）；
      都没有 → remote-only
    """
    base = meta.get("baseModel") or {}
    meta["matchedBaseId"] = None
    if base.get("source") == "remote":
        same_cfg = [b for b in _causal_bases() if _same_config(b, base)]
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
    if meta["compat"] == "missing":
        # 训练时的登记已删除（如重新登记 / 重新下载同一模型）：同一目录或 config.json 字节相同的本地模型仍可加载
        same = [b for b in _causal_bases() if b["path"] == base.get("path") or _same_config(b, base)]
        if same:
            meta["compat"], meta["matchedBaseId"] = "ok", same[0]["id"]
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
