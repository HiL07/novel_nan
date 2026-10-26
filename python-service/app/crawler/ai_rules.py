"""AI 解析地址：给一本书的地址（详情页或目录页），反复「写规则 → 试抓 → 看结果」，直到抓通或达到尝试上限。

流程（一次后台任务，Java 轮询，成功后由 Java 把规则存入 crawl_site_rule 表，之后同站点自动沿用）：
1. 已学到的规则（Java 传 knownRule，同域名之前成功过）→ 2. 内置预设 / 启发式 → 3+. 大模型根据
   页面结构（去脚本、折叠重复节点后的骨架 + 链接分组 / 正文候选的 XPath 提示）和之前每次失败的原因写 XPath。
每次尝试都是一次真实的小规模抓取：解析目录（含分页）+ 试抓首章与中间一章，正文够长且两章不同才算成功。
抓通后再从站点根地址（首页）出发摸清每层跳转规律并逐项实测（_explore：首页 / 站内搜索（找到搜索框后用本书书名模拟搜索）/ 分类 / 书籍 / 目录 / 目录分页 /
章节 / 正文分页 / 书籍信息 / 换一本书按同一套规则试抓），每项标明已掌握 / 部分掌握 / 未掌握 / 本站无此结构 / 未验证；
最后让大模型结合实测结果总结地址规律与规则说明；总结失败不影响结果。

模型配置（含 API Key）只存在于本次任务的内存闭包里，不进任务状态、不写文件。
"""
import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Literal, Optional
from urllib.parse import urlsplit

from lxml import etree
from pydantic import BaseModel, Field

from .. import llm_client
from ..llm_client import LLMError, ModelConfig
from . import parser, rules, service
from .fetcher import BlockedError, CrawlError, Fetcher, check_url
from .rules import CrawlRule

log = logging.getLogger("crawler.ai")

MIN_SAMPLE_CHARS = 200     # 试抓的正文至少这么多字才算抓到正文
SKELETON_CHARS = 7000      # 每个页面骨架给模型看的字数上限
# 模型可以写的规则字段（整站发现用的分类 / 书籍 / 列表翻页字段这里用不到）
AI_FIELDS = ("tocLink", "chapterLinks", "tocNext", "content", "contentNext", "bookName", "author", "intro", "encoding")

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)            # 一本书的地址：详情页或目录页
    maxAttempts: int = Field(default=5, ge=1, le=10)            # 最多尝试几次（含内置规则那一次）
    delayMs: int = Field(default=1000, ge=300, le=30000)
    respectRobots: bool = True
    hint: str = Field(default="", max_length=500)               # 给模型的补充说明（可空）
    knownRule: Optional[CrawlRule] = None                       # 该站点之前学到的规则，先试它
    model: ModelConfig


class Attempt(BaseModel):
    index: int
    strategy: str                 # learned 已学规则 / preset 内置规则 / ai 大模型
    reason: str = ""              # 模型给的依据，或策略说明
    tocUrl: str = ""
    rule: dict = Field(default_factory=dict)   # 只含非空字段
    ok: bool = False
    chapterCount: int = 0
    sampleChars: int = 0
    error: str = ""
    seconds: float = 0
    promptTokens: int = 0         # 这次尝试里调用模型的 token（内置 / 已学规则为 0）
    completionTokens: int = 0


class AnalyzeJob(BaseModel):
    jobId: str
    url: str
    status: JobStatus = "queued"
    progress: int = 0
    message: str = ""
    error: Optional[str] = None
    maxAttempts: int = 5
    attempts: list[Attempt] = Field(default_factory=list)
    # token 用量（实时累加，含成功后的总结）：{source: api|local, model, host, calls, promptTokens, completionTokens, cacheHitTokens}
    usage: dict = Field(default_factory=dict)
    # 成功后：{host, homeUrl, siteName, tocUrl, preset, rule, strategy, summary, bookUrlPattern, tocUrlPattern,
    #          chapterUrlPattern, chapterSamples[], siteMap（见 _explore）,
    #          preview{bookName, author, intro, chapters, chapterCount, tocPages, preset, rule, sample}}
    result: Optional[dict] = None
    createTime: datetime = Field(default_factory=datetime.now)
    finishTime: Optional[datetime] = None


_jobs: dict[str, AnalyzeJob] = {}
_cancel: set[str] = set()
_lock = threading.Lock()
# 与抓取任务分开排队：分析通常一两分钟，不必等一本书抓完
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="crawl-ai")


def submit(req: AnalyzeRequest) -> AnalyzeJob:
    req.url = check_url(req.url.strip())
    job = AnalyzeJob(jobId=uuid.uuid4().hex, url=req.url, maxAttempts=req.maxAttempts, message="排队中",
                     usage=llm_client.new_usage(req.model))
    with _lock:
        _jobs[job.jobId] = job
        finished = sorted((j for j in _jobs.values() if j.finishTime), key=lambda j: j.finishTime)
        for old in finished[:-30]:
            _jobs.pop(old.jobId, None)
    _executor.submit(_run, job, req)
    return job


def get(job_id: str) -> Optional[AnalyzeJob]:
    return _jobs.get(job_id)


def cancel(job_id: str) -> Optional[AnalyzeJob]:
    job = _jobs.get(job_id)
    if job and job.status in ("queued", "running"):
        _cancel.add(job_id)
        job.message = "正在取消（当前这次尝试结束后停止）…"
    return job


# ---------------------------------------------------------------- 任务主体

class _Cancelled(Exception):
    pass


