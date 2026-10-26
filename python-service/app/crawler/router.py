"""小说抓取 API（前缀 /api/crawl），响应 {code, message, data}。由 Java 后端调用（结果由 Java 存入文件管理）。"""
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from ..llm_client import LLMError
from ..local.router import LocalError, ok
from . import ai_rules, catalog, rules, service
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


@router.get("/checkpoints/{key}")
def checkpoint_info(key: str):
    """断点概况（已保存几章），供「继续抓取」前展示。"""
    return ok(_guard(service.checkpoint_info, key))


@router.post("/checkpoints/{key}/delete")
def discard_checkpoint(key: str):
    _guard(service.discard_checkpoint, key)
    return ok()


# ---------------------------------------------------------------- AI 解析地址（模型配置由 Java 随请求下发，不进任务状态）

@router.post("/ai/jobs")
def ai_submit(req: ai_rules.AnalyzeRequest):
    """给一本书的地址：先试已学 / 内置规则，失败再让大模型看页面结构写 XPath，反复试抓直到成功或达到上限。"""
    return ok(_guard(ai_rules.submit, req))


@router.get("/ai/jobs/{job_id}")
def ai_get(job_id: str):
    job = ai_rules.get(job_id)
    if job is None:
        raise LocalError(404, "AI 解析任务不存在（AI 服务可能已重启）")
    return ok(job)


@router.post("/ai/jobs/{job_id}/cancel")
def ai_cancel(job_id: str):
    job = ai_rules.cancel(job_id)
    if job is None:
        raise LocalError(404, "AI 解析任务不存在（AI 服务可能已重启）")
    return ok(job)


# ---------------------------------------------------------------- 全自动爬虫：按学到的规律采集书目（Java 下发规则，书目由 Java 入库）

@router.post("/catalog/jobs")
def catalog_submit(req: catalog.CatalogRequest):
    """从站点首页找书，逐本取书名 / 作者 / 简介 / 标签 / 目录（目录写入 data/<catalogDir>/toc/），抽检首章正文，给出测试报告。"""
    return ok(_guard(catalog.submit, req))


@router.get("/catalog/jobs/{job_id}")
def catalog_get(job_id: str, since: int = 0, tocSince: int = 0):
    """状态 + 第 since 本之后的书目、第 tocSince 条之后的目录补全结果（增量）+ 结束时的报告。"""
    job = catalog.get(job_id, since, tocSince)
    if job is None:
        raise LocalError(404, "书目采集任务不存在（AI 服务可能已重启）")
    return ok(job)


@router.post("/catalog/jobs/{job_id}/cancel")
def catalog_cancel(job_id: str):
    job = catalog.cancel(job_id)
    if job is None:
        raise LocalError(404, "书目采集任务不存在（AI 服务可能已重启）")
    return ok(job)


def _ai(fn, req):
    try:
        return fn(req)
    except LLMError as e:
        raise LocalError(400, f"大模型调用失败：{e}") from e


@router.post("/catalog/plot-tags")
def catalog_plot_tags(req: catalog.PlotTagsRequest):
    """按情节找书（省 token）：模型理解描述后从书目已有标签里挑标签，Java 再按标签筛书。"""
    return ok(_ai(catalog.pick_tags, req))


@router.post("/catalog/intro-match")
def catalog_intro_match(req: catalog.IntroMatchRequest):
    """按情节找书（耗 token）：模型分批逐本读简介打分。"""
    return ok(_ai(catalog.intro_match, req))


@router.post("/catalog/tag")
def catalog_tag(req: catalog.TagRequest):
    """AI 补标签：按书名 / 简介给每本书打 3~6 个题材标签。"""
    return ok(_ai(catalog.tag, req))
