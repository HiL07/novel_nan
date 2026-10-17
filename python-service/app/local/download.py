"""下载基础模型到 models/base/<id>/weights/（在 worker 子进程中运行），完成后自动登记。

下载源（settings.DOWNLOAD_SOURCE 或请求的 source）：
- huggingface：官方站（HF_ENDPOINT 可改地址）
- hf-mirror：Hugging Face 镜像（HF_MIRROR_ENDPOINT，默认 hf-mirror.com）
- modelscope：魔搭社区（MODELSCOPE_ENDPOINT），用其 HTTP 接口下载，逐文件校验大小与 SHA-256，不依赖 modelscope 包
- auto：按 DOWNLOAD_AUTO_ORDER 依次尝试，某个源不可用或下载失败就换下一个

镜像有时会把请求 308 重定向回 huggingface.co，huggingface_hub 拿不到文件元数据，最终报 LocalEntryNotFoundError
（看起来像断网）。因此 HF 类的源在下载前先取一次 config.json 的元数据，确认该源真的能提供文件。
"""
import hashlib
import shutil
import time
from fnmatch import fnmatch
from pathlib import Path

from . import hardware, registry, settings

ALLOW = ["*.json", "*.safetensors", "*.txt", "*.model", "*.tiktoken", "*.jinja", "tokenizer*"]
SOURCES = ("auto", "modelscope", "hf-mirror", "huggingface")
SOURCE_LABELS = {"modelscope": "ModelScope 魔搭", "hf-mirror": "hf-mirror 镜像", "huggingface": "Hugging Face 官方"}


class SourceUnavailable(RuntimeError):
    """该下载源当前不能提供这个仓库（不存在、被重定向、网络不通等）。"""


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _allowed(path: str) -> bool:
    return any(fnmatch(path, p) or fnmatch(Path(path).name, p) for p in ALLOW)


# ---------------- Hugging Face（官方 / 镜像） ----------------

def _hf_endpoint(source: str) -> str:
    return settings.HF_MIRROR_ENDPOINT if source == "hf-mirror" else settings.HF_OFFICIAL_ENDPOINT


def _hf_plan(source: str, repo: str) -> list[tuple[str, int]]:
    from huggingface_hub import HfApi, get_hf_file_metadata, hf_hub_url

    ep = _hf_endpoint(source)
    try:
        info = HfApi(endpoint=ep).model_info(repo, files_metadata=True)
        meta = get_hf_file_metadata(hf_hub_url(repo, "config.json", endpoint=ep), timeout=30)
    except Exception as e:  # noqa: BLE001  网络错误、404、鉴权等
        first = (str(e).strip().splitlines() or [""])[0]
        raise SourceUnavailable(f"{ep} 无法访问该仓库：{type(e).__name__}: {first[:200]}") from e
    if not meta.commit_hash:
        raise SourceUnavailable(f"{ep} 没有返回文件元数据（可能被重定向到其他站点），无法用它下载")
    return [(s.rfilename, s.size or 0) for s in info.siblings if _allowed(s.rfilename)]


def _hf_fetch(source: str, repo: str, files: list[tuple[str, int]], target: Path) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(repo, local_dir=str(target), allow_patterns=[f for f, _ in files], endpoint=_hf_endpoint(source))


# ---------------- ModelScope ----------------

def _ms_client():
    import httpx

    return httpx.Client(timeout=httpx.Timeout(60, connect=20), follow_redirects=True)


def _ms_plan(repo: str) -> list[tuple[str, int, str | None]]:
    url = f"{settings.MODELSCOPE_ENDPOINT}/api/v1/models/{repo}/repo/files"
    try:
        with _ms_client() as c:
            r = c.get(url, params={"Revision": "master", "Recursive": "true"})
            data = r.json()
    except Exception as e:  # noqa: BLE001
        raise SourceUnavailable(f"{settings.MODELSCOPE_ENDPOINT} 无法访问：{type(e).__name__}: {str(e)[:200]}") from e
    if r.status_code != 200 or data.get("Code") != 200:
        raise SourceUnavailable(f"ModelScope 上没有找到 {repo}：{data.get('Message') or r.status_code}")
    return [(f["Path"], int(f.get("Size") or 0), f.get("Sha256") or None)
            for f in data["Data"]["Files"] if f.get("Type") == "blob" and _allowed(f["Path"])]


