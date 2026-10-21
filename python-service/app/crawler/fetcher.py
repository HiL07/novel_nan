"""HTTP 抓取：地址校验（只允许公网 http/https）、robots.txt、限速、重试、编码识别。"""
import ipaddress
import logging
import os
import re
import socket
import threading
import time
from typing import Optional
from urllib import robotparser
from urllib.parse import quote, urljoin, urlsplit

import httpx

from ..text_loader import decode_text

log = logging.getLogger("crawler")

DEFAULT_UA = os.getenv(
    "CRAWL_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
)
# 测试时用本机假站点需打开（默认禁止抓内网地址，避免把本机 / 局域网服务当目标）
ALLOW_PRIVATE = os.getenv("CRAWL_ALLOW_PRIVATE", "").lower() in ("1", "true", "yes")
MAX_PAGE_BYTES = 5 * 1024 * 1024
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([\w-]+)""", re.IGNORECASE)


_FAKE_IP_NET = ipaddress.ip_network("198.18.0.0/15")


class CrawlError(Exception):
    pass


class NetworkError(CrawlError):
    """断网 / DNS 失败 / 超时 / 5xx 等暂时性故障（重试已用完）。抓取任务遇到它会等待后重试同一章，而不是记为失败。"""


class BlockedError(CrawlError):
    """站点的反爬校验页（Cloudflare 人机验证、脚本跳转令牌等）：程序不执行脚本，换规则也抓不到，直接告诉用户原因。"""


_CF_MARKERS = ("just a moment", "cf-chl", "challenge-platform", "cf_chl_opt", "attention required! | cloudflare")
_JS_JUMP = re.compile(r"(?:window\.|document\.|top\.|self\.)?location(?:\.href)?\s*=|location\.(?:replace|assign)\s*\(",
                      re.IGNORECASE)


def blocked_reason(status: int, headers, body: bytes) -> Optional[str]:
    """识别反爬校验页 → 原因说明；不是则 None。只认明确特征，避免把正常的小页面误判。"""
    head = body[:20000].decode("utf-8", errors="ignore").lower()
    if status in (403, 429, 503) and ("cloudflare" in (headers.get("server") or "").lower()
                                      or any(m in head for m in _CF_MARKERS)):
        return ("站点开启了 Cloudflare 人机验证（「Just a moment…」页面），需要浏览器执行脚本通过校验，程序无法自动抓取；"
                "请换一个站点")
    # 整页只有一段 <script> 把地址拼出来再跳转（常带一次性令牌），没有任何正文 / 链接
    if status == 200 and len(body) < 3000 and "<a " not in head and "<script" in head and _JS_JUMP.search(head):
        return "站点返回的是脚本跳转校验页（反爬：要执行页面脚本拿到令牌才给内容），程序不执行脚本，无法自动抓取；请换一个站点"
    return None


def quote_url(url: str) -> str:
    """只编码非 ASCII 等不安全字符，已编码的 %XX 保持不变。"""
    return quote(url, safe=":/?#[]@!$&'()*+,;=%~")


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def check_url(url: str) -> str:
    """只接受 http/https 公网地址，返回去掉首尾空白的 URL。"""
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise CrawlError("请输入 http:// 或 https:// 开头的网址")
    if not ALLOW_PRIVATE:
        try:
            infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
        except socket.gaierror:
            raise NetworkError(f"无法解析域名：{parts.hostname}（网络断开，或站点域名已失效）")
        is_domain = not _is_ip_literal(parts.hostname)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
            # Clash 等代理的 TUN / fake-ip 模式把所有域名解析到 198.18.0.0/15，真实目标由代理决定，不能当内网拒绝
            if is_domain and ip in _FAKE_IP_NET:
                continue
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise CrawlError("不允许抓取本机或内网地址")
    return url


class Fetcher:
    """一个抓取任务用一个实例：共享连接、robots 缓存，并保证两次请求间隔 ≥ delay。"""

    def __init__(self, delay_ms: int = 1000, respect_robots: bool = True, encoding: str = "",
                 timeout: float = 20, retries: int = 2):
        self.delay = max(delay_ms, 0) / 1000
        self.respect_robots = respect_robots
        self.encoding = encoding
        self.retries = retries
        self._robots: dict[str, Optional[robotparser.RobotFileParser]] = {}
        self._last = 0.0
        self._lock = threading.Lock()
        # 远程站点走系统代理（与 llm_client 一致）；内网测试地址不走代理
        self.client = httpx.Client(timeout=timeout, follow_redirects=True, trust_env=not ALLOW_PRIVATE,
                                   headers={"User-Agent": DEFAULT_UA, "Accept-Language": "zh-CN,zh;q=0.9"})

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def get_html(self, url: str, referer: str = "") -> tuple[str, str]:
        """返回 (最终 URL, 解码后的 HTML)。4xx 直接失败，5xx / 网络错误重试。"""
        # 中文路径（如维基文库）要百分号编码：请求头（Referer）只能是 ASCII
        url, referer = quote_url(check_url(url)), quote_url(referer) if referer else ""
        if not self._allowed(url):
            raise CrawlError(f"该站点的 robots.txt 不允许抓取：{url}（如确认有权抓取，可在高级选项中关闭 robots 检查）")
        last_err: Exception = CrawlError("未知错误")
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                resp = self.client.get(url, headers={"Referer": referer} if referer else None)
                if resp.status_code == 404:
                    raise CrawlError(f"页面不存在（404）：{url}")
                reason = blocked_reason(resp.status_code, resp.headers, resp.content)
                if reason:
                    raise BlockedError(f"{reason}：{url}")
                if resp.status_code in (401, 403):
                    raise CrawlError(f"站点拒绝访问（HTTP {resp.status_code}），可能有反爬限制：{url}")
                if resp.status_code >= 400:
                    raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
                if len(resp.content) > MAX_PAGE_BYTES:
                    raise CrawlError(f"页面过大（>{MAX_PAGE_BYTES // 1024 // 1024} MB），不像小说页面：{url}")
                return str(resp.url), self._decode(resp)
            except CrawlError:
                raise
            except (httpx.HTTPError, OSError) as e:
                last_err = e
                log.info("抓取失败（第 %d 次）%s：%s", attempt + 1, url, e)
                time.sleep(min(2 ** attempt, 5))
        raise NetworkError(f"请求失败：{url}（{last_err}）")

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                resp = self.client.get(urljoin(origin, "/robots.txt"), timeout=10)
                # 没有 robots.txt（404 等）视为全部允许；5xx / 网络错误也不阻塞
                rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            except httpx.HTTPError:
                rp.parse([])
            self._robots[origin] = rp
        return self._robots[origin].can_fetch(DEFAULT_UA, url)

    def _decode(self, resp: httpx.Response) -> str:
        data = resp.content
        enc = self.encoding or _declared_charset(resp, data)
        if enc:
            try:
                # gb2312 / gbk 页面常混入扩展字符，统一按超集 gb18030 解
                return data.decode("gb18030" if enc.lower() in ("gb2312", "gbk") else enc, errors="replace")
            except LookupError:
                pass
        return decode_text(data)


def _declared_charset(resp: httpx.Response, data: bytes) -> str:
    ctype = resp.headers.get("content-type", "")
    m = re.search(r"charset=([\w-]+)", ctype, re.IGNORECASE)
    if m:
        return m.group(1)
    m = _META_CHARSET.search(data[:4096])
    return m.group(1).decode("ascii", errors="ignore") if m else ""
