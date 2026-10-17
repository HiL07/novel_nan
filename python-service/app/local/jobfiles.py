"""后台任务的文件约定（API 进程与 worker 子进程共用，不依赖 torch）。

models/jobs/<id>/
├── job.json        状态与配置：{id, kind, backend, status, config, result, error, pid, createdAt, startedAt, endedAt}
├── progress.json   训练进度：{step, maxSteps, epoch, loss, learningRate, elapsed, eta, history[]}
├── job.log         子进程 stdout/stderr
├── samples.txt     训练样本（提交时由 API 进程准备好）
└── cancel          取消标记（存在即请求停止）
"""
import json
import time
from pathlib import Path

from . import settings

STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")


def job_dir(job_id: str) -> Path:
    return settings.JOBS_DIR / job_id


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_job(job_id: str) -> dict | None:
    return read(job_dir(job_id) / "job.json")


def update_job(job_id: str, **fields) -> dict:
    path = job_dir(job_id) / "job.json"
    job = read(path) or {}
    job.update(fields)
    write(path, job)
    return job


def write_progress(job_id: str, progress: dict) -> None:
    write(job_dir(job_id) / "progress.json", progress)


def read_progress(job_id: str) -> dict | None:
    return read(job_dir(job_id) / "progress.json")


def cancel_requested(job_id: str) -> bool:
    return (job_dir(job_id) / "cancel").exists()


def tail_log(job_id: str, lines: int = 200) -> str:
    path = job_dir(job_id) / "job.log"
    try:
        data = path.read_bytes()[-256 * 1024:]
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    # tqdm 等用 \r 刷新同一行，只保留每行最后一次刷新
    text = "\n".join(seg.split("\r")[-1] for seg in text.split("\n"))
    return "\n".join(text.splitlines()[-lines:])
