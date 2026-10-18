"""后台任务管理：每个任务（训练 / 下载）是一个独立子进程 `python -m app.local.worker <jobId>`。

- 子进程结束即释放显存和内存，API 进程保持响应；日志写入 models/jobs/<id>/job.log
- 通道（lane）调度：每个任务属于一个通道，通道内按创建顺序排队，同时最多运行 LANE_LIMITS 个
  · local-gpu：本机训练（占 GPU；开始前卸载推理模型，章节生成进行中则继续排队）
  · local-io：模型下载
  · <backend>:<targetId>：远程执行（如 remote:autodl），不占本机 GPU，不阻塞本地推理 / 生成
- 排队中 = status "queued" 且尚未分配进程（无 pid）；已分配进程 = 占用通道名额
- 进程归属：pid 与进程启动时间（pidStart）成对记录，防止 pid 被系统复用后误判为「仍在运行」
- 状态由 worker 写入 job.json；子进程异常退出未写状态时，由监视线程 / 调度线程补记 failed
- 服务重启后：仍在运行的 worker 继续跑（调度线程接管收尾）；已不存在的标记为 failed，
  RESUMABLE_BACKENDS 中的后端（远程执行）改为重新拉起 worker 接管，由执行器核对远程真实状态
- 同一个 models/ 目录只允许一个 API 进程使用（调度器不跨进程加锁）
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
LANE_LIMITS = {"local-gpu": 1, "local-io": 1}  # 未列出的通道（远程）默认 1
MAX_WAITING_PER_LANE = int(os.getenv("LOCAL_MAX_QUEUED", "5"))
RESUMABLE_BACKENDS: set[str] = {"remote"}  # 进程丢失后应重新接管而不是判失败的后端（执行器自行核对远程状态）
TICK_SECONDS = 5

_lock = threading.RLock()
_watched: set[str] = set()  # 本进程启动、由监视线程负责收尾的任务
_scheduler_started = False


class JobError(RuntimeError):
    pass


# ---------------------------------------------------------------- 进程探测

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


def process_start_time(pid: int | None) -> int | None:
    """进程启动时间（Windows：FILETIME 100ns 计数；Linux：开机后的时钟滴答）。取不到时返回 None。"""
    if not pid:
        return None
    if sys.platform == "win32":
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            times = [ctypes.c_ulonglong() for _ in range(4)]
            if not k32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
                return None
            return times[0].value
        finally:
            k32.CloseHandle(handle)
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as f:
            return int(f.read().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def process_owned(job: dict) -> bool:
    """job 记录的进程仍在运行且就是当初那个进程（启动时间一致；旧记录没有 pidStart 时只看存活）。"""
    pid = job.get("pid")
    if not pid_alive(pid):
        return False
    expected = job.get("pidStart")
    return expected is None or process_start_time(pid) == expected


# ---------------------------------------------------------------- 查询

def lane_of(job: dict) -> str:
    if job.get("lane"):
        return job["lane"]
    backend = job.get("backend", "local")
    if backend == "local":
        return "local-gpu" if job.get("kind") == "train" else "local-io"
    return f"{backend}:{(job.get('config') or {}).get('targetId') or 'default'}"


def _waiting(job: dict) -> bool:
    return job.get("status") == "queued" and not job.get("pid")


def _occupying(job: dict) -> bool:
    return job.get("status") in ACTIVE and bool(job.get("pid"))


def _all_jobs() -> list[dict]:
    jobs = []
    for f in settings.JOBS_DIR.glob("*/job.json"):
        job = jobfiles.read(f)
        if job:
            job["lane"] = lane_of(job)
            jobs.append(job)
    return sorted(jobs, key=lambda j: (j.get("createdAt", ""), j["id"]))


def _annotate(jobs: list[dict]) -> list[dict]:
    """补充 queuePosition（通道内第几个等待者，从 1 开始）和 progress。"""
    pos: dict[str, int] = {}
    for job in jobs:
        if _waiting(job):
            pos[job["lane"]] = pos.get(job["lane"], 0) + 1
            job["queuePosition"] = pos[job["lane"]]
        else:
            job["queuePosition"] = None
        job["progress"] = jobfiles.read_progress(job["id"])
    return jobs


def list_jobs(limit: int = 50) -> list[dict]:
    jobs = _annotate(_all_jobs())
    return sorted(jobs, key=lambda j: j.get("createdAt", ""), reverse=True)[:limit]


def get_job(job_id: str) -> dict:
    job = jobfiles.read_job(job_id)
    if job is None:
        raise JobError(f"任务不存在：{job_id}")
    job["lane"] = lane_of(job)
    for j in _annotate(_all_jobs()):
        if j["id"] == job_id:
            return j
    return job


def active_jobs(lane: str | None = None) -> list[dict]:
    return [j for j in list_jobs(limit=1000) if j["status"] in ACTIVE and (lane is None or j["lane"] == lane)]


def active_job() -> dict | None:
    """最近一个进行中的任务（任意通道；兼容旧接口 /api/local/system 的 activeJob）。"""
    jobs = active_jobs()
    return jobs[0] if jobs else None


def gpu_busy() -> bool:
    """本机 GPU 是否被训练占用：只看 local-gpu 通道中已分配进程的任务（排队中的不算，远程任务不算）。"""
    return any(_occupying(j) for j in _all_jobs() if j["lane"] == "local-gpu")


inference.set_gpu_busy_check(gpu_busy)


# ---------------------------------------------------------------- 创建 / 调度

def create(kind: str, config: dict, *, samples: str | None = None, backend: str = "local") -> dict:
    """建任务目录并入队；通道有空位时立即启动 worker。samples：训练样本文本（训练任务）。"""
    with _lock:
        job = {"kind": kind, "backend": backend, "config": config}
        lane = lane_of(job)
        waiting = [j for j in _all_jobs() if j["lane"] == lane and _waiting(j)]
        if len(waiting) >= MAX_WAITING_PER_LANE:
            raise JobError(f"排队任务已达上限（{MAX_WAITING_PER_LANE} 个），请等待或取消后再提交")
        job_id = f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
        d = jobfiles.job_dir(job_id)
        d.mkdir(parents=True)
        if samples is not None:
            (d / "samples.txt").write_text(samples, encoding="utf-8")
        job.update(id=job_id, lane=lane, status="queued", result=None, error=None, pid=None, pidStart=None,
                   waitReason=None, createdAt=jobfiles.now(), startedAt=None, endedAt=None)
        jobfiles.write(d / "job.json", job)
        log.info("任务入队 %s lane=%s", job_id, lane)
        _dispatch(lane)
        _ensure_scheduler()
        return get_job(job_id)


def _dispatch(lane: str) -> None:
    """通道有空位时按创建顺序启动等待中的任务。调用方持有 _lock。"""
    jobs = [j for j in _all_jobs() if j["lane"] == lane]
    free = LANE_LIMITS.get(lane, 1) - sum(_occupying(j) for j in jobs)
    for job in (j for j in jobs if _waiting(j)):
        if free <= 0:
            break
        if jobfiles.cancel_requested(job["id"]):
            jobfiles.update_job(job["id"], status="cancelled", endedAt=jobfiles.now())
            continue
        if lane == "local-gpu" and job["kind"] == "train":
            try:
                inference.unload()  # 释放推理模型占用的显存；章节生成 / 模型加载中会抛错 → 继续排队
            except RuntimeError as e:
                if job.get("waitReason") != str(e):
                    jobfiles.update_job(job["id"], waitReason=str(e))
                break
        _spawn(job["id"])
        free -= 1


def _spawn(job_id: str) -> None:
    d = jobfiles.job_dir(job_id)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
           # Windows 上减少显存碎片导致的 OOM
           "PYTORCH_CUDA_ALLOC_CONF": os.environ.get("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")}
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if sys.platform == "win32" else 0
    logf = open(d / "job.log", "ab")  # noqa: SIM115 —— 由监视线程在进程结束后关闭
    proc = subprocess.Popen([sys.executable, "-m", "app.local.worker", job_id], cwd=str(settings.SERVICE_ROOT),
                            stdout=logf, stderr=subprocess.STDOUT, env=env, creationflags=flags)
    # worker 启动后会改写为自己的 pid（Windows venv 的 python.exe 是启动器，真正的解释器是其子进程）
    jobfiles.update_job(job_id, pid=proc.pid, pidStart=process_start_time(proc.pid), waitReason=None)
    _watched.add(job_id)
    log.info("任务已启动 %s pid=%s", job_id, proc.pid)

    def watch() -> None:
        code = proc.wait()
        logf.close()
        with _lock:
            _finalize_dead(job_id, f"任务进程异常退出（code {code}）")
            _watched.discard(job_id)
            log.info("任务结束 %s code=%s status=%s", job_id, code, (jobfiles.read_job(job_id) or {}).get("status"))
            _dispatch(lane_of(jobfiles.read_job(job_id) or {"id": job_id}))

    threading.Thread(target=watch, daemon=True, name=f"watch-{job_id}").start()


def _finalize_dead(job_id: str, reason: str) -> None:
    """进程已不在但状态仍是进行中：按是否请求过取消补记 cancelled / failed。"""
    job = jobfiles.read_job(job_id) or {}
    if job.get("status") not in ACTIVE:
        return
    if jobfiles.cancel_requested(job_id):
        jobfiles.update_job(job_id, status="cancelled", endedAt=jobfiles.now())
    else:
        tail = jobfiles.tail_log(job_id, 15)
        jobfiles.update_job(job_id, status="failed", endedAt=jobfiles.now(),
                            error=f"{reason}。日志末尾：\n{tail}"[-2000:])


def _respawn(job_id: str) -> None:
    """可接管后端的 worker 丢失：清除进程记录后重新拉起（执行器自行核对远程状态，决定继续 / 收尾）。"""
    jobfiles.update_job(job_id, pid=None, pidStart=None, resumedAt=jobfiles.now())
    log.warning("重新接管任务 %s", job_id)
    _spawn(job_id)


def _reconcile() -> None:
    """调度线程：收尾本进程未监视的已死任务（服务重启后接手的），然后为各通道派发排队任务。调用方持有 _lock。"""
    for job in _all_jobs():
        if job["id"] in _watched or not _occupying(job) or process_owned(job):
            continue
        if job.get("backend", "local") in RESUMABLE_BACKENDS and not jobfiles.cancel_requested(job["id"]):
            _respawn(job["id"])
        else:
            _finalize_dead(job["id"], "任务进程已不存在（服务重启期间结束或被中断）")
    for lane in {j["lane"] for j in _all_jobs() if _waiting(j)}:
        _dispatch(lane)


def _ensure_scheduler() -> None:
    global _scheduler_started
    with _lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    def loop() -> None:
        while True:
            time.sleep(TICK_SECONDS)
            try:
                with _lock:
                    _reconcile()
            except Exception:  # noqa: BLE001 —— 调度线程不能退出
                log.exception("任务调度出错")

    threading.Thread(target=loop, daemon=True, name="job-scheduler").start()


def recover() -> None:
    """服务启动时调用：核对进行中任务的进程归属（已死的补记状态或重新接管），并启动调度线程。"""
    with _lock:
        _reconcile()
    _ensure_scheduler()


# ---------------------------------------------------------------- 取消

def cancel(job_id: str) -> dict:
    with _lock:
        job = get_job(job_id)
        if job["status"] not in ACTIVE:
            raise JobError("任务已结束，无需取消")
        (jobfiles.job_dir(job_id) / "cancel").touch()
        if _waiting(job):
            jobfiles.update_job(job_id, status="cancelled", endedAt=jobfiles.now())
            return get_job(job_id)
        pid = job.get("pid")
        if not process_owned(job):
            jobfiles.update_job(job_id, status="cancelled", endedAt=jobfiles.now())
            _dispatch(job["lane"])
        elif job["kind"] == "download":
            _terminate(pid)  # 下载可直接结束；训练先等它在当前 step 结束后优雅退出
        elif job.get("backend", "local") != "local":
            pass  # 远程执行：本机执行器把取消转发到远程并负责超时后结束远程进程，不能先杀本机执行器
        else:
            # 训练 / 远程执行：worker 在当前 step（远程：下一次轮询）结束时响应取消标记
            def force_kill() -> None:
                time.sleep(90)
                cur = jobfiles.read_job(job_id) or {}
                if cur.get("status") in ACTIVE and process_owned(cur):
                    log.warning("任务未在 90s 内响应取消，强制结束 pid=%s", cur.get("pid"))
                    _terminate(cur["pid"])

            threading.Thread(target=force_kill, daemon=True).start()
        return get_job(job_id)


def _terminate(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        os.kill(pid, 9)
