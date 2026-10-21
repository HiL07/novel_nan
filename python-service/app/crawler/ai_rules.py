"""AI 解析地址：给一本书的地址（详情页或目录页），反复「写规则 → 试抓 → 看结果」，直到抓通或达到尝试上限。

流程（一次后台任务，Java 轮询，成功后由 Java 把规则存入 crawl_site_rule 表，之后同站点自动沿用）：
1. 已学到的规则（Java 传 knownRule，同域名之前成功过）→ 2. 内置预设 / 启发式 → 3+. 大模型根据
   页面结构（去脚本、折叠重复节点后的骨架 + 链接分组 / 正文候选的 XPath 提示）和之前每次失败的原因写 XPath。
每次尝试都是一次真实的小规模抓取：解析目录（含分页）+ 试抓首章与中间一章，正文够长且两章不同才算成功。
成功后再让大模型总结地址规律（书籍 / 目录 / 章节地址模板）与规则说明；总结失败不影响结果。

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
from .fetcher import CrawlError, Fetcher, check_url
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
    # 成功后：{host, siteName, tocUrl, preset, rule, strategy, summary, bookUrlPattern, tocUrlPattern,
    #          chapterUrlPattern, chapterSamples[], preview{bookName, author, intro, chapters, chapterCount, tocPages, preset, rule, sample}}
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
                except (CrawlError, ValueError) as e:
                    trial, attempt.ok, attempt.error = None, False, str(e)
                attempt.seconds = round(time.monotonic() - started, 1)
                job.attempts.append(attempt)
                _remember(job.jobId, i, trial)
                log.info("AI 解析 %s 第 %s 次（%s）：%s %s", req.url, i, strategy, "成功" if attempt.ok else "失败", attempt.error)
                if attempt.ok:
                    job.progress, job.message = 92, "抓取成功，正在总结地址规律…"
                    job.result = _result(req, f, host, strategy, rule, trial, job.usage)
                    job.progress, job.status = 100, "succeeded"
                    job.message = (f"第 {i} 次尝试成功（{_STRATEGY[strategy]}）：目录 {attempt.chapterCount} 章，"
                                   f"首章 {attempt.sampleChars} 字")
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

def _trial(f: _CachedFetcher, entry: str, rule: CrawlRule) -> dict:
    """入口 →（tocLink）→ 目录（含分页）→ 首章 + 中间一章。→ {tocUrl, toc, samples, problems}"""
    f.encoding = rule.encoding
    toc_url = service.resolve_toc_url(f, entry, rule)
    toc = None
    try:
        toc = service._load_toc(f, toc_url, rule)
    except CrawlError:
        if rule.tocLink or rule.chapterLinks:
            raise
    if not rule.tocLink and not rule.chapterLinks:
        # 启发式：详情页上常有「全部章节 / 查看目录」链到真正的目录页，入口只列了最新几章时以章节多的为准
        final, html = f.get_html(entry)
        guessed = parser.parse_book_detail(html, final, rule)["tocUrl"]
        if guessed and guessed != final and (toc is None or len(toc["chapters"]) < 30):
            try:
                other = service._load_toc(f, guessed, rule)
                if toc is None or len(other["chapters"]) > len(toc["chapters"]):
                    toc, toc_url = other, guessed
            except CrawlError:
                pass
    if toc is None:
        raise CrawlError("目录页上没有识别到章节链接")

    chapters = toc["chapters"]
    picks = [0] + ([len(chapters) // 2] if len(chapters) >= 5 else [])
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


# ---------------------------------------------------------------- 成功：总结规律

SUMMARY_TEMPLATE = """下面是一次已经成功的网络小说抓取。请总结这个站点的地址规律和抓取规则，方便以后抓同站其他书。

入口地址：{entry}
目录页：{toc}
章节地址样本：{chapters}
书名：{book}
最终规则（XPath）：{rule}

严格按 JSON 输出：
{{"siteName":"站点名（中文名或域名）",
 "summary":"2~4 句中文：入口地址是什么页面、目录在哪、章节地址格式、正文位置、需要注意的地方",
 "bookUrlPattern":"书籍地址模板，变量用 {{bookId}} 这类占位，如 https://www.example.com/book/{{bookId}}/",
 "tocUrlPattern":"目录页地址模板",
 "chapterUrlPattern":"章节地址模板，如 https://www.example.com/book/{{bookId}}/{{chapterId}}.html"}}"""


def _result(req: AnalyzeRequest, f: _CachedFetcher, host: str, strategy: str, rule: CrawlRule, trial: dict,
            usage: dict) -> dict:
    toc, chapters = trial["toc"], trial["toc"]["chapters"]
    samples = [c["url"] for c in chapters[:3]]
    summary = {
        "siteName": "", "summary": "",
        "bookUrlPattern": url_pattern(req.url),
        "tocUrlPattern": url_pattern(trial["tocUrl"]),
        "chapterUrlPattern": url_pattern(chapters[0]["url"]) if chapters else "",
    }
    try:
        text = llm_client.chat(req.model, [{"role": "system", "content": "你是网络爬虫专家，只输出 JSON。"},
                                           {"role": "user", "content": SUMMARY_TEMPLATE.format(
                                               entry=req.url, toc=trial["tocUrl"], chapters=samples,
                                               book=toc.get("bookName") or "", rule=_compact(rule) or "全部自动识别")}],
                               max_tokens=600, usage=usage)
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
    return {"host": host, "tocUrl": trial["tocUrl"], "strategy": strategy, "preset": preset_key,
            "rule": _compact(rule), "chapterSamples": samples, **summary, "preview": preview}


def url_pattern(url: str) -> str:
    """把地址里的数字段换成占位：https://x.com/book/500489/123.html → https://x.com/book/{n}/{n}.html"""
    return re.sub(r"(?<=[/_=-])\d{2,}(?=[/._?&-]|$)", "{n}", url)
