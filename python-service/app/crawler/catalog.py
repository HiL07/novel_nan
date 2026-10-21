"""全自动爬虫的「书目采集」：基于 AI 解析学到的站点规律（Java 下发规则 + 学习样例地址），从站点首页出发
自动找书（首页 / 分类 → 列表翻页 → 书籍页），逐本取书名 / 作者 / 简介 / 标签 / 目录，并抽几本试抓首章正文，
最后给出「这套规律能不能用」的测试报告。正文不在这里保存——用户看过报告、筛选好书目后，由 Java 逐本走普通抓取任务。

- phase=test：小规模试跑（默认 8 本、抽 3 本试正文），用来判断规律是否可用；
- phase=scan：扩充书目（跳过 knownUrls 里已采集的书，默认不再试正文）。
两种都会把每本书的目录写到 ``data/<catalogDir>/toc/<key>.json``（catalogDir 由 Java 按首页地址给出，
同一首页的数据放在一起）；书目元数据（简介 / 标签 / 章节数…）随任务状态返回，由 Java 存入数据库。

找书优先用「书籍地址规律」：学习样例地址的路径正则（数字段 → \\d+，见 ai_rules.path_regex），
页面上符合该格式的同域链接就是书；规则里写了 bookLinks 时用它；都找不到时退回列表页启发式。

任务在内存中（同抓取任务），一次一个；Java 用 since 增量取书目。AI 检索 / 补标签是同步接口（模型配置随请求下发）。
"""
import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from ..config import DATA_DIR
from ..llm_client import LLMError, ModelConfig, chat, new_usage, parse_json
from . import ai_rules, parser, rules, service
from .fetcher import CrawlError, Fetcher, NetworkError, check_url
from .rules import CrawlRule

log = logging.getLogger("crawler.catalog")

MIN_CONTENT_CHARS = ai_rules.MIN_SAMPLE_CHARS
MAX_NETWORK_FAILS = 5        # 连续这么多本因网络问题失败就停下（已采集的照常返回）
CATALOG_ROOT = (DATA_DIR / "site-catalog").resolve()

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class CatalogRequest(BaseModel):
    homeUrl: str = Field(min_length=8, max_length=2000)           # 站点首页（规则的 homeUrl）
    preset: str = ""
    rule: Optional[CrawlRule] = None
    sampleUrl: str = Field(default="", max_length=2000)           # AI 解析时的书籍地址：推出书籍地址规律
    categories: list[dict] = Field(default_factory=list, max_length=60)  # 解析时发现的分类 [{name, url}]（首页没找到时用）
    knownUrls: list[str] = Field(default_factory=list, max_length=5000)  # 已采集的书（scan 时跳过）
    phase: Literal["test", "scan"] = "test"
    maxBooks: int = Field(default=8, ge=1, le=500)
    maxCategories: int = Field(default=10, ge=1, le=50)
    maxListPages: int = Field(default=3, ge=1, le=50)
    contentSamples: int = Field(default=3, ge=0, le=10)           # 抽几本试抓首章正文
    tocPages: int = Field(default=10, ge=1, le=service.MAX_TOC_PAGES)  # 每本目录最多翻几页
    delayMs: int = Field(default=1000, ge=300, le=30000)
    respectRobots: bool = True
    catalogDir: str = Field(pattern=r"^site-catalog/[A-Za-z0-9._-]{1,120}$")


class CatalogJob(BaseModel):
    jobId: str
    homeUrl: str
    phase: str = "test"
    status: JobStatus = "queued"
    progress: int = 0
    message: str = ""
    error: Optional[str] = None
    siteName: str = ""
    # 每本：{bookName, author, intro, tags[], category, bookUrl, tocUrl, chapterCount, firstChapter, latestChapter,
    #        tocPages, tocPath, detailOk, tocOk, contentChecked, contentOk, contentChars, contentSample, error}
    books: list[dict] = Field(default_factory=list)
    categories: list[dict] = Field(default_factory=list)   # 访问过的分类 [{name, url, pages, books, error}]
    categoriesAll: list[dict] = Field(default_factory=list)
    bookPattern: str = ""          # 用来认书的地址规律（正则）
    report: Optional[dict] = None  # 结束时的测试报告（见 _report）
    createTime: datetime = Field(default_factory=datetime.now)
    finishTime: Optional[datetime] = None


