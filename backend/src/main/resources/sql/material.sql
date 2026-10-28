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
    merged_into INTEGER,                           -- 已并入哪个主条目（精炼 / 合并）；非空的素材不出现在列表 / 检索 / AI 里，拆分时清空
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

-- 精炼 / 合并建议：本地向量模型找出的相似素材组（同分类，跨书或同书），可让 AI 写合并稿，用户确认后才合并
-- （主条目 = 新素材，source = {type: merge, members, variants}；成员的 material.merged_into 指向它，可拆分还原）
CREATE TABLE IF NOT EXISTS material_merge (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT    NOT NULL,
    member_ids  TEXT    NOT NULL,                  -- JSON 数组：组内素材 id（按 id 升序，同一组成员 = 同一建议）
    score       REAL,                              -- 组内平均相似度（余弦）
    cross_book  INTEGER NOT NULL DEFAULT 0,        -- 1 = 成员来自不同的书
    status      TEXT    NOT NULL,                  -- FOUND（待处理）/DRAFTING/DRAFTED（AI 合并稿已写好）/APPLIED（已合并）/IGNORED
    draft       TEXT,                              -- AI 合并稿 JSON {same, title, subtype, summary, detail, attributes, tags, variants, model}
    message     TEXT,                              -- 写合并稿失败的原因等
    material_id INTEGER,                           -- 合并后的主条目 id
    create_time TEXT    NOT NULL,
    update_time TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_material_merge_status ON material_merge (status);
