-- 小说提取任务（SQLite）。完整结果不入库：存于 data/extract-results/<id>.json，这里只记相对路径、大小、SHA-256 与统计
CREATE TABLE IF NOT EXISTS novel_extract (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL,              -- 源文件 id（file 表，逻辑关联）
    file_name       TEXT,
    status          TEXT    NOT NULL,              -- QUEUED/RUNNING/SUCCEEDED/FAILED
    progress        INTEGER NOT NULL DEFAULT 0,    -- 0~100
    message         TEXT,                          -- 进度说明 / 失败原因（≤1000 字）
    job_id          TEXT,                          -- Python 服务任务 id
    result_path     TEXT,                          -- 结果 JSON 相对 data/ 的路径，如 extract-results/12.json
    result_size     INTEGER,                       -- 结果文件字节数
    result_sha256   TEXT,                          -- 结果文件 SHA-256（读取时校验）
    word_count      INTEGER,                       -- 统计：总字数
    chapter_count   INTEGER,                       -- 统计：章节数
    candidate_count INTEGER,                       -- 统计：素材候选数
    create_time     TEXT    NOT NULL,
    update_time     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_novel_extract_file_id ON novel_extract (file_id);
CREATE INDEX IF NOT EXISTS idx_novel_extract_status ON novel_extract (status);