class _CachedFetcher(Fetcher):
    """同一页面在多次尝试之间只请求一次（换规则不必重新下载）；按编码区分缓存。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages: dict[tuple[str, str], tuple[str, str]] = {}

    def get_html(self, url: str, referer: str = "") -> tuple[str, str]:
        key = (url, self.encoding)
        if key not in self.pages:
            self.pages[key] = super().get_html(url, referer)
        return self.pages[key]


def _run(job: AnalyzeJob, req: AnalyzeRequest) -> None:
    job.status = "running"
    host = urlsplit(req.url).hostname or ""
    try:
        with _CachedFetcher(req.delayMs, req.respectRobots) as f:
            job.message = "读取入口页…"
            f.get_html(req.url)   # 入口页都打不开就没必要请模型了（网络 / robots / 404 的原因直接报给用户）
            queue: list[tuple[str, CrawlRule, str]] = []
            if req.knownRule and any(req.knownRule.model_dump().values()):
                queue.append(("learned", req.knownRule, "沿用该站点之前学到的规则"))
            preset_key, preset_rule = rules.resolve("", None, host)
            queue.append(("preset", preset_rule, f"内置规则：{rules.find_preset(preset_key).name}"))

            for i in range(1, req.maxAttempts + 1):
                if job.jobId in _cancel:
                    raise _Cancelled()
                job.progress = min(90, (i - 1) * 90 // req.maxAttempts)
                started = time.monotonic()
                before = (job.usage["promptTokens"], job.usage["completionTokens"])
                if queue:
                    strategy, rule, reason = queue.pop(0)
                else:
                    strategy = "ai"
                    job.message = f"第 {i}/{req.maxAttempts} 次：请大模型分析页面结构、写规则…"
                    try:
                        rule, reason = _propose(req, f, job)
                    except LLMError as e:
                        if e.fatal:
                            raise
                        job.attempts.append(Attempt(index=i, strategy=strategy, ok=False, error=f"模型输出不可用：{e}",
                                                    seconds=round(time.monotonic() - started, 1),
                                                    **_tokens_since(job, before)))
                        continue
                attempt = Attempt(index=i, strategy=strategy, reason=reason, rule=_compact(rule),
                                  **_tokens_since(job, before))
                job.message = f"第 {i}/{req.maxAttempts} 次：按{_STRATEGY[strategy]}试抓（目录 + 两章正文）…"
                try:
                    trial = _trial(f, req.url, rule)
                    attempt.tocUrl = trial["tocUrl"]
                    attempt.chapterCount = len(trial["toc"]["chapters"])
                    attempt.sampleChars = trial["samples"][0].get("chars", 0) if trial["samples"] else 0
                    attempt.ok, attempt.error = not trial["problems"], "；".join(trial["problems"])
                except BlockedError as e:   # 反爬校验页：换规则也没用，不再请模型
                    attempt.ok, attempt.error = False, str(e)
                    attempt.seconds = round(time.monotonic() - started, 1)
                    job.attempts.append(attempt)
                    raise
                except (CrawlError, ValueError) as e:
                    trial, attempt.ok, attempt.error = None, False, str(e)
                attempt.seconds = round(time.monotonic() - started, 1)
                job.attempts.append(attempt)
                _remember(job.jobId, i, trial)
                log.info("AI 解析 %s 第 %s 次（%s）：%s %s", req.url, i, strategy, "成功" if attempt.ok else "失败", attempt.error)
                if attempt.ok:
                    job.progress, job.message = 92, "本书抓取成功，正在验证站点结构（首页 / 分类 / 其他书）…"
                    job.result = _result(req, f, host, strategy, rule, trial, job)
                    sm = job.result["siteMap"]
                    job.progress, job.status = 100, "succeeded"
                    job.message = (f"第 {i} 次尝试成功（{_STRATEGY[strategy]}）：目录 {attempt.chapterCount} 章，"
                                   f"首章 {attempt.sampleChars} 字；站点规律掌握 {sm['mastered']}/{sm['total']} 项")
                    return
            job.status = "failed"
            job.error = f"已尝试 {req.maxAttempts} 次仍未抓通，最后一次：{job.attempts[-1].error if job.attempts else '无'}"
    except _Cancelled:
        job.status, job.message = "cancelled", f"已取消（尝试了 {len(job.attempts)} 次）"
    except LLMError as e:
        job.status, job.error = "failed", f"大模型调用失败：{e}"
    except (CrawlError, ValueError) as e:
        job.status, job.error = "failed", str(e)
    except Exception as e:  # 任何异常都落到 failed，供 Java 轮询拿到原因
        log.exception("AI 解析地址失败 jobId=%s url=%s", job.jobId, req.url)
        job.status, job.error = "failed", str(e) or e.__class__.__name__
    finally:
        _cancel.discard(job.jobId)
        _trials.pop(job.jobId, None)
        job.finishTime = datetime.now()


def _tokens_since(job: AnalyzeJob, before: tuple[int, int]) -> dict:
    return {"promptTokens": job.usage["promptTokens"] - before[0],
            "completionTokens": job.usage["completionTokens"] - before[1]}


_STRATEGY = {"learned": "已学到的规则", "preset": "内置规则", "ai": "AI 规则"}

# 每次尝试的详细结果（章节标题样本、正文开头），只用于下一轮提示词，不进任务状态
_trials: dict[str, dict[int, Optional[dict]]] = {}


def _remember(job_id: str, index: int, trial: Optional[dict]) -> None:
    _trials.setdefault(job_id, {})[index] = trial


def _compact(rule: CrawlRule) -> dict:
    return {k: v for k, v in rule.model_dump().items() if v}


# ---------------------------------------------------------------- 一次试抓

def _trial(f: _CachedFetcher, entry: str, rule: CrawlRule, max_pages: int = service.MAX_TOC_PAGES,
           sample_count: int = 2) -> dict:
    """入口 →（tocLink）→ 目录（含分页）→ 首章 + 中间一章。→ {tocUrl, toc, samples, problems}
    max_pages / sample_count 调小用于「换一本书验证」（只看目录前几页 + 首章）。"""
    f.encoding = rule.encoding
    toc_url = service.resolve_toc_url(f, entry, rule)
    toc = None
    try:
        toc = service._load_toc(f, toc_url, rule, max_pages=max_pages)
    except CrawlError:
        if rule.tocLink or rule.chapterLinks:
            raise
    if not rule.tocLink and not rule.chapterLinks:
        # 启发式：详情页上常有「全部章节 / 查看目录」链到真正的目录页，入口只列了最新几章时以章节多的为准
        final, html = f.get_html(entry)
        guessed = parser.parse_book_detail(html, final, rule)["tocUrl"]
        if guessed and guessed != final and (toc is None or len(toc["chapters"]) < 30):
            try:
                other = service._load_toc(f, guessed, rule, max_pages=max_pages)
                if toc is None or len(other["chapters"]) > len(toc["chapters"]):
                    toc, toc_url = other, guessed
            except CrawlError:
                pass
    if toc is None:
        raise CrawlError("目录页上没有识别到章节链接")

    chapters = toc["chapters"]
    picks = [0] + ([len(chapters) // 2] if len(chapters) >= 5 and sample_count >= 2 else [])
    samples, problems = [], []
    for idx in picks:
        ch = chapters[idx]
        try:
            text = service._load_chapter(f, ch, rule, toc_url)
            samples.append({"title": ch["title"], "url": ch["url"], "chars": len(text), "text": text[:600]})
        except (CrawlError, ValueError) as e:
            samples.append({"title": ch["title"], "url": ch["url"], "chars": 0, "text": "", "error": str(e)})
    for s in samples:
        if s.get("error"):
            problems.append(f"「{s['title']}」正文抓取失败：{s['error']}")
        elif s["chars"] < MIN_SAMPLE_CHARS:
            problems.append(f"「{s['title']}」正文只有 {s['chars']} 字，可能没选中正文区块")
    if len(samples) == 2 and samples[0]["text"] and samples[0]["text"][:80] == samples[1]["text"][:80]:
        problems.append("两章正文开头完全相同，正文规则可能选中了页面公共区块")
    return {"tocUrl": toc_url, "toc": toc, "samples": samples, "problems": problems}


# ---------------------------------------------------------------- 请模型写规则

PROPOSE_SYSTEM = "你是网络小说站点的爬虫规则专家，熟悉 XPath 1.0（lxml 求值）。只输出 JSON，不要任何多余文字。"

PROPOSE_TEMPLATE = """任务：为下面这本网络小说写抓取规则。抓取流程：入口页 →（可选：按 tocLink 跳到目录页）→ 目录页按 chapterLinks 取全部章节 →（目录分页时按 tocNext 翻页）→ 每章按 content 取正文（一章分页时按 contentNext 翻页）。

