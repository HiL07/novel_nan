"""本地推理：在 API 进程内加载「基础模型 (+ 可选 LoRA 适配器)」并生成文本。

- 显存有限：同一时间只驻留一个模型；训练开始前由 jobs 调用 unload() 释放显存，训练期间拒绝加载
- 加载在后台线程进行（大模型需数十秒），状态通过 status() 查询：idle / loading / loaded / error
- torch / transformers 延迟导入：未安装训练依赖时，其余接口（文本提取等）照常可用
"""
import gc
import logging
import threading
import time

from . import hardware, registry

log = logging.getLogger("local.inference")

_lock = threading.RLock()        # 保护 _state
_gen_lock = threading.Lock()     # 生成串行（单卡）
_state: dict = {"status": "idle", "baseId": None, "adapterId": None, "quantization": None,
                "error": None, "loadedAt": None, "loadSeconds": None}
_model = None
_tokenizer = None
_gpu_busy_check = lambda: False  # 由 jobs 注入：训练进行中返回 True


def set_gpu_busy_check(fn) -> None:
    global _gpu_busy_check
    _gpu_busy_check = fn


def status() -> dict:
    with _lock:
        s = dict(_state)
    if s["status"] == "loaded" and hardware.torch_info()["cuda"]:
        import torch

        s["vramAllocatedGB"] = round(torch.cuda.memory_allocated() / hardware.GB, 2)
    return s


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


def _do_load(base: dict, adapter: dict | None, quantization: str) -> None:
    global _model, _tokenizer
    start = time.monotonic()
    try:
        model, tokenizer = load_model_and_tokenizer(base["path"], quantization)
        if adapter:
            from peft import PeftModel

            model = PeftModel.from_pretrained(model, str(registry.adapter_dir(adapter["id"])))
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
        msg = str(e) or e.__class__.__name__
        if "out of memory" in msg.lower():
            msg = f"显存不足：{msg[:200]}。可尝试 4-bit 量化、换更小的模型或关闭其他占用显存的程序"
        with _lock:
            _state.update(status="error", error=msg[:500])


def load(base_id: str, adapter_id: str | None = None, quantization: str = "auto") -> dict:
    """异步加载；立即返回当前状态。"""
    if _gpu_busy_check():
        raise RuntimeError("有训练任务正在使用 GPU，请等待完成或取消后再加载模型")
    if not hardware.deps_info()["ready"]:
        raise RuntimeError("未安装本地模型依赖（torch / transformers / peft / accelerate），见 requirements-local.txt")
    base = registry.get_base(base_id)
    if not base["exists"]:
        raise RuntimeError(f"模型目录不存在：{base['path']}")
    adapter = None
    if adapter_id:
        adapter = registry.get_adapter(adapter_id)
        if adapter["baseModel"]["id"] != base_id:
            raise RuntimeError(f"适配器「{adapter['name']}」是基于「{adapter['baseModel']['name']}」训练的，不能用于当前基础模型")
        if adapter["compat"] == "changed":
            raise RuntimeError("基础模型的 config.json 已与训练时不同，适配器可能不兼容")
    quant = resolve_quantization(quantization)
    with _lock:
        if _state["status"] == "loading":
            raise RuntimeError("已有模型正在加载，请稍候")
        unload()
        _state.update(status="loading", baseId=base_id, adapterId=adapter_id, quantization=quant,
                      error=None, loadedAt=None, loadSeconds=None)
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
    with _lock:
        if _state["status"] == "loading":
            raise RuntimeError("模型正在加载，暂时不能卸载")
        with _gen_lock:
            _free()
        _state.update(status="idle", baseId=None, adapterId=None, quantization=None, error=None,
                      loadedAt=None, loadSeconds=None)


def generate(prompt: str, *, max_new_tokens: int = 200, temperature: float = 0.8, top_p: float = 0.9,
             repetition_penalty: float = 1.1, use_chat_template: bool = False) -> dict:
    """use_chat_template=False：直接续写（风格微调后的推荐用法）；True：按对话格式提问。"""
    import torch

    with _lock:
        if _state["status"] != "loaded" or _model is None:
            raise RuntimeError("请先加载模型")
        model, tokenizer = _model, _tokenizer
    with _gen_lock:
        if use_chat_template and tokenizer.chat_template:
            text = tokenizer.apply_chat_template([{"role": "user", "content": prompt}], tokenize=False,
                                                 add_generation_prompt=True)
        else:
            text = prompt
        inputs = tokenizer(text, return_tensors="pt").to(model.device)
        start = time.monotonic()
        with torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=temperature > 0,
                                 temperature=max(temperature, 1e-5), top_p=top_p,
                                 repetition_penalty=repetition_penalty, pad_token_id=tokenizer.pad_token_id)
        new_tokens = out[0][inputs["input_ids"].shape[1]:]
        seconds = time.monotonic() - start
    return {
        "text": tokenizer.decode(new_tokens, skip_special_tokens=True),
        "promptTokens": int(inputs["input_ids"].shape[1]),
        "newTokens": int(len(new_tokens)),
        "seconds": round(seconds, 2),
        "tokensPerSecond": round(len(new_tokens) / seconds, 1) if seconds > 0 else None,
        "baseId": _state["baseId"],
        "adapterId": _state["adapterId"],
    }

