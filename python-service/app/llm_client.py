"""大模型调用：OpenAI 兼容接口（DeepSeek / 通义千问 / Kimi / OpenAI / 本地 llama.cpp 等）
和 Anthropic Messages 接口（protocol = anthropic，在 _post_chat 里转换请求 / 响应，调用方都按 OpenAI 格式用）。

模型配置（地址、模型名、API Key）由 Java 后端随请求传入，本服务不保存密钥。
"""
import json
import threading
import time
from typing import Literal
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
    """一次调用所需的模型配置。protocol = openai：请求 {baseUrl}/chat/completions；
    anthropic：请求 {baseUrl}/v1/messages（baseUrl 已以 /v1 结尾则 {baseUrl}/messages）。"""

    baseUrl: str = Field(min_length=8)
    apiKey: str = ""
    model: str = Field(min_length=1)
    concurrency: int = Field(default=1, ge=1, le=8)
    protocol: Literal["openai", "anthropic"] = "openai"

    def __repr__(self) -> str:  # 日志/异常里不出现密钥
        return f"ModelConfig(baseUrl={self.baseUrl!r}, model={self.model!r})"

    __str__ = __repr__


class LLMError(RuntimeError):
    """fatal=True 表示配置级错误（密钥无效、余额不足、模型不存在），继续调用也不会成功。"""

    def __init__(self, message: str, fatal: bool = False):
        super().__init__(message)
        self.fatal = fatal


ANTHROPIC_VERSION = "2023-06-01"


