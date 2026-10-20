-- 创作素材库（SQLite）：素材卡片（概括 ≤300 字、属性为小 JSON）、标签索引、AI 提取的待确认候选
CREATE TABLE IF NOT EXISTS material (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT    NOT NULL,                  -- world/faction/character/monster/location/item/plot
    subtype     TEXT,
    title       TEXT    NOT NULL,
    summary     TEXT,
    attributes  TEXT,                              -- JSON：{"外形":"…","弱点":["火"]}
    detail      TEXT,
    tags        TEXT,                              -- JSON 数组（检索走 material_tag）
    source      TEXT,                              -- JSON：{type, extractId, fileId, fileName, chapters, excerpt}
    source_book TEXT,                              -- 来源书名（文件名去扩展名；手动添加可自填），按书筛选 / 屏蔽 / 删除
    pinned      INTEGER NOT NULL DEFAULT 0,        -- 1 = 保留：按书删除、屏蔽来源书都不影响它
    use_count   INTEGER NOT NULL DEFAULT 0,
    create_time TEXT    NOT NULL,
    update_time TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_material_category ON material (category);
CREATE INDEX IF NOT EXISTS idx_material_update_time ON material (update_time);
-- source_book 的索引与旧库加列在 config/SchemaMigrations 中处理（本脚本先于迁移执行，旧库此时还没有该列）

CREATE TABLE IF NOT EXISTS material_tag (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL,
    tag         TEXT    NOT NULL,
    UNIQUE (material_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_material_tag_tag ON material_tag (tag);

CREATE TABLE IF NOT EXISTS material_candidate (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    extract_id    INTEGER NOT NULL,                -- 来源提取任务（novel_extract，逻辑关联）
    file_id       INTEGER,
    file_name     TEXT,
    candidate_key TEXT    NOT NULL,                -- 提取结果中的 candidateId（同一任务内去重）
    category      TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    payload       TEXT    NOT NULL,                -- 候选内容 JSON（约 1 KB）
    status        TEXT    NOT NULL,                -- PENDING/SAVED/IGNORED
    material_id   INTEGER,
    create_time   TEXT    NOT NULL,
    update_time   TEXT    NOT NULL,
    UNIQUE (extract_id, candidate_key)
);
CREATE INDEX IF NOT EXISTS idx_material_candidate_status ON material_candidate (status);
