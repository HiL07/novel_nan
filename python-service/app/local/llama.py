"""llama.cpp（llama-server）管理：在「llama.cpp」页选一个 GGUF → 检查 → 启动 / 停止。

- 同一时间只跑一个 llama-server（端口 LLAMA_PORT，默认 8001）；再次启动会先关掉上一个。
  端口被别的 llama-server（比如 start-llama.bat 手动开的）占着时，要作者确认后才结束它；被其他程序占着则不能启动
- 后台启动不弹窗口，输出写到 models/llama/llama-server.log；固定带 --parallel 1 --cache-ram 0
  （RTX 4060 Laptop 上的稳定配置：默认 4 个并发槽 + 8GB prompt cache 跑约 15 分钟会 CUDA error）
- Windows 上把进程放进「随句柄关闭而结束」的作业对象：Python 服务退出（含崩溃）时 llama-server 一起退出
- 运行后其他功能用「GGUF」模型来源调用它：api_config() 给出 OpenAI 兼容配置（本机、无 Key），按大模型同样的方式调用
- 启动失败（显存不足 / 架构不支持 / 文件损坏 / 端口被占）从日志里认出原因，给出中文提示
"""
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import hardware, registry, settings

log = logging.getLogger("local.llama")

STATE_DIR = settings.MODELS_DIR / "llama"
STATE_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = STATE_DIR / "settings.json"
LOG_FILE = STATE_DIR / "llama-server.log"

DEFAULT_SERVER = os.getenv(
    "LLAMA_SERVER_PATH", r"D:\workplace\llama.cpp_cuda12-12.4\llama-b9538-bin-win-cuda-12.4-x64\llama-server.exe")
PORT = int(os.getenv("LLAMA_PORT", "8001"))
STABLE_ARGS = ["--parallel", "1", "--cache-ram", "0"]
START_TIMEOUT = 300   # 秒：大模型从慢盘加载可能要一两分钟
CTX_RANGE = (512, 131072)
OVERHEAD_GB = 0.4     # CUDA 上下文 + 计算缓冲（估计）


class LlamaError(Exception):
    def __init__(self, message: str, data=None):
        super().__init__(message)
        self.data = data


_lock = threading.RLock()
_proc: subprocess.Popen | None = None
_job_handle = None
_gen = 0  # 每次启动 +1：旧的监视线程看到代数变了就退出
_state: dict = {"status": "stopped", "pid": None, "baseId": None, "name": None, "path": None, "quant": None,
                "ctx": None, "ngl": None, "port": PORT, "startedAt": None, "readyAt": None, "error": None,
                "estimateGB": None}


# ---------------------------------------------------------------- 设置

def get_settings() -> dict:
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    server = saved.get("serverPath") or DEFAULT_SERVER
    return {"serverPath": server, "serverExists": Path(server).is_file(), "port": PORT,
            "last": saved.get("last"), "stableArgs": " ".join(STABLE_ARGS)}


def _save(**kw) -> None:
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    saved.update(kw)
    SETTINGS_FILE.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")


def save_settings(server_path: str) -> dict:
    p = Path(server_path.strip().strip('"')).expanduser()
    if p.is_dir():
        p = p / ("llama-server.exe" if sys.platform == "win32" else "llama-server")
    if not p.is_file():
        raise LlamaError(f"找不到 llama-server：{p}")
    if not p.name.lower().startswith("llama-server"):
        raise LlamaError("请选择 llama-server 可执行文件（llama.cpp 发布包里的 llama-server.exe）")
    _save(serverPath=str(p.resolve()))
    return get_settings()


# ---------------------------------------------------------------- 模型与显存估算

def _resolve(base_id: str | None, path: str | None) -> dict:
    """已登记的 GGUF（baseId）或直接给的 .gguf 路径 → {baseId, name, path, quant, contextLength, sizeBytes, …}。"""
    if base_id:
        rec = registry.get_base(base_id)
        if rec.get("task") != "gguf":
            raise LlamaError(f"「{rec['name']}」不是 GGUF 模型（safetensors 模型请在「本地模型」页加载）")
        info = registry.inspect_gguf(rec["path"])
        return {**info, "baseId": base_id, "name": rec["name"]}
    if not path or not path.strip():
        raise LlamaError("请选择一个 GGUF 模型")
    p = path.strip().strip('"')
    if not registry.is_gguf_path(p):
        raise LlamaError(f"不是 .gguf 文件：{p}")
    info = registry.inspect_gguf(p)
    return {**info, "baseId": None, "name": Path(info["path"]).stem}


