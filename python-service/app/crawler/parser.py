"""HTML 解析：目录页（书名 / 作者 / 简介 / 章节链接）与章节页（正文）。规则字段为空时用启发式。"""
import re
from collections import Counter
from typing import Optional
from urllib.parse import urlsplit

import lxml.html
from lxml import etree

from .rules import DEFAULT_REMOVE_PATTERNS, CrawlRule

# 章节链接文字（与 text_loader.CHAPTER_RE 同口径，但不要求独占一行）
CHAPTER_TITLE_RE = re.compile(
    r"第[零〇一二三四五六七八九十百千万两\d]+[章回节卷集部篇]|chapter\s*\d+|^\s*\d{1,4}[.、．\s]|序章|楔子|引子|尾声|番外|后记",
    re.IGNORECASE,
)
NAV_TEXTS = {"上一页", "下一页", "上一章", "下一章", "返回目录", "目录", "首页", "末页", "尾页", "加入书架", "加入书签"}
_CONTENT_HINT = re.compile(r"content|chapter|txt|booktext|read|article|nr1|zhangjie", re.IGNORECASE)
# 找正文容器时向上跳过的「行内 / 列表项」标签
_SKIP_UP = {"li", "dd", "dt", "span", "p", "td", "tr", "tbody", "strong", "b", "font", "em", "i"}
_STRIP_TAGS = ["script", "style", "noscript", "iframe", "form", "select", "button", "header", "footer", "nav", "ins"]
_BLOCK_TAGS = {"p", "div", "br", "h1", "h2", "h3", "h4", "li", "section", "article"}
_XML_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.IGNORECASE)
_SPACES = "　\xa0 \t\r"


def parse_doc(html: str, url: str):
    # 带 <?xml encoding?> 声明的 str 会被 lxml 拒绝，先去掉
    tree = lxml.html.document_fromstring(_XML_DECL.sub("", html) or "<html></html>")
    tree.make_links_absolute(url, resolve_base_href=True)
    return tree


# ---------------------------------------------------------------- 目录页

def parse_toc(html: str, url: str, rule: CrawlRule) -> dict:
    """→ {bookName, author, intro, chapters: [{title, url}], nextUrl}"""
    tree = parse_doc(html, url)
    chapters = _rule_links(tree, rule.chapterLinks) if rule.chapterLinks else _guess_chapter_links(tree, url)
    return {
        "bookName": _first_text(tree, rule.bookName) or _guess_book_name(tree),
        "author": _first_text(tree, rule.author) or _guess_author(tree),
        "intro": _join_text(tree, rule.intro) if rule.intro else _guess_intro(tree),
        "chapters": dedupe_keep_last(chapters, url),
        "nextUrl": _rule_href(tree, rule.tocNext) if rule.tocNext else _guess_next(tree, url, same_stem=False),
    }


def _rule_links(tree, xp: str) -> list[dict]:
    out = []
    for el in _xpath(tree, xp):
        if isinstance(el, etree._Element):
            href = el.get("href")
            if href:
                out.append({"title": _clean_inline(el.text_content()), "url": href})
    return out


def _guess_chapter_links(tree, toc_url: str) -> list[dict]:
    """找「第X章」类链接集中的容器（目录常按卷 / 上下部拆成多块，章节数不少于最多那块一半的都算）；
    容器内章节链接占多数时取容器内全部链接（包括「作品相关」等），否则只取匹配的。结果按页面顺序。"""
    links = [a for a in tree.iter("a") if _usable_href(a.get("href"))]
    matched = [a for a in links if _looks_like_chapter(a)]
    if not matched:
        return []
    containers = Counter(_container(a) for a in matched)
    top = containers.most_common(1)[0][1]
    # 匹配数太少（如侧栏「最新章节」）时容器不可靠，直接用全页匹配链接
    if top < 3:
        chosen = matched
    else:
        keep = {c for c, n in containers.items() if n * 2 >= top and n >= 3}
        chosen = []
        for c in keep:
            inside = [a for a in c.iter("a") if _usable_href(a.get("href"))
                      and _clean_inline(a.text_content()) not in NAV_TEXTS]
            chosen += inside if containers[c] * 2 >= len(inside) else [a for a in matched if _container(a) is c]
        order = {a: i for i, a in enumerate(links)}
        chosen = sorted(set(chosen), key=lambda a: order.get(a, 0))
    return [{"title": _clean_inline(a.text_content()), "url": a.get("href")} for a in chosen
            if _clean_inline(a.text_content())]


