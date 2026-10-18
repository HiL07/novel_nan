"""任务子进程入口：python -m app.local.worker <jobId>

RUNNERS 按 (kind, backend) 分派；以后接远程训练只需新增如 ("train", "remote") 的执行器。
"""
import os
import sys
import traceback

from . import jobfiles


def _runners():
    from . import download, training

    return {("train", "local"): training.run, ("download", "local"): download.run}


def main(job_id: str) -> int:
    job = jobfiles.read_job(job_id)
    if job is None:
        print(f"job {job_id} not found", file=sys.stderr)
        return 2
    from .jobs import process_start_time

    jobfiles.update_job(job_id, status="running", pid=os.getpid(), pidStart=process_start_time(os.getpid()),
                        startedAt=job.get("startedAt") or jobfiles.now())
    try:
        runner = _runners().get((job["kind"], job.get("backend", "local")))
        if runner is None:
            raise RuntimeError(f"不支持的任务类型：{job['kind']} / {job.get('backend')}")
        result = runner(job) or {}
        status = "cancelled" if result.get("cancelled") else "succeeded"
        jobfiles.update_job(job_id, status=status, result=result, endedAt=jobfiles.now())
        return 0
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        msg = str(e) or e.__class__.__name__
        if "out of memory" in msg.lower():
            msg = f"显存不足（CUDA OOM）：请减小「序列长度」或 batch，或改用更小的模型。原始错误：{msg[:300]}"
        jobfiles.update_job(job_id, status="failed", error=msg[:2000], endedAt=jobfiles.now())
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
