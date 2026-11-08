-- 架空工作区（2026-11-06）：每次架空是一个独立的工作区；勾选素材库里的原素材加入待加工，逐条生成架空版（material，source.type = portable）
CREATE TABLE IF NOT EXISTS portable_workspace (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL,
    target_world  TEXT,                          -- 示例世界（空 = 每条由 AI 选一个和原作类型差别大的世界）
    model         TEXT,                          -- JSON {source: api|gguf}
    filter        TEXT,                          -- JSON 上次用的筛选条件 {category, sourceBook, keyword, tags}（页面显示「筛选标准」）
    status        TEXT    NOT NULL,              -- IDLE / RUNNING / PAUSED（服务重启时 RUNNING → PAUSED）
    message       TEXT,
    create_time   TEXT    NOT NULL,
    update_time   TEXT    NOT NULL
);

-- 架空工作区的条目：一条原素材在一个工作区里最多一条（不同工作区互相独立）
CREATE TABLE IF NOT EXISTS portable_item (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id  INTEGER NOT NULL,              -- portable_workspace（逻辑关联）
    origin_id     INTEGER NOT NULL,              -- 原素材 material.id
    status        TEXT    NOT NULL,              -- QUEUED / RUNNING / DONE / FAILED
    portable_id   INTEGER,                       -- 生成的架空版 material.id
    leaks         INTEGER NOT NULL DEFAULT 0,    -- 示例 / 通用名里还漏着的原作专名个数
    error         TEXT,
    update_time   TEXT    NOT NULL,
    UNIQUE (workspace_id, origin_id)
);
CREATE INDEX IF NOT EXISTS idx_portable_item_ws ON portable_item (workspace_id, status);
