-- AI 模型配置（SQLite）
CREATE TABLE IF NOT EXISTS ai_model_config (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,               -- 显示名称
    provider_type  TEXT,                           -- preset（第三方模型提供商）/ custom（自定义模型 API）
    provider_id    TEXT,                           -- 预设键或自定义 Provider ID
    protocol       TEXT,                           -- openai / anthropic（null = openai）
    models         TEXT,                           -- 模型目录 JSON 数组
    base_url       TEXT    NOT NULL,               -- API 根地址
    model          TEXT    NOT NULL,               -- 模型名
    api_key        TEXT,                           -- API Key（接口不回显明文）
    concurrency    INTEGER NOT NULL DEFAULT 1,     -- 任务内并发请求数
    status         TEXT    NOT NULL,               -- UNVERIFIED/VERIFIED/FAILED
    verify_message TEXT,
    verified_time  TEXT,
    active         INTEGER NOT NULL DEFAULT 0,     -- 0/1 是否当前启用
    create_time    TEXT    NOT NULL,
    update_time    TEXT    NOT NULL
);
