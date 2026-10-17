"""统一的模型调用接口。

生成流程只依赖 TextGenerator：计数（count_messages / count_text）、尾部截取（tail_tokens）、
上下文上限（context_limit）和 generate(messages, params)。
- LocalHFGenerator：本机 Transformers 模型（复用 app.local.inference 中已加载的模型）
- 远程模型（Hugging Face Inference / OpenAI 兼容等）以后实现同样的接口，在 get_generator 中按 source 分派
"""
import functools
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

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

    def __init__(self, base_id: str):
        try:
            self.base = registry.get_base(base_id)
        except registry.RegistryError as e:
            raise GenerationError(str(e)) from e
        if not self.base["exists"]:
            raise GenerationError(f"模型目录不存在：{self.base['path']}")
        self.name = self.base["name"]
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
        if loaded["adapterId"]:
            raise GenerationError("当前加载的模型带有 LoRA 适配器；本阶段小说生成只使用基础模型，请重新加载（不选适配器）")

    def generate(self, messages: list[dict], params: GenParams) -> GenResult:
        self.ensure_ready()
        try:
            r = inference.chat_generate(messages, max_new_tokens=params.max_new_tokens, temperature=params.temperature,
                                        top_p=params.top_p, top_k=params.top_k,
                                        repetition_penalty=params.repetition_penalty, stop_event=params.stop_event)
        except RuntimeError as e:
            msg = str(e)
            if "out of memory" in msg.lower():
                msg = "显存不足，请选择更小的上下文窗口或减少每段生成长度"
            raise GenerationError(msg) from e
        return GenResult(r["text"], r["promptTokens"], r["completionTokens"], r["finishReason"], r["seconds"])


def get_generator(model: dict) -> TextGenerator:
    """按工作区的模型配置创建调用器。model: {source: local|remote, baseId?, ...}"""
    source = (model or {}).get("source", "local")
    if source == "local":
        if not model.get("baseId"):
            raise GenerationError("工作区未选择本地模型")
        return LocalHFGenerator(model["baseId"])
    raise GenerationError("远程模型生成暂未接入（接口已预留：实现 TextGenerator 并在 get_generator 中注册）")
