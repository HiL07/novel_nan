"""通用小说页面爬虫（纯规则，不调用任何 AI / LLM，不消耗 token）。

用法（在 python-service/ 下）：
    .venv/Scripts/python crawler/crawler.py <url> [--max-pages 1] [--delay 2] [--selector "div.mw-parser-output"]

- 遵守 robots.txt；同一站点请求间隔 --delay 秒；失败重试 2 次。
- 编码：HTTP 头 charset → <meta charset> → 严格 UTF-8 → 严格 GB18030（兼容 GBK 中文站）。
- 正文：站点规则 / --selector 优先，否则按“文本量 − 链接文本量”评分自动选出正文块。
- 翻页：<link rel=next> 或文字为 下一章/下一页/下一回/Next 的同站链接，最多 --max-pages 页。
- 输出：crawler/output/<host>/<时间戳>/pages.jsonl（每页一行）+ book.txt（拼接正文）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "nan_novel-crawler/0.1 (personal testing; non-commercial)"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# 已知站点规则：content = 正文选择器，drop = 正文内需删除的块（选择器仅支持 tag / #id / .class / tag.class）
_WIKISOURCE = {"content": "div.mw-parser-output", "drop": ["#headerContainer", ".ws-noexport", "#plainSister"]}
SITE_RULES: dict[str, dict] = {
    "zh.wikisource.org": _WIKISOURCE,
    "en.wikisource.org": _WIKISOURCE,
    "www.gutenberg.org": {"content": "body", "drop": []},
}
# 无规则时先尝试的常见正文容器
COMMON_SELECTORS = ["#chaptercontent", "#content", "#BookText", "#htmlContent", ".read-content", "article"]

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
DROP_TAGS = {"script", "style", "noscript", "iframe", "svg", "form", "nav", "header", "footer", "aside",
             "button", "select", "textarea", "sup", "template"}
BLOCK_TAGS = {"p", "div", "section", "article", "main", "li", "ul", "ol", "dl", "dt", "dd", "table", "tr",
              "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "center", "td", "th", "body"}
NOISE_RE = re.compile(
    r"(^|[\s_-])(nav|navbox|menu|footer|header|sidebar|comment|share|breadcrumb|advert|ads?|toc|noprint|"
    r"mw-editsection|catlinks|printfooter|reference|copyright|recommend|tool)s?($|[\s_-])", re.I)
NEXT_RE = re.compile(r"^\s*(下一章|下一页|下一回|下一节|下页|下章|下一篇|next( page| chapter)?|›|»|→)\s*[>》→]*\s*$", re.I)


# ---------------------------------------------------------------- DOM

class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict | None = None, parent: "Node | None" = None):
        self.tag, self.attrs, self.children, self.parent = tag, attrs or {}, [], parent

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def iter(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.iter()

    def matches(self, sel: str) -> bool:
        m = re.fullmatch(r"([a-zA-Z0-9]*)(?:#([\w-]+))?(?:\.([\w-]+))?", sel.strip())
        if not m:
            raise ValueError(f"不支持的选择器: {sel}")
        tag, id_, cls = m.groups()
        return ((not tag or self.tag == tag.lower()) and (not id_ or self.attrs.get("id") == id_)
                and (not cls or cls in self.classes))

    def select(self, sel: str) -> "Node | None":
        return next((n for n in self.iter() if n.matches(sel)), None)


class TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        if tag not in VOID_TAGS:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, {k: (v or "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:  # 容忍未闭合标签
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse_html(html: str) -> Node:
    b = TreeBuilder()
    b.feed(html)
    b.close()
    return b.root


# ---------------------------------------------------------------- 抽取

def is_noise(n: Node) -> bool:
    if n.tag in DROP_TAGS:
        return True
    if "display:none" in n.attrs.get("style", "").replace(" ", ""):
        return True
    return bool(NOISE_RE.search(f"{n.attrs.get('class', '')} {n.attrs.get('id', '')}"))


def to_text(n: Node) -> str:
    out: list[str] = []

    def walk(x):
        if isinstance(x, str):
            out.append(re.sub(r"[ \t\r\n\f]+", " ", x))
            return
        if is_noise(x):
            return
        if x.tag == "br":
            out.append("\n")
            return
        block = x.tag in BLOCK_TAGS
        if block:
            out.append("\n")
        for c in x.children:
            walk(c)
        if block:
            out.append("\n")

    walk(n)
    lines = [ln.strip().replace("　", "  ").strip() for ln in "".join(out).split("\n")]
    return "\n".join(ln for ln in lines if ln)


def text_len(n: Node, links_only=False) -> int:
    total = 0
    for c in n.children:
        if isinstance(c, str):
            if not links_only:
                total += len(c.strip())
        elif not is_noise(c):
            total += text_len(c, False) if (links_only and c.tag == "a") else text_len(c, links_only)
    return total


def drop_blocks(node: Node, selectors: list[str]) -> None:
    for n in list(node.iter()):
        if n is not node and n.parent is not None and any(n.matches(s) for s in selectors):
            n.parent.children.remove(n)
            n.parent = None


def pick_content(root: Node, host: str, selector: str | None) -> tuple[Node, str]:
    rule = SITE_RULES.get(host, {})
    for sel in ([selector] if selector else []) + ([rule["content"]] if rule else []):
        node = root.select(sel)
        if node is not None:
            drop_blocks(node, rule.get("drop", []))
            return node, f"selector:{sel}"
    for sel in COMMON_SELECTORS:
        node = root.select(sel)
        if node is not None and text_len(node) > 300:
            return node, f"common:{sel}"
    best, best_score = root, -1.0
    for n in root.iter():
        if n.tag not in {"div", "article", "section", "main", "td", "body"} or is_noise(n):
            continue
        t = text_len(n)
        if t < 200:
            continue
        score = t - 2 * text_len(n, links_only=True)
        if score > best_score * 1.05:  # 同分时偏向更外层，避免只选中一个段落
            best, best_score = n, score
    return best, "auto:density"


def find_title(root: Node) -> str:
    for sel in ("h1", "title"):
        n = root.select(sel)
        if n is not None and (t := to_text(n)):
            return t.splitlines()[0]
    return ""


def increment_last_number(url: str) -> str | None:
    """.../第001回 → .../第002回（保留补零位数）；URL 中无数字时返回 None。"""
    path = unquote(urlparse(url).path)
    nums = list(re.finditer(r"\d+", path))
    if not nums:
        return None
    m = nums[-1]
    return path[:m.start()] + str(int(m.group()) + 1).zfill(len(m.group())) + path[m.end():]


def find_next(root: Node, base_url: str) -> str | None:
    host = urlparse(base_url).netloc
    links = []
    for n in root.iter():
        href = n.attrs.get("href")
        if not href:
            continue
        if (n.tag == "link" and n.attrs.get("rel", "").lower() == "next") or \
                (n.tag == "a" and NEXT_RE.match(to_text(n) or n.attrs.get("title", ""))):
            url = urljoin(base_url, href).split("#")[0]
            if urlparse(url).netloc == host and url != base_url:
                return url
        if n.tag == "a":
            links.append(n.attrs["href"])
    # 回退：页面上存在“当前 URL 末尾数字 +1”的同站链接（编号章节，如 第001回 → 第002回）
    if want := increment_last_number(base_url):
        for href in links:
            url = urljoin(base_url, href).split("#")[0]
            if urlparse(url).netloc == host and unquote(urlparse(url).path) == want:
                return url
    return None


# ---------------------------------------------------------------- 抓取

def decode(resp: httpx.Response) -> tuple[str, str]:
    raw = resp.content
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", "replace"), "utf-8-sig"
    cands = []
    if m := re.search(r"charset=([\w-]+)", resp.headers.get("content-type", ""), re.I):
        cands.append(m.group(1))
    if m := re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:4096], re.I):
        cands.append(m.group(1).decode("ascii", "ignore"))
    cands += ["utf-8", "gb18030"]
    for enc in cands:
        enc = "gb18030" if enc.lower() in {"gb2312", "gbk"} else enc
        try:
            return raw.decode(enc), enc
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace"), "utf-8(replace)"


class Fetcher:
    def __init__(self, delay: float, timeout: float):
        self.delay = delay
        self.client = httpx.Client(headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
                                   timeout=timeout, follow_redirects=True)
        self.robots: dict[str, RobotFileParser] = {}
        self.last: dict[str, float] = {}

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        key = f"{p.scheme}://{p.netloc}"
        if key not in self.robots:
            rp = RobotFileParser()
            try:
                r = self.client.get(key + "/robots.txt")
                if r.status_code in (401, 403):
                    rp.disallow_all = True
                elif r.status_code >= 400:
                    rp.allow_all = True
                else:
                    rp.parse(decode(r)[0].splitlines())
            except httpx.HTTPError as e:
                print(f"[warn] robots.txt 获取失败（{e.__class__.__name__}），按允许处理", file=sys.stderr)
                rp.allow_all = True
            self.robots[key] = rp
        return self.robots[key].can_fetch(USER_AGENT, url)

    def get(self, url: str) -> httpx.Response:
        if not self.allowed(url):
            raise PermissionError(f"robots.txt 不允许抓取: {url}")
        host = urlparse(url).netloc
        wait = self.last.get(host, 0) + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        err: Exception | None = None
        for attempt in range(3):
            try:
                r = self.client.get(url)
                self.last[host] = time.monotonic()
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                return r
            except httpx.HTTPError as e:
                err = e
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 429:
                    break
                time.sleep(self.delay * (attempt + 1))
        raise RuntimeError(f"抓取失败 {url}: {err}")


def crawl(url: str, max_pages: int, delay: float, selector: str | None, timeout: float) -> Path:
    fetcher = Fetcher(delay, timeout)
    host = urlparse(url).netloc
    out = OUTPUT_DIR / host.replace(":", "_") / datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    with open(out / "pages.jsonl", "w", encoding="utf-8") as jf, open(out / "book.txt", "w", encoding="utf-8") as bf:
        for i in range(1, max_pages + 1):
            if url in seen:
                break
            seen.add(url)
            t0 = time.monotonic()
            resp = fetcher.get(url)
            html, enc = decode(resp)
            root = parse_html(html)
            nxt = find_next(root, str(resp.url))  # 先找翻页链接：pick_content 会删除导航块
            node, method = pick_content(root, host, selector)
            title, text = find_title(root), to_text(node)
            rec = {"index": i, "url": str(resp.url), "status": resp.status_code, "encoding": enc, "title": title,
                   "method": method, "chars": len(text), "next": nxt, "seconds": round(time.monotonic() - t0, 2),
                   "text": text}
            jf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            bf.write(f"{title}\n\n{text}\n\n")
            print(f"[{i}] {resp.status_code} {enc} {method} {len(text)}字 「{title}」 next={nxt}")
            if not nxt:
                break
            url = nxt
    return out


def main():
    ap = argparse.ArgumentParser(description="通用小说页面爬虫（无 AI）")
    ap.add_argument("url")
    ap.add_argument("--max-pages", type=int, default=1, help="最多抓取页数（沿“下一章”翻页），默认 1")
    ap.add_argument("--delay", type=float, default=2.0, help="同站请求间隔秒数，默认 2")
    ap.add_argument("--selector", help="正文选择器：tag / #id / .class / tag.class")
    ap.add_argument("--timeout", type=float, default=30.0)
    a = ap.parse_args()
    try:
        out = crawl(a.url, max(1, a.max_pages), max(0.5, a.delay), a.selector, a.timeout)
    except (PermissionError, RuntimeError) as e:
        sys.exit(f"[error] {e}")
    print(f"输出目录: {out}")


if __name__ == "__main__":
    main()
