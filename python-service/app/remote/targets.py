"""远程机器配置（手工维护的 JSON，不提供编辑接口）。

默认位置 models/remote/targets.json（REMOTE_TARGETS_FILE 可覆盖），models/ 已被 git 忽略。格式：
{"targets": [{
  "id": "autodl", "name": "...", "host": "...", "port": 14597, "user": "root",
  "keyPath": "C:/Users/<you>/.ssh/id_rsa",          # 只记私钥文件路径，不存私钥内容 / 密码
  "knownHosts": "C:/Users/<you>/.ssh/known_hosts",  # 主机密钥须事先人工核实后写入
  "python": "/root/autodl-tmp/venvs/qlora/bin/python", "workDir": "/root/autodl-tmp/nan_novel",
  "env": {"HF_HOME": "...", "TMPDIR": "..."},
  "models": [{"id": "...", "name": "...", "repoId": "Qwen/...", "source": "modelscope", "path": "/root/...",
              "manifest": "/root/.../xxx.manifest.json"}]   # manifest：下载时保存的官方文件清单（含 Revision / Sha256）
}]}
"""
import json
import os
from pathlib import Path

from ..local import settings

TARGETS_FILE = Path(os.getenv("REMOTE_TARGETS_FILE") or settings.MODELS_DIR / "remote" / "targets.json")
_SECRET_KEYS = ("password", "passphrase", "privateKey", "token")


class TargetError(ValueError):
    pass


def _load() -> list[dict]:
    if not TARGETS_FILE.exists():
        return []
    data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    targets = data.get("targets", [])
    for t in targets:
        bad = [k for k in t if k in _SECRET_KEYS]
        if bad:
            raise TargetError(f"targets.json 中不允许保存敏感字段：{', '.join(bad)}（只能写私钥文件路径 keyPath）")
    return targets


def list_targets() -> list[dict]:
    return _load()


def get(target_id: str) -> dict:
    for t in _load():
        if t["id"] == target_id:
            return t
    raise TargetError(f"远程机器不存在：{target_id}（见 {TARGETS_FILE}）")


def get_model(target: dict, model_id: str) -> dict:
    for m in target.get("models", []):
        if m["id"] == model_id:
            return m
    raise TargetError(f"远程机器「{target['id']}」上没有登记模型：{model_id}")


def public_view(t: dict) -> dict:
    """给前端看的只读信息：不含私钥路径以外的任何本机文件细节。"""
    return {"id": t["id"], "name": t.get("name") or t["id"], "host": t["host"], "port": t["port"], "user": t["user"],
            "workDir": t.get("workDir"), "python": t.get("python"),
            "keyFile": Path(t.get("keyPath", "")).name or None,
            "models": [{k: m.get(k) for k in ("id", "name", "repoId", "source", "path")} for m in t.get("models", [])]}
