-- 整理卡片任务（SQLite）：对一次小说提取（novel_extract）的实体档案单独发起，产出的素材卡 / 剧情段进入待确认候选。
-- 一次提取可以整理多次（换模型 / 换范围）。断点在 Python 的 data/extract-cache/k<id>/
CREATE TABLE IF NOT EXISTS material_compile (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    extract_id      INTEGER NOT NULL,              -- 来源提取任务（novel_extract，逻辑关联）
    status          TEXT    NOT NULL,              -- QUEUED/RUNNING/INTERRUPTED（中断，可继续）/SUCCEEDED/FAILED
    progress        INTEGER NOT NULL DEFAULT 0,    -- 0~100
    message         TEXT,                          -- 进度说明 / 失败原因（≤1000 字）
    job_id          TEXT,                          -- Python 服务任务 id
    options         TEXT,                          -- 参数 JSON {model, entityKeys?, categories?, topN?, plot}，继续时复用
    entity_count    INTEGER,                       -- 交给模型整理的实体数
    card_count      INTEGER,                       -- 统计：素材卡（含体系卡）
    arc_count       INTEGER,                       -- 统计：剧情段
    candidate_count INTEGER,                       -- 统计：实际进入待确认的条数（同书重复的不算）
    create_time     TEXT    NOT NULL,
    update_time     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_material_compile_extract ON material_compile (extract_id);