def _arch_meta(path: str) -> dict:
    """层数 / KV 头数 / 每头维度（估算上下文缓存用）。"""
    p = registry._gguf_main_file(path)
    with p.open("rb") as f:
        meta = registry._gguf_metadata(f, ("general.architecture",))
    arch = meta.get("general.architecture") or ""
    with p.open("rb") as f:
        meta = registry._gguf_metadata(f, (f"{arch}.",))
    g = lambda k: meta.get(f"{arch}.{k}")  # noqa: E731
    layers = g("block_count") or 0
    heads = g("attention.head_count") or 0
    kv_heads = g("attention.head_count_kv") or heads
    head_dim = g("attention.key_length") or ((g("embedding_length") or 0) // heads if heads else 0)
    return {"layers": int(layers), "kvHeads": int(kv_heads), "headDim": int(head_dim)}


def estimate(model: dict, ctx: int, ngl: int) -> dict:
    """显存估算（GB）：权重按放进 GPU 的层数比例 + f16 上下文缓存（KV） + 固定开销。"""
    try:
        a = _arch_meta(model["path"])
    except (OSError, registry.RegistryError):
        a = {"layers": 0, "kvHeads": 0, "headDim": 0}
    weights = model["sizeBytes"] / hardware.GB
    share = 1.0 if not a["layers"] else min(max(ngl, 0), a["layers"]) / a["layers"]
    kv = 2 * a["layers"] * a["kvHeads"] * a["headDim"] * ctx * 2 / hardware.GB * share if a["layers"] else ctx / 8192 * 1.0
    need = weights * share + kv + (OVERHEAD_GB if ngl > 0 else 0)
    return {"weightsGB": round(weights * share, 2), "kvGB": round(kv, 2), "overheadGB": OVERHEAD_GB if ngl > 0 else 0,
            "needGB": round(need, 2), "layers": a["layers"], "gpuShare": round(share, 2)}


# ---------------------------------------------------------------- 端口占用

def _port_owner(port: int) -> dict | None:
    """监听该端口的进程 {pid, name}；没人监听 None。只在 Windows 上识别进程名。"""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10,
                             creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].rsplit(":", 1)[-1] == str(port):
            pid = int(parts[4])
            return {"pid": pid, "name": _process_name(pid)}
    return None


def _process_name(pid: int) -> str:
    if sys.platform != "win32":
        return ""
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, timeout=10, creationflags=_NO_WINDOW).stdout.strip()
        return out.split('","')[0].strip('"') if out.startswith('"') else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _is_llama(owner: dict | None) -> bool:
    return bool(owner) and owner["name"].lower().startswith("llama-server")


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------- 检查

def check(base_id: str | None, path: str | None, ctx: int, ngl: int) -> dict:
    """启动前检查 → {level: ok|warn|error, problems[{level, text}], model, estimate, gpu, portOwner}。"""
    problems: list[dict] = []
    add = lambda lv, t: problems.append({"level": lv, "text": t})  # noqa: E731
    model = None
    try:
        model = _resolve(base_id, path)
    except (LlamaError, registry.RegistryError) as e:
        add("error", str(e))
    s = get_settings()
    if not s["serverExists"]:
        add("error", f"找不到 llama-server：{s['serverPath']}（在本页「llama-server 位置」里设置）")
    if not CTX_RANGE[0] <= ctx <= CTX_RANGE[1]:
        add("error", f"上下文长度要在 {CTX_RANGE[0]}–{CTX_RANGE[1]} 之间")
    est, gpu = None, hardware.gpu_info()
    owner = _port_owner(PORT)
    with _lock:
        ours = _proc is not None and owner is not None and owner["pid"] == _state["pid"]
    external_llama = bool(owner) and not ours and _is_llama(owner)
    if model:
        if model.get("shardsMissing"):
            add("error", f"缺少 {model['shardsMissing']} 个分片文件，模型不完整")
        if model.get("contextLength") and ctx > model["contextLength"]:
            add("warn", f"上下文 {ctx} 超过模型训练长度 {model['contextLength']}，超出部分效果会变差")
        est = estimate(model, ctx, ngl)
        if gpu and ngl > 0:
            with _lock:
                mine = _state["estimateGB"] if _state["status"] in ("running", "starting") else 0
            free = gpu["freeGB"] + (mine or 0)
            est["freeGB"] = round(free, 2)
            est["reclaimGB"] = round(mine or 0, 2)
            if est["needGB"] > free:
                if external_llama:
                    add("warn", f"预计需要显存约 {est['needGB']} GB，现在可用约 {free:.1f} GB；"
                                "结束端口上那个 llama-server 后会释放它占的显存，通常就够了")
                else:
                    add("warn", f"预计需要显存约 {est['needGB']} GB，可用约 {free:.1f} GB"
                                f"{'（含关掉当前 llama 后释放的）' if mine else ''}：很可能启动失败，"
                                "可减小上下文、减少 GPU 层数，或先卸载「本地模型」页的生成 / 检索模型")
            elif est["needGB"] > free * 0.85:
                add("warn", f"预计显存约 {est['needGB']} GB，接近可用上限 {free:.1f} GB")
        elif not gpu and ngl > 0:
            add("warn", "没检测到 NVIDIA 显卡（nvidia-smi），GPU 层数会不起作用")
    if owner and not ours:
        if external_llama:
            add("warn", f"端口 {PORT} 上已有一个不是本页启动的 llama-server（PID {owner['pid']}，可能是 start-llama.bat 开的），"
                        "启动时需要先结束它")
        else:
            add("error", f"端口 {PORT} 被其他程序占用：{owner['name'] or '未知程序'}（PID {owner['pid']}）")
    level = "error" if any(p["level"] == "error" for p in problems) else "warn" if problems else "ok"
    return {"level": level, "problems": problems, "model": model, "estimate": est, "gpu": gpu,
            "portOwner": owner if owner and not ours else None, "running": status()}


