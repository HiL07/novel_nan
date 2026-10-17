"""服务配置：全部可用环境变量覆盖。"""
import os

# Java 文件管理后端（文件的唯一数据源，按 fileId 读取）
JAVA_BACKEND_URL = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080").rstrip("/")

# 本地千问 llama.cpp 服务（OpenAI 兼容接口），见 ~/.claude/skills/qwen/SKILL.md
QWEN_URL = os.getenv("QWEN_URL", "http://127.0.0.1:8001").rstrip("/")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen2.5-7b-instruct")

# 每块最大字数：模型上下文约 19968 token，6000 字留足 prompt + 输出余量
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "6000"))

# 单块生成上限与超时（约 20~24 token/s）
QWEN_MAX_TOKENS = int(os.getenv("QWEN_MAX_TOKENS", "1024"))
QWEN_TIMEOUT = float(os.getenv("QWEN_TIMEOUT", "300"))

# 支持提取的扩展名
SUPPORTED_EXTS = {"txt", "md", "docx", "pdf"}
