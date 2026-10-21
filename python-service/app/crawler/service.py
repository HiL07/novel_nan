"""目录预览与抓取任务。任务状态在内存中（同提取任务）：Java 轮询状态，成功后取走全文存入文件管理，再通知释放。
带 resumeKey 的任务逐章写断点（checkpoint.py），进程关闭 / 断网 / 换域名后可从断点继续。

与 copybook 的差异：copybook 用 scrapy 并发爬整站、每章一条记录直接写 sqlite；
这里一次只抓一本、单线程限速、章节顺序天然有序，失败章节留占位继续，结果合成一份 txt。
"""
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from . import checkpoint, parser, rules
from .fetcher import CrawlError, Fetcher, NetworkError, check_url
from .rules import CrawlRule

log = logging.getLogger("crawler")

MAX_TOC_PAGES = 30          # 目录分页上限
MAX_SUB_PAGES = 20          # 一章内分页上限
MAX_CHAPTERS = 5000         # 单任务章节上限
MAX_CONSECUTIVE_FAILS = 10  # 连续失败这么多章即判定被封 / 规则不对，终止任务
KEEP_TEXTS = 3              # 内存中最多保留几份未取走的全文
NETWORK_WAITS = (10, 20, 30, 60, 60, 120)  # 断网 / 站点暂时不可达时，同一章的等待重试间隔（秒，共约 5 分钟）

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class CrawlOptions(BaseModel):
    url: str = Field(min_length=8, max_length=2000)   # 目录页地址
    preset: str = ""                                  # 规则预设 key；空 = 按域名匹配，否则 auto
    rule: Optional[CrawlRule] = None                  # 自定义规则，非空字段覆盖预设
    delayMs: int = Field(default=1000, ge=300, le=30000)  # 两次请求的最小间隔
    respectRobots: bool = True


class CrawlRequest(CrawlOptions):
    startIndex: int = Field(default=1, ge=1)          # 抓取范围（目录中的序号，1 起，含两端）
    endIndex: Optional[int] = Field(default=None, ge=1)
    # 断点 key（Java 生成，见 checkpoint.py）。有断点时沿用断点里的章节清单与范围，已抓的章节不再请求
    resumeKey: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    # 站点换了域名 / IP（路径不变）：把断点和入口里旧站点下的地址整体换到这个 scheme://host[:port]
    newOrigin: Optional[str] = Field(default=None, max_length=300)


class SiteOptions(BaseModel):
    """整站发现参数（copybook 式：首页 → 分类 → 列表翻页 → 书籍）。url 为站点首页或分类列表页。"""
    url: str = Field(min_length=8, max_length=2000)
    preset: str = ""
    rule: Optional[CrawlRule] = None
    delayMs: int = Field(default=1000, ge=300, le=30000)
    respectRobots: bool = True
    maxCategories: int = Field(default=10, ge=1, le=30)             # 最多看几个分类
    maxListPages: int = Field(default=5, ge=1, le=20)               # 每个分类最多翻几页
    maxBooks: int = Field(default=20, ge=1, le=120)                 # 最多发现几本书
    categories: list[str] = Field(default_factory=list)             # 只要含这些名字的分类（空 = 全部）
    verify: bool = True                                             # 解析每本的目录（多花请求，但能提前发现规则不对）


class CrawlJob(BaseModel):
    jobId: str
    url: str
    status: JobStatus = "queued"
    progress: int = 0
    message: str = ""
    error: Optional[str] = None
    preset: str = ""
    bookName: str = ""
    author: str = ""
    chapterTotal: int = 0
    chapterDone: int = 0
    chapterFailed: int = 0
    failedChapters: list[str] = Field(default_factory=list)  # 前 50 个失败章节「标题：原因」
    wordCount: int = 0
    resumeKey: Optional[str] = None
    resumedChapters: int = 0   # 从断点直接复用的章节数
    createTime: datetime = Field(default_factory=datetime.now)
    finishTime: Optional[datetime] = None


_jobs: dict[str, CrawlJob] = {}
_texts: dict[str, str] = {}
_cancel: set[str] = set()
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="crawl")


# ---------------------------------------------------------------- 预览

