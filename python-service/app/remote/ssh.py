"""SSH 调用：系统 OpenSSH 客户端 + 严格安全选项。

- StrictHostKeyChecking=yes：主机密钥必须已在 knownHosts 中（人工核实），不会自动接受
- 只用 targets.json 指定的私钥（IdentitiesOnly），BatchMode=yes：不回退密码 / 交互式认证
- 每次调用都有超时；错误信息只包含 ssh 的 stderr 摘要（不含凭据）
"""
import os
import shlex
import shutil
import subprocess


class SSHError(RuntimeError):
    pass


_WIN_OPENSSH = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "OpenSSH", "ssh.exe")


def _ssh_bin(target: dict) -> str:
    # Windows 优先用系统自带的 OpenSSH：Git 的 msys ssh 在无控制台的子进程中会初始化失败（0xC0000142）
    native = _WIN_OPENSSH if os.name == "nt" and os.path.isfile(_WIN_OPENSSH) else None
    path = target.get("sshPath") or native or shutil.which("ssh")
    if not path:
        raise SSHError("找不到 ssh 客户端（可在 targets.json 中设置 sshPath）")
    return path


def base_args(target: dict) -> list[str]:
    key, known = target.get("keyPath"), target.get("knownHosts")
    if not key or not os.path.isfile(key):
        raise SSHError(f"私钥文件不存在：{key}")
    if not known or not os.path.isfile(known):
        raise SSHError(f"known_hosts 文件不存在：{known}（主机密钥须人工核实后写入）")
    return [_ssh_bin(target), "-p", str(target["port"]), "-i", key,
            "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={known}", "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no", "-o", "PreferredAuthentications=publickey",
            "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=4",
            "-o", "LogLevel=ERROR", f"{target['user']}@{target['host']}"]


def run(target: dict, command: str, *, input: bytes | None = None, timeout: float = 60, check: bool = True
        ) -> subprocess.CompletedProcess:
    """在远程执行 bash 命令。返回 CompletedProcess（stdout/stderr 为 bytes）。"""
    try:
        # 没有输入时显式给空 stdin：worker 子进程继承的 stdin 可能让 ssh.exe 一直不结束
        stdin = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
        cp = subprocess.run(base_args(target) + [f"bash -c {shlex.quote(command)}"], **stdin,
                            capture_output=True, timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired as e:
        raise SSHError(f"远程命令超时（{timeout:.0f}s）") from e
    if check and cp.returncode != 0:
        err = cp.stderr.decode("utf-8", "replace").strip()[-600:]
        if cp.returncode == 255:
            raise SSHError(f"SSH 连接失败：{err or 'exit 255'}")
        raise SSHError(f"远程命令失败（exit {cp.returncode}）：{err}")
    return cp


def text(target: dict, command: str, **kw) -> str:
    return run(target, command, **kw).stdout.decode("utf-8", "replace")


def put_bytes(target: dict, data: bytes, remote_path: str, timeout: float = 600) -> None:
    q = shlex.quote(remote_path)
    run(target, f"mkdir -p \"$(dirname {q})\" && cat > {q}.part && mv {q}.part {q}", input=data, timeout=timeout)


def get_bytes(target: dict, remote_path: str, timeout: float = 1800) -> bytes:
    return run(target, f"cat {shlex.quote(remote_path)}", timeout=timeout).stdout


def tunnel(target: dict, local_port: int, remote_port: int) -> subprocess.Popen:
    """本机 127.0.0.1:local_port → 远程 127.0.0.1:remote_port 的端口转发（常驻进程，调用方负责结束）。"""
    args = base_args(target)
    args = args[:-1] + ["-N", "-o", "ExitOnForwardFailure=yes",
                        "-L", f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}", args[-1]]
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
