"""从 Hugging Face 下载基础模型到 models/base/<id>/weights/（在 worker 子进程中运行），完成后自动登记。"""
import shutil
import time

from . import hardware, registry, settings

ALLOW = ["*.json", "*.safetensors", "*.txt", "*.model", "*.tiktoken", "*.jinja", "tokenizer*"]
MIRROR = "https://hf-mirror.com"


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run(job: dict) -> dict:
    from fnmatch import fnmatch

    from huggingface_hub import HfApi, snapshot_download

    cfg = job["config"]
    repo, model_id = cfg["repoId"], cfg["modelId"]
    endpoint = MIRROR if cfg.get("useMirror") else None
    target = settings.BASE_DIR / model_id / "weights"

    info = HfApi(endpoint=endpoint).model_info(repo, files_metadata=True)
    files = [s for s in info.siblings if any(fnmatch(s.rfilename, p) for p in ALLOW)]
    size_gb = sum(s.size or 0 for s in files) / hardware.GB
    free_gb = hardware.disk_free_gb(settings.MODELS_DIR)
    _log(f"{repo}：{len(files)} 个文件，约 {size_gb:.2f} GB；目标磁盘剩余 {free_gb:.1f} GB")
    if size_gb + 2 > free_gb:
        raise RuntimeError(f"磁盘空间不足：需要约 {size_gb:.1f} GB（另留 2 GB 余量），{settings.MODELS_DIR} 所在磁盘仅剩 {free_gb:.1f} GB。"
                           "可设置环境变量 LOCAL_MODELS_DIR 指向空间更大的磁盘，或把模型下载到别处后用「登记本地模型」")
    try:
        snapshot_download(repo, local_dir=str(target), allow_patterns=ALLOW, endpoint=endpoint)
        rec = registry.register_base(cfg["name"], str(target), origin=f"hf:{repo}", model_id=model_id)
    except Exception:
        shutil.rmtree(settings.BASE_DIR / model_id, ignore_errors=True)  # 磁盘紧张，失败不保留残缺文件
        raise
    _log(f"下载完成并已登记：{rec['name']}（{rec['numParams'] / 1e9:.2f}B 参数）")
    return {"baseId": model_id}
