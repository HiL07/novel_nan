"""任务调度回归测试（走真实 HTTP 接口，脚本自己启动 / 重启测试服务）：

  1. 本地训练回归：短 QLoRA 训练成功并产出适配器（与改动前行为一致）
  2. 通道排队：第二、三个训练排队（无进程），取消排队任务；第一个结束后第二个自动开始
  3. 通道隔离：训练进行中，下载任务（local-io）不排队、立即启动；训练中加载推理模型被拒绝
  4. 取消运行中的训练：状态 cancelled，不产出适配器
  5. 重启恢复（worker 存活）：杀掉 API 进程、worker 继续，重启后任务正常收尾，排队任务被派发
  6. 重启恢复（worker 已死 / pid 被复用）：标记 failed，不会误判为仍在运行

只在测试端口运行，并使用独立的 LOCAL_MODELS_DIR / DATA_DIR（不影响日常服务的任务与模型登记）：
  .venv/Scripts/python scripts/jobs_queue_test.py --model-path "D:/.../Qwen2.5-1.5B-Instruct" --work-dir <空目录> [--port 8011]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ("夜雨落在青石巷里，一声，又一声。灯是旧的，人也是旧的。老陈推开铺子的木门，门轴吱呀一响，像是替他叹了口气。"
           "他不说话，只把伞靠在墙角，任水顺着伞骨往下淌，淌成一小摊，映着昏黄的灯。来人是个年轻人，肩头湿透，眼神却亮。"
           "他在柜台前站定，掏出一枚铜钱，搁下，又推了推。铜钱很轻，落在木头上，几乎没有声响。老陈看了很久。\n") * 6
results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> bool:
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}", flush=True)
    return bool(cond)


class Api:
    def __init__(self, port: int):
        self.base = f"http://localhost:{port}/api/local"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, method: str, path: str, body=None, timeout=60):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=timeout) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def job(self, job_id: str) -> dict:
        return self.call("GET", f"/jobs/{job_id}")[1]["data"]


class Server:
    def __init__(self, port: int, work: Path):
        self.port, self.work, self.proc = port, work, None

    def start(self) -> None:
        env = {**os.environ, "LOCAL_MODELS_DIR": str(self.work / "models"), "DATA_DIR": str(self.work / "data"),
               "JAVA_BACKEND_URL": "http://localhost:8012", "PYTHONIOENCODING": "utf-8"}
        log = open(self.work / f"server-{int(time.time())}.log", "ab")  # noqa: SIM115
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(self.port)],
                                     cwd=str(SERVICE_ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
        api = Api(self.port)
        for _ in range(120):
            try:
                if api.call("GET", "/jobs", timeout=5)[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(1)
        raise RuntimeError("测试服务未能启动")

    def listen_pid(self) -> int | None:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            m = re.search(rf"127\.0\.0\.1:{self.port}\s+\S+\s+LISTENING\s+(\d+)", line)
            if m:
                return int(m.group(1))
        return None

    def kill(self) -> None:
        """只结束 API 进程本身（不带 /T），模拟服务崩溃 / 重启；worker 子进程不受影响。"""
        pid = self.listen_pid()
        if pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        if self.proc:
            self.proc.wait(timeout=30)
        for _ in range(30):
            if not self.listen_pid():
                return
            time.sleep(1)
        raise RuntimeError("测试服务未能停止")


def pid_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def wait_for(fn, timeout: float, interval: float = 1.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(interval)
    return None


def train(api: Api, base_id: str, name: str, steps: int) -> dict:
    code, res = api.call("POST", "/train", {"baseModelId": base_id, "adapterName": name, "method": "qlora",
                                            "sampleText": SAMPLES, "maxSeqLen": 128, "batchSize": 1, "gradAccum": 1,
                                            "maxSteps": steps, "force": True})
    if code != 200:
        raise RuntimeError(f"提交训练失败 {code}: {res}")
    return res["data"]


def wait_final(api: Api, job_id: str, timeout: float = 600) -> dict:
    return wait_for(lambda: (j := api.job(job_id))["status"] not in ("queued", "running") and j, timeout, 2) or api.job(job_id)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-path", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--port", type=int, default=8011)
    args = ap.parse_args()
    if args.port in (8021, 8022, 5173):
        sys.exit("不要在日常端口上运行测试")
    work = Path(args.work_dir).resolve()
    if work.exists() and any(work.iterdir()):
        sys.exit(f"工作目录不为空：{work}")
    work.mkdir(parents=True, exist_ok=True)
    server, api = Server(args.port, work), Api(args.port)
    server.start()
    try:
        code, res = api.call("POST", "/models/register", {"name": "test-base", "path": args.model_path})
        if not check("register_base", code == 200, res.get("message", "")):
            return 1
        base_id = res["data"]["id"]

        # ---- 1-3 排队 / 隔离 / 本地回归
        a = train(api, base_id, "p1-a", 3)
        b = train(api, base_id, "p1-b", 3)
        c = train(api, base_id, "p1-c", 3)
        b0, c0 = api.job(b["id"]), api.job(c["id"])
        check("queue_waiting", b0["status"] == "queued" and not b0["pid"] and b0["queuePosition"] == 1
              and c0["queuePosition"] == 2, f"b={b0['status']}/pos{b0['queuePosition']} c=pos{c0['queuePosition']}")
        code, res = api.call("POST", f"/jobs/{c['id']}/cancel")
        c1 = api.job(c["id"])
        check("cancel_queued", code == 200 and c1["status"] == "cancelled" and not c1["pid"], c1["status"])
        wait_for(lambda: api.job(a["id"])["status"] == "running", 120)
        code, res = api.call("POST", "/inference/load", {"baseId": base_id})
        check("gpu_busy_blocks_inference", code == 400, res.get("message", ""))
        code, res = api.call("POST", "/models/download", {"repoId": "nan-novel-test/does-not-exist", "source": "modelscope"})
        dl = res.get("data") or {}
        dl1 = wait_for(lambda: (j := api.job(dl["id"]))["pid"] and j, 30) if code == 200 else None
        check("io_lane_not_blocked_by_train", bool(dl1) and api.job(a["id"])["status"] == "running",
              f"download pid={dl1 and dl1['pid']} lane={dl1 and dl1['lane']}")
        a1 = wait_final(api, a["id"])
        check("local_train_regression", a1["status"] == "succeeded" and a1["result"]
              and (work / "models" / "adapters" / a1["result"]["adapterId"] / "adapter_model.safetensors").exists(),
              f"status={a1['status']} error={(a1.get('error') or '')[:200]}")
        b1 = wait_final(api, b["id"])
        check("queued_auto_dispatch", b1["status"] == "succeeded" and b1["startedAt"] >= a1["endedAt"],
              f"status={b1['status']} startedAt={b1['startedAt']} a.endedAt={a1['endedAt']}")
        dlf = wait_final(api, dl["id"], 120) if dl else {}
        check("download_failed_cleanly", dlf.get("status") == "failed", (dlf.get("error") or "")[:120])

        # ---- 4 取消运行中的训练
        d = train(api, base_id, "p1-d", 40)
        wait_for(lambda: ((api.job(d["id"]).get("progress") or {}).get("step") or 0) >= 1, 300)
        api.call("POST", f"/jobs/{d['id']}/cancel")
        d1 = wait_final(api, d["id"], 150)
        check("cancel_running", d1["status"] == "cancelled" and not (work / "models" / "adapters" / d1["config"]["adapterId"]).exists(),
              f"status={d1['status']} step={(d1.get('progress') or {}).get('step')}")

        # ---- 5 重启恢复：worker 存活
        e = train(api, base_id, "p1-e", 15)
        f = train(api, base_id, "p1-f", 3)
        e_run = wait_for(lambda: (j := api.job(e["id"]))["status"] == "running" and j["pid"] and j, 120)
        server.kill()
        alive = bool(e_run) and pid_alive(e_run["pid"])
        check("worker_survives_api_kill", alive, f"pid={e_run and e_run['pid']}")
        server.start()
        e1 = wait_final(api, e["id"], 600)
        check("resume_alive_worker", e1["status"] == "succeeded", f"status={e1['status']} error={(e1.get('error') or '')[:200]}")
        f1 = wait_final(api, f["id"], 600)
        check("dispatch_after_restart", f1["status"] == "succeeded", f"status={f1['status']}")

        # ---- 6 重启恢复：worker 已死 + pid 被复用
        g = train(api, base_id, "p1-g", 40)
        g_run = wait_for(lambda: (j := api.job(g["id"]))["status"] == "running" and j["pid"] and j, 120)
        server.kill()
        if g_run:
            subprocess.run(["taskkill", "/PID", str(g_run["pid"]), "/T", "/F"], capture_output=True)
            wait_for(lambda: not pid_alive(g_run["pid"]), 30)
        fake_id = "train-20000101-000000-fake"
        fake_dir = work / "models" / "jobs" / fake_id
        fake_dir.mkdir(parents=True)
        # pid 指向一个存活但无关的进程（本测试脚本），启动时间对不上 → 必须判定为不属于该任务
        (fake_dir / "job.json").write_text(json.dumps({
            "id": fake_id, "kind": "train", "backend": "local", "lane": "local-gpu", "status": "running",
            "config": {"adapterName": "fake"}, "pid": os.getpid(), "pidStart": 1, "createdAt": "2000-01-01 00:00:00"},
            ensure_ascii=False), encoding="utf-8")
        server.start()
        g1 = wait_for(lambda: (j := api.job(g["id"]))["status"] != "running" and j, 30) or api.job(g["id"])
        check("dead_worker_marked_failed", g1["status"] == "failed", f"status={g1['status']} error={(g1.get('error') or '')[:80]}")
        fk = wait_for(lambda: (j := api.job(fake_id))["status"] != "running" and j, 30) or api.job(fake_id)
        check("pid_reuse_not_owned", fk["status"] == "failed", f"status={fk['status']}")
    finally:
        try:
            server.kill()
        except Exception as e:  # noqa: BLE001
            print("停止测试服务失败：", e)
    failed = [n for n, ok, _ in results if not ok]
    print("\nSUMMARY", f"{len(results) - len(failed)}/{len(results)} passed", "FAILED:" if failed else "", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
