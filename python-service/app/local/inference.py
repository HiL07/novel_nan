"""本地推理：在 API 进程内加载「基础模型 (+ 可选 LoRA 适配器)」并生成文本。

- 显存有限：同一时间只驻留一个模型；训练开始前由 jobs 调用 unload() 释放显存，训练期间拒绝加载
- 加载在后台线程进行（大模型需数十秒），状态通过 status() 查询：idle / loading / loaded / error
- torch / transformers 延迟导入：未安装训练依赖时，其余接口（文本提取等）照常可用
- 适配器切换不重载基础模型：同一基础模型 + 量化已驻留时，只挂载 / 启用 / 停用适配器（attachedAdapterId = 已挂载，
  adapterId = 当前启用；停用时生成在 PeftModel.disable_adapter() 中进行，即纯基础模型输出）
"""
import contextlib
import gc
import logging
import threading
import time

from . import hardware, registry

log = logging.getLogger("local.inference")

_lock = threading.RLock()        # 保护 _state
_gen_lock = threading.Lock()     # 生成串行（单卡）
_state: dict = {"status": "idle", "baseId": None, "adapterId": None, "attachedAdapterId": None, "quantization": None,
                "error": None, "loadedAt": None, "loadSeconds": None}
_model = None
_tokenizer = None
_gpu_busy_check = lambda: False  # 由 jobs 注入：训练进行中返回 True
_generation_busy_check = lambda: False  # 由 generation 注入：小说章节生成进行中返回 True


def set_gpu_busy_check(fn) -> None:
    global _gpu_busy_check
    _gpu_busy_check = fn


def set_generation_busy_check(fn) -> None:
    global _generation_busy_check
    _generation_busy_check = fn


def status() -> dict:
    with _lock:
        s = dict(_state)
    if s["status"] == "loaded" and hardware.torch_info()["cuda"]:
        import torch

        s["vramAllocatedGB"] = round(torch.cuda.memory_allocated() / hardware.GB, 2)
    return s


def resident_vram_gb() -> float:
    """本服务中驻留模型占用的显存（PyTorch 已保留的部分，卸载后可回收）；未加载为 0。"""
    with _lock:
        if _model is None:
            return 0.0
    import torch

    return torch.cuda.memory_reserved() / hardware.GB if torch.cuda.is_available() else 0.0


def resolve_quantization(quantization: str) -> str:
    """auto：有 CUDA 且装了 bitsandbytes → 4bit，否则 none。"""
    if quantization != "auto":
        return quantization
    deps = hardware.deps_info()
    return "4bit" if deps["torch"]["cuda"] and deps["qloraReady"] else "none"


def load_model_and_tokenizer(model_path: str, quantization: str):
    """训练与推理共用的加载逻辑。quantization: "4bit" | "none"。"""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tinfo = hardware.torch_info()
    compute_dtype = torch.bfloat16 if tinfo["bf16"] else torch.float16
    kwargs = {"low_cpu_mem_usage": True, "trust_remote_code": False}
    if tinfo["cuda"]:
        kwargs["device_map"] = {"": 0}
        if quantization == "4bit":
            from transformers import BitsAndBytesConfig

            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=compute_dtype)
        else:
            kwargs["torch_dtype"] = compute_dtype
    else:
        if quantization == "4bit":
            raise RuntimeError("4-bit 量化需要 CUDA GPU")
        kwargs["torch_dtype"] = torch.float32
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_path, **kwargs)
    return model, tokenizer


def _load_error(e: Exception) -> str:
    msg = str(e) or e.__class__.__name__
    if "out of memory" in msg.lower():
        msg = f"显存不足：{msg[:200]}。可尝试 4-bit 量化、换更小的模型或关闭其他占用显存的程序"
    elif "paging file" in msg.lower() or "页面文件" in msg or isinstance(e, MemoryError):
        msg = f"内存不足（加载权重时系统内存 / 虚拟内存耗尽）：{msg[:200]}。请关闭占内存的程序后重试"
    return msg[:500]


