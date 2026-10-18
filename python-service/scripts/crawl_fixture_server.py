"""把本地假书城跑起来，用于在「小说抓取」页面上复现**整站模式**（全程不访问任何真实站点）。

    .venv/Scripts/python scripts/crawl_fixture_server.py [port]     # 默认 8899

复现步骤：
1. 用放行内网的模式启动 AI 服务（fetcher 默认拒绝 127.0.0.1）：
       set CRAWL_ALLOW_PRIVATE=1 && .venv/Scripts/python -m uvicorn app.main:app --port 8021
   （测试实例再加 JAVA_BACKEND_URL=http://localhost:8012、--port 8011）
2. 打开「小说抓取」页面 → 切到「整站（分类 → 所有书）」→ 站点地址填 http://127.0.0.1:8899/
3. 点「发现书籍」→ 应出现 3 个分类、8 本书（其中《诡秘之主》来自玄幻分类第 2 页，用于验证列表翻页）
4. 勾选后「开始抓取」→ 每本存成一个 txt 到文件管理

数据与 scripts/crawl_site_selftest.py 共用（同一套 build_site）。
"""
import os
import sys
import tempfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import crawl_site_selftest as fixture  # noqa: E402  复用同一套假站点数据


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    root = os.path.join(tempfile.mkdtemp(prefix="crawl-fixture-"), "site")
    fixture.build_site(root)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), partial(SimpleHTTPRequestHandler, directory=root))
    print(f"假书城已启动：http://127.0.0.1:{port}/")
    print("  3 个分类（玄幻 / 都市 / 科幻）、8 本书、每本 3 章；《诡秘之主》在玄幻分类第 2 页")
    print(f"  静态文件目录：{root}")
    print("  注意：AI 服务需以 CRAWL_ALLOW_PRIVATE=1 启动，否则会拒绝抓取本机地址")
    print("  Ctrl+C 停止")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