入口地址：{url}
地址结构：域名 {host}，路径分段 {segments}
{hint}
{pages}

【之前的尝试】（不要重复失败的写法）
{history}

严格按下面的 JSON 输出（不需要的字段写空串）：
{{"reason":"一句话：你判断的页面结构，以及相对上次改了什么",
 "rule":{{"tocLink":"入口页上通往完整目录页的 <a> 元素（入口页本身就是完整目录则空）",
          "chapterLinks":"目录页上章节 <a> 元素",
          "tocNext":"目录分页时「下一页」的 <a> 元素，不分页则空",
          "content":"章节页上正文容器元素",
          "contentNext":"一章拆成多页时「下一页」的 <a> 元素，否则空",
          "bookName":"书名文本，如 //h1/text()",
          "author":"作者文本，可空",
          "intro":"简介文本，可空",
          "encoding":"页面编码，一般留空自动识别；乱码时填 gbk"}}}}
要求：
- chapterLinks / tocLink / tocNext / contentNext 选中 <a> 元素本身，不要以 /@href 或 /text() 结尾；content 选中容器元素本身。
- 章节链接只要正文目录，排除「最新章节 / 最近更新」区块与导航链接。
- 多个 class 的元素用 contains(@class,'xxx')；优先用 id，其次 class，避免依赖 [3] 这类位置序号。"""


def _propose(req: AnalyzeRequest, f: _CachedFetcher, job: AnalyzeJob) -> tuple[CrawlRule, str]:
    parts = urlsplit(req.url)
    trials = _trials.get(job.jobId, {})
    prompt = PROPOSE_TEMPLATE.format(
        url=req.url, host=parts.hostname, segments=[s for s in parts.path.split("/") if s] or "（无）",
        hint=f"用户补充：{req.hint}" if req.hint.strip() else "",
        pages=_pages_digest(f, req.url, job.attempts, trials),
        history=_history(job.attempts, trials),
    )
    text = llm_client.chat(req.model, [{"role": "system", "content": PROPOSE_SYSTEM},
                                       {"role": "user", "content": prompt}], max_tokens=900, usage=job.usage)
    data = llm_client.parse_json(text)
    raw = data.get("rule") if isinstance(data.get("rule"), dict) else data
    values = {}
    for key in AI_FIELDS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            value = value.strip()
            if key != "encoding":
                _check_xpath(key, value)
            values[key] = value
    if not values.get("chapterLinks") and not values.get("content"):
        raise LLMError("模型没有给出章节链接或正文规则")
    reason = str(data.get("reason") or "").strip()[:300]
    return CrawlRule(**values), reason


def _check_xpath(key: str, xp: str) -> None:
    try:
        etree.XPath(xp)
    except etree.XPathSyntaxError as e:
        raise LLMError(f"{key} 不是合法 XPath：{xp}（{e}）") from e


def _history(attempts: list[Attempt], trials: dict[int, Optional[dict]]) -> str:
    if not attempts:
        return "（无）"
    lines = []
    for a in attempts:
        head = f"{a.index}. {_STRATEGY.get(a.strategy, a.strategy)}，规则 {a.rule or '{}（全部自动识别）'}"
        if a.tocUrl:
            head += f"，目录页 {a.tocUrl}，识别到 {a.chapterCount} 章"
        lines.append(head + f" → 失败：{a.error}")
        trial = trials.get(a.index)
        if trial:
            chapters = trial["toc"]["chapters"]
            titles = [c["title"] for c in chapters[:5]] + (["…"] + [c["title"] for c in chapters[-3:]] if len(chapters) > 8 else [])
            lines.append(f"   章节标题样本：{titles}")
            if chapters:
                lines.append(f"   章节地址样本：{[c['url'] for c in chapters[:2]]}")
            for s in trial["samples"]:
                if s.get("text"):
                    lines.append(f"   「{s['title']}」取到的正文开头：{s['text'][:120]!r}")
    return "\n".join(lines)


def _pages_digest(f: _CachedFetcher, entry: str, attempts: list[Attempt], trials: dict[int, Optional[dict]]) -> str:
    """入口页 + 最近一次尝试的目录页（与入口不同时）+ 一个章节页的结构骨架。只用已缓存或必要的少量请求。"""
    blocks = [("入口页", entry)]
    toc_url = next((a.tocUrl for a in reversed(attempts) if a.tocUrl), "")
    if toc_url and toc_url != entry:
        blocks.append(("目录页", toc_url))
    chapter_url = next((t["toc"]["chapters"][0]["url"] for t in reversed(list(trials.values()))
                        if t and t["toc"]["chapters"]), "")
    if chapter_url:
        blocks.append(("章节页（第一章）", chapter_url))
    out = []
    for label, url in blocks:
        try:
            final, html = f.get_html(url)
        except (CrawlError, ValueError) as e:
            out.append(f"【{label}】{url}\n（打不开：{e}）")
            continue
        out.append(f"【{label}】{final}\n{page_digest(html, final)}")
    return "\n\n".join(out)


# ---------------------------------------------------------------- 页面骨架（给模型看的压缩 HTML）

_DROP_XPATH = "//script|//style|//noscript|//iframe|//svg|//link|//meta|//comment()"


def page_digest(html: str, url: str, limit: int = SKELETON_CHARS) -> str:
    """标题 + 链接分组（附 XPath）+ 正文候选（附 XPath）+ 折叠后的 DOM 骨架。"""
    tree = parser.parse_doc(html, url)
    for bad in tree.xpath(_DROP_XPATH):
        if bad.getparent() is not None:
            bad.drop_tree() if isinstance(bad.tag, str) else bad.getparent().remove(bad)
    title = (tree.findtext(".//title") or "").strip()
    lines = [f"<title>：{title[:80]}"]
    lines.append("链接最多的容器（容器 XPath：链接数，前几个 / 最后几个链接文字 → 地址）：")
    lines += [f"  {g}" for g in _link_groups(tree)] or ["  （无）"]
    lines.append("文字最多的区块（XPath：字数，开头）：")
    lines += [f"  {b}" for b in _text_blocks(tree)] or ["  （无）"]
    lines.append("页面骨架（重复的兄弟节点已折叠）：")
    body = tree.find("body")
    out: list[str] = []
    _walk(body if body is not None else tree, 0, out, limit)
    return "\n".join(lines + out)


def _link_groups(tree, top: int = 6) -> list[str]:
    groups: dict = {}
    for a in tree.iter("a"):
        href, text = a.get("href"), parser._clean_inline(a.text_content())
        if not href or not text or href.startswith("javascript"):
            continue
        groups.setdefault(parser._container(a), []).append((text, href))
    ranked = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)[:top]
    out = []
    for el, links in ranked:
        sample = links[:3] + (links[-2:] if len(links) > 5 else [])
        shown = "；".join(f"{t[:20]} → {_short(h)}" for t, h in sample)
        out.append(f"{el_path(el)}//a：{len(links)} 个｜{shown}")
    return out


def _text_blocks(tree, top: int = 3) -> list[str]:
    scored = []
    for el in tree.iter("div", "article", "section", "td", "dd", "pre", "p"):
        own = len((el.text or "").strip()) + sum(len((c.tail or "").strip()) for c in el if isinstance(c.tag, str))
        own += sum(len(c.text_content().strip()) for c in el if c.tag == "p")
        if own >= 50:
            scored.append((own, el))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [f"{el_path(el)}：约 {n} 字，开头 {parser._clean_inline(el.text_content())[:40]!r}" for n, el in scored[:top]]


def el_path(el) -> str:
    """元素的 XPath：遇到带 id 的祖先就从那里开始（//div[@id='list']/dl），否则按标签 + 首个 class 拼。"""
    segs = []
    while el is not None and isinstance(el.tag, str) and el.tag != "html":
        seg, eid = el.tag, el.get("id")
        if eid and "'" not in eid:
            segs.append(f"{seg}[@id='{eid}']")
            return "//" + "/".join(reversed(segs))
        cls = (el.get("class") or "").split()
        if cls and "'" not in cls[0]:
            seg += f"[contains(@class,'{cls[0]}')]"
        segs.append(seg)
        el = el.getparent()
    segs.reverse()
    return "//" + "/".join(segs[-4:]) if len(segs) > 4 else "/html/" + "/".join(segs)