def _looks_like_chapter(a) -> bool:
    text = _clean_inline(a.text_content())
    return 0 < len(text) <= 60 and CHAPTER_TITLE_RE.search(text) is not None


def _container(el):
    p = el.getparent()
    while p is not None and p.tag in _SKIP_UP and p.getparent() is not None:
        p = p.getparent()
    return p


def dedupe_keep_last(chapters: list[dict], toc_url: str) -> list[dict]:
    """目录顶部常有「最新章节」重复块：同一地址只保留最后一次出现的位置，顺序即正文目录顺序。"""
    last: dict[str, int] = {}
    for i, ch in enumerate(chapters):
        if _same_page(ch["url"], toc_url):
            continue
        last[ch["url"]] = i
    return [chapters[i] for i in sorted(last.values())]


def _guess_book_name(tree) -> str:
    for xp in ("//meta[@property='og:novel:book_name']/@content", "//h1"):
        text = _first_text(tree, xp)
        if text:
            return text[:80]
    # og:title / <title> 常带站名后缀（「西遊記 - 维基文库，自由的图书馆」）
    title = _first_text(tree, "//meta[@property='og:title']/@content") or _first_text(tree, "//title")
    return re.split(r"\s+[-|—｜]\s+|[_|｜]", title)[0].strip()[:80] if title else ""


def _guess_author(tree) -> str:
    text = _first_text(tree, "//meta[@property='og:novel:author']/@content")
    if text:
        return text[:50]
    m = re.search(r"作\s*者\s*[:：]\s*([^\s|/，,<]{1,30})", tree.text_content())
    return m.group(1) if m else ""


def _guess_intro(tree) -> str:
    text = _first_text(tree, "//meta[@property='og:description']/@content") \
        or _first_text(tree, "//meta[@name='description']/@content")
    if not text:
        text = _join_text(tree, "//*[@id='intro' or contains(@class,'intro')]")
    return text[:2000]


# ---------------------------------------------------------------- 章节页

def parse_content(html: str, url: str, rule: CrawlRule) -> tuple[str, Optional[str]]:
    """→ (正文纯文本（按行）, 本章下一页地址或 None)"""
    tree = parse_doc(html, url)
    next_url = _rule_href(tree, rule.contentNext) if rule.contentNext else _guess_next(tree, url, same_stem=True)
    for bad in tree.xpath("|".join(f"//{t}" for t in _STRIP_TAGS)):
        bad.drop_tree()
    if rule.content:
        nodes = _xpath(tree, rule.content)
        parts = [_block_text(n) if isinstance(n, etree._Element) else str(n) for n in nodes]
        raw = "\n".join(parts)
    else:
        el = _guess_content_el(tree)
        raw = _block_text(el) if el is not None else ""
    return clean_lines(raw, rule.removePatterns), next_url


def _guess_content_el(tree):
    """直接文本（自身文字 + 子元素尾随文字 + 直接 <p> 子元素文字）最多的块，类名像正文的加权。"""
    best, best_score = None, 0.0
    for el in tree.iter("div", "article", "section", "td", "dd", "pre"):
        score = len((el.text or "").strip())
        for child in el:
            if not isinstance(child.tag, str):
                continue
            score += len((child.tail or "").strip())
            if child.tag == "p":
                score += len(child.text_content().strip())
        if _CONTENT_HINT.search(f"{el.get('id', '')} {el.get('class', '')}"):
            score *= 1.5
        if score > best_score:
            best, best_score = el, score
    return best


def _block_text(el) -> str:
    """元素文本：<br> 与块级标签处换行。"""
    for node in el.iter():
        if isinstance(node.tag, str) and node.tag in _BLOCK_TAGS and node is not el:
            node.tail = "\n" + (node.tail or "")
            if node.tag != "br":
                node.text = "\n" + (node.text or "")
    return el.text_content()