def _attach(model, adapter: dict):
    """把适配器挂到已加载的模型上（已有其他适配器时先移除，基础权重不重载）。返回新的模型对象。"""
    from peft import PeftModel

    if isinstance(model, PeftModel):
        model = model.unload()  # 去掉 LoRA 层、不合并，得到原基础模型
    model = PeftModel.from_pretrained(model, str(registry.adapter_dir(adapter["id"])))
    model.eval()
    return model


def _do_load(base: dict, adapter: dict | None, quantization: str) -> None:
    global _model, _tokenizer
    start = time.monotonic()
    try:
        model, tokenizer = load_model_and_tokenizer(base["path"], quantization)
        if adapter:
            model = _attach(model, adapter)
        model.eval()
        with _lock:
            _model, _tokenizer = model, tokenizer
            _state.update(status="loaded", error=None, loadedAt=time.strftime("%Y-%m-%d %H:%M:%S"),
                          loadSeconds=round(time.monotonic() - start, 1))
        log.info("模型已加载 base=%s adapter=%s quant=%s %.1fs", base["id"], adapter and adapter["id"],
                 quantization, time.monotonic() - start)
    except Exception as e:  # noqa: BLE001 —— 任何加载失败都要落到 error 状态给前端看
        log.exception("模型加载失败 base=%s", base["id"])
        _free()
        with _lock:
            _state.update(status="error", error=_load_error(e), adapterId=None, attachedAdapterId=None)


def _do_attach(adapter: dict) -> None:
    global _model
    start = time.monotonic()
    try:
        with _gen_lock:
            model = _attach(_model, adapter)
        with _lock:
            _model = model
            _state.update(status="loaded", error=None, loadSeconds=round(time.monotonic() - start, 1))
        log.info("适配器已挂载 %s %.1fs", adapter["id"], time.monotonic() - start)
    except Exception as e:  # noqa: BLE001
        log.exception("适配器挂载失败 %s", adapter["id"])
        # 挂载失败时 PEFT 可能已改动模型结构，不再信任当前模型：整体释放，需重新加载
        _free()
        with _lock:
            _state.update(status="error", error="适配器挂载失败，已释放模型，请重新加载：" + _load_error(e),
                          adapterId=None, attachedAdapterId=None)


def check_adapter(adapter_id: str, base_id: str) -> dict:
    """适配器能否用于该基础模型（不兼容时抛出明确原因）。远程训练的适配器以 registry 校验出的 matchedBaseId 为准。"""
    adapter = registry.get_adapter(adapter_id)
    trained_on = adapter.get("baseModel") or {}
    compat = adapter.get("compat")
    if trained_on.get("source") == "remote":
        reasons = {
            "unverified": "本地基础模型的 config 与训练时一致，但尚未校验权重指纹（请先校验基础模型权重）",
            "changed": "本地基础模型权重与训练时使用的官方权重不一致",
            "remote-only": f"本地没有与训练时一致的基础模型「{trained_on.get('name')}」（需相同 config 与权重）",
        }
        if compat != "ok":
            raise RuntimeError(f"适配器「{adapter['name']}」不能加载：{reasons.get(compat, compat)}")
        if adapter["matchedBaseId"] != base_id:
            raise RuntimeError(f"适配器「{adapter['name']}」是基于「{trained_on.get('name')}」训练的，"
                               f"只能与已校验一致的本地模型 {adapter['matchedBaseId']} 一起加载")
        return adapter
    if trained_on.get("id") != base_id:
        raise RuntimeError(f"适配器「{adapter['name']}」是基于「{trained_on.get('name')}」训练的，不能用于当前基础模型")
    if compat == "changed":
        raise RuntimeError("基础模型的 config.json 已与训练时不同，适配器可能不兼容")
    if compat == "missing":
        raise RuntimeError("适配器训练时使用的基础模型已不存在")
    return adapter