def _walk(el, depth: int, out: list[str], limit: int) -> None:
    if sum(len(s) + 1 for s in out) > limit or depth > 30:
        if out and not out[-1].endswith("已截断）"):
            out.append("…（结构过长已截断）")
        return
    attrs = ""
    if el.get("id"):
        attrs += f" id={el.get('id')!r}"
    if el.get("class"):
        attrs += f" class={el.get('class')[:40]!r}"
    if el.tag == "a" and el.get("href"):
        attrs += f" href={_short(el.get('href'))!r}"
    own = " ".join(t.strip() for t in [el.text or ""] + [c.tail or "" for c in el if isinstance(c.tag, str)] if t.strip())
    text = f" {own[:30]!r}" + (f"…(共{len(own)}字)" if len(own) > 30 else "") if own else ""
    out.append("  " * depth + f"<{el.tag}{attrs}>{text}")
    children = [c for c in el if isinstance(c.tag, str)]
    for c, skipped in _collapse(children):
        if skipped:
            out.append("  " * (depth + 1) + f"…（同类 <{c.tag} class={c.get('class') or ''!r}> 省略 {skipped} 个）")
        else:
            _walk(c, depth + 1, out, limit)


def _collapse(children: list) -> list[tuple]:
    """连续 6 个以上同标签同 class 的兄弟：保留前 2 个和最后 1 个，中间折叠成一行。"""
    out, i = [], 0
    while i < len(children):
        sig = (children[i].tag, children[i].get("class"))
        j = i
        while j < len(children) and (children[j].tag, children[j].get("class")) == sig:
            j += 1
        run = children[i:j]
        if len(run) >= 6:
            out += [(run[0], 0), (run[1], 0), (run[2], len(run) - 3), (run[-1], 0)]
        else:
            out += [(c, 0) for c in run]
        i = j
    return out


def _short(href: str) -> str:
    parts = urlsplit(href)
    return (parts.path + (f"?{parts.query}" if parts.query else ""))[:80] or href[:80]


# ---------------------------------------------------------------- 成功后：摸清站点结构（根地址 + 每层跳转规律，逐项验证）

# 每项状态：ok 已掌握 / partial 部分掌握 / failed 未掌握 / na 本站无此结构 / skipped 前置步骤失败未验证
SITE_MAP_STEPS = (("home", "站点首页"), ("search", "站内搜索"), ("category", "分类页"), ("book", "书籍页"), ("toc", "目录页"),
                  ("tocPaging", "目录分页"), ("chapter", "章节页"), ("contentPaging", "正文分页"),
                  ("bookInfo", "书名 / 作者 / 简介"), ("generalize", "换一本书验证"))


