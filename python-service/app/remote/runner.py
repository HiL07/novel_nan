"""远程训练执行器：worker.RUNNERS[("train", "remote")]，在本机 worker 子进程中运行（不占本机 GPU）。

阶段（progress.json 的 stage）：prechecking → uploading → launching → training（远程）→ downloading → registering
- 远程执行的就是现有的 `python -m app.local.worker <jobId>`（training.run），代码以快照上传到 <workDir>/code/<sha>/
- 远程任务目录 <workDir>/models/jobs/<jobId>/（与本地同名）；远程 job.json 由远程 worker 写，是训练状态的真实来源
- 接管（本机 worker 丢失后由 jobs 重新拉起）：本地 job.json 的 remote.launched 为真时跳过上传 / 启动，直接核对远程状态
- 远程进程归属：pid + /proc 启动时间 + cmdline 含任务 ID，三者一致才算「仍在运行」
- 取消：本地 cancel 标记 → 远程 cancel 标记（训练在当前 step 后停止）→ 120s 未停则 TERM 进程组，再 30s 后 KILL
- 下载：远程逐文件 SHA256 清单 → 下载到 adapters/<id>.partial/ → 逐文件校验 → 写 checksums.json → 原子改名
"""
import hashlib
import io
import json
import shlex
import tarfile
import time
from pathlib import Path

from ..local import jobfiles, registry, settings
from . import ssh, targets

POLL_SECONDS = 10
MAX_OFFLINE_SECONDS = 600
START_GRACE_SECONDS = 180
CANCEL_TERM_AFTER = 120
CODE_GLOBS = ("app/__init__.py", "app/config.py", "app/text_loader.py", "app/local/*.py")

_POLL_SCRIPT = r'''
import json, os, sys
d, off, jid = sys.argv[1], int(sys.argv[2]), sys.argv[3]
def rd(p):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception: return None
job, prog = rd(d + "/job.json"), rd(d + "/progress.json")
log, size = b"", 0
try:
    size = os.path.getsize(d + "/job.log")
    with open(d + "/job.log", "rb") as f:
        f.seek(off); log = f.read(262144)
    if len(log) == 262144 and b"\n" in log: log = log[:log.rindex(b"\n") + 1]
except OSError: pass
alive, pid = False, (job or {}).get("pid")
if pid:
    try:
        st = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[19])
        cmd = open(f"/proc/{pid}/cmdline", "rb").read().decode("utf-8", "replace")
        alive = st == job.get("pidStart") and jid in cmd
    except Exception: alive = False
print(json.dumps({"job": job, "progress": prog, "log": log.decode("utf-8", "replace"), "logEnd": off + len(log),
                  "size": size, "alive": alive}, ensure_ascii=False))
'''

_MANIFEST_SCRIPT = r'''
import hashlib, json, os, sys
d = sys.argv[1]
out = []
for name in sorted(os.listdir(d)):
    p = os.path.join(d, name)
    if os.path.isfile(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""): h.update(chunk)
        out.append({"name": name, "size": os.path.getsize(p), "sha256": h.hexdigest()})
print(json.dumps(out))
'''


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] [remote] {msg}", flush=True)


def _stage(job_id: str, stage: str, **extra) -> None:
    prog = jobfiles.read_progress(job_id) or {}
    prog.update(stage=stage, **extra)
    jobfiles.write_progress(job_id, prog)


def _py(t: dict, script: str, *args: str, timeout: float = 120) -> str:
    cmd = f"{shlex.quote(t['python'])} - " + " ".join(shlex.quote(a) for a in args)
    return ssh.text(t, cmd, input=script.encode("utf-8"), timeout=timeout)


def _env(t: dict) -> str:
    w = t["workDir"]
    env = {"LOCAL_MODELS_DIR": f"{w}/models", "DATA_DIR": f"{w}/data", "PYTHONUNBUFFERED": "1",
           "PYTHONIOENCODING": "utf-8", "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True", **t.get("env", {})}
    return " ".join(f"{k}={shlex.quote(str(v))}" for k, v in env.items())


def code_bundle() -> tuple[bytes, str]:
    root = settings.SERVICE_ROOT
    files = sorted({p for g in CODE_GLOBS for p in root.glob(g)})
    h, buf = hashlib.sha256(), io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for f in files:
            rel = f.relative_to(root).as_posix()
            data = f.read_bytes()
            h.update(rel.encode() + b"\0" + data)
            info = tarfile.TarInfo(rel)
            info.size, info.mtime = len(data), int(f.stat().st_mtime)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue(), h.hexdigest()[:12]


