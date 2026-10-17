"""小说生成：设定 → 约束、分层上下文（真实 tokenizer 计数）、分段生成章节、章节摘要。

模块：
- backends  统一的模型调用接口 TextGenerator（本地 HF 已实现；远程预留）
- spec      前端设定（buildSpec 输出）→ 核心设定 / 按需检索卡片 / 未确定事项
- context   分层上下文组装与 token 预算
- prompts   提示词模板
- chapter   分段生成章节 + 摘要 + 前情合并
- store     工作区存储（JSON 文件：data/novels/<id>/，见 data/README.md）
- defaults  默认模型（Qwen2.5-1.5B-Instruct）检测
- router    /api/gen/** 接口
"""
