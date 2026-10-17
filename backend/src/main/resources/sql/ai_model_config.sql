-- AI 模型配置（SQLite）
CREATE TABLE IF NOT EXISTS ai_model_config (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,               -- 显示名称
    base_url       TEXT    NOT NULL,               -- OpenAI 兼容根地址
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