def load(base_id: str, adapter_id: str | None = None, quantization: str = "auto") -> dict:
    """异步加载；立即返回当前状态。同一基础模型 + 量化已加载时只切换适配器，不重载基础模型。"""
    if _gpu_busy_check():
        raise RuntimeError("有训练任务正在使用 GPU，请等待完成或取消后再加载模型")
    if _generation_busy_check():
        raise RuntimeError("小说章节正在生成，请等待完成或取消后再切换模型")
    if not hardware.deps_info()["ready"]:
        raise RuntimeError("未安装本地模型依赖（torch / transformers / peft / accelerate），见 requirements-local.txt")
    base = registry.get_base(base_id)
    if not base["exists"]:
        raise RuntimeError(f"模型目录不存在：{base['path']}")
    adapter = check_adapter(adapter_id, base_id) if adapter_id else None
    quant = resolve_quantization(quantization)
    with _lock:
        if _state["status"] == "loading":
            raise RuntimeError("已有模型正在加载，请稍候")
        same_base = (_state["status"] == "loaded" and _model is not None and _state["baseId"] == base_id
                     and _state["quantization"] == quant)
        if same_base and (adapter_id is None or adapter_id == _state["attachedAdapterId"]):
            if not _gen_lock.acquire(timeout=0.5):
                raise RuntimeError("正在生成文本，请等待完成后再切换适配器")
            try:
                _state.update(adapterId=adapter_id, error=None)  # 只切换启用状态：无需重载
            finally:
                _gen_lock.release()
            return {**status(), "switched": True}
        if same_base:
            _state.update(status="loading", adapterId=adapter_id, attachedAdapterId=adapter_id, error=None)
            threading.Thread(target=_do_attach, args=(adapter,), daemon=True, name="adapter-attach").start()
            return {**status(), "switched": True}
        unload()
        _state.update(status="loading", baseId=base_id, adapterId=adapter_id, attachedAdapterId=adapter_id,
                      quantization=quant, error=None, loadedAt=None, loadSeconds=None)
    threading.Thread(target=_do_load, args=(base, adapter, quant), daemon=True, name="model-load").start()
    return status()


def _free() -> None:
    global _model, _tokenizer
    _model, _tokenizer = None, None
    gc.collect()
    if hardware.torch_info()["cuda"]:
        import torch

        torch.cuda.empty_cache()


def unload() -> None:
    if _generation_busy_check():
        raise RuntimeError("小说章节正在生成，请等待完成或取消后再卸载模型 / 开始训练")
    with _lock:
        if _state["status"] == "loading":
            raise RuntimeError("模型正在加载，暂时不能卸载")
        with _gen_lock:
            _free()
        _state.update(status="idle", baseId=None, adapterId=None, attachedAdapterId=None, quantization=None, error=None,
                      loadedAt=None, loadSeconds=None)


def _adapter_scope(model, use_adapter: bool):
    """use_adapter=False 且模型挂着适配器时，在停用适配器的上下文中生成（= 纯基础模型）。"""
    if not use_adapter and hasattr(model, "disable_adapter"):
        return model.disable_adapter()
    return contextlib.nullcontext()


def generate(prompt: str, *, max_new_tokens: int = 200, temperature: float = 0.8, top_p: float = 0.9,
             repetition_penalty: float = 1.1, use_chat_template: bool = False, use_adapter: bool | None = None,
             seed: int | None = None) -> dict:
    """use_chat_template=False：直接续写（风格微调后的推荐用法）；True：按对话格式提问。
    use_adapter：None = 按当前启用状态；True / False = 本次强制启用 / 停用已挂载的适配器（对照生成用）。
    seed：固定采样种子，便于同一提示词的基础模型 / 微调模型对照。"""
    import torch

    with _lock:
        if _state["status"] != "loaded" or _model is None:
            raise RuntimeError("请先加载模型")
        model, tokenizer = _model, _tokenizer
        attached = _state["attachedAdapterId"]
        active = _state["adapterId"] is not None if use_adapter is None else use_adapter
        if active and not attached:
            raise RuntimeError("当前没有挂载适配器，请先加载适配器")
        base_id = _state["baseId"]
    with _gen_lock:
        if use_chat_template and tokenizer.chat_template:
            text = tokenizer.apply_chat_template([{"role": "user", "content": prompt}], tokenize=False,
                                                 add_generation_prompt=True)
        else:
            text = prompt
        inputs = tokenizer(text, return_tensors="pt").to(model.device)
        if seed is not None:
            torch.manual_seed(seed)
        start = time.monotonic()
        try:
            with torch.inference_mode(), _adapter_scope(model, active):
                out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=temperature > 0,
                                     temperature=max(temperature, 1e-5), top_p=top_p,
                                     repetition_penalty=repetition_penalty, pad_token_id=tokenizer.pad_token_id)
        except torch.cuda.OutOfMemoryError as e:
            torch.cuda.empty_cache()
            raise RuntimeError("生成时显存不足：请减少生成长度或缩短提示词") from e
        new_tokens = out[0][inputs["input_ids"].shape[1]:]
        seconds = time.monotonic() - start
    return {
        "text": tokenizer.decode(new_tokens, skip_special_tokens=True),
        "promptTokens": int(inputs["input_ids"].shape[1]),
        "newTokens": int(len(new_tokens)),
        "seconds": round(seconds, 2),
        "tokensPerSecond": round(len(new_tokens) / seconds, 1) if seconds > 0 else None,
        "baseId": base_id,
        "adapterId": attached if active else None,
        "seed": seed,
    }


