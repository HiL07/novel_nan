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
    name, name_el = _detail_book_name(tree, rule)
    return {
        "bookName": name or _guess_book_name(tree),
        "author": _detail_author(tree, rule, name, name_el),
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
    # <meta name=description> 常是全站通用的站点介绍，排在页面上的简介块之后
    text = _first_text(tree, "//meta[@property='og:description']/@content") \
        or _join_text(tree, "//*[@id='intro' or contains(@class,'intro')]") \
        or _first_text(tree, "//meta[@name='description']/@content")
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


def parse_site(html: str, url: str, rule: CrawlRule, book_re=None) -> dict:
    """站点首页 → {siteName, categories: [{name, url}], fromRule}。
    book_re：已知的书籍地址规律（AI 解析 / 全自动都知道），符合它的链接是书，不会被当成分类。"""
    tree = parse_doc(html, url)
    cats = ([{"name": c["title"][:20], "url": c["url"]} for c in _rule_links(tree, rule.categoryLinks)]
            if rule.categoryLinks else _guess_categories(tree, url, book_re))
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
    name, name_el = _detail_book_name(tree, rule)
    author = _detail_author(tree, rule, name, name_el)
    category = _detail_category(tree, name, name_el)
    tags = _tags(tree, rule, {name, author})
    if category and category not in tags:
        tags = [category, *tags][:MAX_TAGS]
    return {"bookName": name, "author": author, "category": category,
            "intro": _join_text(tree, rule.intro) if rule.intro else _guess_intro(tree),
            "tags": tags, "tocUrl": toc}


# 书籍页上的书名 / 作者 / 分类：以这本书自己的页面为准。站点自己写的 og:novel:* 最可靠；没有时，候选（规则 XPath、
# 每个 h1 / h2）要和 <title> 对得上——<title> 第一段几乎总是书名（「剑来最新章节_剑来全文阅读_某某书城」），
# 页头的站名 h1、侧栏推荐书的标题、别处的「作者：」都排除掉。
_TITLE_NOISE = re.compile(r"(最新章节.*|全文阅读.*|全文免费阅读.*|无弹窗.*|章节目录.*|目录.*|小说.*|全集.*|txt.*)$", re.IGNORECASE)
_BREADCRUMB_HINT = re.compile(r"path|bread|crumb|location|weizhi", re.IGNORECASE)
_BREADCRUMB_SEP = re.compile(r"当前位置|您的位置|>|»|›|→")
_AUTHOR_RE = re.compile(r"作\s*者\s*[:：]\s*([^\s|/，,<>：:]{1,30})")


def _norm(text: str) -> str:
    return re.sub(r"[\s《》「」【】]", "", text or "")


def _title_parts(tree) -> tuple[str, str]:
    """<title> / og:title → (第一段去掉「最新章节 / 全文阅读」等后缀, 最后一段 = 多半是站名)"""
    title = _first_text(tree, "//meta[@property='og:title']/@content") or _first_text(tree, "//title")
    segs = [s for s in re.split(r"\s*[-|—｜_]\s*", title) if s.strip()]
    if not segs:
        return "", ""
    first = _TITLE_NOISE.sub("", _clean_inline(segs[0])).strip("《》 ")
    return first, (_clean_inline(segs[-1]) if len(segs) > 1 else "")


# 有的站把搜索词拼进书名：「港综世界大枭雄小说全文阅读顶点」「我只会拍烂片啊最新章节无弹窗免费阅读」。
# 只去掉含「阅读 / 下载 / 最新章节 / 无弹窗」的组合尾巴，正常书名（哪怕以「小说」结尾）不动。
_SEO_TAIL = re.compile(
    r"(?:最新章节.*|无弹窗.*|(?:小说)?(?:全文|全本|全集|txt|TXT)?(?:免费)?(?:全文)?(?:在线)?(?:阅读|下载)(?:顶点|笔趣阁|全文|免费)*)$")


def clean_book_name(name: str) -> str:
    cleaned = _SEO_TAIL.sub("", name or "").strip(" 《》_-|")
    return cleaned if len(cleaned) >= 2 else (name or "")


def _detail_book_name(tree, rule: CrawlRule) -> tuple[str, Optional[object]]:
    """→ (书名, 书名所在元素或 None)，书名去掉搜索词尾巴（clean_book_name）。"""
    name, el = _detail_book_name_raw(tree, rule)
    return clean_book_name(name), el


def _detail_book_name_raw(tree, rule: CrawlRule) -> tuple[str, Optional[object]]:
    """→ (书名, 书名所在元素或 None)。元素用来在它附近找作者 / 分类。"""
    meta = _first_text(tree, "//meta[@property='og:novel:book_name']/@content")
    first, site = _title_parts(tree)
    cands: list[tuple[str, Optional[object]]] = []
    if rule.bookName:
        for node in _xpath(tree, rule.bookName)[:3]:
            el = node if isinstance(node, etree._Element) else (node.getparent() if hasattr(node, "getparent") else None)
            text = _clean_inline(node.text_content() if isinstance(node, etree._Element) else str(node))
            if text:
                cands.append((text[:80], el))
    for h in tree.xpath("//h1|//h2")[:12]:
        text = _clean_inline(h.text_content())
        if 1 <= len(text) <= 60:
            cands.append((text, h))

    def el_for(name: str):
        return next((el for text, el in cands if _norm(text) == _norm(name) and el is not None), None)

    if meta:
        return meta[:80], el_for(meta)
    nf, ns = _norm(first), _norm(site)
    # 与 <title> 第一段对得上的（第一段里包含它，或它包含第一段），且不是站名；取最长的
    good = [(t, el) for t, el in cands if _norm(t) and _norm(t) != ns and nf and (_norm(t) in nf or nf in _norm(t))]
    if good:
        return max(good, key=lambda c: len(_norm(c[0])))
    if first and _norm(first) != ns:
        return first[:80], el_for(first)
    rest = [(t, el) for t, el in cands if _norm(t) != ns]
    return rest[0] if rest else ("", None)


def _lines(el) -> str:
    """元素文字，元素边界处换行：<p>作者：张三</p><p>类别：玄幻</p> 不会粘成「张三类别」。"""
    return "\n".join(t.strip() for t in el.itertext() if t.strip())


def _near_text(el, levels: int = 3) -> list[str]:
    """元素自身及往上几层祖先的文字（由近到远），用来在书名附近找作者 / 分类。"""
    out = []
    while el is not None and levels >= 0 and isinstance(el.tag, str) and el.tag not in ("body", "html"):
        out.append(_lines(el))
        el = el.getparent()
        levels -= 1
    return out


def _detail_author(tree, rule: CrawlRule, name: str, name_el) -> str:
    """og:novel:author → 书名元素所在块 → 书名元素之后的文字（书籍信息一般紧跟在书名后面）→ 规则 XPath
    → <body> 里书名之后第一个「作者：」。页头 / 侧栏里更早出现的「作者：」不会被取到。"""
    meta = _first_text(tree, "//meta[@property='og:novel:author']/@content")
    if meta:
        return meta[:50]
    if name_el is not None:
        for block in _near_text(name_el, levels=1):
            m = _AUTHOR_RE.search(block)
            if m:
                return m.group(1)
        after = "\n".join(t.strip() for t in name_el.xpath("following::text()") if t.strip())[:1500]
        m = _AUTHOR_RE.search(after)
        if m:
            return m.group(1)
    if rule.author:
        text = _first_text(tree, rule.author)
        if text:
            return re.sub(r"^作\s*者\s*[:：]\s*", "", text)[:50]
    body = tree.find("body")
    full = _lines(body if body is not None else tree)
    positions = [m.end() for m in re.finditer(re.escape(name), full)] if name else []
    m = _AUTHOR_RE.search(full, positions[-1] if len(positions) > 1 else (positions[0] if positions else 0))
    return m.group(1) if m else ""


def _detail_category(tree, name: str, name_el) -> str:
    """这本书自己的分类：og:novel:category → 面包屑（当前位置：首页 > 玄幻小说 > 书名）→ 书名附近的「类别 / 分类：」。"""
    meta = _first_text(tree, "//meta[@property='og:novel:category']/@content")
    if meta:
        return _short_category(meta)
    # 面包屑：class / id 像 path / bread / crumb / location，或自身文字里有「当前位置 / 您的位置」（笔趣阁模板的 con_top）
    crumbs = [el for el in tree.xpath("//*[@class or @id]") if el.tag not in ("html", "body")
              and _BREADCRUMB_HINT.search(f"{el.get('class', '')} {el.get('id', '')}")]
    crumbs += [el for el in tree.xpath("//*[contains(text(),'当前位置') or contains(text(),'您的位置')]") if el not in crumbs]
    for el in crumbs:
        if not _BREADCRUMB_SEP.search(el.text_content()):   # 面包屑都有「当前位置」或 > 分隔，导航栏没有
            continue
        links = [_clean_inline(a.text_content()) for a in el.iter("a")]
        links = [t for t in links if t and t not in ("首页", "主页", "网站首页") and _norm(t) != _norm(name)
                 and len(t) <= 12]
        if links:
            return _short_category(links[-1])
    for block in _near_text(name_el):
        m = _TAG_KV.search(block)
        if m:
            return _short_category(m.group(1))
    return ""


def _short_category(text: str) -> str:
    """「玄幻小说」→「玄幻」，与分类导航 / 标签口径一致。"""
    text = _clean_inline(text).strip("[]【】")
    return text[:-2] if text.endswith("小说") and len(text) > 3 else text[:12]


# 详情页上的「标签：玄幻 热血」「类别：都市」「状态：连载中」这类文字
_TAG_LINE = re.compile(r"(?:标\s*签|关键词|tags?)\s*[:：]\s*([^\n]{1,80})", re.IGNORECASE)
_TAG_KV = re.compile(r"(?:类\s*别|分\s*类|类\s*型|题\s*材|频\s*道)\s*[:：]\s*([^\s|/，,<>：:]{1,10})")
_TAG_STATUS = re.compile(r"状\s*态\s*[:：]\s*(连载中?|已?完结|完本|已完本)")
_TAG_SPLIT = re.compile(r"[\s,，、|/;；#]+")
_TAG_HINT = re.compile(r"tag|label|keyword|biaoqian", re.IGNORECASE)
MAX_TAGS = 12


def _tags(tree, rule: CrawlRule, exclude: set) -> list[str]:
    """标签：规则 XPath；否则 og:novel:category / status、class 像 tag 的块里的短文字、「标签 / 类别 / 状态：」文字。"""
    out: list[str] = []

    def add(text: str) -> None:
        text = _clean_inline(text).strip("#[]【】()（）")
        if 1 <= len(text) <= 10 and text not in out and text not in exclude and text not in _NON_LINK_TEXTS \
                and not _PAGE_TEXT.match(text) and not CHAPTER_TITLE_RE.search(text):
            out.append(text)

    if rule.tags:
        for node in _xpath(tree, rule.tags):
            text = node.text_content() if isinstance(node, etree._Element) else str(node)
            for part in _TAG_SPLIT.split(text):
                add(part)
        return out[:MAX_TAGS]
    for prop in ("og:novel:category", "og:novel:status", "og:novel:tags", "og:novel:keywords"):
        for part in _TAG_SPLIT.split(_first_text(tree, f"//meta[@property='{prop}']/@content")):
            add(part)
    for el in tree.xpath("//*[@class or @id]"):
        if not _TAG_HINT.search(f"{el.get('class', '')} {el.get('id', '')}") or el.tag in ("html", "body"):
            continue
        kids = [k for k in el.iter("a", "span", "em", "li", "b") if k is not el]
        for k in kids[:20]:
            add(k.text_content())
        if len(out) >= MAX_TAGS:
            break
    text = tree.text_content()
    for m in _TAG_LINE.finditer(text):
        for part in _TAG_SPLIT.split(m.group(1))[:8]:
            add(part)
    for m in _TAG_KV.finditer(text):
        add(m.group(1))
    m = _TAG_STATUS.search(text)
    if m:
        add(m.group(1))
    return out[:MAX_TAGS]


def parse_next(html: str, url: str, xpath: str) -> Optional[str]:
    """分类列表页 / 目录页的「下一页」地址（规则为空时按链接文字找）。"""
    tree = parse_doc(html, url)
    return _rule_href(tree, xpath) if xpath else _guess_next(tree, url, same_stem=False)


# 分类名里常见的字眼（玄幻奇幻 / 武侠仙侠 / 女频言情 / 现代都市 / 历史军事 …）
CATEGORY_WORDS = re.compile(r"玄幻|奇幻|武侠|仙侠|修真|都市|言情|女频|男频|历史|军事|科幻|灵异|悬疑|推理|游戏|竞技|网游|"
                            r"体育|穿越|重生|架空|同人|耽美|青春|校园|恐怖|二次元|轻小说|其他|其它|完本|全本|连载|排行")


def _guess_categories(tree, url: str, book_re=None) -> list[dict]:
    """分类链接：同域、文字很短、成组出现的链接（导航条 / 分类栏），排除书籍链接，再给每组打分：
    文字像分类名（CATEGORY_WORDS）的一个加 3 分、地址有共同的目录前缀（如都在 /class/ 下）的整组翻倍。
    以前只取「最多的一组」，首页的推荐书单（十几本书名也很短）会被误当成分类。"""
    cands = [a for a in tree.iter("a") if _candidate(a, url, 12)
             and not (book_re is not None and book_re.fullmatch(_path_and_query(a.get("href"))))]
    if not cands:
        return []
    groups: dict = {}
    for a in cands:
        groups.setdefault(_container(a), []).append(a)

    def score(links: list) -> float:
        words = sum(1 for a in links if CATEGORY_WORDS.search(_clean_inline(a.text_content())))
        firsts = Counter((urlsplit(a.get("href")).path.strip("/").split("/") or [""])[0] for a in links)
        prefix, n = firsts.most_common(1)[0]
        shared = bool(prefix) and n * 10 >= len(links) * 6 and not prefix[0].isdigit()
        return (len(links) + 3 * words) * (2 if shared else 1)

    ranked = sorted((g for g in groups.values() if len(g) >= 3), key=score, reverse=True)
    if not ranked:
        return []
    return [{"name": _clean_inline(a.text_content())[:20], "url": a.get("href")} for a in ranked[0]]


def _path_and_query(href: str) -> str:
    parts = urlsplit(href or "")
    return parts.path + (f"?{parts.query}" if parts.query else "")


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


# ---------------------------------------------------------------- 站内搜索框

_SEARCH_HINT = re.compile(r"search|so(?:u)?|query|keyword|key|wd|kw|q|searchkey|搜索|搜书|查找|书名|作者", re.IGNORECASE)
_TEXT_INPUT_TYPES = {"", "text", "search"}
_PAGE_CHARSET = re.compile(r"""<meta[^>]+charset\s*=\s*["']?\s*([\w-]+)""", re.IGNORECASE)


def find_search_forms(html: str, url: str) -> list[dict]:
    """页面上的搜索表单 → [{action, method, field, params, charset, score, label}]，最像搜索的在前。

    只认真正的 <form>：里面有文字输入框（type 为空 / text / search）；action / 输入框名 / 占位文字 / 按钮像「搜索」的加分。
    params = 其余要一起提交的字段（hidden、select 的默认值、有 name 的提交按钮），模拟搜索时原样带上。
    搜索框由脚本生成（没有 <form>）的站点这里找不到。"""
    tree = parse_doc(html, url)
    m = _PAGE_CHARSET.search(html[:4096])
    page_charset = m.group(1).lower() if m else ""
    out = []
    for form in tree.iter("form"):
        inputs = [i for i in form.iter("input") if i.get("name")]
        texts = [i for i in inputs if (i.get("type") or "").lower() in _TEXT_INPUT_TYPES]
        if not texts:
            continue
        # 有多个文字框时（如 用户名 + 密码 登录框里的用户名）挑最像搜索的
        field = max(texts, key=lambda i: bool(_SEARCH_HINT.search(f"{i.get('name')} {i.get('placeholder', '')} {i.get('id', '')}")))
        if any((i.get("type") or "").lower() == "password" for i in form.iter("input")):
            continue   # 登录框
        action = form.get("action") or url
        if not _usable_href(action):
            continue
        params: dict[str, str] = {}
        for i in inputs:
            t = (i.get("type") or "").lower()
            if i is field or t in ("checkbox", "radio", "file", "image", "reset", "button"):
                continue
            if t == "submit" and not i.get("value"):
                continue
            params[i.get("name")] = i.get("value") or ""
        for sel in form.iter("select"):
            if sel.get("name"):
                opt = next((o for o in sel.iter("option") if o.get("selected") is not None), None) \
                    or next(iter(sel.iter("option")), None)
                params[sel.get("name")] = (opt.get("value") if opt is not None and opt.get("value") is not None
                                           else _clean_inline(opt.text_content()) if opt is not None else "")
        for btn in form.iter("button"):
            if btn.get("name") and (btn.get("type") or "submit").lower() == "submit":
                params[btn.get("name")] = btn.get("value") or ""
        label = " ".join(filter(None, [field.get("placeholder"), _clean_inline(form.text_content())[:30]]))
        score = 0
        score += 3 if _SEARCH_HINT.search(action) else 0
        score += 2 if _SEARCH_HINT.search(f"{field.get('name')} {field.get('placeholder', '')}") else 0
        score += 1 if re.search(r"搜索|搜书|search", _clean_inline(form.text_content()) + " ".join(
            b.get("value", "") for b in form.iter("input")), re.IGNORECASE) else 0
        out.append({"action": action.split("#")[0], "method": (form.get("method") or "get").upper(),
                    "field": field.get("name"), "params": params,
                    "charset": (form.get("accept-charset") or page_charset).split(",")[0].strip().lower(),
                    "score": score, "label": label[:60]})
    out.sort(key=lambda f: -f["score"])
    return out


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
