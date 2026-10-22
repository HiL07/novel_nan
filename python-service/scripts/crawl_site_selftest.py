"""抓取自测：起一个本地假书城（http.server），验证全自动书目采集与单本抓取。

    .venv/Scripts/python scripts/crawl_site_selftest.py

覆盖：
1. 全自动书目采集（catalog.py）：按学习样例的书籍地址规律，首页 → 3 个分类 → 玄幻分类翻 2 页 → 书籍页
   （书名 / 作者 / 简介 / 标签）→ 目录（写入 data/site-catalog/<测试目录>/toc/）→ 抽检首章正文 → 测试报告；
   再以 scan 阶段 + knownUrls 扩充，只采集新书；
2. AI 解析的站点结构探查（_explore，不调用模型）：首页搜索框 → 用书名模拟 GET 搜索 → 结果页里有该书；
   再换一个只有登录框的首页，确认不会把登录框当搜索框；
3. 单本抓取：用采集结果里的目录地址提交任务，直到成功，取回全文并检查章节数与首尾内容。

假站点不开真实网络：靠 CRAWL_ALLOW_PRIVATE=1 放行 127.0.0.1（fetcher 默认禁止内网地址）。
"""
import os
import shutil
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# 必须在导入 app.crawler.fetcher 之前设置：模块加载时读一次
os.environ["CRAWL_ALLOW_PRIVATE"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.crawler import ai_rules, catalog, parser, rules, service  # noqa: E402
from app.crawler.fetcher import Fetcher  # noqa: E402

CATEGORIES = [("玄幻", "xuanhuan"), ("都市", "dushi"), ("科幻", "kehuan")]
BOOKS = {  # 分类 → 该分类下的书（含翻页）
    "xuanhuan": [("剑来", "jw"), ("凡人修仙", "frxx"), ("雪中悍刀行", "xzhdh")],
    "dushi": [("都市之最强狂兵", "dszq"), ("重生之金融巨头", "csjr")],
    "kehuan": [("三体", "st"), ("流浪地球", "lldq")],
}
PAGE2 = [("诡秘之主", "gmzz")]  # 玄幻分类第 2 页


def page(title: str, body: str) -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{title} - 测试书城</title>"
            f"<meta name='description' content='测试书城的简介'></head><body>{body}</body></html>")


def build_site(root: str) -> None:
    def write(rel: str, html: str) -> None:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

    nav = "".join(f"<li><a href='/cat/{slug}.html'>{name}</a></li>" for name, slug in CATEGORIES)
    search = ("<form action='/search.html' method='get'><input type='text' name='searchkey' placeholder='书名 / 作者'>"
              "<input type='hidden' name='t' value='articlename'><input type='submit' value='搜索'></form>")
    write("index.html", page("首页", f"{search}<ul class='channel-nav-list'>{nav}</ul><div>最新更新</div>"))
    login = ("<form action='/login.php' method='post'><input type='text' name='username'>"
             "<input type='password' name='password'><input type='submit' value='登录'></form>")
    write("login-only.html", page("只有登录框", login))

    def book_list(slug: str, items: list[tuple[str, str]], next_href: str | None) -> str:
        lis = "".join(f"<li><a href='/book/{b[1]}/'>{b[0]}</a></li>" for b in items)
        nxt = f"<a class='next' href='{next_href}'>下一页</a>" if next_href else ""
        return page("列表", f"<ul class='seeWell cf'>{lis}</ul>{nxt}")

    for name, slug in CATEGORIES:
        write(f"cat/{slug}.html", book_list(slug, BOOKS[slug], f"/cat/{slug}-2.html"))
        write(f"cat/{slug}-2.html", book_list(slug, PAGE2 if slug == "xuanhuan" else [], None))

    all_books = [b for books in BOOKS.values() for b in books] + PAGE2
    results = "".join(f"<li><a href='/book/{slug}/'>{name}</a> 测试作者</li>" for name, slug in all_books)
    write("search.html", page("搜索结果", f"<ul class='result'>{results}</ul>"))

    for name, slug in all_books:
        write(f"book/{slug}/index.html", page(name, (
            f"<div class='b-info'><h1>{name}</h1></div>"
            f"<a class='reader' href='/book/{slug}/toc.html'>开始阅读</a>"
            f"<div id='intro'>这是《{name}》的简介。</div>"
            f"<div class='tags'><a href='/tag/1.html'>热血</a><a href='/tag/2.html'>测试标签</a></div>"
            f"<p>状态：连载中</p>"
            f"<div class='bookDetail'><dl class='bookso'><dd> 作者：测试作者 </dd></dl></div>")))
        chs = "".join(
            f"<dd><a href='/book/{slug}/{i}.html'>第{i}章 测试章节{i}</a></dd>" for i in range(1, 4))
        write(f"book/{slug}/toc.html", page(name, f"<div id='list'><dl>{chs}</dl></div>"))
        for i in range(1, 4):
            body_text = f"{name} 第{i}章的正文内容，这一行足够长以便被识别为正文区块，而不是导航或广告。" * 6
            write(f"book/{slug}/{i}.html", page(f"第{i}章", f"<div id='content'>{body_text}</div>"))