def clean_lines(raw: str, extra_patterns: list[str]) -> str:
    """逐行去首尾空白（含全角空格 / &nbsp;）、去空行、去广告行。默认规则只删短行（≤80 字），避免误删正文。"""
    defaults = [re.compile(p, re.IGNORECASE) for p in DEFAULT_REMOVE_PATTERNS]
    extras = [re.compile(p) for p in extra_patterns]
    out = []
    for line in raw.splitlines():
        line = line.strip(_SPACES)
        if not line:
            continue
        if any(p.search(line) for p in extras):
            continue
        if len(line) <= 80 and any(p.search(line) for p in defaults):
            continue
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------- 整站发现（copybook 式：分类 → 列表翻页 → 书籍 → 目录）

# 分类 / 书籍链接里要排除的导航文字
_NON_LINK_TEXTS = NAV_TEXTS | {
    "更多", "全部", "排行榜", "排行", "书架", "登录", "注册", "客户端", "下载APP", "手机版",
    "帮助", "完本", "全本", "搜索", "设为首页", "加入收藏", "充值", "投稿", "反馈",
}
_TOC_TEXT = re.compile(r"开始阅读|点击阅读|章节目录|全部章节|查看目录|目录|阅读|start\s*reading", re.IGNORECASE)
_PAGE_TEXT = re.compile(r"^(?:上一页|下一页|首页|末页|尾页|\d+)$")


def parse_site(html: str, url: str, rule: CrawlRule) -> dict:
    """站点首页 → {siteName, categories: [{name, url}], fromRule}。"""
    tree = parse_doc(html, url)
    cats = ([{"name": c["title"][:20], "url": c["url"]} for c in _rule_links(tree, rule.categoryLinks)]
            if rule.categoryLinks else _guess_categories(tree, url))
    return {"siteName": _guess_site_name(tree), "categories": _dedupe_dicts(cats),
            "fromRule": bool(rule.categoryLinks)}


def parse_book_links(html: str, url: str, rule: CrawlRule) -> list[dict]:
    """分类列表页 → [{title, url}]（书籍链接，按页面顺序）。"""
    tree = parse_doc(html, url)
    links = ([{"title": lk["title"], "url": lk["url"]} for lk in _rule_links(tree, rule.bookLinks)]
             if rule.bookLinks else _guess_book_links(tree, url))
    return _dedupe_dicts([lk for lk in links if lk["url"]])


def parse_book_detail(html: str, url: str, rule: CrawlRule) -> dict:
    """书籍详情页 → {bookName, author, intro, tocUrl}。详情页本身就是目录页时 tocUrl = url。"""
    tree = parse_doc(html, url)
    toc = (_rule_href(tree, rule.tocLink) if rule.tocLink else _guess_toc_link(tree, url)) or ""
    if not toc and _has_chapters(tree, url):
        toc = url
    return {"bookName": _first_text(tree, rule.bookName) or _guess_book_name(tree),
            "author": _first_text(tree, rule.author) or _guess_author(tree),
            "intro": _join_text(tree, rule.intro) if rule.intro else _guess_intro(tree),
            "tocUrl": toc}


def parse_next(html: str, url: str, xpath: str) -> Optional[str]:
    """分类列表页 / 目录页的「下一页」地址（规则为空时按链接文字找）。"""
    tree = parse_doc(html, url)
    return _rule_href(tree, xpath) if xpath else _guess_next(tree, url, same_stem=False)


def _guess_categories(tree, url: str) -> list[dict]:
    """分类链接：文字很短、同域、成组出现的链接里取最多的那一组（导航条 / 分类栏）。"""
    cands = [a for a in tree.iter("a") if _candidate(a, url, 12)]
    if not cands:
        return []
    groups = Counter(_container(a) for a in cands)
    best, n = groups.most_common(1)[0]
    if n < 3:
        return []
    return [{"name": _clean_inline(a.text_content())[:20], "url": a.get("href")}
            for a in cands if _container(a) is best]


def _guess_book_links(tree, url: str) -> list[dict]:
    """书籍链接：同域、非章节、非分页、文字不长的链接里取最多的那一组容器。

    列表页每页通常有十几本，所以「最多的一组」很可靠；但当页只有 1~2 本（末页 / 稀疏列表）时
    容器判断不可靠，退回全部候选链接，宁可多发现也不漏书。
    """
    cands = [a for a in tree.iter("a") if _candidate(a, url, 40)]
    if not cands:
        return []
    groups = Counter(_container(a) for a in cands)
    best, n = groups.most_common(1)[0]
    chosen = cands if n < 2 else [a for a in cands if _container(a) is best]
    return [{"title": _clean_inline(a.text_content())[:60], "url": a.get("href")} for a in chosen]