_jobs: dict[str, CatalogJob] = {}
_cancel: set[str] = set()
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="crawl-catalog")


def submit(req: CatalogRequest) -> CatalogJob:
    req.homeUrl = check_url(req.homeUrl)
    _catalog_dir(req.catalogDir)
    job = CatalogJob(jobId=uuid.uuid4().hex, homeUrl=req.homeUrl, phase=req.phase, message="排队中")
    with _lock:
        _jobs[job.jobId] = job
        finished = sorted((j for j in _jobs.values() if j.finishTime), key=lambda j: j.finishTime)
        for old in finished[:-20]:
            _jobs.pop(old.jobId, None)
    _executor.submit(_run, job, req)
    return job


def get(job_id: str, since: int = 0) -> Optional[dict]:
    """任务状态；books 只返回第 since 本之后的（Java 增量入库），booksTotal 为总数。"""
    job = _jobs.get(job_id)
    if job is None:
        return None
    data = job.model_dump(exclude={"books"})
    data["books"] = job.books[max(since, 0):]
    data["booksSince"] = max(since, 0)
    data["booksTotal"] = len(job.books)
    return data


def cancel(job_id: str) -> Optional[dict]:
    job = _jobs.get(job_id)
    if job and job.status in ("queued", "running"):
        _cancel.add(job_id)
        job.message = "正在取消（当前这本处理完后停止，已采集的书目保留）…"
    return get(job_id, len(job.books)) if job else None


# ---------------------------------------------------------------- 任务主体

class _Cancelled(Exception):
    pass