def preview(opts: CrawlOptions) -> dict:
    """解析目录（含分页）并试抓第一章，供用户确认规则是否正确、选择抓取范围。"""
    url = check_url(opts.url)
    preset_key, rule = rules.resolve(opts.preset, opts.rule, urlsplit(url).hostname or "")
    with Fetcher(opts.delayMs, opts.respectRobots, rule.encoding) as f:
        url = resolve_toc_url(f, url, rule)
        toc = _load_toc(f, url, rule)
        sample = None
        if toc["chapters"]:
            first = toc["chapters"][0]
            try:
                text = _load_chapter(f, first, rule, url)
                sample = {"title": first["title"], "url": first["url"], "chars": len(text), "text": text[:600]}
            except (CrawlError, ValueError) as e:
                sample = {"title": first["title"], "url": first["url"], "chars": 0, "text": "", "error": str(e)}
    return {**toc, "tocUrl": url, "preset": preset_key, "rule": rule.model_dump(), "chapterCount": len(toc["chapters"]),
            "sample": sample}


def resolve_toc_url(f: Fetcher, url: str, rule: CrawlRule) -> str:
    """规则带 tocLink 时（如 AI 学到的规则、整站预设），给的是书籍详情页也能跳到目录页；
    页面上没有该链接（本身就是目录页）时原样返回。"""
    if not rule.tocLink:
        return url
    final_url, html = f.get_html(url)
    href = parser.parse_next(html, final_url, rule.tocLink)
    return href or url


def _load_toc(f: Fetcher, url: str, rule: CrawlRule, max_pages: int = MAX_TOC_PAGES) -> dict:
    final_url, html = f.get_html(url)
    toc = parser.parse_toc(html, final_url, rule)
    seen = {final_url, url}
    chapters, next_url, pages = list(toc["chapters"]), toc["nextUrl"], 1
    while next_url and next_url not in seen and pages < max_pages:
        seen.add(next_url)
        page_url, html = f.get_html(next_url, referer=final_url)
        more = parser.parse_toc(html, page_url, rule)
        chapters += more["chapters"]
        next_url, pages = more["nextUrl"], pages + 1
    toc["chapters"] = parser.dedupe_keep_last(chapters, final_url)
    toc["tocPages"] = pages
    toc.pop("nextUrl", None)
    if not toc["chapters"]:
        raise CrawlError("目录页上没有识别到章节链接：请确认填的是「章节目录页」地址，或在高级选项中填写章节链接 XPath")
    return toc


# ---------------------------------------------------------------- 整站发现（copybook 式）

VERIFY_TOC_PAGES = 3   # 发现阶段只翻目录前几页，够判断规则对不对即可


def discover(opts: SiteOptions) -> dict:
    """站点首页 → 分类 → 分类列表翻页 → 书籍 →（可选）解析目录，返回可勾选的书籍清单。

    对应 copybook 的 parse（分类）/ getNext（列表翻页）/ getBooks（详情）三段；
    copybook 是一次性全站铺开，这里按 maxCategories / maxListPages / maxBooks 有界采样，先给用户看清单。
    """
    url = check_url(opts.url)
    preset_key, rule = rules.resolve(opts.preset, opts.rule, urlsplit(url).hostname or "")
    books: list[dict] = []
    seen_books: set[str] = set()
    categories: list[dict] = []
    truncated = False
    site_name, home_url = "", url

    with Fetcher(opts.delayMs, opts.respectRobots, rule.encoding) as f:
        home_url, html = f.get_html(url)
        site = parser.parse_site(html, home_url, rule)
        site_name = site["siteName"]
        cats = site["categories"]
        if not cats:  # 首页没有分类导航，或用户直接给了一个分类列表页：当成单个「整站」入口
            cats = [{"name": site_name or "整站", "url": home_url}]
        all_cats = [{"name": c["name"], "url": c["url"]} for c in cats]  # 站点上发现的全部分类（UI 展示）
        if opts.categories:
            wanted = [w.strip() for w in opts.categories if w.strip()]
            picked = [c for c in cats if any(w in c["name"] for w in wanted)]
            cats = picked or cats
        cats = cats[:opts.maxCategories]
        log.info("整站发现 %s → %s 个分类，上限 %s 本", url, len(cats), opts.maxBooks)

        for cat in cats:
            page_url, pages, found, cat_error = cat["url"], 0, 0, ""
            while page_url and pages < opts.maxListPages:
                try:
                    page_final, page_html = f.get_html(page_url, referer=home_url)
                except (CrawlError, ValueError) as e:
                    cat_error = str(e)
                    break
                for link in parser.parse_book_links(page_html, page_final, rule):
                    if link["url"] in seen_books:
                        continue
                    seen_books.add(link["url"])
                    books.append({"bookName": link["title"], "author": "", "intro": "",
                                  "sourceUrl": link["url"], "tocUrl": "", "category": cat["name"],
                                  "chapterCount": None, "error": ""})
                    found += 1
                    if len(books) >= opts.maxBooks:
                        truncated = True
                        break
                pages += 1
                if len(books) >= opts.maxBooks:
                    break
                page_url = parser.parse_next(page_html, page_final, rule.listNext)
            categories.append({"name": cat["name"], "url": cat["url"], "pages": pages,
                               "books": found, "error": cat_error})
            if len(books) >= opts.maxBooks:
                break

        if not books:
            raise CrawlError("没有发现任何书籍链接：请确认填的是站点首页或分类列表页，"
                             "或在高级选项中填写「分类链接 / 书籍链接」XPath")

        for i, book in enumerate(books, 1):
            try:
                detail_final, detail_html = f.get_html(book["sourceUrl"], referer=home_url)
                detail = parser.parse_book_detail(detail_html, detail_final, rule)
                book["bookName"] = detail["bookName"] or book["bookName"] or "未命名小说"
                book["author"] = detail["author"]
                book["intro"] = detail["intro"]
                book["tocUrl"] = detail["tocUrl"] or book["sourceUrl"]
            except (CrawlError, ValueError) as e:
                book["tocUrl"] = book["sourceUrl"]
                book["error"] = f"详情页解析失败：{e}"
                continue
            if not opts.verify:
                continue
            try:
                toc = _load_toc(f, book["tocUrl"], rule, max_pages=VERIFY_TOC_PAGES)
                book["chapterCount"] = len(toc["chapters"])
                # 详情页已经解析出的名字/作者更可信（目录页的 <title> 常带「目录」后缀），只做兜底
                book["bookName"] = book["bookName"] or toc["bookName"] or "未命名小说"
                book["author"] = book["author"] or toc["author"]
            except (CrawlError, ValueError) as e:
                book["error"] = str(e)
            log.info("发现 %s/%s：%s（%s 章）", i, len(books), book["bookName"], book["chapterCount"])

    return {"siteName": site_name, "url": home_url, "preset": preset_key, "rule": rule.model_dump(),
            "categoriesAll": all_cats, "categories": categories, "books": books,
            "bookCount": len(books), "truncated": truncated,
            "limits": {"maxCategories": opts.maxCategories, "maxListPages": opts.maxListPages,
                       "maxBooks": opts.maxBooks, "verify": opts.verify}}


