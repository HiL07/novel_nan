"""下载基础模型（在 worker 子进程中运行），完成后自动登记。

保存位置：默认 models/base/<id>/weights/；也可指定任意目录 targetDir（如 7B 模型约 15 GB，放到空间大的盘），
实际写入 <targetDir>/<仓库名>/，登记为「本服务下载」（ownsFiles），删除登记时一并删除这些文件。
目录里放一个 DOWNLOAD_MARKER 标记，下载中断后可以对同一目录重新下载（其他非空目录一律拒绝，避免覆盖别人的文件）。

下载源（settings.DOWNLOAD_SOURCE 或请求的 source）：
- huggingface：官方站（HF_ENDPOINT 可改地址）
- hf-mirror：Hugging Face 镜像（HF_MIRROR_ENDPOINT，默认 hf-mirror.com）
- modelscope：魔搭社区（MODELSCOPE_ENDPOINT），用其 HTTP 接口下载，逐文件校验大小与 SHA-256，不依赖 modelscope 包
- auto：按 DOWNLOAD_AUTO_ORDER 依次尝试，某个源不可用或下载失败就换下一个

镜像有时会把请求 308 重定向回 huggingface.co，huggingface_hub 拿不到文件元数据，最终报 LocalEntryNotFoundError
（看起来像断网）。因此 HF 类的源在下载前先取一次 config.json 的元数据，确认该源真的能提供文件。
"""
import hashlib
import os
import re
import shutil
import time
from fnmatch import fnmatch
from pathlib import Path

from . import hardware, registry, settings

ALLOW = ["*.json", "*.safetensors", "*.txt", "*.model", "*.tiktoken", "*.jinja", "tokenizer*"]
SOURCES = ("auto", "modelscope", "hf-mirror", "huggingface")
SOURCE_LABELS = {"modelscope": "ModelScope 魔搭", "hf-mirror": "hf-mirror 镜像", "huggingface": "Hugging Face 官方"}
DOWNLOAD_MARKER = ".nan_novel_downloading"
DISK_MARGIN_GB = 2


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


# ---------------- 保存位置 ----------------

def existing_ancestor(path: Path) -> Path:
    """path 本身或最近一个已存在的上级目录（用来查所在磁盘的剩余空间）。"""
    p = path
    while not p.exists() and p.parent != p:
        p = p.parent
    return p


def resolve_target(target_dir: str | None, repo: str, model_id: str) -> Path:
    """确定权重的保存目录并校验：空 → models/base/<id>/weights；否则 <target_dir>/<仓库名>。
    要求绝对路径、所在磁盘存在、不在系统目录下；目标已存在时必须为空或是本服务未完成的下载。"""
    if not target_dir or not target_dir.strip():
        return settings.BASE_DIR / model_id / "weights"
    raw = Path(target_dir.strip().strip('"'))
    if not raw.is_absolute():
        raise ValueError("保存位置请填写绝对路径，如 D:\\models")
    base = raw.resolve()
    if not Path(base.anchor).exists():
        raise ValueError(f"磁盘不存在：{base.anchor}")
    system_root = os.environ.get("SystemRoot")
    if system_root and _is_under(base, Path(system_root)):
        raise ValueError("不能下载到系统目录")
    if base.exists() and not base.is_dir():
        raise ValueError(f"{base} 是文件，不是目录")
    folder = re.sub(r'[\\/:*?"<>|]', "_", repo.split("/")[-1])
    target = base / folder
    if target.exists():
        if not target.is_dir():
            raise ValueError(f"{target} 已存在且不是目录")
        if any(target.iterdir()) and not (target / DOWNLOAD_MARKER).exists():
            raise ValueError(f"{target} 已存在且不为空：请换个位置；如果里面就是这个模型，请用「登记本地模型」直接登记")
    return target


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def check(repo: str, source: str, target_dir: str | None) -> dict:
    """下载前检查：哪个源可用、模型多大、目标磁盘还剩多少。→ {source, files, sizeGb, target, freeGb, enough}"""
    target = resolve_target(target_dir, repo, "<id>")
    errors = []
    for src in resolve_order(source):
        try:
            files = _ms_plan(repo) if src == "modelscope" else [(f, s, None) for f, s in _hf_plan(src, repo)]
        except SourceUnavailable as e:
            errors.append(f"{SOURCE_LABELS[src]}：{e}")
            continue
        size_gb = sum(s for _, s, _ in files) / hardware.GB
        free_gb = hardware.disk_free_gb(existing_ancestor(target))
        return {"source": src, "sourceLabel": SOURCE_LABELS[src], "files": len(files), "sizeGb": round(size_gb, 2),
                "target": str(target), "freeGb": free_gb, "enough": size_gb + DISK_MARGIN_GB <= free_gb,
                "hasWeights": any(f.endswith(".safetensors") for f, _, _ in files)}
    raise RuntimeError("所有下载源都无法提供该仓库：\n" + "\n".join(errors))


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
    free_gb = hardware.disk_free_gb(existing_ancestor(target))
    _log(f"{SOURCE_LABELS[source]}：{repo} 共 {len(files)} 个文件，约 {size_gb:.2f} GB；保存到 {target}，所在磁盘剩余 {free_gb:.1f} GB")
    if size_gb + DISK_MARGIN_GB > free_gb:
        # 磁盘不足换源也没用，直接失败
        raise RuntimeError(f"磁盘空间不足：需要约 {size_gb:.1f} GB（另留 {DISK_MARGIN_GB} GB 余量），{target} 所在磁盘仅剩 {free_gb:.1f} GB。"
                           "请在下载对话框里换一个空间更大的「保存位置」（如 D 盘）")
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
    external = bool(cfg.get("targetDir"))
    target = Path(cfg["targetDir"]) if external else model_dir / "weights"
    _log(f"下载源：{source}" + (f"（依次尝试 {' → '.join(order)}）" if source == "auto" else ""))
    _log(f"保存位置：{target}")

    errors = []
    for i, src in enumerate(order):
        try:
            target.mkdir(parents=True, exist_ok=True)
            (target / DOWNLOAD_MARKER).write_text(repo, encoding="utf-8")
            _try_source(src, repo, target)
            (target / DOWNLOAD_MARKER).unlink(missing_ok=True)
            rec = registry.register_base(cfg["name"], str(target), model_id=model_id, owns_files=external,
                                         origin=f"{'modelscope' if src == 'modelscope' else 'hf'}:{repo}")
        except Exception as e:  # noqa: BLE001
            # 磁盘紧张，失败不保留残缺文件（外部目录只删本次创建的 <仓库名> 子目录）
            shutil.rmtree(target if external else model_dir, ignore_errors=True)
            if isinstance(e, RuntimeError) and str(e).startswith("磁盘空间不足"):
                raise
            errors.append(f"{SOURCE_LABELS[src]}：{e}")
            _log(f"{SOURCE_LABELS[src]} 失败：{e}" + ("，改用下一个下载源" if i + 1 < len(order) else ""))
            continue
        _log(f"下载完成并已登记：{rec['name']}（{rec['numParams'] / 1e9:.2f}B 参数，来源 {SOURCE_LABELS[src]}）")
        return {"baseId": model_id, "source": src, "path": str(target)}
    raise RuntimeError("所有下载源均失败：\n" + "\n".join(errors))
