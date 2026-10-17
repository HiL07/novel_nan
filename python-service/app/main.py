"""FastAPI 入口：小说提取异步任务。

POST /api/extract/jobs        提交任务 → jobId（立即返回，后台单线程执行，千问只有 1 个并发槽）
GET  /api/extract/jobs/{id}   查询状态 queued/running/succeeded/failed + 进度 + 结果
GET  /api/health              本服务 + 千问服务健康状态

任务状态只保存在内存中；结果的持久化由 Java 后端负责（系统唯一数据源）。
"""
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import config, extractor, qwen_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
log = logging.getLogger("extract")

app = FastAPI(title="nan_novel AI service")

JobStatus = Literal["queued", "running", "succeeded", "failed"]


class ExtractRequest(BaseModel):
    fileId: int = Field(gt=0)
    fileExt: str


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


def _run(job: Job, file_ext: str) -> None:
    def on_progress(progress: int, message: str) -> None:
        job.progress, job.message = progress, message

    job.status = "running"
    try:
        job.result = extractor.extract(job.fileId, file_ext, on_progress)
        job.progress, job.status = 100, "succeeded"
    except Exception as e:  # 任何异常都要落到 failed，供 Java 端轮询拿到原因
        log.exception("提取失败 jobId=%s fileId=%s", job.jobId, job.fileId)
        job.status, job.error = "failed", str(e) or e.__class__.__name__


@app.get("/api/health")
def health() -> dict:
    return {"code": 0, "message": "ok", "data": {"qwen": qwen_client.health()}}


@app.post("/api/extract/jobs")
def submit(req: ExtractRequest) -> Job:
    ext = req.fileExt.lower()
    if ext not in config.SUPPORTED_EXTS:
        raise HTTPException(400, f"不支持的文件类型：{ext}")
    job = Job(jobId=uuid.uuid4().hex, fileId=req.fileId, message="排队中")
    with _lock:
        _jobs[job.jobId] = job
    _executor.submit(_run, job, ext)
    return job


@app.get("/api/extract/jobs/{job_id}")
def get_job(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    return job