def _load_chapter(f: Fetcher, chapter: dict, rule: CrawlRule, referer: str) -> str:
    url, parts, seen = chapter["url"], [], set()
    while url and url not in seen and len(seen) < MAX_SUB_PAGES:
        seen.add(url)
        final_url, html = f.get_html(url, referer=referer)
        text, url = parser.parse_content(html, final_url, rule)
        parts.append(_strip_title(text, chapter["title"]))
        referer = final_url
    text = "\n".join(p for p in parts if p)
    if not text.strip():
        raise CrawlError("正文为空（规则不匹配或页面需要登录 / 脚本加载）")
    return text


def _strip_title(text: str, title: str) -> str:
    """每页正文开头常重复章节名，去掉。"""
    first, _, rest = text.partition("\n")
    return rest if first.replace(" ", "") == title.replace(" ", "") else text


# ---------------------------------------------------------------- 任务

def submit(req: CrawlRequest) -> CrawlJob:
    saved = checkpoint.load(req.resumeKey) if req.resumeKey else None
    if req.newOrigin:
        req.newOrigin = _origin_only(req.newOrigin)
        req.url = checkpoint.rewrite_origin(req.url, checkpoint.origin_of(req.url), req.newOrigin)
    if req.endIndex is not None and req.endIndex < req.startIndex:
        raise ValueError("结束章节不能小于起始章节")
    # 有断点时不依赖入口地址（目录页失效 / 域名解析失败也能续抓），地址问题留给具体章节处理
    url = req.url.strip() if saved else check_url(req.url)
    preset_key, rule = rules.resolve(req.preset, req.rule, urlsplit(url).hostname or "")
    with _lock:
        if req.resumeKey:
            # Java 重启后再次续抓，而上一次的任务其实还在跑：直接接管它，避免同一断点被两个任务同时写
            for old in _jobs.values():
                if old.resumeKey == req.resumeKey and old.status in ("queued", "running"):
                    return old
        job = CrawlJob(jobId=uuid.uuid4().hex, url=url, preset=preset_key, message="排队中",
                       resumeKey=req.resumeKey)
        _jobs[job.jobId] = job
        _evict()
    _executor.submit(_run, job, req, rule)
    return job


def get(job_id: str) -> Optional[CrawlJob]:
    return _jobs.get(job_id)