# ---------------------------------------------------------------- 启动 / 停止

def start(base_id: str | None, path: str | None, ctx: int, ngl: int, stop_external: bool = False) -> dict:
    global _proc, _gen
    report = check(base_id, path, ctx, ngl)
    errors = [p["text"] for p in report["problems"] if p["level"] == "error"]
    if errors:
        raise LlamaError("；".join(errors), report)
    owner = report["portOwner"]
    if owner:
        if not stop_external:
            raise LlamaError(f"端口 {PORT} 上已有 llama-server（PID {owner['pid']}）在运行，确认结束它后再启动",
                             {"needConfirm": True, "portOwner": owner})
        _kill_pid(owner["pid"])
        _wait_port_free(10)
    model, est = report["model"], report["estimate"]
    with _lock:
        _stop_locked()
        exe = get_settings()["serverPath"]
        args = [exe, "-m", model["path"], "--host", "127.0.0.1", "--port", str(PORT), "-c", str(ctx),
                "-ngl", str(ngl), *STABLE_ARGS]
        logf = LOG_FILE.open("w", encoding="utf-8", errors="replace")
        logf.write(f"# {datetime.now():%Y-%m-%d %H:%M:%S} {subprocess.list2cmdline(args)}\n")
        logf.flush()
        try:
            _proc = subprocess.Popen(args, cwd=str(Path(exe).parent), stdout=logf, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
        except OSError as e:
            logf.close()
            raise LlamaError(f"无法启动 llama-server：{e}") from e
        _attach_job(_proc)
        _gen += 1
        _state.update(status="starting", pid=_proc.pid, baseId=model.get("baseId"), name=model["name"],
                      path=model["path"], quant=model.get("quant"), ctx=ctx, ngl=ngl, port=PORT,
                      startedAt=datetime.now().isoformat(timespec="seconds"), readyAt=None, error=None,
                      estimateGB=est["needGB"] if est else None)
        _save(last={"baseId": model.get("baseId"), "path": model["path"], "ctx": ctx, "ngl": ngl})
        threading.Thread(target=_watch, args=(_gen, _proc, logf), daemon=True, name="llama-watch").start()
        log.info("llama-server 启动中：%s（ctx=%s ngl=%s pid=%s）", model["name"], ctx, ngl, _proc.pid)
        return dict(_state)


def stop() -> dict:
    with _lock:
        _stop_locked()
        return dict(_state)


def _stop_locked() -> None:
    global _proc, _gen
    p = _proc
    _proc = None
    _gen += 1
    if p is not None and p.poll() is None:
        _kill_pid(p.pid)
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass
        log.info("llama-server 已停止（pid=%s）", p.pid)
    _state.update(status="stopped", pid=None, readyAt=None, error=None, estimateGB=None)


def shutdown() -> None:
    """Python 服务退出时调用：本服务启动的 llama-server 一起关掉。"""
    try:
        stop()
    except Exception:  # noqa: BLE001
        log.exception("关闭 llama-server 失败")


def _kill_pid(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15,
                       creationflags=_NO_WINDOW)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def _wait_port_free(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end and _port_owner(PORT):
        time.sleep(0.5)


def _health_ok() -> bool:
    import httpx

    try:
        r = httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=2, trust_env=False)
        return r.status_code == 200 and "ok" in r.text
    except httpx.HTTPError:
        return False


def _watch(gen: int, proc: subprocess.Popen, logf) -> None:
    """启动阶段等 /health ok；之后盯着进程，意外退出时记下原因。"""
    deadline = time.monotonic() + START_TIMEOUT
    try:
        while True:
            if gen != _gen:
                return
            code = proc.poll()
            if code is not None:
                with _lock:
                    if gen == _gen:
                        was = _state["status"]
                        reason = explain_failure(tail(80))
                        _state.update(status="error", pid=None, estimateGB=None,
                                      error=(f"启动失败：{reason}" if was == "starting"
                                             else f"llama-server 意外退出（代码 {code}）：{reason}"))
                        log.warning("llama-server 退出：%s", _state["error"])
                return
            if _state["status"] == "starting":
                if _health_ok():
                    with _lock:
                        if gen == _gen:
                            _state.update(status="running", readyAt=datetime.now().isoformat(timespec="seconds"))
                            log.info("llama-server 已就绪：%s", _state["name"])
                elif time.monotonic() > deadline:
                    with _lock:
                        if gen == _gen:
                            _stop_locked()
                            _state.update(status="error", error=f"{START_TIMEOUT} 秒内没有启动完成，已停止："
                                                                + explain_failure(tail(80)))
                    return
            time.sleep(1 if _state["status"] == "starting" else 3)
    finally:
        try:
            logf.close()
        except OSError:
            pass


# ---------------------------------------------------------------- 状态 / 日志

_FAILURES = [
    (re.compile(r"out of memory|cudaMalloc failed|failed to allocate|CUDA error: out of memory|unable to allocate", re.I),
     "显存不足：减小上下文长度、减少 GPU 层数，或先卸载其他占用显存的模型"),
    (re.compile(r"unknown (model )?architecture", re.I), "这个 llama.cpp 版本不支持该模型架构，请升级 llama.cpp"),
    (re.compile(r"invalid magic|failed to read magic|not a gguf|corrupt|tensor .* data is not within", re.I),
     "模型文件损坏或不完整（可能没下载完）"),
    (re.compile(r"couldn't bind|address already in use|bind.*failed", re.I), f"端口 {PORT} 被占用"),
    (re.compile(r"failed to load model|error loading model", re.I), "模型加载失败（详见日志）"),
]


def explain_failure(text: str) -> str:
    for pat, msg in _FAILURES:
        if pat.search(text):
            return msg
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1][:200] if lines else "未知原因（日志为空）"


