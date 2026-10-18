"""抓取自测：起一个本地假书城（http.server），验证两种采集模式。

    .venv/Scripts/python scripts/crawl_site_selftest.py

覆盖：
1. 整站发现（copybook 式）：首页 → 3 个分类 → 玄幻分类翻 2 页 → 书籍详情 → 目录，返回可勾选清单；
2. 单本抓取：用发现结果里的目录地址提交任务，直到成功，取回全文并检查章节数与首尾内容。

假站点不开真实网络：靠 CRAWL_ALLOW_PRIVATE=1 放行 127.0.0.1（fetcher 默认禁止内网地址）。
"""
import os
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# 必须在导入 app.crawler.fetcher 之前设置：模块加载时读一次
os.environ["CRAWL_ALLOW_PRIVATE"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.crawler import service  # noqa: E402

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
    write("index.html", page("首页", f"<ul class='channel-nav-list'>{nav}</ul><div>最新更新</div>"))

    def book_list(slug: str, items: list[tuple[str, str]], next_href: str | None) -> str:
        lis = "".join(f"<li><a href='/book/{b[1]}/'>{b[0]}</a></li>" for b in items)
        nxt = f"<a class='next' href='{next_href}'>下一页</a>" if next_href else ""
        return page("列表", f"<ul class='seeWell cf'>{lis}</ul>{nxt}")

    for name, slug in CATEGORIES:
        write(f"cat/{slug}.html", book_list(slug, BOOKS[slug], f"/cat/{slug}-2.html"))
        write(f"cat/{slug}-2.html", book_list(slug, PAGE2 if slug == "xuanhuan" else [], None))

    for name, slug in [b for books in BOOKS.values() for b in books] + PAGE2:
        write(f"book/{slug}/index.html", page(name, (
            f"<div class='b-info'><h1>{name}</h1></div>"
            f"<a class='reader' href='/book/{slug}/toc.html'>开始阅读</a>"
            f"<div id='intro'>这是《{name}》的简介。</div>"
            f"<div class='bookDetail'><dl class='bookso'><dd> 作者：测试作者 </dd></dl></div>")))
        chs = "".join(
            f"<dd><a href='/book/{slug}/{i}.html'>第{i}章 测试章节{i}</a></dd>" for i in range(1, 4))
        write(f"book/{slug}/toc.html", page(name, f"<div id='list'><dl>{chs}</dl></div>"))
        for i in range(1, 4):
            body_text = f"{name} 第{i}章的正文内容，这一行足够长以便被识别为正文区块，而不是导航或广告。" * 2
            write(f"book/{slug}/{i}.html", page(f"第{i}章", f"<div id='content'>{body_text}</div>"))


def main() -> int:
    root = tempfile.mkdtemp(prefix="crawl-fixture-")
    build_site(root)
    handler = partial(SimpleHTTPRequestHandler, directory=root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    print(f"假书城：{base}（{root}）")

    try:
        # ---------------- 1. 整站发现 ----------------
        site = service.discover(service.SiteOptions(url=base + "/", delayMs=300, maxBooks=5, verify=True))
        print(f"\n站点名={site['siteName']!r} 全部分类={[c['name'] for c in site['categoriesAll']]} "
              f"已访问={[c['name'] for c in site['categories']]} 书籍={site['bookCount']} 截断={site['truncated']}")
        for b in site["books"]:
            print(f"  [{b['category']}] {b['bookName']} / {b['author']} / {b['chapterCount']} 章 "
                  f"/ toc={b['tocUrl']} / err={b['error'] or '-'}")
        assert len(site["categoriesAll"]) == 3, f"应发现 3 个分类，实际 {site['categoriesAll']}"
        assert site["bookCount"] == 5, f"maxBooks=5 应发现 5 本，实际 {site['bookCount']}"
        assert site["truncated"] is True, "达到 maxBooks 应标记 truncated"
        assert any(b["category"] == "玄幻" for b in site["books"]), "玄幻分类应有书"
        for b in site["books"]:
            assert not b["error"], f"书籍 {b['bookName']} 解析有错：{b['error']}"
            assert b["tocUrl"].endswith("/toc.html"), f"目录地址不对：{b['tocUrl']}"
            assert b["chapterCount"] == 3, f"{b['bookName']} 章节数应为 3，实际 {b['chapterCount']}"
        # copybook 的关键行为：列表翻页（玄幻第 2 页的《诡秘之主》在 maxBooks 内应被发现）
        assert any(b["bookName"] == "诡秘之主" for b in site["books"]), "分类列表翻页没有生效"

        # ---------------- 2. 单本抓取（用发现结果里的目录地址） ----------------
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

    print("\n全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
