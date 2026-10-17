"""后台任务管理：每个任务（训练 / 下载）是一个独立子进程 `python -m app.local.worker <jobId>`。

- 子进程结束即释放显存和内存，API 进程保持响应；日志写入 models/jobs/<id>/job.log
- 单卡单任务：同一时间只允许一个任务运行；训练开始前卸载推理模型
- 状态由 worker 写入 job.json；子进程异常退出未写状态时，由监视线程补记 failed
- 服务重启后：仍在运行的 worker 继续跑（状态照常更新），已不存在的标记为 failed
"""
import ctypes
import logging
import os
import subprocess
import sys
import threading
import time
import uuid

from . import inference, jobfiles, settings

log = logging.getLogger("local.jobs")

ACTIVE = ("queued", "running")
_lock = threading.Lock()


class JobError(RuntimeError):
    pass


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if sys.platform == "win32":
        # 注意：Windows 上 os.kill(pid, 0) 会直接结束进程，不能用来探测
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def list_jobs(limit: int = 50) -> list[dict]:
    jobs = []
    for f in settings.JOBS_DIR.glob("*/job.json"):
        job = jobfiles.read(f)
        if job:
            job["progress"] = jobfiles.read_progress(job["id"])
            jobs.append(job)
    return sorted(jobs, key=lambda j: j.get("createdAt", ""), reverse=True)[:limit]


def get_job(job_id: str) -> dict:
    job = jobfiles.read_job(job_id)
    if job is None:
        raise JobError(f"任务不存在：{job_id}")
    job["progress"] = jobfiles.read_progress(job_id)
    return job


def active_job() -> dict | None:
    for job in list_jobs():
        if job["status"] in ACTIVE:
            return job
    return None


def gpu_busy() -> bool:
    job = active_job()
    return bool(job and job["kind"] == "train")


inference.set_gpu_busy_check(gpu_busy)


def recover() -> None:
    """服务启动时调用：worker 已不存在的进行中任务标记为 failed。"""
    for job in list_jobs(limit=1000):
        if job["status"] in ACTIVE and not pid_alive(job.get("pid")):
            jobfiles.update_job(job["id"], status="failed", endedAt=jobfiles.now(),
                                error=job.get("error") or "服务重启时任务进程已不存在（被中断）")


def create(kind: str, config: dict, *, samples: str | None = None, backend: str = "local") -> dict:
    """建任务目录并启动 worker。samples：训练样本文本（训练任务）。"""
    with _lock:
        running = active_job()
        if running:
            raise JobError(f"已有任务在进行中（{running['kind']} {running['id']}），请等待完成或取消后再试")
        if kind == "train":
            inference.unload()  # 释放推理模型占用的显存
        job_id = f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
        d = jobfiles.job_dir(job_id)
        d.mkdir(parents=True)
        if samples is not None:
            (d / "samples.txt").write_text(samples, encoding="utf-8")
        job = {"id": job_id, "kind": kind, "backend": backend, "status": "queued", "config": config,
               "result": None, "error": None, "pid": None, "createdAt": jobfiles.now(),
               "startedAt": None, "endedAt": None}
        jobfiles.write(d / "job.json", job)
        _spawn(job_id)
        return get_job(job_id)


def _spawn(job_id: str) -> None:
    d = jobfiles.job_dir(job_id)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
           # Windows 上减少显存碎片导致的 OOM
           "PYTORCH_CUDA_ALLOC_CONF": os.environ.get("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")}
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if sys.platform == "win32" else 0
    logf = open(d / "job.log", "ab")  # noqa: SIM115 —— 由监视线程在进程结束后关闭
    proc = subprocess.Popen([sys.executable, "-m", "app.local.worker", job_id], cwd=str(settings.SERVICE_ROOT),
                            stdout=logf, stderr=subprocess.STDOUT, env=env, creationflags=flags)
    jobfiles.update_job(job_id, pid=proc.pid)
    log.info("任务已启动 %s pid=%s", job_id, proc.pid)

    def watch() -> None:
        code = proc.wait()
        logf.close()
        job = jobfiles.read_job(job_id) or {}
        if job.get("status") in ACTIVE:
            if jobfiles.cancel_requested(job_id):
                jobfiles.update_job(job_id, status="cancelled", endedAt=jobfiles.now())
            else:
                tail = jobfiles.tail_log(job_id, 15)
                jobfiles.update_job(job_id, status="failed", endedAt=jobfiles.now(),
                                    error=f"任务进程异常退出（code {code}）。日志末尾：\n{tail}"[-2000:])
        log.info("任务结束 %s code=%s status=%s", job_id, code, (jobfiles.read_job(job_id) or {}).get("status"))

    threading.Thread(target=watch, daemon=True, name=f"watch-{job_id}").start()


def cancel(job_id: str) -> dict:
    job = get_job(job_id)
    if job["status"] not in ACTIVE:
        raise JobError("任务已结束，无需取消")
    (jobfiles.job_dir(job_id) / "cancel").touch()
    pid = job.get("pid")
    if not pid_alive(pid):
        jobfiles.update_job(job_id, status="cancelled", endedAt=jobfiles.now())
    elif job["kind"] != "train":
        _terminate(pid)  # 下载可直接结束；训练先等它在当前 step 结束后优雅退出
    else:
        def force_kill() -> None:
            time.sleep(90)
            if pid_alive(pid):
                log.warning("训练未在 90s 内响应取消，强制结束 pid=%s", pid)
                _terminate(pid)

        threading.Thread(target=force_kill, daemon=True).start()
    return get_job(job_id)


def _terminate(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        os.kill(pid, 9)
