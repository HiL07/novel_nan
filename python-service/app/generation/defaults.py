"""默认生成模型（Qwen2.5-1.5B-Instruct）检测：服务启动时与工作区页面调用。

找到的条件：已登记且目录存在，名称 / 来源 / 目录名为 Qwen2.5-1.5B-Instruct。
找不到时给出下载方式：页面一键下载（走 /api/local/models/download，保存到 models/base/<id>/weights/ 并自动登记），
或手动下载后在「本地模型」页登记目录。
"""
import logging
from pathlib import Path

from ..local import registry, settings

log = logging.getLogger("generation")

DEFAULT_REPO = "Qwen/Qwen2.5-1.5B-Instruct"
_KEY = "qwen2.5-1.5b-instruct"


def _matches(m: dict) -> bool:
    names = [m.get("name", ""), m.get("origin") or "", Path(m.get("path", "")).name]
    return any(_KEY in n.lower().replace("hf:qwen/", "") for n in names)


def find_default() -> dict | None:
    return next((m for m in registry.list_base() if m["exists"] and _matches(m)), None)


def status() -> dict:
    m = find_default()
    return {
        "repoId": DEFAULT_REPO,
        "found": m is not None,
        "model": {k: m[k] for k in ("id", "name", "path", "numParams")} if m else None,
        "downloadDir": str(settings.BASE_DIR),
        "links": {"huggingface": f"https://huggingface.co/{DEFAULT_REPO}",
                  "mirror": f"{settings.HF_MIRROR_ENDPOINT}/{DEFAULT_REPO}",
                  "modelscope": f"{settings.MODELSCOPE_ENDPOINT}/models/{DEFAULT_REPO}"},
    }


def check_on_startup() -> None:
    s = status()
    if s["found"]:
        log.info("默认生成模型已就绪：%s（%s）", s["model"]["name"], s["model"]["path"])
    else:
        log.warning("未找到默认生成模型 %s：可在「小说创作」工作区页面一键下载（保存到 %s），或下载后在「本地模型」页登记",
                    DEFAULT_REPO, s["downloadDir"])