# ---------------------------------------------------------------- 准备与启动

def _precheck(t: dict, m: dict, rjob: str) -> dict:
    out = ssh.text(t, " ; ".join([
        "nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader,nounits",
        "echo APPS=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l)",
        f"echo FREE=$(df -B1 --output=avail {shlex.quote(t['workDir'].rsplit('/', 1)[0])} | tail -1)",
        f"test -e {shlex.quote(rjob)} && echo JOBDIR=exists || echo JOBDIR=free",
        f"test -f {shlex.quote(m['path'])}/config.json && echo MODEL=ok || echo MODEL=missing",
        f"test -x {shlex.quote(t['python'])} && echo PY=ok || echo PY=missing"]), timeout=60)
    kv = dict(line.split("=", 1) for line in out.splitlines() if "=" in line and line.split("=", 1)[0].isupper())
    gpu = out.splitlines()[0].split(", ") if out else []
    problems = []
    if kv.get("APPS") != "0":
        problems.append(f"远程 GPU 上已有 {kv.get('APPS')} 个计算进程")
    if int(kv.get("FREE", "0")) < 5 * 1024 ** 3:
        problems.append("远程数据盘剩余不足 5 GB")
    if kv.get("JOBDIR") != "free":
        problems.append(f"远程任务目录已存在：{rjob}")
    if kv.get("MODEL") != "ok":
        problems.append(f"远程模型目录缺少 config.json：{m['path']}")
    if kv.get("PY") != "ok":
        problems.append(f"远程 Python 不存在：{t['python']}")
    if problems:
        raise RuntimeError("远程预检未通过：" + "；".join(problems))
    info = {"gpu": gpu[0] if gpu else None, "gpuMemUsedMiB": gpu[1] if len(gpu) > 1 else None,
            "gpuMemTotalMiB": gpu[2] if len(gpu) > 2 else None, "diskFreeGB": round(int(kv["FREE"]) / 1024 ** 3, 1)}
    _log(f"预检通过：{info}")
    return info


def _upload_code(t: dict) -> str:
    data, sha = code_bundle()
    code_dir = f"{t['workDir']}/code/{sha}"
    q = shlex.quote(code_dir)
    ssh.run(t, f"test -d {q}/app/local || (mkdir -p {q}.part && tar -xf - -C {q}.part && mv {q}.part {q})",
            input=data, timeout=300)
    _log(f"代码快照已上传：{code_dir}")
    return code_dir


def _remote_base(t: dict, m: dict, code_dir: str) -> dict:
    """在远程用现有 registry.inspect_model_dir 读取模型信息；附加来源、revision 与官方清单指纹。"""
    script = (
        "import json, sys\nsys.path.insert(0, sys.argv[1])\nfrom app.local import registry\n"
        "print(json.dumps(registry.inspect_model_dir(sys.argv[2])))\n")
    rec = json.loads(_py(t, script, code_dir, m["path"], timeout=120).strip().splitlines()[-1])
    rec.update(id=m["id"], name=m["name"], source="remote", origin=m.get("repoId"), targetId=t["id"])
    if m.get("manifest"):
        man = json.loads(ssh.get_bytes(t, m["manifest"], timeout=60))
        cfg = next((f for f in man if f["Path"] == "config.json"), {})
        rec["revision"] = cfg.get("Revision")
        rec["weightsFingerprint"] = registry.manifest_fingerprint(
            {f["Path"]: f["Sha256"] for f in man if f["Path"].endswith((".safetensors", ".bin"))})
        rec["manifestSource"] = m.get("source")
    return rec


