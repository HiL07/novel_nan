"""统一的模型调用接口。

生成流程只依赖 TextGenerator：计数（count_messages / count_text）、尾部截取（tail_tokens）、
上下文上限（context_limit）和 generate(messages, params)。
- LocalHFGenerator：本机 Transformers 模型（复用 app.local.inference 中已加载的模型）
- ApiChatGenerator：大模型（OpenAI 兼容 API，Java「模型配置」中启用并验证过的那一个）。配置含 API Key，
  由 Java 随请求传入，只在本次任务内存中使用，不落盘、不进任务状态
- 远程模型（source=remote，AutoDL 等远程 GPU 上的基础模型 + 适配器）预留，尚未接入
"""
import functools
import json
import math
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import llm_client
from ..local import inference, registry


class GenerationError(RuntimeError):
    pass


@dataclass
class GenParams:
    max_new_tokens: int = 768
    temperature: float = 0.7
    top_p: float = 0.8
    top_k: int = 20
    repetition_penalty: float = 1.1
    use_adapter: bool = True  # False：本次停用工作区的 LoRA 适配器（摘要等指令型调用用基础模型更稳）
    json_mode: bool = False   # 大模型：要求输出 JSON（response_format）；本地模型忽略，由调用方容错解析
    stop_event: threading.Event | None = field(default=None, repr=False)


@dataclass
class GenResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str  # stop | length | cancelled
    seconds: float


class TextGenerator:
    """模型调用接口。实现类需提供计数（用该模型自己的 tokenizer）与生成。"""

    name: str = ""
    context_limit: int = 0

    def count_messages(self, messages: list[dict]) -> int:
        raise NotImplementedError

    def count_text(self, text: str) -> int:
        raise NotImplementedError

    def tail_tokens(self, text: str, max_tokens: int) -> str:
        """取文本末尾不超过 max_tokens 个 token 的部分。"""
        raise NotImplementedError

    def ensure_ready(self) -> None:
        """生成前检查（如模型已加载）；不满足时抛 GenerationError。"""

    def generate(self, messages: list[dict], params: GenParams) -> GenResult:
        raise NotImplementedError


@functools.lru_cache(maxsize=4)
def _tokenizer(model_path: str):
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(model_path)


class LocalHFGenerator(TextGenerator):
    """本机 Hugging Face 模型。计数只需加载 tokenizer（预览上下文时不必加载模型）。"""

    def __init__(self, base_id: str, adapter_id: str | None = None):
        try:
            self.base = registry.get_base(base_id)
            self.adapter = registry.get_adapter(adapter_id) if adapter_id else None
        except registry.RegistryError as e:
            raise GenerationError(str(e)) from e
        if not self.base["exists"]:
            raise GenerationError(f"模型目录不存在：{self.base['path']}")
        self.adapter_id = adapter_id
        self.name = self.base["name"] + (f" + {self.adapter['name']}" if self.adapter else "")
        self.tokenizer = _tokenizer(self.base["path"])
        cfg = json.loads((Path(self.base["path"]) / "config.json").read_text(encoding="utf-8"))
        self.context_limit = int(cfg.get("max_position_embeddings") or 4096)

    def count_messages(self, messages: list[dict]) -> int:
        ids = self.tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
        return len(ids)

    def count_text(self, text: str) -> int:
        return len(self.tokenizer(text, add_special_tokens=False)["input_ids"]) if text else 0

    def tail_tokens(self, text: str, max_tokens: int) -> str:
        ids = self.tokenizer(text, add_special_tokens=False)["input_ids"]
        if len(ids) <= max_tokens:
            return text
        return self.tokenizer.decode(ids[-max_tokens:], skip_special_tokens=True)

    def ensure_ready(self) -> None:
        loaded = inference.loaded_model()
        if not loaded or loaded["baseId"] != self.base["id"]:
            raise GenerationError(f"模型「{self.name}」未加载，请先在工作区点击「加载模型」")
        if loaded["adapterId"] != self.adapter_id:
            want = f"适配器「{self.adapter['name']}」" if self.adapter else "不带适配器的基础模型"
            raise GenerationError(f"当前加载的模型与工作区不一致（工作区使用{want}），请在工作区点击「加载模型」")

    def generate(self, messages: list[dict], params: GenParams) -> GenResult:
        self.ensure_ready()
        try:
            r = inference.chat_generate(messages, max_new_tokens=params.max_new_tokens, temperature=params.temperature,
                                        top_p=params.top_p, top_k=params.top_k,
                                        repetition_penalty=params.repetition_penalty, stop_event=params.stop_event,
                                        use_adapter=None if params.use_adapter else False)
        except RuntimeError as e:
            msg = str(e)
            if "out of memory" in msg.lower():
                msg = "显存不足，请选择更小的上下文窗口或减少每段生成长度"
            raise GenerationError(msg) from e
        return GenResult(r["text"], r["promptTokens"], r["completionTokens"], r["finishReason"], r["seconds"])


