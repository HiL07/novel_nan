"""小说抓取 API（前缀 /api/crawl），响应 {code, message, data}。由 Java 后端调用（结果由 Java 存入文件管理）。"""
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from ..local.router import LocalError, ok
from . import rules, service
from .fetcher import CrawlError

router = APIRouter(prefix="/api/crawl", tags=["novel-crawl"])


def _guard(fn, *args):
    try:
        return fn(*args)
    except (CrawlError, ValueError) as e:
        raise LocalError(400, str(e)) from e


def _job(job_id: str) -> service.CrawlJob:
    job = service.get(job_id)
    if job is None:
        raise LocalError(404, "抓取任务不存在（AI 服务可能已重启）")
    return job


@router.get("/presets")
def presets():
    return ok([p.model_dump() for p in rules.PRESETS])


@router.post("/preview")
def preview(req: service.CrawlOptions):
    """解析目录 + 试抓第一章（同步，通常数秒）。"""
    return ok(_guard(service.preview, req))


@router.post("/discover")
def discover(req: service.SiteOptions):
    """整站发现（copybook 式）：首页 → 分类 → 列表翻页 → 书籍详情 → 目录，同步返回书籍清单。"""
    return ok(_guard(service.discover, req))


@router.post("/jobs")
def submit(req: service.CrawlRequest):
    return ok(_guard(service.submit, req))


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    return ok(_job(job_id))


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str):
    _job(job_id)
    return ok(service.cancel(job_id))


@router.get("/jobs/{job_id}/text")
def text(job_id: str):
    _job(job_id)
    content = service.text_of(job_id)
    if content is None:
        raise LocalError(404, "全文不存在（任务未成功或已释放）")
    return PlainTextResponse(content, media_type="text/plain; charset=utf-8")


@router.post("/jobs/{job_id}/release")
def release(job_id: str):
    service.release(job_id)
    return ok()