def text_of(job_id: str) -> Optional[str]:
    return _texts.get(job_id)


def cancel(job_id: str) -> Optional[CrawlJob]:
    job = _jobs.get(job_id)
    if job and job.status in ("queued", "running"):
        _cancel.add(job_id)
        job.message = "正在取消…"
    return job


def release(job_id: str) -> None:
    """Java 已保存全文后调用，释放内存；成功任务的断点随之删除。"""
    with _lock:
        _texts.pop(job_id, None)
        job = _jobs.get(job_id)
    if job and job.resumeKey and job.status == "succeeded":
        checkpoint.remove(job.resumeKey)


def checkpoint_info(key: str) -> dict:
    """断点概况 → {exists, url, bookName, chapterTotal, chapterSaved}"""
    saved = checkpoint.load(key)
    if not saved:
        return {"exists": False}
    meta = saved["meta"]
    return {"exists": True, "url": meta.get("url"), "bookName": meta.get("bookName"),
            "chapterTotal": len(meta.get("chapters") or []), "chapterSaved": len(saved["done"])}


def discard_checkpoint(key: str) -> None:
    """放弃断点（从头重新抓取时）。正在使用该断点的任务结束前不删除。"""
    with _lock:
        if any(j.resumeKey == key and j.status in ("queued", "running") for j in _jobs.values()):
            raise ValueError("该断点正在被抓取任务使用，请先取消任务")
    checkpoint.remove(key)


