"""本地模型：注册 / 下载、推理、LoRA/QLoRA 风格微调。

扩展点（远程推理 / 远程训练暂未实现）：
- registry 记录带 source 字段（目前只有 "local"）
- jobs 记录带 backend 字段，worker.RUNNERS 按 (kind, backend) 分派执行器
- inference 目前只有本机进程内实现；远程推理可另写模块并在 router 中按 source 分派
"""
