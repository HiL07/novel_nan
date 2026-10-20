"""本地模型 API（前缀 /api/local），响应统一为 {code, message, data}，code=0 表示成功。"""
import logging
import os
import re
import string
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import text_loader
from . import download, hardware, inference, jobfiles, jobs, registry, settings, train_config

log = logging.getLogger("local.api")
router = APIRouter(prefix="/api/local", tags=["local-models"])


class LocalError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


def local_error_handler(_, exc: LocalError) -> JSONResponse:
    status = exc.code if 400 <= exc.code < 600 else 400
    return JSONResponse(status_code=status, content={"code": exc.code, "message": exc.message, "data": exc.data})


def ok(data=None) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def _guard(fn, *args, **kwargs):
    """把业务异常转成 LocalError（400），其余异常交给全局处理。"""
    try:
        return fn(*args, **kwargs)
    except (registry.RegistryError, jobs.JobError, RuntimeError) as e:
        raise LocalError(400, str(e)) from e


# ---------------------------------------------------------------- 系统 / 模型

@router.get("/system")
def system():
    return ok({**hardware.system_info(), "inference": inference.status(), "activeJob": jobs.active_job()})


def _with_load_status(models: list[dict]) -> list[dict]:
    st = inference.status()
    for m in models:
        m["loadStatus"] = st["status"] if st["baseId"] == m["id"] else "idle"
        m["managed"] = registry.is_managed(m)
    return models


@router.get("/models")
def list_models():
    return ok(_with_load_status(registry.list_base()))


