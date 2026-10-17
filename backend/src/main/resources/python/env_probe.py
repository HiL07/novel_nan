"""Python 环境探测脚本：由 Java 后端用「被检测的 python.exe」执行，结果以一行 JSON 打印到 stdout。

用法：python env_probe.py <requirements 文件>...
只依赖标准库（被检测环境可能什么都没装），兼容 Python 3.6+，以便低版本时也能报告版本号。
"""
import json
import os
import platform
import re
import sys

try:
    from importlib import metadata as md
except ImportError:  # Python < 3.8
    md = None


def installed_version(name):
    if md is None:
        return None
    try:
        return md.version(name)
    except Exception:
        return None


def parse_version(v):
    """'2.6.0+cu124' → (2, 6, 0)；只比较数字段，足够判断依赖是否满足。"""
    v = v.split("+")[0]
    nums = []
    for part in v.split("."):
        m = re.match(r"\d+", part)
        if not m:
            break
        nums.append(int(m.group()))
    return tuple(nums)


def cmp(a, b):
    n = max(len(a), len(b))
    a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
    return (a > b) - (a < b)


def satisfies(version, spec):
    """spec 形如 '>=4.45,<5'；支持 >= <= > < == != ~=。"""
    if not spec:
        return True
    v = parse_version(version)
    for clause in spec.split(","):
        clause = clause.strip()
        m = re.match(r"(~=|==|!=|>=|<=|>|<)\s*([\w.*+]+)", clause)
        if not m:
            continue
        op, target = m.groups()
        if target.endswith(".*"):
            prefix = parse_version(target[:-2])
            ok = v[:len(prefix)] == prefix
            if (op == "==" and not ok) or (op == "!=" and ok):
                return False
            continue
        t = parse_version(target)
        c = cmp(v, t)
        if op == ">=" and c < 0 or op == "<=" and c > 0 or op == ">" and c <= 0 or op == "<" and c >= 0:
            return False
        if op == "==" and c != 0 or op == "!=" and c == 0:
            return False
        if op == "~=":
            upper = t[:-1]
            if c < 0 or cmp(v[:len(upper)], upper) != 0:
                return False
    return True


def check_requirements(path):
    items = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        return {"file": path, "error": str(e), "items": items}
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        line = line.split(";", 1)[0].strip()  # 忽略环境标记
        m = re.match(r"([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(.*)", line)
        if not m:
            continue
        name, spec = m.group(1), m.group(3).strip()
        ver = installed_version(name)
        status = "missing" if ver is None else ("ok" if satisfies(ver, spec) else "mismatch")
        items.append({"name": name, "spec": spec, "installed": ver, "status": status})
    return {"file": path, "items": items}


def check_cuda():
    info = {"torchInstalled": False, "torchVersion": None, "cudaAvailable": False, "cudaVersion": None,
            "gpuName": None, "vramTotalMB": None, "bf16": False, "error": None}
    if installed_version("torch") is None:
        return info
    try:
        import torch

        info.update(torchInstalled=True, torchVersion=torch.__version__, cudaVersion=torch.version.cuda,
                    cudaAvailable=bool(torch.cuda.is_available()))
        if info["cudaAvailable"]:
            props = torch.cuda.get_device_properties(0)
            info.update(gpuName=props.name, vramTotalMB=int(props.total_memory // (1024 * 1024)),
                        bf16=bool(torch.cuda.is_bf16_supported()))
    except Exception as e:  # torch 损坏、DLL 缺失等
        info["error"] = "%s: %s" % (e.__class__.__name__, e)
    return info


def main():
    result = {
        "executable": sys.executable,
        "version": platform.python_version(),
        "versionInfo": list(sys.version_info[:3]),
        "implementation": platform.python_implementation(),
        "arch": platform.architecture()[0],
        "prefix": sys.prefix,
        "isVenv": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
        "condaEnv": os.environ.get("CONDA_DEFAULT_ENV") or (
            os.path.basename(sys.prefix) if os.path.isdir(os.path.join(sys.prefix, "conda-meta")) else None),
        "requirements": [check_requirements(p) for p in sys.argv[1:]],
        "cuda": check_cuda(),
    }
    sys.stdout.write("@@PROBE@@" + json.dumps(result, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