def tail(lines: int = 60) -> str:
    try:
        with LOG_FILE.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 64 * 1024))
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return "\n".join(data.splitlines()[-max(1, min(lines, 500)):])


def status() -> dict:
    with _lock:
        s = dict(_state)
    s["baseUrl"] = f"http://127.0.0.1:{PORT}/v1"
    return s


def api_config() -> dict:
    """「GGUF」来源调用用的 OpenAI 兼容配置；llama 没在运行时报错。"""
    s = status()
    if s["status"] != "running":
        hint = "正在启动，请稍候" if s["status"] == "starting" else "请先到「llama.cpp」页选择 GGUF 模型并启动"
        raise LlamaError(f"llama.cpp 没有运行：{hint}")
    return {"baseUrl": s["baseUrl"], "apiKey": "", "model": s["name"] or "llama.cpp", "concurrency": 1}


def display_name() -> str:
    return f"llama.cpp · {_state['name'] or 'GGUF'}"


# ---------------------------------------------------------------- Windows 作业对象（随服务退出）

def _attach_job(proc: subprocess.Popen) -> None:
    """把 llama-server 放进 KILL_ON_JOB_CLOSE 的作业对象：本进程的句柄关闭（服务退出 / 崩溃）时系统结束它。"""
    global _job_handle
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if _job_handle is None:
            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

            class BASIC(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class EXTENDED(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

            k32.CreateJobObjectW.restype = wintypes.HANDLE
            job = k32.CreateJobObjectW(None, None)
            info = EXTENDED()
            info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)):
                return
            _job_handle = job
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x0001 | 0x0100, False, proc.pid)  # PROCESS_TERMINATE | PROCESS_SET_QUOTA
        if h:
            k32.AssignProcessToJobObject(wintypes.HANDLE(_job_handle), wintypes.HANDLE(h))
            k32.CloseHandle(wintypes.HANDLE(h))
    except Exception:  # noqa: BLE001
        log.debug("llama-server 加入作业对象失败（服务退出时可能不会自动结束它）", exc_info=True)