def compare(prompt: str, *, seed: int = 1234, **kw) -> dict:
    """同一提示词、同一种子：先停用适配器（基础模型），再启用适配器（微调模型）各生成一次。基础模型只驻留一份。"""
    with _lock:
        if not _state["attachedAdapterId"]:
            raise RuntimeError("对照生成需要先加载带适配器的模型")
    return {"base": generate(prompt, use_adapter=False, seed=seed, **kw),
            "adapter": generate(prompt, use_adapter=True, seed=seed, **kw)}



def loaded_model() -> dict | None:
    """当前已加载的模型信息（未加载返回 None）。"""
    with _lock:
        if _state["status"] != "loaded" or _model is None:
            return None
        return {"baseId": _state["baseId"], "adapterId": _state["adapterId"], "quantization": _state["quantization"]}


def chat_generate(messages: list[dict], *, max_new_tokens: int, temperature: float = 0.7, top_p: float = 0.8,
                  top_k: int = 20, repetition_penalty: float = 1.1, stop_event: threading.Event | None = None) -> dict:
    """按聊天模板生成（支持 system 消息）。stop_event 被置位时在下一个 token 处停止。

    返回 {text, promptTokens, completionTokens, finishReason: stop|length|cancelled, seconds}
    """
    import torch
    from transformers import StoppingCriteria, StoppingCriteriaList

    with _lock:
        if _state["status"] != "loaded" or _model is None:
            raise RuntimeError("请先加载模型")
        model, tokenizer = _model, _tokenizer
        use_adapter = _state["adapterId"] is not None

    class _Cancel(StoppingCriteria):
        def __call__(self, input_ids, scores, **kwargs):
            return bool(stop_event and stop_event.is_set())

    with _gen_lock:
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors="pt").to(model.device)
        start = time.monotonic()
        with torch.inference_mode(), _adapter_scope(model, use_adapter):
            out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=temperature > 0,
                                 temperature=max(temperature, 1e-5), top_p=top_p, top_k=top_k,
                                 repetition_penalty=repetition_penalty, pad_token_id=tokenizer.pad_token_id,
                                 stopping_criteria=StoppingCriteriaList([_Cancel()]))
        new_tokens = out[0][inputs["input_ids"].shape[1]:]
        seconds = time.monotonic() - start
    eos_ids = model.generation_config.eos_token_id
    eos_ids = set(eos_ids if isinstance(eos_ids, list) else [eos_ids]) | {tokenizer.eos_token_id}
    if stop_event and stop_event.is_set():
        reason = "cancelled"
    elif len(new_tokens) and int(new_tokens[-1]) in eos_ids:
        reason = "stop"
    else:
        reason = "length" if len(new_tokens) >= max_new_tokens else "stop"
    return {
        "text": tokenizer.decode(new_tokens, skip_special_tokens=True),
        "promptTokens": int(inputs["input_ids"].shape[1]),
        "completionTokens": int(len(new_tokens)),
        "finishReason": reason,
        "seconds": round(seconds, 2),
    }