def _anthropic_base(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/v1") else base + "/v1"


def _endpoint(cfg: ModelConfig) -> str:
    if cfg.protocol == "anthropic":
        return _anthropic_base(cfg.baseUrl) + "/messages"
    return cfg.baseUrl.rstrip("/") + "/chat/completions"


def _headers(protocol: str, api_key: str) -> dict:
    if protocol == "anthropic":
        h = {"anthropic-version": ANTHROPIC_VERSION}
        if api_key:
            h["x-api-key"] = api_key
        return h
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _trust_env(cfg) -> bool:
    # 本机服务不走系统代理（Clash 等会把 localhost 请求转成 502）；远程服务沿用系统代理设置
    url = cfg if isinstance(cfg, str) else cfg.baseUrl
    return urlparse(url).hostname not in _LOCAL_HOSTS


def _to_anthropic(payload: dict) -> dict:
    """OpenAI chat 请求 → Anthropic Messages 请求：system 消息合并成 system 字段，相邻同角色消息合并；
    没有 JSON 模式（靠 prompt 约束）；temperature 限在 0–1；不带 top_p（新模型不许和 temperature 同时给）。"""
    system, messages = [], []
    for m in payload.get("messages") or []:
        role, text = m.get("role"), m.get("content") or ""
        if role == "system":
            system.append(text)
            continue
        role = "assistant" if role == "assistant" else "user"
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n\n" + text
        else:
            messages.append({"role": role, "content": text})
    if not messages or messages[0]["role"] != "user":
        messages.insert(0, {"role": "user", "content": "请继续。"})
    out = {"model": payload["model"], "messages": messages, "max_tokens": int(payload.get("max_tokens") or 1024)}
    if system:
        out["system"] = "\n\n".join(system)
    if payload.get("temperature") is not None:
        out["temperature"] = max(0.0, min(1.0, float(payload["temperature"])))
    return out


def _from_anthropic(data: dict) -> dict:
    """Anthropic Messages 响应 → OpenAI 形状（choices[0].message.content / finish_reason / usage）。"""
    text = "".join(b.get("text") or "" for b in data["content"] if b.get("type") == "text")
    usage = data.get("usage") or {}
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    prompt = int(usage.get("input_tokens") or 0) + cache_read + int(usage.get("cache_creation_input_tokens") or 0)
    return {"choices": [{"message": {"role": "assistant", "content": text},
                         "finish_reason": "length" if data.get("stop_reason") == "max_tokens" else "stop"}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": int(usage.get("output_tokens") or 0),
                      "prompt_tokens_details": {"cached_tokens": cache_read}}}


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


# 不认 thinking 参数的服务（baseUrl, model）：第一次被 400 拒绝后记住，之后不再带
_NO_THINKING_PARAM: set[tuple[str, str]] = set()


def _send(url: str, payload: dict, headers: dict, timeout: float, trust_env: bool,
          cancel: threading.Event | None) -> httpx.Response:
    """发一次 POST。cancel 不为空（后台任务）时请求放到守护线程里，每 0.5 秒看一次取消标记，并限制总耗时：
    httpx 的 timeout 只管「两次收到数据的间隔」，服务端忙时断断续续回数据（DeepSeek 503 过载时）一次调用能拖好几分钟，
    取消也要等它返回（2026-11-03「一直显示正在取消」）。取消 → 致命 LLMError（任务按已取消收尾，被丢下的请求自己结束）。"""
    if cancel is None:
        return httpx.post(url, json=payload, headers=headers, timeout=timeout, trust_env=trust_env)
    box: dict = {}

    def run() -> None:
        try:
            box["resp"] = httpx.post(url, json=payload, headers=headers, timeout=timeout, trust_env=trust_env)
        except BaseException as e:  # noqa: BLE001 — 原样交给调用方
            box["err"] = e

    t = threading.Thread(target=run, name="llm-call", daemon=True)
    t.start()
    deadline = time.monotonic() + timeout
    while t.is_alive():
        if cancel.wait(0.5):
            raise LLMError("已取消", fatal=True)
        if time.monotonic() > deadline:
            raise httpx.ReadTimeout(f"总耗时超过 {timeout:.0f}s")
    if "err" in box:
        raise box["err"]
    return box["resp"]


def _post_chat(cfg: ModelConfig, payload: dict, retries: int, timeout: float | None,
               cancel: threading.Event | None = None) -> dict:
    """POST /chat/completions（或 Anthropic /v1/messages，转换后返回 OpenAI 形状），返回响应 JSON。
    429/5xx/超时自动重试；不支持 json_object 的服务自动降级；不认 thinking 参数的服务去掉后重发。
    cancel = 后台任务的取消标记：等待中途也能取消（见 _send）。"""
    headers = _headers(cfg.protocol, cfg.apiKey)
    timeout = timeout or config.LLM_TIMEOUT
    anthropic = cfg.protocol == "anthropic"
    if anthropic:
        payload = _to_anthropic(payload)
    elif "thinking" in payload and (cfg.baseUrl, cfg.model) in _NO_THINKING_PARAM:
        payload.pop("thinking")

    for attempt in range(retries + 1):
        try:
            resp = _send(_endpoint(cfg), payload, headers, timeout, _trust_env(cfg), cancel)
            if resp.status_code == 400 and "response_format" in payload and "response_format" in resp.text:
                # 不支持 JSON 模式：去掉后立即重发（不占用重试次数），靠 prompt 约束输出 JSON
                payload.pop("response_format")
                resp = _send(_endpoint(cfg), payload, headers, timeout, _trust_env(cfg), cancel)
            if resp.status_code in (400, 422) and "thinking" in payload and "thinking" in resp.text:
                # 不认 thinking 参数：去掉后重发，并记住这个服务
                payload.pop("thinking")
                _NO_THINKING_PARAM.add((cfg.baseUrl, cfg.model))
                resp = _send(_endpoint(cfg), payload, headers, timeout, _trust_env(cfg), cancel)
            _raise_for_status(resp)
            data = resp.json()
            if anthropic:
                data = _from_anthropic(data)
            data["choices"][0]["message"]  # 校验结构
            return data
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
            raise LLMError("模型返回格式不符合 " + ("Anthropic Messages" if anthropic else "OpenAI 兼容") + " 接口",
                           fatal=True)
        if cancel is not None:
            if cancel.wait(2 * (attempt + 1)):
                raise LLMError("已取消", fatal=True)
        else:
            time.sleep(2 * (attempt + 1))
    raise LLMError("模型调用失败")


def source_of(cfg: ModelConfig) -> str:
    """local = 本机 OpenAI 兼容服务（llama.cpp 等，不计费）；api = 远端大模型接口（按 token 计费）"""
    return "local" if urlparse(cfg.baseUrl).hostname in _LOCAL_HOSTS else "api"


def new_usage(cfg: ModelConfig) -> dict:
    """token 用量累加器（不含密钥，可放进任务状态）。cacheHitTokens 是 promptTokens 里命中缓存的部分。"""
    return {"source": source_of(cfg), "model": cfg.model, "host": urlparse(cfg.baseUrl).hostname or "",
            "calls": 0, "promptTokens": 0, "completionTokens": 0, "cacheHitTokens": 0}


def add_usage(acc: dict, data: dict) -> dict:
    """把一次响应的 usage 累加进 acc，返回本次的 {promptTokens, completionTokens, cacheHitTokens}。"""
    usage = data.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    one = {"promptTokens": int(usage.get("prompt_tokens") or 0),
           "completionTokens": int(usage.get("completion_tokens") or 0),
           # DeepSeek: prompt_cache_hit_tokens；OpenAI / 通义: prompt_tokens_details.cached_tokens
           "cacheHitTokens": int(usage.get("prompt_cache_hit_tokens") or details.get("cached_tokens") or 0),
           # 推理模型的思考 token（已含在 completionTokens 里）
           "reasoningTokens": int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)}
    if data["choices"][0].get("finish_reason") == "length":
        acc["truncated"] = acc.get("truncated", 0) + 1
    acc["calls"] = acc.get("calls", 0) + 1
    for k, v in one.items():
        acc[k] = acc.get(k, 0) + v
    return one


