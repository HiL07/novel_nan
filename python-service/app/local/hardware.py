"""硬件与依赖探测 + 资源估算。

探测不导入 torch（nvidia-smi + 系统 API），API 进程常驻时开销小；依赖版本用 importlib.metadata 读取。
估算偏保守：宁可提示「可能超出」，也不要让训练跑到一半 OOM。
"""
import ctypes
import functools
import importlib.metadata as md
import shutil
import subprocess
import sys

from . import settings

GB = 1024 ** 3


def gpu_info() -> dict | None:
    """第一块 NVIDIA GPU：{name, totalGB, usedGB, freeGB, driver}；没有则 None。"""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,memory.used,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip().splitlines()[0]
        name, total, used, driver = [s.strip() for s in out.split(",")]
        total_gb, used_gb = float(total) / 1024, float(used) / 1024
        return {"name": name, "totalGB": round(total_gb, 2), "usedGB": round(used_gb, 2),
                "freeGB": round(total_gb - used_gb, 2), "driver": driver}
    except (subprocess.SubprocessError, OSError, ValueError, IndexError):
        return None


def ram_info() -> dict:
    """系统内存 {totalGB, freeGB}。"""
    if sys.platform == "win32":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = MemoryStatus()
        st.dwLength = ctypes.sizeof(MemoryStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
        return {"totalGB": round(st.ullTotalPhys / GB, 2), "freeGB": round(st.ullAvailPhys / GB, 2)}
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
        return {"totalGB": round(info["MemTotal"] / GB, 2), "freeGB": round(info["MemAvailable"] / GB, 2)}
    except (OSError, KeyError, ValueError):
        return {"totalGB": 0, "freeGB": 0}


def disk_free_gb(path=None) -> float:
    return round(shutil.disk_usage(path or settings.MODELS_DIR).free / GB, 2)


def _version(pkg: str) -> str | None:
    try:
        return md.version(pkg)
    except md.PackageNotFoundError:
        return None


@functools.lru_cache(maxsize=1)
def torch_info() -> dict:
    """首次调用会导入 torch（约 1~2 秒），结果缓存。"""
    if not _version("torch"):
        return {"installed": False, "cuda": False, "bf16": False, "cudaVersion": None}
    import torch

    cuda = torch.cuda.is_available()
    return {"installed": True, "cuda": cuda, "bf16": bool(cuda and torch.cuda.is_bf16_supported()),
            "cudaVersion": torch.version.cuda}


def deps_info() -> dict:
    pkgs = ["torch", "transformers", "peft", "accelerate", "bitsandbytes", "safetensors", "huggingface_hub"]
    versions = {p: _version(p) for p in pkgs}
    ready = all(versions[p] for p in ["torch", "transformers", "peft", "accelerate", "safetensors"])
    return {
        "versions": versions,
        "ready": ready,
        "qloraReady": ready and bool(versions["bitsandbytes"]),
        "torch": torch_info() if versions["torch"] else {"installed": False, "cuda": False, "bf16": False, "cudaVersion": None},
    }


def system_info() -> dict:
    return {"gpu": gpu_info(), "ram": ram_info(), "diskFreeGB": disk_free_gb(), "deps": deps_info(),
            "modelsDir": str(settings.MODELS_DIR)}


# ---------------------------------------------------------------- 资源估算

def _arch(model: dict) -> dict:
    a = model.get("arch") or {}
    return {"hidden": a.get("hidden_size") or 2048, "layers": a.get("num_hidden_layers") or 24,
            "vocab": a.get("vocab_size") or 32000}


def estimate(model: dict, mode: str, *, quantization: str = "4bit", seq_len: int = 512, batch_size: int = 1,
             lora_r: int = 16) -> dict:
    """估算显存 / 内存需求并与当前可用量比较。

    mode: "infer" | "train"；quantization: "4bit"（QLoRA / 4-bit 推理）| "none"（bf16/fp16）
    返回 {level: ok|warn|exceed, vramNeedGB, vramFreeGB, ramNeedGB, ramFreeGB, messages[]}
    """
    params = model.get("numParams") or 0
    a = _arch(model)
    gpu, ram = gpu_info(), ram_info()
    msgs: list[str] = []

    weights = params * (0.6 if quantization == "4bit" else 2.0) / GB  # 4-bit 约 0.5 字节/参数 + 量化常量
    cuda_ctx = 0.6
    if mode == "infer":
        kv = 2 * a["layers"] * a["hidden"] * 2048 * 2 / GB  # 2k 上下文 KV cache（未考虑 GQA，偏保守）
        vram_need = weights + cuda_ctx + kv + 0.3
    else:
        tokens = seq_len * batch_size
        # 梯度检查点下的激活 + fp32 logits（大词表模型的主要开销）+ LoRA 参数/梯度/优化器
        acts = tokens * a["hidden"] * a["layers"] * 2 * 4 / GB
        logits = tokens * a["vocab"] * 4 * 3 / GB
        lora = 7 * 2 * a["layers"] * a["hidden"] * lora_r * 16 / GB
        vram_need = weights + cuda_ctx + acts + logits + lora + 0.5
    # 加载时内存峰值：最大分片（4-bit 量化逐片进行）或整模型（不量化时 CPU 中转）+ torch 运行时
    shard = (model.get("maxShardBytes") or model.get("sizeBytes") or 0) / GB
    ram_need = (shard if quantization == "4bit" else (model.get("sizeBytes") or 0) / GB * 0.6) + 1.5

    level = "ok"
    if gpu is None:
        level = "exceed"
        msgs.append("未检测到 NVIDIA GPU，无法在本机进行训练 / GPU 推理")
    else:
        if vram_need > gpu["freeGB"] * settings.SAFETY_RATIO:
            level = "exceed"
            msgs.append(f"预计需要显存 {vram_need:.1f} GB，当前可用约 {gpu['freeGB']:.1f} GB（{gpu['name']}，"
                        f"其中 {gpu['usedGB']:.1f} GB 已被其他程序占用）")
        elif vram_need > gpu["freeGB"] * 0.75:
            level = "warn"
            msgs.append(f"预计显存 {vram_need:.1f} GB，接近可用上限 {gpu['freeGB']:.1f} GB，建议关闭其他占用显存的程序或减小序列长度")
    if ram_need > ram["totalGB"] * 0.8:
        level = "exceed"
        msgs.append(f"加载预计需要内存 {ram_need:.1f} GB，超过本机内存（{ram['totalGB']:.0f} GB）的安全范围")
    elif ram_need > ram["freeGB"]:
        level = "warn" if level == "ok" else level
        msgs.append(f"加载预计需要内存 {ram_need:.1f} GB，当前空闲仅 {ram['freeGB']:.1f} GB，会使用虚拟内存而变慢；建议先关闭浏览器标签等占内存程序")
    if mode == "train" and quantization == "4bit" and not deps_info()["qloraReady"]:
        level = "exceed"
        msgs.append("未安装 bitsandbytes，无法使用 QLoRA（4-bit）；请安装或改用 LoRA")
    if not msgs:
        msgs.append(f"资源充足：预计显存 {vram_need:.1f} GB / 可用 {gpu['freeGB']:.1f} GB")
    return {
        "level": level,
        "vramNeedGB": round(vram_need, 2),
        "vramFreeGB": gpu["freeGB"] if gpu else 0,
        "ramNeedGB": round(ram_need, 2),
        "ramFreeGB": ram["freeGB"],
        "messages": msgs,
    }