_CJK = re.compile(r"[　-鿿豈-﫿＀-￯]")


class ApiChatGenerator(TextGenerator):
    """OpenAI 兼容的大模型。拿不到对方的 tokenizer：上下文组装按字符估算 token（偏保守），
    实际用量以接口返回的 usage 为准。cfg 为 None 时只能估算（预览上下文），不能生成。"""

    CONTEXT_LIMIT = 65536  # 主流对话模型至少 64K；实际以工作区的上下文窗口为准

    def __init__(self, cfg: llm_client.ModelConfig | None, name: str = ""):
        self.cfg = cfg
        self.name = name or (cfg.model if cfg else "大模型")
        self.context_limit = self.CONTEXT_LIMIT

    def count_text(self, text: str) -> int:
        if not text:
            return 0
        cjk = len(_CJK.findall(text))
        # 中文因模型而异（DeepSeek 约 0.6、部分模型接近 1 token/字），按 1.0 估算以免低估上下文；英文约 4 字符/token，略放大
        return math.ceil(cjk * 1.0 + (len(text) - cjk) * 0.35)

    def count_messages(self, messages: list[dict]) -> int:
        return sum(self.count_text(m["content"]) + 6 for m in messages) + 4

    def tail_tokens(self, text: str, max_tokens: int) -> str:
        if self.count_text(text) <= max_tokens:
            return text
        lo, hi = 0, len(text)  # 二分找最长的、估算不超过 max_tokens 的尾部
        while lo < hi:
            mid = (lo + hi) // 2
            if self.count_text(text[mid:]) <= max_tokens:
                hi = mid
            else:
                lo = mid + 1
        return text[lo:]

    def ensure_ready(self) -> None:
        if self.cfg is None:
            raise GenerationError("大模型生成需要通过 Java 后端发起（由它附带「模型配置」中启用的模型）")

    def generate(self, messages: list[dict], params: GenParams) -> GenResult:
        self.ensure_ready()
        if params.stop_event and params.stop_event.is_set():
            return GenResult("", 0, 0, "cancelled", 0.0)
        start = time.monotonic()
        try:
            r = llm_client.complete(self.cfg, messages, max_tokens=params.max_new_tokens,
                                    temperature=params.temperature, top_p=params.top_p, json_mode=params.json_mode)
        except llm_client.LLMError as e:
            raise GenerationError(f"大模型调用失败：{e}") from e
        prompt = r["promptTokens"] or self.count_messages(messages)
        completion = r["completionTokens"] or self.count_text(r["text"])
        reason = "cancelled" if params.stop_event and params.stop_event.is_set() else r["finishReason"]
        return GenResult(r["text"], prompt, completion, reason, round(time.monotonic() - start, 2))


def get_generator(model: dict, api: dict | None = None) -> TextGenerator:
    """按工作区的模型配置创建调用器。model: {source: local|api|gguf|remote, baseId?, adapterId?, apiName?}；
    api：本次请求由 Java 附带的大模型配置 {baseUrl, apiKey, model, concurrency}（只在 source=api 时使用）；
    gguf：「llama.cpp」页正在运行的 GGUF 模型（本机 OpenAI 兼容接口，按大模型同样的方式调用）。"""
    source = (model or {}).get("source", "local")
    if source == "local":
        if not model.get("baseId"):
            raise GenerationError("工作区未选择本地模型")
        return LocalHFGenerator(model["baseId"], model.get("adapterId") or None)
    if source == "api":
        cfg = llm_client.ModelConfig(**api) if api else None
        return ApiChatGenerator(cfg, (cfg.model if cfg else model.get("apiName")) or "大模型")
    if source == "gguf":
        from ..local import llama

        try:
            cfg = llm_client.ModelConfig(**llama.api_config())
        except llama.LlamaError as e:
            raise GenerationError(str(e)) from e
        return ApiChatGenerator(cfg, llama.display_name())
    if source == "remote":
        raise GenerationError("远程模型（远程 GPU 上的模型 + 适配器）暂未接入")
    raise GenerationError(f"未知的模型来源：{source}")