def _explore(f: _CachedFetcher, req: AnalyzeRequest, rule: CrawlRule, trial: dict, job: AnalyzeJob) -> dict:
    """规则抓通这本书之后，从站点根地址出发把「首页 → 分类 → 书籍 → 目录 → 章节」每一层的地址规律找出来并实测：
    首页能否打开、分类导航、首页 / 分类页上同格式的其他书、目录与章节地址格式、分页，最后拿另一本书按同一套规则试抓。
    → {homeUrl, siteName, items:[{key, label, status, pattern, example, detail}], mastered, failed, total, otherBooks[]}"""
    parts = urlsplit(req.url)
    home_url = f"{parts.scheme}://{parts.netloc}/"
    toc, toc_url = trial["toc"], trial["tocUrl"]
    chapters = toc["chapters"]
    book_re = path_regex(req.url)
    items: dict[str, dict] = {k: {"key": k, "label": label, "status": "skipped", "pattern": "", "example": "", "detail": ""}
                              for k, label in SITE_MAP_STEPS}

    def put(key, status, detail="", pattern="", example=""):
        items[key].update(status=status, detail=detail, pattern=pattern, example=example)

    # 首页 + 分类导航 + 首页上的其他书
    site_name, others, cats, home_links = "", [], [], None
    job.message = "验证站点结构：读取站点首页…"
    try:
        home_final, home_html = f.get_html(home_url)
        site = parser.parse_site(home_html, home_final, CrawlRule(), book_re)
        site_name, cats = site["siteName"], site["categories"]
        others = _book_links(home_html, home_final, book_re, (req.url, toc_url))
        home_links = home_link_rules(home_html, home_final, book_re, cats)
        put("home", "ok", f"首页可访问，标题「{site_name or '-'}」；首页上找到 {len(others)} 个同格式的书籍链接",
            home_url, home_final)
    except (CrawlError, ValueError) as e:
        put("home", "failed", f"首页打不开：{e}", home_url)

    if items["home"]["status"] == "ok":
        if not cats:
            put("category", "failed", "首页上没有识别到分类导航（站点可能没有分类，或导航是脚本生成的）")
        else:
            job.message = f"验证站点结构：打开分类「{cats[0]['name']}」…"
            try:
                cat_final, cat_html = f.get_html(cats[0]["url"], referer=home_url)
                in_cat = _book_links(cat_html, cat_final, book_re, (req.url, toc_url))
                others += [u for u in in_cat if u not in others]
                names = "、".join(c["name"] for c in cats[:6])
                pattern = _common_pattern([c["url"] for c in cats])
                if in_cat:
                    put("category", "ok", f"识别到 {len(cats)} 个分类（{names}…）；「{cats[0]['name']}」页里有 "
                        f"{len(in_cat)} 个同格式书籍链接", pattern, cats[0]["url"])
                else:
                    put("category", "partial", f"识别到 {len(cats)} 个分类（{names}…），但「{cats[0]['name']}」页里"
                        "没找到与本书同格式的书籍链接，分类 → 书籍这一跳没掌握", pattern, cats[0]["url"])
            except (CrawlError, ValueError) as e:
                put("category", "failed", f"分类页「{cats[0]['name']}」打不开：{e}", "", cats[0]["url"])

    # 站内搜索：找到首页的搜索框，用本书书名真的搜一次，看结果里有没有这本书
    search_cfg = None
    if items["home"]["status"] == "ok":
        job.message = "验证站点结构：模拟站内搜索…"
        search_cfg = _probe_search(f, home_html, home_final, toc.get("bookName") or "", (req.url, toc_url), book_re, put)

    # 书籍页：输入地址的格式能否在站内找到其他实例
    book_pattern = url_pattern(req.url, generic=True)
    if others:
        put("book", "ok", f"站内找到 {len(others)} 个同格式的书籍地址（首页 / 分类页），书籍地址规律成立", book_pattern,
            others[0])
    elif items["home"]["status"] == "ok":
        put("book", "partial", "本书能抓，但首页 / 分类页上没找到同格式的其他书籍地址，无法确认这个格式适用于全站",
            book_pattern, req.url)
    else:
        put("book", "partial", "本书能抓；首页打不开，无法在站内找其他书确认地址格式", book_pattern, req.url)

    # 目录页：与书籍页的关系
    if parser._same_page(toc_url, req.url):
        relation = "书籍页本身就是目录页"
    elif rule.tocLink:
        relation = f"从书籍页按 tocLink（{rule.tocLink}）跳到目录页"
    else:
        relation = "从书籍页上的「目录 / 全部章节」链接跳到目录页（自动识别）"
    put("toc", "ok", f"{relation}；识别到 {len(chapters)} 章", url_pattern(toc_url, generic=True), toc_url)

    pages = toc.get("tocPages") or 1
    if pages > 1:
        put("tocPaging", "ok", f"目录共 {pages} 页，按{'tocNext 规则' if rule.tocNext else '「下一页」链接（自动识别）'}翻页")
    else:
        put("tocPaging", "na", "目录只有 1 页，不需要翻页")

    # 章节页：地址格式是否统一 + 正文
    if chapters:
        ch_re = path_regex(chapters[0]["url"])
        fit = sum(1 for c in chapters if ch_re.fullmatch(_path_of(c["url"])))
        ratio = fit / len(chapters)
        chars = "、".join(f"{s['chars']} 字" for s in trial["samples"])
        detail = f"{fit}/{len(chapters)} 个章节地址符合该格式；试抓正文 {chars}"
        put("chapter", "ok" if ratio >= 0.9 else "partial",
            detail if ratio >= 0.9 else detail + "（格式不统一，个别章节地址另有规律）",
            url_pattern(chapters[0]["url"], generic=True), chapters[0]["url"])
        try:
            final, html = f.get_html(chapters[0]["url"])
            _, sub = parser.parse_content(html, final, rule)
            if sub:
                put("contentPaging", "ok", f"一章分多页，按{'contentNext 规则' if rule.contentNext else '「下一页」链接（自动识别）'}"
                    "翻页，已合并", url_pattern(sub, generic=True), sub)
            else:
                put("contentPaging", "na", "正文不分页（一章一个页面）")
        except (CrawlError, ValueError) as e:
            put("contentPaging", "failed", f"复查章节页失败：{e}")

    got = {"书名": toc.get("bookName"), "作者": toc.get("author"), "简介": toc.get("intro")}
    have = [k for k, v in got.items() if v]
    miss = [k for k, v in got.items() if not v]
    status = "ok" if not miss else "partial" if "书名" in have else "failed"
    put("bookInfo", status, (f"取到：{'、'.join(have)}" if have else "都没取到") + (f"；没取到：{'、'.join(miss)}" if miss else ""),
        example=f"《{toc.get('bookName') or '-'}》 {toc.get('author') or ''}".strip())

    # 换一本书：同一套规则在另一本书上也能抓通，才算真正掌握「每本书」的跳转规律
    if others:
        other = others[0]
        job.message = "验证站点结构：换一本书按同一套规则试抓…"
        try:
            t2 = _trial(f, other, rule, max_pages=2, sample_count=1)
            name2 = t2["toc"].get("bookName") or other
            s2 = t2["samples"][0] if t2["samples"] else {}
            if t2["problems"]:
                put("generalize", "failed", f"《{name2}》：{'；'.join(t2['problems'])}", "", other)
            else:
                put("generalize", "ok", f"《{name2}》：目录 {len(t2['toc']['chapters'])}+ 章，首章 {s2.get('chars', 0)} 字，"
                    "同一套规则可用", "", other)
        except (CrawlError, ValueError) as e:
            put("generalize", "failed", f"按同一套规则抓不通：{e}", "", other)
    else:
        put("generalize", "skipped", "站内没找到第二本书，未能验证规则是否适用于其他书")
    f.encoding = rule.encoding

    out = list(items.values())
    return {"homeUrl": home_url, "siteName": site_name, "items": out, "otherBooks": others[:5],
            "categories": [{"name": c["name"], "url": c["url"]} for c in cats[:12]],
            # 学到的搜索方式（搜索可用或部分可用时）：{action, method, field, params, charset, pattern, testKeyword, works}
            "search": search_cfg,
            # 首页链接规律：首页上每一类链接的地址规律、显示文字规律、数量和例子（见 home_link_rules）
            "homeLinks": home_links,
            "mastered": sum(1 for i in out if i["status"] == "ok"),
            "failed": sum(1 for i in out if i["status"] in ("failed", "partial")),
            "total": sum(1 for i in out if i["status"] != "na")}