def chat(cfg: ModelConfig, messages: list[dict], max_tokens: int, json_mode: bool = True,
         retries: int = 2, timeout: float | None = None, usage: dict | None = None, think: bool = False,
         cancel: threading.Event | None = None) -> str:
    """发送一次对话，返回文本（提取 / 校验用：低温度，默认 JSON 模式）。usage 不为空时累加本次 token 用量。
    think=False（默认）对推理模型传 thinking: disabled——结构化提取不需要先「思考」，开着的话思考 token 也算进
    max_tokens，会把 JSON 挤断（deepseek-v4.1-flash 实测一章思考约 1800 token，2026-11-03）；不认这个参数的服务自动去掉。"""
    payload = {
        "model": cfg.model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if not think and source_of(cfg) == "api":
        payload["thinking"] = {"type": "disabled"}
    data = _post_chat(cfg, payload, retries, timeout, cancel)
    if usage is not None:
        add_usage(usage, data)
    return data["choices"][0]["message"]["content"] or ""


def complete(cfg: ModelConfig, messages: list[dict], *, max_tokens: int, temperature: float, top_p: float,
             json_mode: bool = False, retries: int = 2, timeout: float | None = None, think: bool = True) -> dict:
    """创作用的一次对话：返回 {text, promptTokens, completionTokens, finishReason: stop|length}。
    token 数取服务端 usage（没有时为 0，由调用方估算）。think=False：关掉推理模型的思考（思考 token 也算进 max_tokens，
    上限只有几百的短任务会被吃光、content 为空）；不认这个参数的服务自动去掉（_post_chat）。"""
    payload = {"model": cfg.model, "messages": messages, "max_tokens": max_tokens,
               "temperature": temperature, "top_p": top_p}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if not think:
        payload["thinking"] = {"type": "disabled"}
    data = _post_chat(cfg, payload, retries, timeout)
    choice = data["choices"][0]
    usage = data.get("usage") or {}
    return {"text": choice["message"].get("content") or "",
            "promptTokens": int(usage.get("prompt_tokens") or 0),
            "completionTokens": int(usage.get("completion_tokens") or 0),
            "finishReason": "length" if choice.get("finish_reason") == "length" else "stop"}


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


class ListModelsRequest(BaseModel):
    """「获取可用模型」：列出服务端的模型目录（不需要模型名）。"""

    baseUrl: str = Field(min_length=8)
    apiKey: str = ""
    protocol: Literal["openai", "anthropic"] = "openai"

    def __repr__(self) -> str:
        return f"ListModelsRequest(baseUrl={self.baseUrl!r}, protocol={self.protocol!r})"

    __str__ = __repr__


def list_models(req: ListModelsRequest) -> dict:
    """GET {baseUrl}/models（OpenAI 兼容）或 {baseUrl}/v1/models（Anthropic）→ {ok, models[{id, name}], message}。
    不少兼容服务没有这个接口（404），那时只能手动填模型名。"""
    if req.protocol == "anthropic":
        url = _anthropic_base(req.baseUrl) + "/models?limit=1000"
    else:
        url = req.baseUrl.rstrip("/") + "/models"
    try:
        resp = httpx.get(url, headers=_headers(req.protocol, req.apiKey), timeout=VERIFY_TIMEOUT,
                         trust_env=_trust_env(req.baseUrl))
        if resp.status_code == 404:
            return {"ok": False, "models": [], "message": "这个服务没有提供模型列表接口（404），请手动添加模型名"}
        _raise_for_status(resp)
        data = resp.json()
    except LLMError as e:
        return {"ok": False, "models": [], "message": str(e)}
    except httpx.TimeoutException:
        return {"ok": False, "models": [], "message": f"请求超时（{VERIFY_TIMEOUT:.0f}s）"}
    except httpx.HTTPError as e:
        return {"ok": False, "models": [], "message": f"无法连接模型服务：{e.__class__.__name__}"}
    except ValueError:
        return {"ok": False, "models": [], "message": "模型列表不是 JSON"}
    rows = data.get("data") if isinstance(data, dict) else data
    if isinstance(data, dict) and rows is None:
        rows = data.get("models")
    models, seen = [], set()
    for r in rows or []:
        mid = (r.get("id") or r.get("name") or r.get("model")) if isinstance(r, dict) else r
        if not isinstance(mid, str) or not mid.strip() or mid.strip() in seen:
            continue
        mid = mid.strip()[:200]
        seen.add(mid)
        name = r.get("display_name") if isinstance(r, dict) else None
        models.append({"id": mid, "name": str(name or "")[:200]})
    models.sort(key=lambda m: m["id"].lower())
    return {"ok": True, "models": models[:1000], "message": f"获取到 {len(models)} 个模型"}


def build_chunk_prompt(title: str, content: str, extra: str = "") -> str:
    """extra：追加的输出要求（如素材候选，见 app/materials.py），插在正文之前。大模型 / 本地模型提取共用。"""
    prompt = USER_TEMPLATE.format(title=title, content=content)
    if extra:
        head, sep, tail = prompt.partition("\n\n标题：")
        prompt = f"{head}\n{extra}{sep}{tail}"
    return prompt


def analyze_chunk(cfg: ModelConfig, title: str, content: str, extra: str = "") -> dict:
    prompt = build_chunk_prompt(title, content, extra)
    text = chat(cfg, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ], max_tokens=config.LLM_MAX_TOKENS + (600 if extra else 0))
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