def _ms_fetch(repo: str, files: list[tuple[str, int, str | None]], target: Path) -> None:
    url = f"{settings.MODELSCOPE_ENDPOINT}/api/v1/models/{repo}/repo"
    with _ms_client() as c:
        for i, (path, size, sha) in enumerate(files, 1):
            dest = target / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_name(dest.name + ".part")
            h, done, next_mark = hashlib.sha256(), 0, 0.1
            _log(f"[{i}/{len(files)}] {path}（{size / hardware.GB:.2f} GB）")
            with c.stream("GET", url, params={"Revision": "master", "FilePath": path}) as r:
                r.raise_for_status()
                with open(part, "wb") as fh:
                    for chunk in r.iter_bytes(1 << 20):
                        fh.write(chunk)
                        h.update(chunk)
                        done += len(chunk)
                        if size > 200 * 1024 * 1024 and done / size >= next_mark:
                            _log(f"    {path}：{done / size:.0%}")
                            next_mark += 0.1
            if size and done != size:
                raise RuntimeError(f"{path} 大小不符：应为 {size} 字节，实际 {done} 字节")
            if sha and h.hexdigest() != sha.lower():
                raise RuntimeError(f"{path} SHA-256 校验失败，文件可能损坏")
            part.replace(dest)


# ---------------- 入口 ----------------

def resolve_order(source: str) -> list[str]:
    if source == "auto":
        order = [s for s in settings.DOWNLOAD_AUTO_ORDER if s in SOURCE_LABELS]
        return order or ["modelscope", "hf-mirror", "huggingface"]
    if source not in SOURCE_LABELS:
        raise ValueError(f"未知下载源：{source}（可选 {', '.join(SOURCES)}）")
    return [source]


def _try_source(source: str, repo: str, target: Path) -> None:
    if source == "modelscope":
        files = _ms_plan(repo)
    else:
        files = [(f, s, None) for f, s in _hf_plan(source, repo)]
    if not any(f.endswith(".safetensors") for f, _, _ in files):
        raise SourceUnavailable(f"{SOURCE_LABELS[source]} 上的 {repo} 没有 safetensors 权重文件")
    size_gb = sum(s for _, s, _ in files) / hardware.GB
    free_gb = hardware.disk_free_gb(settings.MODELS_DIR)
    _log(f"{SOURCE_LABELS[source]}：{repo} 共 {len(files)} 个文件，约 {size_gb:.2f} GB；目标磁盘剩余 {free_gb:.1f} GB")
    if size_gb + 2 > free_gb:
        # 磁盘不足换源也没用，直接失败
        raise RuntimeError(f"磁盘空间不足：需要约 {size_gb:.1f} GB（另留 2 GB 余量），{settings.MODELS_DIR} 所在磁盘仅剩 {free_gb:.1f} GB。"
                           "可设置环境变量 LOCAL_MODELS_DIR 指向空间更大的磁盘，或把模型下载到别处后用「登记本地模型」")
    if source == "modelscope":
        _ms_fetch(repo, files, target)
    else:
        _hf_fetch(source, repo, [(f, s) for f, s, _ in files], target)


def run(job: dict) -> dict:
    cfg = job["config"]
    repo, model_id = cfg["repoId"], cfg["modelId"]
    # 旧任务只有 useMirror：True → hf-mirror，False → 官方
    source = cfg.get("source") or ("hf-mirror" if cfg.get("useMirror") else "huggingface")
    order = resolve_order(source)
    model_dir = settings.BASE_DIR / model_id
    target = model_dir / "weights"
    _log(f"下载源：{source}" + (f"（依次尝试 {' → '.join(order)}）" if source == "auto" else ""))

    errors = []
    for i, src in enumerate(order):
        try:
            _try_source(src, repo, target)
            rec = registry.register_base(cfg["name"], str(target), model_id=model_id,
                                         origin=f"{'modelscope' if src == 'modelscope' else 'hf'}:{repo}")
        except Exception as e:  # noqa: BLE001
            shutil.rmtree(model_dir, ignore_errors=True)  # 磁盘紧张，失败不保留残缺文件
            if isinstance(e, RuntimeError) and str(e).startswith("磁盘空间不足"):
                raise
            errors.append(f"{SOURCE_LABELS[src]}：{e}")
            _log(f"{SOURCE_LABELS[src]} 失败：{e}" + ("，改用下一个下载源" if i + 1 < len(order) else ""))
            continue
        _log(f"下载完成并已登记：{rec['name']}（{rec['numParams'] / 1e9:.2f}B 参数，来源 {SOURCE_LABELS[src]}）")
        return {"baseId": model_id, "source": src}
    raise RuntimeError("所有下载源均失败：\n" + "\n".join(errors))