# 搜索结果页上表示「搜不了」的提示：限频 / 验证码 / 要登录
_SEARCH_REFUSED = re.compile(r"搜索间隔|搜索太频繁|过于频繁|操作频繁|稍后再试|请输入验证码|验证码错误|captcha|请先登录|登录后才能",
                             re.IGNORECASE)


def _probe_search(f: _CachedFetcher, html: str, home_url: str, keyword: str, own_urls: tuple, book_re: re.Pattern,
                  put) -> Optional[dict]:
    """首页搜索框 → 模拟搜索（用本书书名），最多试 2 个最像搜索的表单。
    ok = 结果里有本书（或直接跳到了本书页面）；partial = 搜索能用但没搜到；failed = 打不开 / 被拒；na = 没有搜索框。
    → 搜索方式 {action, method, field, params, charset, pattern, testKeyword, works}（failed / na 时为 None）"""
    forms = parser.find_search_forms(html, home_url)
    if not forms:
        put("search", "na", "首页上没有找到搜索框（站点可能没有站内搜索，或搜索框由脚本生成）")
        return None
    if not keyword:
        put("search", "skipped", "找到了搜索框，但本书没取到书名，没法模拟搜索", _search_pattern(forms[0]))
        return None
    partial: Optional[tuple[dict, str, str]] = None
    errors: list[str] = []
    for form in forms[:2]:
        pattern = _search_pattern(form)
        cfg = {**{k: form[k] for k in ("action", "method", "field", "params", "charset")},
               "pattern": pattern, "testKeyword": keyword, "works": False}
        try:
            final, page = f.submit_form(form["action"], form["method"], {**form["params"], form["field"]: keyword},
                                        form["charset"], referer=home_url)
        except (CrawlError, ValueError) as e:
            errors.append(f"{pattern}：{e}")
            continue
        hit = _search_hit(page, final, keyword, own_urls, book_re)
        if hit:
            cfg["works"] = True
            put("search", "ok", f"用书名「{keyword}」模拟搜索：{hit}", pattern, final)
            return cfg
        text = parser.parse_doc(page, final).text_content()
        refused = _SEARCH_REFUSED.search(text)
        if refused:
            snippet = parser._clean_inline(text[max(0, refused.start() - 12):refused.end() + 18])
            errors.append(f"{pattern}：搜索页提示「{snippet}」（限频 / 验证码 / 需要登录）")
            continue
        partial = partial or (cfg, pattern, final)
    if partial:
        cfg, pattern, final = partial
        put("search", "partial", f"搜索能提交、结果页也打开了，但用「{keyword}」没搜到这本书（可能搜索只认作者 / 关键词，"
                                 "或结果由脚本加载）" + (f"；另一个搜索框：{errors[0]}" if errors else ""), pattern, final)
        return cfg
    put("search", "failed", "找到搜索框，但模拟搜索失败：" + "；".join(errors)[:300], _search_pattern(forms[0]))
    return None


def _search_hit(page: str, final: str, keyword: str, own_urls: tuple, book_re: re.Pattern) -> Optional[str]:
    """搜索结果里有没有这本书 → 说明文字；没有返回 None。"""
    if any(parser._same_page(final, u) for u in own_urls):
        return "直接跳到了这本书的页面"
    tree = parser.parse_doc(page, final)
    norm = re.sub(r"\s+", "", keyword)
    exact, titled = False, 0
    for a in tree.iter("a"):
        href = (a.get("href") or "").split("#")[0]
        if href and any(parser._same_page(href, u) for u in own_urls):
            exact = True
        text = re.sub(r"\s+", "", a.text_content())
        if norm and norm in text and (not href or book_re.fullmatch(_path_of(href)) or len(text) <= len(norm) + 12):
            titled += 1
    if exact:
        return f"结果里有这本书的链接（共 {titled or 1} 个相关结果）"
    if titled:
        return f"结果里有 {titled} 个标题含「{keyword}」的链接"
    return None


def _search_pattern(form: dict) -> str:
    """搜索地址模板：GET 拼成 地址?字段={书名}&其他参数，POST 写成「POST 地址（字段={书名}，…）」。"""
    from urllib.parse import urlencode
    others = urlencode(form["params"]) if form["params"] else ""
    if form["method"] == "POST":
        return f"POST {form['action']}（{form['field']}={{书名}}" + (f"，{others}" if others else "") + "）"
    sep = "&" if urlsplit(form["action"]).query else "?"
    return f"{form['action']}{sep}{form['field']}={{书名}}" + (f"&{others}" if others else "")


def _book_links(html: str, url: str, book_re: re.Pattern, exclude: tuple) -> list[str]:
    """页面上与「书籍页」同格式（同域名、路径符合 book_re）的链接，去重，排除本书。"""
    tree = parser.parse_doc(html, url)
    host = urlsplit(url).hostname
    out = []
    for a in tree.iter("a"):
        href = (a.get("href") or "").split("#")[0]
        if not parser._usable_href(href) or urlsplit(href).hostname != host:
            continue
        if not book_re.fullmatch(_path_of(href)) or any(parser._same_page(href, x) for x in exclude):
            continue
        if href not in out:
            out.append(href)
    return out[:50]


