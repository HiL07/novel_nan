"""断点续抓自测（不联网）：本地假书城 → 抓到一半取消 → 站点「换端口」（模拟换域名 / IP）→ 带 newOrigin 继续。

    .venv/Scripts/python scripts/crawl_resume_selftest.py

断言：
1. 取消后断点里保存了已抓的章节；
2. 旧地址已失效（服务关闭）时，带 newOrigin 继续只请求剩下的章节，且不再访问目录页；
3. 结果全文章节完整，release 后断点被删除。
断点写到临时 DATA_DIR，不碰项目 data/。
"""
import os
import shutil
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

os.environ["CRAWL_ALLOW_PRIVATE"] = "1"
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="crawl-resume-data-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.crawler import checkpoint, service  # noqa: E402

CHAPTERS = 8
requested: list[str] = []


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        requested.append(self.path)
        super().do_GET()


def build(root: str) -> None:
    os.makedirs(os.path.join(root, "book"), exist_ok=True)
    links = "".join(f"<dd><a href='/book/{i}.html'>第{i}章 测试{i}</a></dd>" for i in range(1, CHAPTERS + 1))
    with open(os.path.join(root, "book", "index.html"), "w", encoding="utf-8") as f:
        f.write(f"<html><head><meta charset='utf-8'><title>续抓测试书</title></head>"
                f"<body><h1>续抓测试书</h1><div id='list'><dl>{links}</dl></div></body></html>")
    for i in range(1, CHAPTERS + 1):
        body = "<br>".join(f"第{i}章的第{n}段正文，用来测试断点续抓。" for n in range(1, 12))
        with open(os.path.join(root, "book", f"{i}.html"), "w", encoding="utf-8") as f:
            f.write(f"<html><head><meta charset='utf-8'></head><body><h1>第{i}章 测试{i}</h1>"
                    f"<div id='content'>{body}</div></body></html>")


def serve(root: str) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=root))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def wait(job_id: str, until=("succeeded", "failed", "cancelled"), timeout=120) -> service.CrawlJob:
    end = time.time() + timeout
    while time.time() < end:
        job = service.get(job_id)
        if job.status in until:
            return job
        time.sleep(0.2)
    raise AssertionError(f"任务超时：{service.get(job_id)}")


SITE_DIRS: list[str] = []


def main() -> int:
    root = tempfile.mkdtemp(prefix="crawl-resume-site-")
    SITE_DIRS.append(root)
    build(root)
    key = "selftest1"
    checkpoint.remove(key)

    old = serve(root)
    old_origin = f"http://127.0.0.1:{old.server_port}"
    req = service.CrawlRequest(url=f"{old_origin}/book/", delayMs=300, respectRobots=False, resumeKey=key)
    job = service.submit(req)
    while service.get(job.jobId).chapterDone < 3:
        time.sleep(0.1)
    service.cancel(job.jobId)
    job = wait(job.jobId)
    assert job.status == "cancelled", job
    saved = checkpoint.load(key)
    assert saved and len(saved["done"]) >= 3, saved and len(saved["done"])
    print(f"1. 取消：{job.message}；断点 {len(saved['done'])}/{len(saved['meta']['chapters'])} 章")
    old.shutdown()
    old.server_close()

    new = serve(root)
    new_origin = f"http://127.0.0.1:{new.server_port}"
    requested.clear()
    req = service.CrawlRequest(url=f"{old_origin}/book/", delayMs=300, respectRobots=False, resumeKey=key,
                               newOrigin=new_origin)
    job = wait(service.submit(req).jobId)
    assert job.status == "succeeded", (job.status, job.error)
    assert job.resumedChapters == len(saved["done"]), job.resumedChapters
    assert "/book/" not in requested, "续抓不应再访问目录页"
    assert len(requested) == CHAPTERS - len(saved["done"]), requested
    assert job.url.startswith(new_origin), job.url
    print(f"2. 换地址续抓：{job.message}；新请求 {len(requested)} 次 {requested}")

    text = service.text_of(job.jobId)
    assert text.count("的第1段正文") == CHAPTERS, text[:300]
    service.release(job.jobId)
    assert checkpoint.load(key) is None, "release 后断点应删除"
    print("3. 全文完整，断点已清理")
    new.shutdown()
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        shutil.rmtree(os.environ["DATA_DIR"], ignore_errors=True)
        for d in SITE_DIRS:
            shutil.rmtree(d, ignore_errors=True)