def _wait_catalog(job, timeout: float = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        cur = catalog.get(job.jobId)
        if cur["status"] in ("succeeded", "failed", "cancelled"):
            return cur
        time.sleep(0.3)
    raise AssertionError("书目采集超时")


def main() -> int:
    root = tempfile.mkdtemp(prefix="crawl-fixture-")
    build_site(root)
    handler = partial(SimpleHTTPRequestHandler, directory=root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    print(f"假书城：{base}（{root}）")

    try:
        # ---------------- 1. 全自动书目采集 ----------------
        catalog_dir = f"site-catalog/selftest-{os.getpid()}"
        common = dict(homeUrl=base + "/", sampleUrl=base + "/book/jw/", delayMs=300, catalogDir=catalog_dir)
        res = _wait_catalog(catalog.submit(catalog.CatalogRequest(**common, phase="test", maxBooks=5, contentSamples=2)))
        rep = res["report"]
        print(f"\n站点名={res['siteName']!r} 全部分类={[c['name'] for c in res['categoriesAll']]} "
              f"规律={res['bookPattern']!r}\n报告：{rep['summary']} 问题={rep['problems']}")
        for b in res["books"]:
            print(f"  [{b['category']}] {b['bookName']} / {b['author']} / {b['chapterCount']} 章 / 标签={b['tags']} "
                  f"/ toc={b['tocUrl']} / 正文={b['contentOk']} {b['contentChars']} 字 / err={b['error'] or '-'}")
        assert res["status"] == "succeeded", f"采集失败：{res['error']}"
        assert len(res["categoriesAll"]) == 3, f"应发现 3 个分类，实际 {res['categoriesAll']}"
        assert len(res["books"]) == 5, f"maxBooks=5 应采集 5 本，实际 {len(res['books'])}"
        assert rep["verdict"] == "usable", f"规律应判定可用：{rep}"
        assert rep["counts"]["contentChecked"] == 2 and rep["counts"]["content"] == 2, f"正文抽检不对：{rep['counts']}"
        for b in res["books"]:
            assert not b["error"], f"书籍 {b['bookName']} 解析有错：{b['error']}"
            assert b["tocUrl"].endswith("/toc.html"), f"目录地址不对：{b['tocUrl']}"
            assert b["chapterCount"] == 3, f"{b['bookName']} 章节数应为 3，实际 {b['chapterCount']}"
            assert b["intro"].startswith("这是《"), f"简介不对：{b['intro']!r}"
            assert "热血" in b["tags"] and "连载中" in b["tags"], f"标签不对：{b['tags']}"
            toc_file = catalog.DATA_DIR / b["tocPath"]
            assert toc_file.is_file(), f"目录文件没写：{toc_file}"
        assert any(b["bookName"] == "诡秘之主" for b in res["books"]), "分类列表翻页没有生效"
        # 扩充：已采集的书不再重复
        known = [b["bookUrl"] for b in res["books"]]
        more = _wait_catalog(catalog.submit(catalog.CatalogRequest(**common, phase="scan", maxBooks=20,
                                                                   contentSamples=0, knownUrls=known)))
        print(f"扩充：新增 {len(more['books'])} 本：{[b['bookName'] for b in more['books']]}")
        assert more["status"] == "succeeded", more["error"]
        assert len(more["books"]) == 3, f"共 8 本、已采 5 本，应新增 3 本，实际 {len(more['books'])}"
        assert not {b["bookUrl"] for b in more["books"]} & set(known), "扩充时重复采集了已有的书"
        shutil.rmtree(catalog.DATA_DIR / catalog_dir, ignore_errors=True)
        site = {"books": res["books"]}

        # ---------------- 2. AI 解析的站点结构探查：站内搜索 ----------------
        req = ai_rules.AnalyzeRequest(url=base + "/book/jw/", delayMs=300, respectRobots=False,
                                      model={"baseUrl": "http://127.0.0.1:9/v1", "model": "unused"})
        rule = rules.resolve("", None, "127.0.0.1")[1]
        job = ai_rules.AnalyzeJob(jobId="selftest", url=req.url)
        with ai_rules._CachedFetcher(300, False) as af:
            trial = ai_rules._trial(af, req.url, rule)
            sm = ai_rules._explore(af, req, rule, trial, job)
        item = next(i for i in sm["items"] if i["key"] == "search")
        print(f"\n站内搜索：{item['status']} {item['detail']} | {item['pattern']}")
        assert item["status"] == "ok", f"站内搜索应可用：{item}"
        assert "searchkey={书名}" in item["pattern"] and "t=articlename" in item["pattern"], item["pattern"]
        assert sm["search"]["works"] and sm["search"]["field"] == "searchkey" and sm["search"]["method"] == "GET", sm["search"]
        assert sm["search"]["testKeyword"] == "剑来", sm["search"]
        with Fetcher(300, False) as f2:
            _, html = f2.get_html(base + "/login-only.html")
        assert parser.find_search_forms(html, base + "/login-only.html") == [], "登录框不应被当成搜索框"

        # ---------------- 3. 单本抓取（用采集结果里的目录地址） ----------------
        target = site["books"][0]
        job = service.submit(service.CrawlRequest(url=target["tocUrl"], delayMs=300, startIndex=1, endIndex=3))
        deadline = time.time() + 60
        while time.time() < deadline:
            cur = service.get(job.jobId)
            if cur.status in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(0.3)
        print(f"\n抓取《{target['bookName']}》→ {cur.status} {cur.message}")
        assert cur.status == "succeeded", f"抓取失败：{cur.error}"
        text = service.text_of(job.jobId)
        assert text and text.count("第") >= 3, "全文应包含 3 个章节标题"
        assert "测试章节1" in text and "测试章节3" in text, "全文缺少章节"
        assert cur.wordCount > 100, f"字数统计异常：{cur.wordCount}"
        print(f"全文 {len(text)} 字符，{cur.chapterDone} 章，{cur.wordCount} 字；"
              f"开头：{text.splitlines()[0]!r}")
        service.release(job.jobId)
    finally:
        httpd.shutdown()
        shutil.rmtree(root, ignore_errors=True)

    print("\n全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
