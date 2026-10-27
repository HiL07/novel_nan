"""FastAPI 入口：小说提取异步任务。

POST /api/models/verify       验证模型配置（真实发一次极小请求）
POST /api/extract/jobs        提交任务 → jobId（立即返回，后台执行；任务间串行，任务内按配置并发）
GET  /api/extract/jobs/{id}   查询状态 queued/running/succeeded/failed/cancelled + 进度 + 结果
POST /api/extract/jobs/{id}/cancel  取消提取任务（model = 大模型配置，local = 应用内本地模型，二选一）
GET  /api/health              本服务健康状态
/api/local/**                 本地模型：登记 / 下载、推理、LoRA/QLoRA 风格微调（见 app/local/router.py）
/api/gen/**                   小说生成：工作区、分层上下文、分段生成章节（见 app/generation/router.py）
/api/crawl/**                 网络小说抓取：目录预览、抓取任务（见 app/crawler/router.py，由 Java 调用）

模型配置（含 API Key）由 Java 后端随请求传入，本服务不落盘、不回显密钥；
任务状态只保存在内存中，结果的持久化由 Java 后端负责（系统唯一数据源）。
"""
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import config, extractor, llm_client, local_extract
from . import materials as material_mod
from .llm_client import ModelConfig
from .crawler.router import router as crawl_router
from .local import embedding as local_embedding
from .local import jobs as local_jobs
from .local import llama as local_llama
from .generation import defaults as gen_defaults
from .generation.router import router as gen_router
from .local.router import LocalError, local_error_handler, router as local_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
log = logging.getLogger("extract")

app = FastAPI(title="nan_novel AI service")

# 本地模型页面由前端直接调用本服务（日常 5173，测试 5174）
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_exception_handler(LocalError, local_error_handler)
app.include_router(local_router)
app.include_router(gen_router)
app.include_router(crawl_router)
local_jobs.recover()
app.router.on_shutdown.append(local_llama.shutdown)  # 本服务启动的 llama-server 随服务关闭
gen_defaults.check_on_startup()

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class LocalExtract(BaseModel):
    """应用内本地模型（Transformers 基础模型，不挂适配器）。小模型上下文 / 输出有限，按较小的块切分。"""
    baseId: str = Field(min_length=1, max_length=120)
    chunkChars: int = Field(default=2500, ge=1000, le=6000)


class ExtractRequest(BaseModel):
    fileId: int = Field(gt=0)
    fileExt: str
    model: Optional[ModelConfig] = None    # 大模型（OpenAI 兼容）
    local: Optional[LocalExtract] = None   # 本地模型；与 model 二选一
    gguf: bool = False                     # 用「llama.cpp」页正在运行的 GGUF 模型（代替 model）
    materials: Optional[material_mod.MaterialOptions] = None  # 素材候选提取范围；为空则不提取


class VerifyResult(BaseModel):
    ok: bool
    latencyMs: int
    message: str
    reply: str = ""


class Job(BaseModel):
    jobId: str
    fileId: int
    status: JobStatus = "queued"
    progress: int = 0
    message: str = ""
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    createTime: datetime = Field(default_factory=datetime.now)


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="extract")
_stops: dict[str, threading.Event] = {}  # jobId → 取消标记


def _run(job: Job, file_ext: str, req: ExtractRequest) -> None:
    def on_progress(progress: int, message: str) -> None:
        job.progress, job.message = progress, message

    stop = _stops[job.jobId]
    if stop.is_set():  # 排队时已取消
        job.status, job.message = "cancelled", "已取消"
        return
    job.status = "running"
    try:
        job.result = extractor.extract(job.fileId, file_ext, req.model, on_progress, req.materials,
                                       local=req.local.model_dump() if req.local else None, stop_event=stop)
        job.progress, job.status = 100, "succeeded"
    except extractor.Cancelled:
        job.status, job.message = "cancelled", "已取消"
    except Exception as e:  # 任何异常都要落到 failed，供 Java 端轮询拿到原因
        if stop.is_set():
            job.status, job.message = "cancelled", "已取消"
            return
        log.exception("提取失败 jobId=%s fileId=%s", job.jobId, job.fileId)
        job.status, job.error = "failed", str(e) or e.__class__.__name__


@app.get("/api/health")
def health() -> dict:
    return {"code": 0, "message": "ok", "data": None}


@app.post("/api/models/verify")
def verify_model(cfg: ModelConfig) -> VerifyResult:
    result = VerifyResult(**llm_client.verify(cfg))
    log.info("模型验证 %s -> ok=%s %s", cfg, result.ok, result.message)
    return result