def _prepare_and_launch(job: dict, t: dict, m: dict, rjob: str) -> dict:
    job_id, cfg = job["id"], job["config"]
    _stage(job_id, "prechecking")
    pre = _precheck(t, m, rjob)
    _stage(job_id, "uploading")
    code_dir = _upload_code(t)
    base = _remote_base(t, m, code_dir)
    _log(f"远程基础模型：{base['name']} revision={base.get('revision')} configHash={base['configHash']}")
    samples = (jobfiles.job_dir(job_id) / "samples.txt").read_bytes()
    ssh.put_bytes(t, samples, f"{rjob}/samples.txt", timeout=600)
    remote_size = ssh.text(t, f"stat -c %s {shlex.quote(rjob)}/samples.txt").strip()
    if int(remote_size) != len(samples):
        raise RuntimeError(f"样本上传不完整：本地 {len(samples)} 字节，远程 {remote_size} 字节")
    rcfg = {k: v for k, v in cfg.items() if k not in ("estimate", "baseModel")} | {"baseModel": base}
    rjob_json = {"id": job_id, "kind": "train", "backend": "local", "lane": "local-gpu", "status": "queued",
                 "config": rcfg, "result": None, "error": None, "pid": None, "pidStart": None,
                 "createdAt": job["createdAt"], "startedAt": None, "endedAt": None}
    ssh.put_bytes(t, json.dumps(rjob_json, ensure_ascii=False, indent=2).encode("utf-8"), f"{rjob}/job.json")
    _stage(job_id, "launching")
    q = shlex.quote
    pid = ssh.text(t, f"cd {q(code_dir)} && setsid nohup env {_env(t)} {q(t['python'])} -m app.local.worker {q(job_id)} "
                      f">> {q(rjob)}/job.log 2>&1 < /dev/null & echo $!", timeout=60).strip()
    state = {"targetId": t["id"], "host": t["host"], "remoteJobDir": rjob, "codeDir": code_dir,
             "codeSha": code_dir.rsplit("/", 1)[-1], "launcherPid": pid, "launched": True,
             "launchedAt": jobfiles.now(), "launchedTs": time.time(), "precheck": pre, "baseModel": base}
    jobfiles.update_job(job_id, remote=state)
    _log(f"远程训练已启动 pid={pid}，任务目录 {rjob}")
    return state


# ---------------------------------------------------------------- 轮询 / 取消

def _poll(t: dict, state: dict, job_id: str, offset: int) -> dict:
    return json.loads(_py(t, _POLL_SCRIPT, state["remoteJobDir"], str(offset), job_id, timeout=60).strip())


def _follow(job_id: str, t: dict, state: dict) -> dict:
    """跟随远程任务直到结束，返回远程 job.json。"""
    offset = state.get("logOffset", 0)
    offline_since, cancel_sent, termed = None, state.get("cancelSentTs"), False
    while True:
        try:
            r = _poll(t, state, job_id, offset)
            offline_since = None
        except (ssh.SSHError, ValueError) as e:
            offline_since = offline_since or time.time()
            _stage(job_id, "reconnecting", remoteError=str(e)[:300])
            if time.time() - offline_since > MAX_OFFLINE_SECONDS:
                raise RuntimeError(f"远程不可达超过 {MAX_OFFLINE_SECONDS}s（远程训练可能仍在运行，可重新接管）：{e}") from e
            time.sleep(POLL_SECONDS)
            continue
        if r["log"]:
            print(r["log"], end="" if r["log"].endswith("\n") else "\n", flush=True)
            offset = r["logEnd"]
            state["logOffset"] = offset
            jobfiles.update_job(job_id, remote=state)
        rjob, prog = r["job"] or {}, r["progress"]
        if prog:
            jobfiles.write_progress(job_id, {**prog, "stage": prog.get("stage") or "training", "remote": True})
        status = rjob.get("status")
        if status in ("succeeded", "failed", "cancelled"):
            return rjob
        if not r["alive"] and time.time() - state.get("launchedTs", 0) > START_GRACE_SECONDS:
            raise RuntimeError(f"远程训练进程已不存在（远程状态 {status}），日志见远程 {state['remoteJobDir']}/job.log")
        if jobfiles.cancel_requested(job_id):
            if not cancel_sent:
                ssh.run(t, f"touch {shlex.quote(state['remoteJobDir'])}/cancel", timeout=30)
                cancel_sent = time.time()
                state["cancelSentTs"] = cancel_sent
                jobfiles.update_job(job_id, remote=state)
                _log("已向远程发送取消请求（当前 step 结束后停止）")
            elif r["alive"] and time.time() - cancel_sent > CANCEL_TERM_AFTER and rjob.get("pid"):
                sig = "KILL" if termed else "TERM"
                ssh.run(t, f"kill -{sig} -- -{int(rjob['pid'])} 2>/dev/null || kill -{sig} {int(rjob['pid'])}",
                        timeout=30, check=False)
                _log(f"远程训练未在规定时间内停止，已发送 {sig}")
                termed, cancel_sent = True, time.time() - CANCEL_TERM_AFTER + 30
        time.sleep(POLL_SECONDS)


