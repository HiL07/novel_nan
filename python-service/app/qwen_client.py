"""本地千问（llama.cpp OpenAI 兼容接口）调用 + 小说解析 prompt。

prompt 与约束来自 qwen skill：分块输入、低温度、写死 JSON 字段并开启 json_object。
"""
import json

import httpx

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


class QwenError(RuntimeError):
    pass


def health() -> bool:
    try:
        return httpx.get(f"{config.QWEN_URL}/health", timeout=3, trust_env=False).status_code == 200
    except httpx.HTTPError:
        return False


def analyze_chunk(title: str, content: str) -> dict:
    payload = {
        "model": config.QWEN_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(title=title, content=content)},
        ],
        "temperature": 0.2,
        "max_tokens": config.QWEN_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = httpx.post(
            f"{config.QWEN_URL}/v1/chat/completions",
            json=payload,
            timeout=config.QWEN_TIMEOUT,
            trust_env=False,  # 本机服务不走系统代理
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise QwenError(f"调用千问服务失败：{e}") from e

    text = resp.json()["choices"][0]["message"]["content"]
    return parse_json(text)


def parse_json(text: str) -> dict:
    """容错解析：去掉 ```json 包裹，截取首尾大括号。"""
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise QwenError("模型未返回 JSON")
    try:
        data = json.loads(text[start: end + 1])
    except json.JSONDecodeError as e:
        raise QwenError(f"模型返回的 JSON 无法解析：{e}") from e
    return data if isinstance(data, dict) else {}