def _candidate(a, url: str, max_text: int) -> bool:
    """可作为「分类 / 书籍」链接的 <a>：同域、不是当前页、不是导航文字、不是章节链接。"""
    href = a.get("href")
    if not _usable_href(href) or not _same_host(href, url) or _same_page(href, url):
        return False
    text = _clean_inline(a.text_content())
    if not (1 <= len(text) <= max_text) or text in _NON_LINK_TEXTS or _PAGE_TEXT.match(text):
        return False
    return not _looks_like_chapter(a)


def _guess_toc_link(tree, url: str) -> Optional[str]:
    """书籍详情页 → 目录页：「开始阅读 / 全部章节 / 目录」这类链接文字。"""
    for a in tree.iter("a"):
        href = a.get("href")
        if not _usable_href(href) or not _same_host(href, url) or _same_page(href, url):
            continue
        if _TOC_TEXT.search(_clean_inline(a.text_content())):
            return href
    return None


def _has_chapters(tree, url: str) -> bool:
    """详情页里直接就有章节列表（很多站点详情页就是目录页）。"""
    return len(_guess_chapter_links(tree, url)) >= 3


def _guess_site_name(tree) -> str:
    title = _first_text(tree, "//title")
    return re.split(r"\s+[-|—｜_]\s*|[_|｜]", title)[0].strip()[:60] if title else ""


def _same_host(href: str, url: str) -> bool:
    return urlsplit(href).hostname == urlsplit(url).hostname


def _dedupe_dicts(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        key = it.get("url")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


# ---------------------------------------------------------------- 工具

def _xpath(tree, xp: str) -> list:
    try:
        res = tree.xpath(xp)
    except etree.XPathError as e:
        raise ValueError(f"XPath 无效：{xp}（{e}）")
    return res if isinstance(res, list) else [res]


def _first_text(tree, xp: str) -> str:
    if not xp:
        return ""
    for node in _xpath(tree, xp):
        text = _clean_inline(node.text_content() if isinstance(node, etree._Element) else str(node))
        if text:
            return text
    return ""


def _join_text(tree, xp: str) -> str:
    parts = [n.text_content() if isinstance(n, etree._Element) else str(n) for n in _xpath(tree, xp)]
    return clean_lines("\n".join(parts), [])


def _rule_href(tree, xp: str) -> Optional[str]:
    for node in _xpath(tree, xp):
        href = node.get("href") if isinstance(node, etree._Element) else str(node)
        if _usable_href(href):
            return href.strip()
    return None


def _guess_next(tree, url: str, same_stem: bool) -> Optional[str]:
    """「下一页」链接。same_stem=True（章节内分页）时只认 123.html → 123_2.html 这类同一章的分页地址，
    以免把「下一章」当成本章的下一页。"""
    for a in tree.iter("a"):
        href = a.get("href")
        if not _usable_href(href) or _same_page(href, url):
            continue
        if _clean_inline(a.text_content()).rstrip(">》→ ") not in ("下一页", "下页", "下一頁"):
            continue
        if not same_stem or _is_sub_page(url, href):
            return href
    return None


def _is_sub_page(url: str, href: str) -> bool:
    cur, nxt = urlsplit(url), urlsplit(href)
    if cur.netloc != nxt.netloc:
        return False
    stem = re.sub(r"(?:[_-]\d+)?\.\w+$", "", cur.path)
    rest = nxt.path[len(stem):] if nxt.path.startswith(stem) else None
    return rest is not None and re.fullmatch(r"[_-]\d+(?:\.\w+)?", rest) is not None


def _usable_href(href: Optional[str]) -> bool:
    return bool(href) and href.strip().lower().startswith(("http://", "https://"))


def _same_page(a: str, b: str) -> bool:
    return a.split("#")[0].rstrip("/") == b.split("#")[0].rstrip("/")


def _clean_inline(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("　", " ").replace("\xa0", " ")).strip()