# ---------------------------------------------------------------- 下载 / 登记

def _download(job_id: str, t: dict, state: dict, adapter_id: str) -> dict:
    remote_dir = f"{t['workDir']}/models/adapters/{adapter_id}"
    final = registry.adapter_dir(adapter_id)
    if final.exists():
        raise RuntimeError(f"本地已存在同名适配器目录，未覆盖：{final}")
    manifest = json.loads(_py(t, _MANIFEST_SCRIPT, remote_dir, timeout=600).strip())
    names = {f["name"] for f in manifest}
    for need in ("adapter_model.safetensors", "adapter_config.json", "meta.json"):
        if need not in names:
            raise RuntimeError(f"远程适配器缺少文件：{need}")
    tmp = final.with_name(adapter_id + ".partial")
    tmp.mkdir(parents=True, exist_ok=True)
    total = sum(f["size"] for f in manifest)
    done = 0
    for f in manifest:
        _stage(job_id, "downloading", downloadedBytes=done, totalBytes=total, file=f["name"])
        data = ssh.get_bytes(t, f"{remote_dir}/{f['name']}", timeout=1800)
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != f["size"] or digest != f["sha256"]:
            raise RuntimeError(f"文件校验失败：{f['name']}（大小 {len(data)}/{f['size']}，sha256 {digest[:12]}/{f['sha256'][:12]}）"
                               f"；不完整的文件保留在 {tmp}，未登记")
        (tmp / f["name"]).write_bytes(data)
        done += len(data)
        _log(f"已下载并校验 {f['name']}（{len(data)} 字节，sha256 {digest[:16]}…）")
    return {"tmp": tmp, "final": final, "manifest": manifest, "remoteDir": remote_dir}


def _register(job: dict, t: dict, state: dict, dl: dict) -> None:
    tmp, final = dl["tmp"], dl["final"]
    meta = json.loads((tmp / "meta.json").read_text(encoding="utf-8"))
    meta["source"] = "remote"
    base = state["baseModel"]
    meta["baseModel"] = {k: base.get(k) for k in ("id", "name", "path", "configHash", "modelType", "architecture",
                                                  "numParams", "source", "origin", "revision", "weightsFingerprint",
                                                  "manifestSource", "targetId")}
    meta["remote"] = {"targetId": t["id"], "host": t["host"], "jobId": job["id"], "remoteAdapterDir": dl["remoteDir"],
                      "remoteJobDir": state["remoteJobDir"], "codeSha": state["codeSha"],
                      "downloadedAt": jobfiles.now()}
    meta["files"] = dl["manifest"]
    (tmp / "meta.remote-original.json").write_bytes((tmp / "meta.json").read_bytes())
    (tmp / "checksums.json").write_text(json.dumps({"verifiedAt": jobfiles.now(), "files": dl["manifest"]},
                                                   ensure_ascii=False, indent=2), encoding="utf-8")
    registry.save_adapter_meta_at(tmp, meta)
    tmp.rename(final)
    _log(f"适配器已登记：{final}")


# ---------------------------------------------------------------- 入口

def run(job: dict) -> dict:
    job_id, cfg = job["id"], job["config"]
    t = targets.get(cfg["targetId"])
    m = targets.get_model(t, cfg["remoteModelId"])
    rjob = f"{t['workDir']}/models/jobs/{job_id}"
    state = job.get("remote") or {}
    if state.get("launched"):
        _log(f"接管远程任务：{state['remoteJobDir']}")
    else:
        if jobfiles.cancel_requested(job_id):
            return {"cancelled": True}
        state = _prepare_and_launch(job, t, m, rjob)
    _stage(job_id, "training")
    rjob_state = _follow(job_id, t, state)
    status = rjob_state.get("status")
    if status == "cancelled":
        _log("远程训练已取消，未下载适配器")
        return {"cancelled": True}
    if status != "succeeded":
        raise RuntimeError(f"远程训练失败：{(rjob_state.get('error') or '未知错误')[:1500]}")
    adapter_id = (rjob_state.get("result") or {}).get("adapterId")
    if not adapter_id:
        raise RuntimeError("远程训练标记为成功，但没有返回 adapterId")
    _stage(job_id, "downloading")
    dl = _download(job_id, t, state, adapter_id)
    _stage(job_id, "registering")
    _register(job, t, state, dl)
    _stage(job_id, "done")
    return {"adapterId": adapter_id, "remoteJobDir": rjob, "files": len(dl["manifest"])}