class _RecentFetcher(Fetcher):
    """只缓存最近几个页面：详情页兼目录页时不必重复请求，又不会把整站页面都留在内存里。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages: OrderedDict = OrderedDict()

    def get_html(self, url: str, referer: str = "") -> tuple[str, str]:
        key = (url, self.encoding)
        if key in self.pages:
            self.pages.move_to_end(key)
            return self.pages[key]
        page = super().get_html(url, referer)
        self.pages[key] = page
        if len(self.pages) > 6:
            self.pages.popitem(last=False)
        return page


def _run(job: CatalogJob, req: CatalogRequest) -> None:
    job.status = "running"
    started = time.monotonic()
    try:
        _, rule = rules.resolve(req.preset, req.rule, urlsplit(req.homeUrl).hostname or "")
        book_re = ai_rules.path_regex(req.sampleUrl) if req.sampleUrl else None
        job.bookPattern = book_re.pattern if book_re else ""
        known = {u.split("#")[0].rstrip("/") for u in req.knownUrls}
        if req.sampleUrl and req.phase == "test":
            known.discard(req.sampleUrl.split("#")[0].rstrip("/"))
        with _RecentFetcher(req.delayMs, req.respectRobots, rule.encoding) as f:
            links = _discover(job, req, f, rule, book_re, known)
            if not links and book_re is not None:
                # 列表页上的书籍地址和学习样例不是同一种格式（如样例给的是目录页）：退回列表页启发式再找一遍
                log.info("书目采集 %s：没有与样例同格式的书籍地址，改用启发式", req.homeUrl)
                job.categories, job.bookPattern = [], ""
                links = _discover(job, req, f, rule, None, known)
            if not links:
                raise CrawlError("按这套规律在首页 / 分类页上没有找到任何书籍链接："
                                 + ("页面上没有与学习样例同格式的书籍地址，" if book_re else "")
                                 + "可能站点改版、分类导航是脚本生成的，或需要在规则里写「书籍链接」XPath")
            _collect(job, req, f, rule, links)
        job.report = _report(job, req, time.monotonic() - started)
        job.status, job.progress = "succeeded", 100
        job.message = job.report["summary"]
    except _Cancelled:
        job.report = _report(job, req, time.monotonic() - started)
        job.status, job.message = "cancelled", f"已取消（已采集 {len(job.books)} 本）"
    except Exception as e:  # 任何异常都落到 failed，供 Java 轮询拿到原因；已采集的书目照常返回
        if not isinstance(e, (CrawlError, ValueError)):
            log.exception("书目采集失败 jobId=%s url=%s", job.jobId, req.homeUrl)
        job.report = _report(job, req, time.monotonic() - started) if job.books else None
        job.status, job.error = "failed", str(e) or e.__class__.__name__
    finally:
        _cancel.discard(job.jobId)
        job.finishTime = datetime.now()


def _check_cancel(job: CatalogJob) -> None:
    if job.jobId in _cancel:
        raise _Cancelled()


def _discover(job: CatalogJob, req: CatalogRequest, f: Fetcher, rule: CrawlRule, book_re, known: set) -> list[dict]:
    """首页 + 分类列表（含翻页）上找书 → [{title, url, category}]，最多 maxBooks 本（跳过 known）。"""
    found: list[dict] = []
    seen: set[str] = set()

    def take(page_html: str, page_url: str, category: str) -> int:
        n = 0
        for link in _book_links(page_html, page_url, rule, book_re):
            key = link["url"].split("#")[0].rstrip("/")
            if key in seen or key in known:
                continue
            seen.add(key)
            found.append({**link, "category": category})
            n += 1
            if len(found) >= req.maxBooks:
                break
        return n

    job.message = "读取站点首页…"
    home_final, home_html = f.get_html(req.homeUrl)
    site = parser.parse_site(home_html, home_final, rule)
    job.siteName = site["siteName"]
    cats = site["categories"] or [c for c in req.categories if c.get("url")]
    job.categoriesAll = [{"name": c.get("name", ""), "url": c["url"]} for c in cats]
    on_home = take(home_html, home_final, "")
    job.categories.append({"name": "首页", "url": home_final, "pages": 1, "books": on_home, "error": ""})

    for cat in cats[:req.maxCategories]:
        if len(found) >= req.maxBooks:
            break
        _check_cancel(job)
        page_url, pages, n, error = cat["url"], 0, 0, ""
        visited: set[str] = set()
        while page_url and page_url not in visited and pages < req.maxListPages and len(found) < req.maxBooks:
            _check_cancel(job)
            visited.add(page_url)
            job.message = f"在分类「{cat.get('name', '')}」第 {pages + 1} 页找书（已找到 {len(found)} 本）…"
            try:
                final, html = f.get_html(page_url, referer=home_final)
            except (CrawlError, ValueError) as e:
                error = str(e)
                break
            n += take(html, final, cat.get("name", ""))
            pages += 1
            page_url = parser.parse_next(html, final, rule.listNext)
        job.categories.append({"name": cat.get("name", ""), "url": cat["url"], "pages": pages, "books": n, "error": error})
        job.progress = min(15, 2 + len(job.categories) * 2)
    # 首页上的书没有分类：分类页里也出现过的已去重，剩下的保持空
    return found[:req.maxBooks]


def _book_links(html: str, url: str, rule: CrawlRule, book_re) -> list[dict]:
    """页面上的书籍链接：先按学到的书籍地址规律，其次规则 bookLinks，最后列表页启发式（只在没有规律时用）。"""
    if book_re is not None:
        tree = parser.parse_doc(html, url)
        host = urlsplit(url).hostname
        titles: dict[str, str] = {}
        for a in tree.iter("a"):
            href = (a.get("href") or "").split("#")[0]
            if not parser._usable_href(href) or urlsplit(href).hostname != host:
                continue
            if not book_re.fullmatch(ai_rules._path_of(href)):
                continue
            text = parser._clean_inline(a.text_content())
            # 同一本书常有封面图 / 书名 / 「开始阅读」多个链接：留最像书名的文字
            if href not in titles or (_title_score(text) > _title_score(titles[href])):
                titles[href] = text
        if titles:
            return [{"title": t[:60], "url": u} for u, t in titles.items()]
        if not rule.bookLinks:
            return []
    return parser.parse_book_links(html, url, rule)


def _title_score(text: str) -> int:
    if not text or text in parser._NON_LINK_TEXTS or parser._TOC_TEXT.fullmatch(text):
        return 0
    return 2 if len(text) <= 30 else 1


def _collect(job: CatalogJob, req: CatalogRequest, f: Fetcher, rule: CrawlRule, links: list[dict]) -> None:
    folder = _catalog_dir(req.catalogDir) / "toc"
    samples_left, net_fails = req.contentSamples, 0
    for i, link in enumerate(links, 1):
        _check_cancel(job)
        job.message = f"采集第 {i}/{len(links)} 本：{link['title'] or link['url']}"
        book = {"bookName": link["title"], "author": "", "intro": "", "tags": [], "category": link.get("category", ""),
                "bookUrl": link["url"], "tocUrl": "", "chapterCount": 0, "firstChapter": "", "latestChapter": "",
                "tocPages": 0, "tocPath": "", "detailOk": False, "tocOk": False, "contentChecked": False,
                "contentOk": None, "contentChars": 0, "contentSample": "", "error": ""}
        try:
            chapters = _book(f, rule, req, book)
            net_fails = 0
            if chapters:
                book["tocPath"] = _save_toc(folder, req.catalogDir, book, chapters)
                if samples_left > 0:
                    samples_left -= 1
                    _check_content(f, rule, book, chapters)
        except NetworkError as e:
            book["error"] = str(e)
            net_fails += 1
            if net_fails >= MAX_NETWORK_FAILS:
                job.books.append(book)
                raise CrawlError(f"连续 {net_fails} 本因网络问题失败，已停止（已采集的书目已保留）。最后错误：{e}")
        except (CrawlError, ValueError) as e:
            book["error"] = book["error"] or str(e)
        except OSError as e:   # 目录文件写不进去（磁盘满 / 无权限）：后面的书也写不了，整体停下，已采集的照常返回
            job.books.append(book)
            raise CrawlError(f"目录文件写入失败（{folder}）：{e.strerror or e}") from e
        if not book["bookName"]:
            book["bookName"] = "未命名小说"
        if book["category"] and book["category"] not in book["tags"]:
            book["tags"] = [book["category"], *book["tags"]][:parser.MAX_TAGS]
        job.books.append(book)
        job.progress = min(99, 15 + i * 84 // len(links))


def _book(f: Fetcher, rule: CrawlRule, req: CatalogRequest, book: dict) -> list[dict]:
    """书籍页 → 书名 / 作者 / 简介 / 标签 / 目录页 → 目录（≤ tocPages 页）。→ 章节清单"""
    final, html = f.get_html(book["bookUrl"], referer=req.homeUrl)
    detail = parser.parse_book_detail(html, final, rule)
    book["bookName"] = detail["bookName"] or book["bookName"]
    book["author"], book["intro"] = detail["author"], (detail["intro"] or "")[:2000]
    book["tags"] = detail["tags"]
    book["detailOk"] = bool(detail["bookName"])
    toc_url = detail["tocUrl"] or final
    try:
        toc = service._load_toc(f, toc_url, rule, max_pages=req.tocPages)
    except CrawlError:
        if parser._same_page(toc_url, final):
            raise
        toc_url = final   # 目录链接没认对：详情页本身可能就是目录
        toc = service._load_toc(f, toc_url, rule, max_pages=req.tocPages)
    chapters = toc["chapters"]
    book["tocUrl"], book["tocPages"] = toc_url, toc.get("tocPages", 1)
    book["chapterCount"], book["tocOk"] = len(chapters), bool(chapters)
    book["firstChapter"], book["latestChapter"] = chapters[0]["title"], chapters[-1]["title"]
    # 详情页取到的书名 / 作者更可信（目录页 <title> 常带「目录」后缀），目录页只做兜底
    book["bookName"] = book["bookName"] or toc.get("bookName") or ""
    book["author"] = book["author"] or toc.get("author") or ""
    book["intro"] = book["intro"] or (toc.get("intro") or "")[:2000]
    return chapters


def _check_content(f: Fetcher, rule: CrawlRule, book: dict, chapters: list[dict]) -> None:
    book["contentChecked"] = True
    try:
        text = service._load_chapter(f, chapters[0], rule, book["tocUrl"])
    except (CrawlError, ValueError) as e:
        book["contentOk"], book["error"] = False, f"首章正文抓取失败：{e}"
        return
    book["contentChars"], book["contentSample"] = len(text), text[:200]
    book["contentOk"] = len(text) >= MIN_CONTENT_CHARS
    if not book["contentOk"]:
        book["error"] = f"首章正文只有 {len(text)} 字，可能没选中正文区块"


def _catalog_dir(rel: str) -> Path:
    path = (DATA_DIR / rel).resolve()
    if path.parent != CATALOG_ROOT:
        raise ValueError("catalogDir 不合法")
    return path


def _save_toc(folder: Path, catalog_dir: str, book: dict, chapters: list[dict]) -> str:
    """目录写成 JSON（临时文件 → fsync → 原子改名），文件名 = 书籍地址的哈希。→ 相对 data/ 的路径"""
    folder.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(book["bookUrl"].encode("utf-8")).hexdigest()[:16]
    target = folder / f"{key}.json"
    tmp = folder / f"{key}.json.part"
    data = {"bookName": book["bookName"], "author": book["author"], "bookUrl": book["bookUrl"],
            "tocUrl": book["tocUrl"], "chapterCount": len(chapters), "chapters": chapters,
            "savedAt": datetime.now().isoformat(timespec="seconds")}
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False)
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(tmp, target)
    return f"{catalog_dir}/toc/{key}.json"


# ---------------------------------------------------------------- 测试报告

def _rate(n: int, total: int) -> float:
    return round(n / total, 3) if total else 0.0


def _report(job: CatalogJob, req: CatalogRequest, seconds: float) -> dict:
    books = job.books
    total = len(books)
    count = {
        "detail": sum(1 for b in books if b["detailOk"]),
        "toc": sum(1 for b in books if b["tocOk"]),
        "intro": sum(1 for b in books if b["intro"]),
        "tags": sum(1 for b in books if b["tags"]),
        "author": sum(1 for b in books if b["author"]),
        "contentChecked": sum(1 for b in books if b["contentChecked"]),
        "content": sum(1 for b in books if b["contentOk"]),
    }
    problems: list[str] = []
    if total < 2:
        problems.append(f"只找到 {total} 本书，无法确认规律适用于多本书")
    if total and count["toc"] < total:
        problems.append(f"{total - count['toc']} 本没解析出目录")
    if count["contentChecked"] and count["content"] < count["contentChecked"]:
        problems.append(f"抽检 {count['contentChecked']} 本首章正文，{count['contentChecked'] - count['content']} 本不合格")
    if total and count["intro"] * 2 < total:
        problems.append("多数书没取到简介（不影响抓取，但 AI 检索效果会差）")
    if total and not count["tags"]:
        problems.append("没取到任何标签（可用「AI 补标签」根据简介生成）")
    failed_cats = [c["name"] for c in job.categories if c["error"]]
    if failed_cats:
        problems.append(f"分类页打不开：{'、'.join(failed_cats[:5])}")

    toc_rate = _rate(count["toc"], total)
    content_rate = _rate(count["content"], count["contentChecked"]) if count["contentChecked"] else None
    if total >= 2 and toc_rate >= 0.8 and (content_rate is None or content_rate >= 0.66):
        verdict = "usable"
    elif total >= 1 and toc_rate >= 0.5 and (content_rate is None or content_rate > 0):
        verdict = "partial"
    else:
        verdict = "unusable"
    label = {"usable": "规律可用", "partial": "部分可用", "unusable": "规律不可用"}[verdict]
    summary = (f"{label}：找到 {total} 本书，目录 {count['toc']}/{total}，简介 {count['intro']}/{total}，"
               f"标签 {count['tags']}/{total}"
               + (f"，首章正文 {count['content']}/{count['contentChecked']}" if count["contentChecked"] else ""))
    return {"phase": req.phase, "verdict": verdict, "summary": summary, "problems": problems,
            "books": total, "counts": count,
            "rates": {"toc": toc_rate, "intro": _rate(count["intro"], total), "tags": _rate(count["tags"], total),
                      "author": _rate(count["author"], total), "detail": _rate(count["detail"], total),
                      "content": content_rate},
            "categoriesFound": len(job.categoriesAll),
            "categoriesVisited": [{k: c[k] for k in ("name", "pages", "books", "error")} for c in job.categories],
            "bookPattern": job.bookPattern, "siteName": job.siteName,
            "limits": {"maxBooks": req.maxBooks, "maxCategories": req.maxCategories, "maxListPages": req.maxListPages,
                       "contentSamples": req.contentSamples, "tocPages": req.tocPages},
            "seconds": round(seconds, 1)}


# ---------------------------------------------------------------- 按情节找书 / 补标签（同步，模型配置随请求下发、不保存）

class BookItem(BaseModel):
    id: int
    bookName: str = ""
    author: str = ""
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    intro: str = ""


class PlotTagsRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)                       # 想找的情节 / 内容描述
    vocabulary: list[str] = Field(default_factory=list, max_length=600)   # 书目里已有的标签（按出现次数）
    model: ModelConfig


class IntroMatchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    items: list[BookItem] = Field(min_length=1, max_length=1000)
    threshold: int = Field(default=50, ge=0, le=100)                       # 低于这个分数的不返回
    model: ModelConfig


class TagRequest(BaseModel):
    items: list[BookItem] = Field(min_length=1, max_length=30)
    vocabulary: list[str] = Field(default_factory=list, max_length=400)
    model: ModelConfig


SYSTEM = "你是网络小说书库的检索与分类助手，熟悉各类网文题材与标签，只输出 JSON。"


def _str_list(value, limit: int) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[,，、\s]+", value)
    if not isinstance(value, list):
        return []
    out = []
    for v in value:
        s = str(v).strip().strip("#")
        if s and len(s) <= 12 and s not in out:
            out.append(s)
    return out[:limit]


def pick_tags(req: PlotTagsRequest) -> dict:
    """具体情节 → 标签：模型理解描述后只从书目已有标签里挑（原样），用这些标签筛书，一次调用、省 token。
    → {tags（已有标签）, suggested（书目里没有、但模型认为相关的标签，仅供参考）, reason, usage}"""
    usage = new_usage(req.model)
    vocab = [v for v in req.vocabulary if v]
    text = chat(req.model, [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": (
            f"用户想找这样情节 / 内容的小说：{req.query}\n"
            f"书库现有标签（只能从中原样挑选）：{'、'.join(vocab[:500]) or '（暂无）'}\n\n"
            "先判断用户要的题材、背景、流派、主角特点、核心情节，再从现有标签里挑出能筛到这类小说的标签"
            "（宁缺毋滥，1~8 个，按相关度从高到低）。现有标签里没有、但很贴切的标签放进 suggested。\n"
            '输出 {"analysis":"一句话：你理解的用户要找什么","tags":["现有标签"],"suggested":["书库没有的标签"]}')},
    ], max_tokens=500, retries=1, usage=usage)
    data = parse_json(text)
    picked, suggested = [], []
    for t in _str_list(data.get("tags"), 12):
        # 模型偶尔会改写标签（「修仙」→「修仙流」）：按包含关系映射回现有标签
        hit = t if t in vocab else next((v for v in vocab if t in v or v in t), None)
        if hit and hit not in picked:
            picked.append(hit)
        elif not hit and t not in suggested:
            suggested.append(t)
    for t in _str_list(data.get("suggested"), 8):
        if t not in vocab and t not in suggested:
            suggested.append(t)
    return {"tags": picked[:8], "suggested": suggested[:8],
            "reason": str(data.get("analysis") or "")[:200], "usage": usage}


INTRO_BATCH = 25   # 每次调用让模型读多少本的简介


def intro_match(req: IntroMatchRequest) -> dict:
    """具体情节 → 逐本读简介打分（耗 token）：分批（每批 25 本）按模型配置的并发数并行调用，
    某一批失败不影响其他批（配置级错误除外）。→ {results[{id, score, reason}]（≥ threshold，高分在前）,
    analyzed, batches, failedBatches, errors[], usage}"""
    usage = new_usage(req.model)
    lock = threading.Lock()
    batches = [req.items[i:i + INTRO_BATCH] for i in range(0, len(req.items), INTRO_BATCH)]

    def run(batch: list[BookItem]) -> list[dict]:
        lines = "\n".join(
            f"{b.id}|{b.bookName}|{'、'.join(b.tags[:6]) or b.category}|{(b.intro or '（无简介）')[:300].replace(chr(10), ' ')}"
            for b in batch)
        one = new_usage(req.model)
        text = chat(req.model, [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": (
                f"用户想找这样情节 / 内容的小说：{req.query}\n\n"
                f"逐本阅读下面的小说简介（id|书名|标签|简介），判断它的情节与用户描述的吻合程度：\n{lines}\n\n"
                "每本都打分（0~100，简介里明确有用户要的情节给 80 以上，只是题材相近给 40~60，无关给 20 以下），"
                "理由不超过 30 字。输出 {\"items\":[{\"id\":数字,\"score\":数字,\"reason\":\"理由\"}]}")},
        ], max_tokens=60 + 45 * len(batch), retries=1, usage=one)
        with lock:
            for k in ("calls", "promptTokens", "completionTokens", "cacheHitTokens"):
                usage[k] = usage.get(k, 0) + one.get(k, 0)
        ids = {b.id for b in batch}
        out = []
        for r in parse_json(text).get("items") or []:
            try:
                rid, score = int(r.get("id")), int(r.get("score") or 0)
            except (TypeError, ValueError, AttributeError):
                continue
            if rid in ids:
                out.append({"id": rid, "score": max(0, min(100, score)), "reason": str(r.get("reason") or "")[:60]})
        return out

    results: dict[int, dict] = {}
    errors: list[str] = []
    analyzed = 0
    workers = max(1, min(req.model.concurrency or 1, 8, len(batches)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="intro-match") as pool:
        futures = [(pool.submit(run, b), len(b)) for b in batches]
        for fut, size in futures:
            try:
                for r in fut.result():
                    results[r["id"]] = r
                analyzed += size
            except LLMError as e:
                if e.fatal:
                    raise
                errors.append(str(e))
    if errors and len(errors) == len(batches):
        raise LLMError(f"所有批次都失败了：{errors[0]}")
    ranked = sorted((r for r in results.values() if r["score"] >= req.threshold), key=lambda r: -r["score"])
    return {"results": ranked, "analyzed": analyzed,
            "scored": len(results), "batches": len(batches), "failedBatches": len(errors), "errors": errors[:3],
            "usage": usage}


def tag(req: TagRequest) -> list[dict]:
    """根据书名 / 简介给每本书打 3~6 个题材标签（优先沿用已有标签，便于统一筛选）→ [{id, tags[]}]"""
    vocab = "、".join(req.vocabulary[:300]) or "（暂无）"
    lines = "\n".join(
        f"{b.id}|{b.bookName}|{'、'.join(b.tags[:6]) or b.category}|{b.intro[:200].replace(chr(10), ' ')}"
        for b in req.items)
    text = chat(req.model, [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": (
            f"给下面每本小说打 3~6 个标签（题材 / 背景 / 流派 / 主角特点，如 玄幻、修仙、系统流、都市、重生、女强）。"
            f"能用已有标签就原样用已有的：{vocab}\n"
            f"小说（id|书名|站点标签|简介开头）：\n{lines}\n\n"
            '输出 {"items":[{"id":数字,"tags":["标签1","标签2"]}]}，每本都要有。')},
    ], max_tokens=1500, retries=1)
    ids = {b.id for b in req.items}
    out = []
    for r in parse_json(text).get("items") or []:
        try:
            rid = int(r.get("id"))
        except (TypeError, ValueError, AttributeError):
            continue
        tags = _str_list(r.get("tags"), 6)
        if rid in ids and tags:
            out.append({"id": rid, "tags": tags})
    return out