def _path_of(url: str) -> str:
    parts = urlsplit(url)
    return parts.path + (f"?{parts.query}" if parts.query else "")


def path_regex(url: str) -> re.Pattern:
    """地址路径 → 正则：数字段换成 \\d+；路径里没有数字（如拼音 slug）时把最后一段换成任意段。"""
    path = _path_of(url)
    pattern, n = re.subn(r"\d+", "@@NUM@@", path)
    escaped = re.escape(pattern).replace("@@NUM@@", r"\d+")
    if not n:
        segs = path.rstrip("/").split("/")
        if len(segs) > 1 and segs[-1]:
            tail = "/" if path.endswith("/") else ""
            escaped = re.escape("/".join(segs[:-1]) + "/") + r"[^/?#]+" + re.escape(tail)
    return re.compile(escaped)


def _common_pattern(urls: list[str]) -> str:
    """一组地址（如分类页）的公共模板：取出现最多的 url_pattern。"""
    counts: dict[str, int] = {}
    for u in urls:
        p = url_pattern(u, generic=True)
        counts[p] = counts.get(p, 0) + 1
    return max(counts, key=counts.get) if counts else ""


def _site_map_text(site_map: dict) -> str:
    lines = [f"- {i['label']}：{_STATUS_TEXT[i['status']]}；{i['pattern'] or ''} {i['detail']}" for i in site_map["items"]]
    hl = site_map.get("homeLinks") or {}
    if hl.get("groups"):
        lines.append(f"首页链接规律（共 {hl['total']} 个链接）：")
        lines += [f"  · {g['label']} {g['count']} 个：地址 {g['pattern']}；文字 {g['textRule']}；例：" +
                  "、".join(e["text"] for e in g["examples"][:3] if e["text"]) for g in hl["groups"]]
    return "\n".join(lines)


# ---------------------------------------------------------------- 首页链接规律（以首页为核心，每一类链接的地址 / 文字规律）

ROLE_LABEL = {"category": "分类导航", "book": "书籍", "chapter": "章节", "list": "列表 / 分页", "nav": "站内其他",
              "external": "站外", "script": "脚本链接（地址要执行脚本才知道）"}
ROLE_ORDER = ["category", "book", "chapter", "list", "nav", "external", "script"]


def home_link_rules(html: str, url: str, book_re: re.Pattern, cats: list[dict]) -> dict:
    """首页上所有 <a> 按「类型 + 地址规律」归类：分类导航 / 书籍 / 章节 / 列表分页 / 站内其他 / 站外 / 脚本链接。
    每类给出地址规律（数字段 → {n}）、显示文字的规律（长度、共同前后缀、「第N章」格式、截断的「…」）、
    数量、出现在页面哪些区块、最多 8 个例子。→ {total, groups:[{role, label, pattern, count, textRule, areas, examples}]}"""
    tree = parser.parse_doc(html, url)
    host = urlsplit(url).hostname
    cat_urls = {c["url"].split("#")[0].rstrip("/") for c in cats}
    buckets: dict[tuple[str, str], dict] = {}
    total = 0
    for a in tree.iter("a"):
        raw = (a.get("href") or "").strip()
        text = parser._clean_inline(a.text_content())
        if not raw or raw.startswith("#"):
            continue
        total += 1
        if raw.lower().startswith("javascript") or not parser._usable_href(raw):
            role, pattern = "script", raw[:40]
        else:
            href = raw.split("#")[0]
            parts = urlsplit(href)
            if parts.hostname != host:
                role, pattern = "external", f"{parts.scheme}://{parts.netloc}/…"
            else:
                path = _path_of(href)
                if href.rstrip("/") in cat_urls:
                    role = "category"
                elif book_re.fullmatch(path):
                    role = "book"
                elif parser._looks_like_chapter(a) or re.search(r"/\d+\.html?$", parts.path):
                    role = "chapter"
                elif re.fullmatch(r"上一页|下一页|下页|\d{1,4}", text) or re.search(r"(page|list|sort|class|top|rank)", parts.path, re.I):
                    role = "list"
                else:
                    role = "nav"
                pattern = url_pattern(href, generic=role not in ("nav",))
        b = buckets.setdefault((role, pattern), {"role": role, "pattern": pattern, "texts": [], "examples": [],
                                                 "areas": {}, "images": 0})
        if text:
            b["texts"].append(text)
        else:
            b["images"] += 1
        area = _area_label(parser._container(a))
        b["areas"][area] = b["areas"].get(area, 0) + 1
        if text and len(b["examples"]) < 8:
            b["examples"].append({"text": text, "url": raw})
        elif not text and not b.get("imageExample"):
            b["imageExample"] = {"text": "", "url": raw}
    groups = []
    for b in buckets.values():
        if not b["examples"] and b.get("imageExample"):   # 全是图片链接时，至少给一个例子
            b["examples"].append(b["imageExample"])
        count = len(b["texts"]) + b["images"]
        groups.append({"role": b["role"], "label": ROLE_LABEL[b["role"]], "pattern": b["pattern"], "count": count,
                       "textRule": _text_rule(b["role"], b["texts"], b["images"]),
                       "areas": [f"{k}（{v}）" for k, v in sorted(b["areas"].items(), key=lambda kv: -kv[1])[:4]],
                       "examples": b["examples"]})
    # 站内其他里地址各不相同的零散链接（首页 / 登录 / 手机版…）合成一组，规律表才不会被单个链接刷屏
    nav = [g for g in groups if g["role"] == "nav" and g["count"] == 1]
    groups = [g for g in groups if not (g["role"] == "nav" and g["count"] == 1)]
    if nav:
        groups.append({"role": "nav", "label": ROLE_LABEL["nav"], "pattern": "（地址各不相同）", "count": len(nav),
                       "textRule": "零散的站内链接：" + "、".join(g["examples"][0]["text"] or "图片" for g in nav[:8]),
                       "areas": [], "examples": [g["examples"][0] for g in nav[:8]]})
    groups.sort(key=lambda g: (ROLE_ORDER.index(g["role"]), -g["count"]))
    return {"total": total, "groups": groups[:20]}


def _area_label(el) -> str:
    """链接所在区块的简短名字：标签 + id / 首个 class，如 div#list、ul.nav。"""
    if el is None or not isinstance(el.tag, str):
        return "页面"
    if el.get("id"):
        return f"{el.tag}#{el.get('id')}"[:30]
    cls = (el.get("class") or "").split()
    return f"{el.tag}.{cls[0]}"[:30] if cls else el.tag