@app.post("/api/materials/expand")
def materials_expand(req: material_mod.ExpandRequest) -> dict:
    """AI 语义检索第 1 步：需求 → 关键词 / 标签 / 分类（Java 用于数据库初筛）。"""
    try:
        return {"ok": True, **material_mod.expand_query(req)}
    except llm_client.LLMError as e:
        return {"ok": False, "message": str(e), "keywords": [], "tags": [], "categories": []}


@app.post("/api/materials/rerank")
def materials_rerank(req: material_mod.RerankRequest) -> dict:
    """AI 语义检索第 2 步：对初筛出的候选按需求打分排序。"""
    try:
        return {"ok": True, "results": material_mod.rerank(req)}
    except llm_client.LLMError as e:
        return {"ok": False, "message": str(e), "results": []}


class VectorItem(BaseModel):
    id: int
    text: str = Field(max_length=20000)


class VectorIndexRequest(BaseModel):
    modelId: Optional[str] = Field(default=None, max_length=120)  # 空 = 默认向量模型
    items: list[VectorItem] = Field(max_length=50000)
    encode: bool = True  # False = 只统计已向量化的条数


class VectorSearchRequest(BaseModel):
    modelId: Optional[str] = Field(default=None, max_length=120)
    query: str = Field(min_length=1, max_length=2000)
    items: list[VectorItem] = Field(max_length=50000)
    limit: int = Field(default=20, ge=1, le=200)
    mode: Literal["vector", "hybrid"] = "hybrid"  # hybrid = 向量 + BM25（jieba）倒数排名融合
    rerank: bool = True  # 有重排模型（bge-reranker-v2-m3）时重排融合后的前 30 条
    vocab: list[str] = Field(default=[], max_length=20000)  # 领域词表（素材标签），给 jieba 分词用


def _vector_call(fn, *args) -> dict:
    try:
        return {"ok": True, **fn(*args)}
    except (RuntimeError, ValueError) as e:  # EmbeddingError / RegistryError
        return {"ok": False, "message": str(e)}


@app.post("/api/materials/vector-index")
def materials_vector_index(req: VectorIndexRequest) -> dict:
    """素材向量化（本地 embedding 模型）：编码全部未缓存的素材，或只统计（encode=false）。"""
    return _vector_call(local_embedding.index, req.modelId or None, [i.model_dump() for i in req.items], req.encode)


@app.post("/api/materials/vector-search")
def materials_vector_search(req: VectorSearchRequest) -> dict:
    """素材检索（本地模型，不用大模型）：Java 传入过滤后的素材文本；向量 + 关键词召回、融合，可选重排。"""
    try:
        return {"ok": True, **local_embedding.search(req.modelId or None, req.query, [i.model_dump() for i in req.items],
                                                     req.limit, mode=req.mode, rerank=req.rerank, vocab=req.vocab)}
    except (RuntimeError, ValueError) as e:  # EmbeddingError / RegistryError
        return {"ok": False, "message": str(e)}


class VectorFeedbackRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    modelId: str = Field(default="", max_length=120)
    shownIds: list[int] = Field(default=[], max_length=500)
    pickedIds: list[int] = Field(default=[], max_length=500)
    context: str = Field(default="", max_length=200)


@app.post("/api/materials/vector-feedback")
def materials_vector_feedback(req: VectorFeedbackRequest) -> dict:
    """向量检索后勾选 / 没勾选的素材：记入 data/material-index/feedback.jsonl（以后 embedding 微调的训练数据）。"""
    local_embedding.record_feedback(req.model_dump())
    return {"ok": True}


@app.post("/api/extract/jobs")
def submit(req: ExtractRequest) -> Job:
    ext = req.fileExt.lower()
    if ext not in config.SUPPORTED_EXTS:
        raise HTTPException(400, f"不支持的文件类型：{ext}")
    if req.gguf:
        try:
            req.model = ModelConfig(**local_llama.api_config())
        except local_llama.LlamaError as e:
            raise HTTPException(400, str(e)) from e
    if (req.model is None) == (req.local is None):
        raise HTTPException(400, "请指定大模型配置或本地模型（二选一）")
    if req.local:
        try:
            local_extract.check_available()
        except llm_client.LLMError as e:
            raise HTTPException(400, str(e)) from e
    job = Job(jobId=uuid.uuid4().hex, fileId=req.fileId, message="排队中")
    with _lock:
        _jobs[job.jobId] = job
        _stops[job.jobId] = threading.Event()
    _executor.submit(_run, job, ext, req)
    return job


@app.get("/api/extract/jobs/{job_id}")
def get_job(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    return job


@app.post("/api/extract/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> Job:
    """取消：排队中的直接结束；运行中的不再开始新的分块（本地模型在下一个 token 处停止）。"""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if job.status in ("queued", "running"):
        _stops[job_id].set()
        job.message = "正在取消…"
    return job
