"""服务配置：全部可用环境变量覆盖。模型地址/密钥不在这里，由 Java 后端的「模型配置」随请求传入。"""
import os
from pathlib import Path

# 共享数据目录（与 Java 相同的 data/，约定见 data/README.md）：默认 <项目根>/data，可用 DATA_DIR 覆盖（Docker 中为 /data）。
# Python 在其中只写 novels/（AI 生成的小说）；上传文件与提取结果由 Java 管理。模型权重不在这里（见 app/local/settings.py）
DATA_DIR = Path(os.getenv("DATA_DIR") or Path(__file__).resolve().parents[2] / "data").resolve()

# Java 文件管理后端（文件的唯一数据源，按 fileId 读取）。日常 8022；测试设 JAVA_BACKEND_URL=http://localhost:8012
# 本服务端口由 uvicorn --port 指定：日常 8021，测试 8011
JAVA_BACKEND_URL = os.getenv("JAVA_BACKEND_URL", "http://localhost:8022").rstrip("/")

# 每块最大字数：兼顾小上下文模型（本地 7B 约 2 万 token）与摘要粒度
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "6000"))

# 单块生成上限与单次请求超时
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1024"))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "180"))

# 支持提取的扩展名
SUPPORTED_EXTS = {"txt", "md", "docx", "pdf"}