def _text_rule(role: str, texts: list[str], images: int) -> str:
    """一组链接显示文字的规律：长度范围、共同前缀 / 后缀、第N章格式、长书名截断。"""
    if not texts:
        return f"没有文字（{images} 个图片 / 封面链接）"
    lens = sorted(len(t) for t in texts)
    span = f"{lens[0]} 字" if lens[0] == lens[-1] else f"{lens[0]}~{lens[-1]} 字"
    rule = {"category": "分类名", "book": "书名", "chapter": "章节名", "list": "列表 / 分页文字"}.get(role, "文字")
    notes = []
    if role == "chapter" and sum(1 for t in texts if parser.CHAPTER_TITLE_RE.search(t)) * 2 >= len(texts):
        notes.append("「第N章 + 标题」格式")
    if len(texts) >= 3:
        pre = _common_prefix(texts)
        suf = _common_prefix([t[::-1] for t in texts])[::-1]
        if len(pre) >= 1 and pre.strip():
            notes.append(f"都以「{pre}」开头")
        if len(suf) >= 1 and suf.strip() and not suf.startswith("…") and suf not in ("...",):
            notes.append(f"都以「{suf}」结尾")
    cut = sum(1 for t in texts if t.endswith(("...", "…")))
    if cut:
        notes.append(f"{cut} 个太长被截断成「…」")
    if images:
        notes.append(f"另有 {images} 个图片 / 封面链接")
    return f"{rule}，{span}" + ("；" + "；".join(notes) if notes else "")


def _common_prefix(texts: list[str]) -> str:
    first = min(texts, key=len)
    for i, ch in enumerate(first):
        if any(t[i] != ch for t in texts):
            return first[:i]
    return first


_STATUS_TEXT = {"ok": "已掌握", "partial": "部分掌握", "failed": "未掌握", "na": "本站无此结构", "skipped": "未验证"}


# ---------------------------------------------------------------- 成功：总结规律

SUMMARY_TEMPLATE = """下面是一次已经成功的网络小说抓取，以及对该站点结构的逐项实测。请总结这个站点的地址规律和抓取规则，方便以后抓同站其他书。

站点首页（根地址）：{home}
入口地址（本书）：{entry}
目录页：{toc}
章节地址样本：{chapters}
书名：{book}
同站其他书籍地址样本：{others}
最终规则（XPath）：{rule}
站点结构实测结果：
{siteMap}

严格按 JSON 输出（summary 里要如实说明哪些规律已掌握、哪些没掌握）：
{{"siteName":"站点名（中文名或域名）",
 "summary":"2~4 句中文：入口地址是什么页面、目录在哪、章节地址格式、正文位置、需要注意的地方",
 "bookUrlPattern":"书籍地址模板，变量用 {{bookId}} 这类占位，如 https://www.example.com/book/{{bookId}}/",
 "tocUrlPattern":"目录页地址模板",
 "chapterUrlPattern":"章节地址模板，如 https://www.example.com/book/{{bookId}}/{{chapterId}}.html"}}"""


def _result(req: AnalyzeRequest, f: _CachedFetcher, host: str, strategy: str, rule: CrawlRule, trial: dict,
            job: AnalyzeJob) -> dict:
    usage = job.usage
    toc, chapters = trial["toc"], trial["toc"]["chapters"]
    samples = [c["url"] for c in chapters[:3]]
    site_map = _explore(f, req, rule, trial, job)
    job.message = "总结地址规律…"
    summary = {
        "siteName": site_map["siteName"], "summary": "",
        "bookUrlPattern": url_pattern(req.url, generic=True),
        "tocUrlPattern": url_pattern(trial["tocUrl"], generic=True),
        "chapterUrlPattern": url_pattern(chapters[0]["url"], generic=True) if chapters else "",
    }
    try:
        text = llm_client.chat(req.model, [{"role": "system", "content": "你是网络爬虫专家，只输出 JSON。"},
                                           {"role": "user", "content": SUMMARY_TEMPLATE.format(
                                               home=site_map["homeUrl"], entry=req.url, toc=trial["tocUrl"],
                                               chapters=samples, book=toc.get("bookName") or "",
                                               others=site_map["otherBooks"][:3] or "（没找到）",
                                               rule=_compact(rule) or "全部自动识别",
                                               siteMap=_site_map_text(site_map))}],
                               max_tokens=700, usage=usage)
        data = llm_client.parse_json(text)
        for key in summary:
            if isinstance(data.get(key), str) and data[key].strip():
                summary[key] = data[key].strip()[:500]
    except LLMError as e:
        log.info("AI 解析：总结规律失败（不影响结果）：%s", e)
    if not summary["summary"]:
        summary["summary"] = (f"入口 {summary['bookUrlPattern']}，目录 {summary['tocUrlPattern']}，"
                              f"章节 {summary['chapterUrlPattern']}；规则：{_STRATEGY[strategy]}。")
    preset_key = "auto" if strategy != "preset" else rules.resolve("", None, host)[0]
    preview = {**{k: v for k, v in toc.items() if k != "chapters"}, "chapters": chapters,
               "chapterCount": len(chapters), "preset": preset_key, "rule": rule.model_dump(),
               "sample": trial["samples"][0] if trial["samples"] else None}
    return {"host": host, "homeUrl": site_map["homeUrl"], "tocUrl": trial["tocUrl"], "strategy": strategy,
            "preset": preset_key, "rule": _compact(rule), "chapterSamples": samples, **summary,
            "siteMap": site_map, "preview": preview}


def url_pattern(url: str, generic: bool = False) -> str:
    """把地址里的数字段换成占位：https://x.com/book/500489/123.html → https://x.com/book/{n}/{n}.html。
    generic=True 且路径里没有数字（拼音 slug 等）时，把最后一段换成 {slug}。"""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"   # 只换路径和参数，域名 / IP 里的数字不动
    out = origin + re.sub(r"(?<=[/_=-])\d+(?=[/._?&-]|$)", "{n}", url[len(origin):])
    if generic and out == url:
        segs = parts.path.rstrip("/").split("/")
        if len(segs) > 1 and segs[-1]:
            tail = "/" if parts.path.endswith("/") else ""
            ext = re.search(r"\.[A-Za-z0-9]{1,6}$", segs[-1])   # 保留扩展名：/cat/xuanhuan.html → /cat/{slug}.html
            out = f"{parts.scheme}://{parts.netloc}" + "/".join(segs[:-1]) + "/{slug}" + (ext.group(0) if ext else "") + tail
    return out
