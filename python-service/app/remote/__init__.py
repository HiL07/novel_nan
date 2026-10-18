"""远程 GPU 执行（AutoDL 等，经 SSH）。

- targets.py   远程机器配置：models/remote/targets.json（手工维护、git 忽略；只含主机、端口、用户、私钥路径等非敏感信息）
- ssh.py       调用系统 OpenSSH（严格校验主机密钥、只用指定私钥、BatchMode 不回退密码），带超时
- runner.py    worker 执行器 ("train", "remote")：上传代码快照与样本 → 远程运行现有 app.local.worker →
               同步进度 / 日志 → 远程取消 → 下载适配器并逐文件 SHA256 校验 → 本地登记
- inference.py 远程推理：经 SSH 隧道调用远程常驻推理进程（remote_server.py，复用 app.local.inference）
"""
