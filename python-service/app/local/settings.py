"""本地模型目录与默认参数（均可用环境变量覆盖）。

models/
├── base/<id>/model.json        基础模型登记（path 指向实际权重目录；下载的模型权重放在 base/<id>/weights/）
├── adapters/<id>/              LoRA 适配器（adapter_model.safetensors + adapter_config.json + meta.json）
└── jobs/<id>/                  后台任务（job.json 状态、progress.json 进度、job.log 日志、samples.txt 训练样本）
"""
import os
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[2]  # python-service/

MODELS_DIR = Path(os.getenv("LOCAL_MODELS_DIR", SERVICE_ROOT / "models")).resolve()
BASE_DIR = MODELS_DIR / "base"
ADAPTER_DIR = MODELS_DIR / "adapters"
JOBS_DIR = MODELS_DIR / "jobs"

for _d in (BASE_DIR, ADAPTER_DIR, JOBS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# 资源评估：显存/内存只用到可用量的这个比例，留出余量给碎片和显示
SAFETY_RATIO = float(os.getenv("LOCAL_SAFETY_RATIO", "0.9"))

# 训练样本下限（字符数），太少学不到风格
MIN_SAMPLE_CHARS = int(os.getenv("LOCAL_MIN_SAMPLE_CHARS", "500"))

# 模型下载源：auto（依次尝试 DOWNLOAD_AUTO_ORDER）/ modelscope / hf-mirror / huggingface；请求里的 source 优先
DOWNLOAD_SOURCE = os.getenv("MODEL_DOWNLOAD_SOURCE", "auto")
DOWNLOAD_AUTO_ORDER = [s.strip() for s in os.getenv("MODEL_DOWNLOAD_AUTO_ORDER", "modelscope,hf-mirror,huggingface").split(",") if s.strip()]
HF_MIRROR_ENDPOINT = os.getenv("HF_MIRROR_ENDPOINT", "https://hf-mirror.com").rstrip("/")
HF_OFFICIAL_ENDPOINT = (os.getenv("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")  # 沿用 huggingface_hub 的标准变量
MODELSCOPE_ENDPOINT = os.getenv("MODELSCOPE_ENDPOINT", "https://modelscope.cn").rstrip("/")
