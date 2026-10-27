"""用应用内的本地模型（Transformers 基础模型，不挂适配器）逐块解析小说，替代大模型 API。

- 单卡串行：调用方保证一次只跑一块；章节生成 / 训练占用 GPU 时拒绝
- 小模型不擅长按格式输出：宽松解析 JSON（代码块、尾逗号），解析不了时按字段正则抢救 summary / characters / events
- 加载的基础模型就是所选模型时不重载；已挂载适配器也不切换，本次调用停用适配器（文风适配器会削弱按格式输出）
"""
import json
import re
import threading

from . import llm_client
from .llm_client import LLMError
from .local import inference, jobs as local_jobs, registry

# 每块输出上限（token）。约 2500 字的块：摘要 + 人物 + 事件 ≈ 400–700 token；含素材时再加
MAX_NEW_TOKENS = 900
MATERIAL_EXTRA_TOKENS = 400

_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_active = threading.Event()  # 有本地提取任务在跑（章节生成 / AI 构思 / 训练据此等待）

inference.set_extract_busy_check(_active.is_set)


def check_available() -> None:
    """提交前检查：GPU 没被训练 / 章节生成占用。"""
    from .generation import chapter  # 延迟导入：避免与 generation 模块循环依赖

    if local_jobs.gpu_busy():
        raise LLMError("有训练任务正在使用 GPU，请等待训练完成或改用大模型提取", fatal=True)
    if chapter.active_job():
        raise LLMError("有章节正在生成或润色，请等待完成或改用大模型提取", fatal=True)


class LocalSession:
    """一次提取任务内使用本地模型：进入时登记占用并加载模型，退出时释放占用（模型保留在显存，便于后续使用）。"""

    def __init__(self, base_id: str, stop_event: threading.Event | None = None):
        self.base_id = base_id
        self.stop_event = stop_event
        self.name = base_id

    def __enter__(self) -> "LocalSession":
        if _active.is_set():
            raise LLMError("已有本地模型提取任务在运行", fatal=True)
        check_available()
        try:
            base = registry.get_base(self.base_id)
        except registry.RegistryError as e:
            raise LLMError(str(e), fatal=True) from e
        if base.get("task") != "causal-lm":
            raise LLMError(registry.not_generation_reason(base, "在本服务里做小说提取"), fatal=True)
        self.name = base["name"]
        _active.set()
        try:
            self._ensure_loaded()
        except BaseException:
            _active.clear()
            raise
        return self

    def __exit__(self, *exc) -> None:
        _active.clear()

    def _ensure_loaded(self) -> None:
        loaded = inference.loaded_model()
        if loaded and loaded["baseId"] == self.base_id:
            return
        try:
            # from_generation=True：跳过「提取进行中」的拦截（就是本任务自己在加载）；训练占用仍会拒绝
            inference.load(self.base_id, None, "auto", from_generation=True)
            inference.wait_loaded(timeout=600, stop_event=self.stop_event)
        except RuntimeError as e:
            raise LLMError(f"本地模型加载失败：{e}", fatal=True) from e

    def analyze_chunk(self, title: str, content: str, extra: str = "") -> dict:
        if local_jobs.gpu_busy():
            raise LLMError("训练任务占用了 GPU，提取中止", fatal=True)
        loaded = inference.loaded_model()
        if not loaded or loaded["baseId"] != self.base_id:
            raise LLMError("本地模型已被卸载或切换，提取中止", fatal=True)
        prompt = llm_client.build_chunk_prompt(title, content, extra)
        messages = [{"role": "system", "content": llm_client.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}]
        try:
            r = inference.chat_generate(messages, max_new_tokens=MAX_NEW_TOKENS + (MATERIAL_EXTRA_TOKENS if extra else 0),
                                        temperature=0.2, top_p=0.9, top_k=40, repetition_penalty=1.05,
                                        stop_event=self.stop_event, use_adapter=False)
        except RuntimeError as e:  # 含 CUDA OOM
            raise LLMError(f"本地模型生成失败：{e}") from e
        if r["finishReason"] == "cancelled":
            raise LLMError("已取消", fatal=True)
        return parse_lenient(r["text"])


def parse_lenient(text: str) -> dict:
    """容错解析小模型输出：去掉 ```json 包裹和尾逗号；整体解析不了时按字段抢救；什么都没有则抛非致命错误（该块跳过）。"""
    body = re.sub(r"^```\w*\s*|\s*```$", "", text.strip())
    body = _TRAILING_COMMA.sub(r"\1", body)
    start, end = body.find("{"), body.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(body[start: end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    data = _salvage(body)
    if not data:
        raise LLMError("本地模型没有按 JSON 格式输出")
    return data


def _salvage(body: str) -> dict:
    """逐字段抢救：summary 字符串、characters / events / foreshadowing 数组里能单独解析的对象或字符串。"""
    out: dict = {}
    m = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', body)
    if m:
        out["summary"] = _unescape(m.group(1))
    for key in ("characters", "events"):
        m = re.search(rf'"{key}"\s*:\s*\[(.*?)(?:\]\s*[,}}]|$)', body, re.S)
        if m:
            items = []
            for obj in re.findall(r"\{[^{}]*\}", m.group(1)):
                try:
                    items.append(json.loads(_TRAILING_COMMA.sub(r"\1", obj)))
                except json.JSONDecodeError:
                    continue
            if items:
                out[key] = items
    m = re.search(r'"foreshadowing"\s*:\s*\[(.*?)\]', body, re.S)
    if m:
        out["foreshadowing"] = [_unescape(s) for s in re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))]
    return out


def _unescape(s: str) -> str:
    try:
        return json.loads(f'"{s}"')
    except json.JSONDecodeError:
        return s
