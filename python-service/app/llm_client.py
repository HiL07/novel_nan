"""OpenAI 兼容的大模型调用（DeepSeek / 通义千问 / Kimi / OpenAI / 本地 llama.cpp 等）。

模型配置（地址、模型名、API Key）由 Java 后端随请求传入，本服务不保存密钥。
"""
import json
import time
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from . import config

SYSTEM_PROMPT = "你是小说解析助手，只输出 JSON，不要任何多余文字。"

USER_TEMPLATE = """阅读下面的小说片段，严格按以下 JSON 结构输出：
{{"summary":"本段摘要，不超过100字",
 "characters":[{{"name":"人物姓名","role":"一句话身份或本段动作"}}],
 "events":[{{"summary":"关键事件","location":"地点，未知写空串","time":"时间，未知写空串"}}],
 "foreshadowing":["伏笔/埋点，没有则为空数组"],
 "style":{{"pace":"节奏：快/中/慢","tone":"基调，如轻松、压抑、热血"}}}}
关键事件 1-3 条，只输出结果，不要复述正文。
原文可能是中文或英文：摘要、身份、事件等描述一律用简体中文输出；人物姓名、地名保持原文写法，不要翻译或音译。

标题：{title}
正文：
{content}"""

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
# 验证须在 Java 端读超时（60s）内返回
VERIFY_TIMEOUT = 30.0


class ModelConfig(BaseModel):
    """一次调用所需的模型配置。baseUrl 为 OpenAI 兼容根地址（请求 {baseUrl}/chat/completions）。"""

    baseUrl: str = Field(min_length=8)
    apiKey: str = ""
    model: str = Field(min_length=1)
    concurrency: int = Field(default=1, ge=1, le=8)

    def __repr__(self) -> str:  # 日志/异常里不出现密钥
        return f"ModelConfig(baseUrl={self.baseUrl!r}, model={self.model!r})"

    __str__ = __repr__


class LLMError(RuntimeError):
    """fatal=True 表示配置级错误（密钥无效、余额不足、模型不存在），继续调用也不会成功。"""

    def __init__(self, message: str, fatal: bool = False):
        super().__init__(message)
        self.fatal = fatal


def _endpoint(cfg: ModelConfig) -> str:
    return cfg.baseUrl.rstrip("/") + "/chat/completions"


def _trust_env(cfg: ModelConfig) -> bool:
    # 本机服务不走系统代理（Clash 等会把 localhost 请求转成 502）；远程服务沿用系统代理设置
    return urlparse(cfg.baseUrl).hostname not in _LOCAL_HOSTS


def _error_detail(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error")
        msg = err.get("message") if isinstance(err, dict) else err
        return str(msg or resp.text)[:200]
    except (ValueError, AttributeError):
        return resp.text[:200]


def _raise_for_status(resp: httpx.Response) -> None:
    code = resp.status_code
    if code < 400:
        return
    detail = _error_detail(resp)
    if code in (401, 403):
        raise LLMError(f"API Key 无效或无权限（{code}）：{detail}", fatal=True)
    if code == 402:
        raise LLMError(f"账户余额不足（402）：{detail}", fatal=True)
    if code == 404:
        raise LLMError(f"接口地址或模型不存在（404）：{detail}", fatal=True)
    if code == 429:
        raise LLMError(f"请求过于频繁或额度受限（429）：{detail}")
    if code >= 500:
        raise LLMError(f"模型服务异常（{code}）：{detail}")
    raise LLMError(f"请求被拒绝（{code}）：{detail}", fatal=code in (400, 422))


def chat(cfg: ModelConfig, messages: list[dict], max_tokens: int, json_mode: bool = True,
         retries: int = 2, timeout: float | None = None) -> str:
    """发送一次对话，返回文本。429/5xx/超时自动重试；不支持 json_object 的服务自动降级。"""
    payload = {
        "model": cfg.model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {cfg.apiKey}"} if cfg.apiKey else {}
    timeout = timeout or config.LLM_TIMEOUT

    for attempt in range(retries + 1):
        try:
            resp = httpx.post(_endpoint(cfg), json=payload, headers=headers,
                              timeout=timeout, trust_env=_trust_env(cfg))
            if resp.status_code == 400 and "response_format" in payload and "response_format" in resp.text:
                # 不支持 JSON 模式：去掉后立即重发（不占用重试次数），靠 prompt 约束输出 JSON
                payload.pop("response_format")
                resp = httpx.post(_endpoint(cfg), json=payload, headers=headers,
                                  timeout=timeout, trust_env=_trust_env(cfg))
            _raise_for_status(resp)
            return resp.json()["choices"][0]["message"]["content"] or ""
        except LLMError as e:
            if e.fatal or attempt == retries:
                raise
        except httpx.TimeoutException:
            if attempt == retries:
                raise LLMError(f"请求超时（{timeout:.0f}s）")
        except httpx.HTTPError as e:
            if attempt == retries:
                raise LLMError(f"无法连接模型服务：{e.__class__.__name__}")
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("模型返回格式不符合 OpenAI 兼容接口", fatal=True)
        time.sleep(2 * (attempt + 1))
    raise LLMError("模型调用失败")


def verify(cfg: ModelConfig) -> dict:
    """用一次极小的真实请求验证配置可用：地址可达、密钥有效、模型存在、能按 JSON 回复。"""
    start = time.monotonic()
    try:
        reply = chat(cfg, [{"role": "user", "content": '请只输出 JSON：{"ok":true}'}],
                     max_tokens=20, retries=0, timeout=VERIFY_TIMEOUT)
    except LLMError as e:
        return {"ok": False, "latencyMs": int((time.monotonic() - start) * 1000), "message": str(e), "reply": ""}
    latency = int((time.monotonic() - start) * 1000)
    if not reply.strip():
        return {"ok": False, "latencyMs": latency, "message": "模型返回为空", "reply": ""}
    return {"ok": True, "latencyMs": latency, "message": f"验证通过，耗时 {latency} ms", "reply": reply[:100]}


def analyze_chunk(cfg: ModelConfig, title: str, content: str) -> dict:
    text = chat(cfg, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_TEMPLATE.format(title=title, content=content)},
    ], max_tokens=config.LLM_MAX_TOKENS)
    return parse_json(text)


def parse_json(text: str) -> dict:
    """容错解析：去掉 ```json 包裹，截取首尾大括号。"""
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("模型未返回 JSON")
    try:
        data = json.loads(text[start: end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"模型返回的 JSON 无法解析：{e}") from e
    return data if isinstance(data, dict) else {}