def _origin_only(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("新站点地址请填 http(s)://域名[:端口]，如 https://www.example.net")
    origin = f"{parts.scheme}://{parts.netloc}"
    check_url(origin + "/")
    return origin


def _evict() -> None:
    finished = sorted((j for j in _jobs.values() if j.finishTime), key=lambda j: j.finishTime)
    with_text = [j for j in finished if j.jobId in _texts]
    for j in with_text[:-KEEP_TEXTS] if len(with_text) > KEEP_TEXTS else []:
        _texts.pop(j.jobId, None)
    for j in finished[:-50]:  # 状态记录保留最近 50 个
        _jobs.pop(j.jobId, None)


def _run(job: CrawlJob, req: CrawlRequest, rule: CrawlRule) -> None:
    job.status = "running"
    chapter_log = None
    try:
        with Fetcher(req.delayMs, req.respectRobots, rule.encoding) as f:
            if job.jobId in _cancel:
                raise _Cancelled()
            toc, chapters, done = _plan(job, req, f, rule)
            if job.resumeKey:
                chapter_log = checkpoint.ChapterLog(job.resumeKey)
            job.chapterTotal = len(chapters)
            body, streak = [], 0
            for i, ch in enumerate(chapters, 1):
                if job.jobId in _cancel:
                    raise _Cancelled()
                if (i - 1) in done:
                    text = done[i - 1]
                    job.resumedChapters += 1
                    job.wordCount += sum(1 for c in text if not c.isspace())
                else:
                    job.message = f"抓取第 {i}/{len(chapters)} 章：{ch['title']}"
                    try:
                        text = _load_chapter_waiting(job, f, ch, rule, i, len(chapters))
                        streak = 0
                        job.wordCount += sum(1 for c in text if not c.isspace())
                        if chapter_log:
                            chapter_log.append(i - 1, text)
                    except NetworkError:
                        raise  # 等待重试后网络仍未恢复：整体暂停，断点保留
                    except (CrawlError, ValueError) as e:
                        streak += 1
                        job.chapterFailed += 1
                        if len(job.failedChapters) < 50:
                            job.failedChapters.append(f"{ch['title']}：{e}")
                        text = f"（本章抓取失败：{e}）"
                        if streak >= MAX_CONSECUTIVE_FAILS:
                            raise CrawlError(f"连续 {streak} 章抓取失败，已终止（可能被站点限制，或正文规则不匹配）。最后错误：{e}")
                body.append(f"{ch['title']}\n\n{text}")
                job.chapterDone = i
                job.progress = min(99, i * 100 // len(chapters))
            if job.chapterFailed * 2 > job.chapterTotal:
                raise CrawlError(f"{job.chapterFailed}/{job.chapterTotal} 章抓取失败，结果不完整，未保存")
            _texts[job.jobId] = _compose(job, toc, body)
            job.progress, job.status = 100, "succeeded"
            job.message = f"抓取完成：{job.chapterDone} 章，{job.wordCount} 字" + \
                (f"（其中 {job.resumedChapters} 章来自断点）" if job.resumedChapters else "") + \
                (f"，{job.chapterFailed} 章失败（已留占位）" if job.chapterFailed else "")
    except _Cancelled:
        job.status, job.message = "cancelled", f"已取消（已抓 {job.chapterDone} 章{_saved_hint(job)}）"
    except Exception as e:  # 任何异常都要落到 failed，供 Java 轮询拿到原因
        if not isinstance(e, (CrawlError, ValueError)):
            log.exception("抓取失败 jobId=%s url=%s", job.jobId, job.url)
        job.status, job.error = "failed", (str(e) or e.__class__.__name__) + _saved_hint(job, "；")
    finally:
        if chapter_log:
            chapter_log.close()
        _cancel.discard(job.jobId)
        job.finishTime = datetime.now()


def _plan(job: CrawlJob, req: CrawlRequest, f: Fetcher, rule: CrawlRule) -> tuple[dict, list[dict], dict[int, str]]:
    """确定本次要抓的章节：有断点用断点（不访问目录页），否则解析目录并写断点。→ (toc, chapters, done)"""
    saved = checkpoint.load(job.resumeKey) if job.resumeKey else None
    if saved:
        meta = saved["meta"]
        if req.newOrigin:
            old = checkpoint.origin_of(meta["url"])
            meta["url"] = checkpoint.rewrite_origin(meta["url"], old, req.newOrigin)
            for ch in meta["chapters"]:
                ch["url"] = checkpoint.rewrite_origin(ch["url"], old, req.newOrigin)
            checkpoint.save_meta(job.resumeKey, meta)
        job.url = meta["url"]
        job.bookName, job.author = meta.get("bookName") or "未命名小说", meta.get("author", "")
        job.message = f"从断点继续：已保存 {len(saved['done'])}/{len(meta['chapters'])} 章"
        log.info("续抓 %s《%s》：断点已有 %s/%s 章", job.resumeKey, job.bookName, len(saved["done"]), len(meta["chapters"]))
        return meta, meta["chapters"], saved["done"]

    job.message = "解析目录…"
    job.url = resolve_toc_url(f, job.url, rule)
    toc = _load_toc(f, job.url, rule)
    job.bookName, job.author = toc["bookName"] or "未命名小说", toc["author"]
    chapters = toc["chapters"][req.startIndex - 1: req.endIndex]
    if not chapters:
        raise CrawlError(f"所选范围内没有章节（目录共 {len(toc['chapters'])} 章）")
    if len(chapters) > MAX_CHAPTERS:
        raise CrawlError(f"一次最多抓取 {MAX_CHAPTERS} 章，请缩小范围")
    meta = {"url": job.url, "bookName": job.bookName, "author": job.author, "intro": toc.get("intro", ""),
            "startIndex": req.startIndex, "endIndex": req.endIndex, "chapters": chapters,
            "createTime": datetime.now().isoformat(timespec="seconds")}
    if job.resumeKey:
        checkpoint.save_meta(job.resumeKey, meta)
    return meta, chapters, {}


def _load_chapter_waiting(job: CrawlJob, f: Fetcher, ch: dict, rule: CrawlRule, i: int, total: int) -> str:
    """抓一章；遇到断网 / DNS 失败 / 5xx 等暂时性故障按 NETWORK_WAITS 等待后重试，等待期间响应取消。"""
    for wait in (*NETWORK_WAITS, None):
        try:
            return _load_chapter(f, ch, rule, job.url)
        except NetworkError as e:
            if wait is None:
                raise NetworkError(f"网络持续不可用（已等待约 {sum(NETWORK_WAITS) // 60} 分钟），已暂停。最后错误：{e}") from e
            for left in range(wait, 0, -1):
                if job.jobId in _cancel:
                    raise _Cancelled()
                job.message = f"网络异常，{left} 秒后重试第 {i}/{total} 章：{ch['title']}"
                time.sleep(1)
    raise AssertionError("unreachable")


def _saved_hint(job: CrawlJob, sep: str = "，") -> str:
    if not job.resumeKey:
        return "，未保存" if sep == "，" else ""
    return f"{sep}进度已保存，可「继续抓取」从断点接着抓"


def _compose(job: CrawlJob, toc: dict, body: list[str]) -> str:
    head = [job.bookName]
    if job.author:
        head.append(f"作者：{job.author}")
    head.append(f"来源：{job.url}")
    if toc.get("intro"):
        head.append(f"简介：\n{toc['intro']}")
    return "\n".join(head) + "\n\n\n" + "\n\n\n".join(body) + "\n"


class _Cancelled(Exception):
    pass