class RegisterReq(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    path: str = Field(min_length=1, max_length=1000)


@router.post("/models/register")
def register_model(req: RegisterReq):
    return ok(_guard(registry.register_base, req.name, req.path))


class DownloadReq(BaseModel):
    repoId: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    name: str = ""
    # auto / modelscope / hf-mirror / huggingface；不传则用服务配置 MODEL_DOWNLOAD_SOURCE（默认 auto）
    source: Literal["auto", "modelscope", "hf-mirror", "huggingface"] | None = None
    useMirror: bool | None = None  # 旧参数：仅在未传 source 时生效（True → hf-mirror，False → huggingface）
    # 保存位置（绝对路径的上级目录，实际写入 <targetDir>/<仓库名>）；空 = models/base/<id>/weights
    targetDir: str | None = Field(default=None, max_length=500)


@router.get("/models/download/sources")
def download_sources():
    return ok({"default": settings.DOWNLOAD_SOURCE, "autoOrder": download.resolve_order("auto"),
               "endpoints": {"modelscope": settings.MODELSCOPE_ENDPOINT, "hf-mirror": settings.HF_MIRROR_ENDPOINT,
                             "huggingface": settings.HF_OFFICIAL_ENDPOINT}})


@router.post("/models/download")
def download_model(req: DownloadReq):
    name = req.name.strip() or req.repoId.split("/")[-1]
    source = req.source or ({True: "hf-mirror", False: "huggingface"}[req.useMirror] if req.useMirror is not None
                            else settings.DOWNLOAD_SOURCE)
    if source not in download.SOURCES:
        raise LocalError(500, f"服务配置 MODEL_DOWNLOAD_SOURCE 无效：{source}（可选 {', '.join(download.SOURCES)}）")
    cfg = {"repoId": req.repoId, "name": name, "modelId": registry.new_id(name), "source": source}
    if req.targetDir and req.targetDir.strip():
        try:
            target = download.resolve_target(req.targetDir, req.repoId, cfg["modelId"])
        except ValueError as e:
            raise LocalError(400, str(e)) from e
        for m in registry.list_base():
            if Path(m["path"]).resolve() == target.resolve():
                raise LocalError(400, f"{target} 已登记为「{m['name']}」")
        cfg["targetDir"] = str(target)
    return ok(_guard(jobs.create, "download", cfg))


class DownloadCheckReq(BaseModel):
    repoId: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    source: Literal["auto", "modelscope", "hf-mirror", "huggingface"] | None = None
    targetDir: str | None = Field(default=None, max_length=500)


@router.post("/models/download/check")
def download_check(req: DownloadCheckReq):
    """下载前检查（同步，需联网几秒）：可用的下载源、模型大小、保存位置所在磁盘的剩余空间。"""
    try:
        return ok(download.check(req.repoId, req.source or settings.DOWNLOAD_SOURCE, req.targetDir))
    except (ValueError, RuntimeError) as e:
        raise LocalError(400, str(e)) from e


@router.get("/fs/dirs")
def list_dirs(path: str = ""):
    """「保存位置」的目录浏览（只列目录，只读）：path 为空时列出各磁盘。→ {path, parent, dirs[{name, path}], freeGb}"""
    if not path.strip():
        drives = [f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")] if os.name == "nt" else ["/"]
        return ok({"path": "", "parent": None, "freeGb": None,
                   "dirs": [{"name": d, "path": d, "freeGb": hardware.disk_free_gb(d)} for d in drives]})
    p = Path(path.strip().strip('"'))
    if not p.is_absolute() or not p.is_dir():
        raise LocalError(400, f"目录不存在：{path}")
    p = p.resolve()
    try:
        children = sorted((c for c in p.iterdir() if c.is_dir() and not c.name.startswith(("$", "."))),
                          key=lambda c: c.name.lower())
    except OSError as e:
        raise LocalError(400, f"无法读取目录：{e}") from e
    parent = str(p.parent) if p.parent != p else ""
    return ok({"path": str(p), "parent": parent, "freeGb": hardware.disk_free_gb(p),
               "dirs": [{"name": c.name, "path": str(c)} for c in children[:500]]})


@router.post("/models/{model_id}/delete")
def delete_model(model_id: str):
    st = inference.status()
    if st["baseId"] == model_id and st["status"] in ("loaded", "loading"):
        raise LocalError(400, "该模型正在使用中，请先卸载")
    _guard(registry.delete_base, model_id)
    return ok()


class EstimateReq(BaseModel):
    baseModelId: str
    mode: Literal["infer", "train"] = "train"
    quantization: Literal["4bit", "none"] = "4bit"
    maxSeqLen: int = Field(default=512, ge=64, le=4096)
    batchSize: int = Field(default=1, ge=1, le=16)
    loraR: int = Field(default=16, ge=1, le=256)
    adapterId: Optional[str] = None  # 推理：要加载的适配器（计入其权重大小）


@router.post("/estimate")
def estimate(req: EstimateReq):
    base = _guard(registry.get_base, req.baseModelId)
    extra = {}
    if req.mode == "infer":
        # 按本服务当前驻留情况估算：同一基础模型已加载 → 只算适配器增量；驻留的是别的模型 → 加载前会释放，计入可用显存
        st = inference.status()
        resident = (st["status"] == "loaded" and st["baseId"] == req.baseModelId
                    and st["quantization"] == req.quantization)
        adapter_bytes = 0
        if req.adapterId and not (resident and st["attachedAdapterId"] == req.adapterId):
            f = _guard(registry.adapter_dir, req.adapterId) / "adapter_model.safetensors"
            adapter_bytes = f.stat().st_size if f.exists() else 0
        extra = {"adapter_bytes": adapter_bytes, "resident": resident,
                 "reclaimable_gb": 0.0 if resident else inference.resident_vram_gb()}
    return ok(hardware.estimate(base, req.mode, quantization=req.quantization, seq_len=req.maxSeqLen,
                                batch_size=req.batchSize, lora_r=req.loraR, **extra))


# ---------------------------------------------------------------- 适配器

@router.get("/adapters")
def list_adapters():
    return ok(registry.list_adapters())


@router.get("/adapters/{adapter_id}")
def get_adapter(adapter_id: str):
    return ok(_guard(registry.get_adapter, adapter_id))


class RenameReq(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.post("/adapters/{adapter_id}/rename")
def rename_adapter(adapter_id: str, req: RenameReq):
    return ok(_guard(registry.rename_adapter, adapter_id, req.name))


@router.post("/adapters/{adapter_id}/delete")
def delete_adapter(adapter_id: str):
    st = inference.status()
    if adapter_id in (st["adapterId"], st["attachedAdapterId"]) and st["status"] in ("loaded", "loading"):
        raise LocalError(400, "该适配器正在使用中，请先卸载模型")
    _guard(registry.delete_adapter, adapter_id)
    return ok()


# ---------------------------------------------------------------- 推理

class LoadReq(BaseModel):
    baseId: str
    adapterId: Optional[str] = None
    quantization: Literal["auto", "4bit", "none"] = "auto"


@router.get("/inference")
def inference_status():
    return ok(inference.status())


@router.post("/inference/load")
def inference_load(req: LoadReq):
    return ok(_guard(inference.load, req.baseId, req.adapterId or None, req.quantization))


@router.post("/inference/unload")
def inference_unload():
    _guard(inference.unload)
    return ok(inference.status())


class GenerateReq(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    maxNewTokens: int = Field(default=200, ge=1, le=1024)
    temperature: float = Field(default=0.8, ge=0, le=2)
    topP: float = Field(default=0.9, gt=0, le=1)
    repetitionPenalty: float = Field(default=1.1, ge=1, le=2)
    useChatTemplate: bool = False
    useAdapter: Optional[bool] = None  # None = 按当前启用状态；true / false = 本次启用 / 停用已挂载的适配器
    seed: Optional[int] = Field(default=None, ge=0, le=2**31 - 1)


def _gen_kwargs(req: GenerateReq) -> dict:
    return {"max_new_tokens": req.maxNewTokens, "temperature": req.temperature, "top_p": req.topP,
            "repetition_penalty": req.repetitionPenalty, "use_chat_template": req.useChatTemplate}


@router.post("/inference/generate")
def inference_generate(req: GenerateReq):
    return ok(_guard(inference.generate, req.prompt, use_adapter=req.useAdapter, seed=req.seed, **_gen_kwargs(req)))


@router.post("/inference/compare")
def inference_compare(req: GenerateReq):
    """同一提示词 + 同一种子分别用基础模型（停用适配器）和微调模型生成；需已加载带适配器的模型。"""
    return ok(_guard(inference.compare, req.prompt, seed=1234 if req.seed is None else req.seed, **_gen_kwargs(req)))


class EvaluateReq(BaseModel):
    text: str = Field(min_length=20, max_length=50000)
    maxTokens: int = Field(default=4096, ge=64, le=16384)


@router.post("/inference/evaluate")
def inference_evaluate(req: EvaluateReq):
    """同一文本在停用 / 启用适配器时的 loss 与困惑度对比（定量验证适配器是否生效）；需已加载带适配器的模型。"""
    return ok(_guard(inference.evaluate, req.text, max_tokens=req.maxTokens))


# ---------------------------------------------------------------- 训练任务

class SampleFile(BaseModel):
    id: int = Field(gt=0)
    ext: str
    name: str = ""


class TrainReq(BaseModel):
    """可调参数（loraR … valRatio）不传时取 train_config 的档位默认值（本机 "local" 档 / 远程 "remote" 档）。"""
    baseModelId: str = ""
    adapterName: str = Field(min_length=1, max_length=100)
    method: Literal["qlora", "lora"] = "qlora"
    sampleText: str = ""
    sampleFiles: list[SampleFile] = []
    loraR: Optional[int] = Field(default=None, ge=1, le=128)
    loraAlpha: Optional[int] = Field(default=None, ge=1, le=256)
    loraDropout: Optional[float] = Field(default=None, ge=0, le=0.5)
    maxSeqLen: Optional[int] = Field(default=None, ge=64, le=4096)
    epochs: Optional[int] = Field(default=None, ge=1, le=50)
    learningRate: Optional[float] = Field(default=None, gt=0, le=1e-2)
    batchSize: Optional[int] = Field(default=None, ge=1, le=16)
    gradAccum: Optional[int] = Field(default=None, ge=1, le=64)
    valRatio: Optional[float] = Field(default=None, ge=0, le=0.3)  # 0 = 不划分验证集
    maxSteps: int = Field(default=0, ge=0, le=100000)
    seed: int = 42
    samplePrompt: Optional[str] = Field(default=None, max_length=200)  # 空 = train_config.SAMPLE_PROMPT
    force: bool = False  # 资源评估为 exceed 时仍强制开始
    # 执行位置：local = 本机 GPU；remote = targets.json 中的远程机器（baseModelId 此时可为空，用 remoteModelId）
    backend: Literal["local", "remote"] = "local"
    targetId: Optional[str] = None
    remoteModelId: Optional[str] = None


@router.get("/train/defaults")
def train_defaults():
    return ok({"profiles": train_config.PROFILES, "samplePrompt": train_config.SAMPLE_PROMPT,
               "sampleParams": train_config.SAMPLE_PARAMS})


def _collect_samples(req: TrainReq) -> tuple[str, list[dict], list[dict]]:
    """返回 (拼接文本, 来源摘要, 来源在拼接文本中的字符区间)；区间供训练时按来源 / 章节划分验证集。"""
    parts, sources = [], []
    if req.sampleText.strip():
        parts.append(text_loader.clean_text(req.sampleText))
        sources.append({"type": "text", "name": "粘贴文本", "chars": len(parts[-1])})
    for f in req.sampleFiles:
        try:
            text = text_loader.to_plain_text(text_loader.fetch_file(f.id), f.ext)
        except Exception as e:  # noqa: BLE001
            raise LocalError(400, f"读取文件「{f.name or f.id}」失败：{e}") from e
        if text:
            parts.append(text)
            sources.append({"type": "file", "fileId": f.id, "name": f.name, "chars": len(text)})
    index, pos = [], 0
    for src, part in zip(sources, parts):
        index.append({**{k: v for k, v in src.items() if k != "chars"}, "start": pos, "end": pos + len(part)})
        pos += len(part) + 2  # "\n\n"
    return "\n\n".join(parts), sources, index


def _start_remote_training(req: TrainReq):
    from ..remote import targets

    try:
        target = targets.get(req.targetId or "")
        model = targets.get_model(target, req.remoteModelId or "")
    except targets.TargetError as e:
        raise LocalError(400, str(e)) from e
    params = train_config.resolve("remote", req.model_dump(include=set(train_config.TUNABLE_KEYS)))
    samples, sources, index = _collect_samples(req)
    if len(samples) < settings.MIN_SAMPLE_CHARS:
        raise LocalError(400, f"写作样本太少（{len(samples)} 字），至少需要 {settings.MIN_SAMPLE_CHARS} 字")
    adapter_id = re.sub(r"[^a-zA-Z0-9-]", "", registry.new_id(req.adapterName))
    cfg = req.model_dump(exclude={"sampleText", "sampleFiles", "force", "baseModelId"}) | params
    cfg.update(adapterId=adapter_id, sampleChars=len(samples), sampleSources=sources, sampleIndex=index,
               paramProfile="remote", remoteModel={k: model.get(k) for k in ("id", "name", "repoId", "path")})
    return ok(_guard(jobs.create, "train", cfg, samples=samples, backend="remote"))


@router.get("/remote/targets")
def remote_targets():
    from ..remote import targets

    try:
        return ok([targets.public_view(t) for t in targets.list_targets()])
    except targets.TargetError as e:
        raise LocalError(400, str(e)) from e


@router.post("/remote/targets/{target_id}/probe")
def remote_probe(target_id: str):
    """测试连接（只读）：主机名、GPU、显存、数据盘空间、Python / torch。"""
    from ..remote import ssh, targets

    try:
        t = targets.get(target_id)
        out = ssh.text(t, "hostname; nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader; "
                          f"df -h {t['workDir'].rsplit('/', 1)[0]} | tail -1; "
                          f"{t['python']} -c 'import torch;print(torch.__version__, torch.cuda.is_available())'",
                       timeout=90)
    except (targets.TargetError, ssh.SSHError) as e:
        raise LocalError(400, str(e)) from e
    lines = out.strip().splitlines()
    return ok({"ok": True, "hostname": lines[0] if lines else None, "gpu": lines[1] if len(lines) > 1 else None,
               "disk": lines[2] if len(lines) > 2 else None, "torch": lines[3] if len(lines) > 3 else None})


@router.post("/train")
def start_training(req: TrainReq):
    if req.backend == "remote":
        return _start_remote_training(req)
    base = _guard(registry.get_base, req.baseModelId)
    if not base["exists"]:
        raise LocalError(400, f"模型目录不存在：{base['path']}")
    deps = hardware.deps_info()
    if not deps["ready"]:
        raise LocalError(400, "未安装本地训练依赖（torch / transformers / peft / accelerate），见 requirements-local.txt")
    quant = "4bit" if req.method == "qlora" else "none"
    params = train_config.resolve("local", req.model_dump(include=set(train_config.TUNABLE_KEYS)))
    est = hardware.estimate(base, "train", quantization=quant, seq_len=params["maxSeqLen"],
                            batch_size=params["batchSize"], lora_r=params["loraR"])
    if est["level"] == "exceed" and not req.force:
        raise LocalError(409, "当前配置可能超出本机资源：" + "；".join(est["messages"]), est)

    samples, sources, index = _collect_samples(req)
    if len(samples) < settings.MIN_SAMPLE_CHARS:
        raise LocalError(400, f"写作样本太少（{len(samples)} 字），至少需要 {settings.MIN_SAMPLE_CHARS} 字，建议 1 万字以上")

    adapter_id = re.sub(r"[^a-zA-Z0-9-]", "", registry.new_id(req.adapterName))
    cfg = req.model_dump(exclude={"sampleText", "sampleFiles", "force", "baseModelId"}) | params
    cfg.update(baseModel=base, adapterId=adapter_id, sampleChars=len(samples), sampleSources=sources,
               sampleIndex=index, paramProfile="local", estimate=est)
    return ok(_guard(jobs.create, "train", cfg, samples=samples))


@router.get("/jobs")
def list_jobs():
    return ok(jobs.list_jobs())


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    return ok(_guard(jobs.get_job, job_id))


@router.get("/jobs/{job_id}/log")
def job_log(job_id: str, lines: int = 300):
    _guard(jobs.get_job, job_id)
    return ok({"log": jobfiles.tail_log(job_id, max(1, min(lines, 2000)))})


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    return ok(_guard(jobs.cancel, job_id))
