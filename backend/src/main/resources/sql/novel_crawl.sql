-- 网络小说抓取任务（SQLite）。抓到的全文存为文件管理中的一个 txt（file 表 + data/upload/），这里只记任务元数据
CREATE TABLE IF NOT EXISTS novel_crawl (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    url            TEXT    NOT NULL,               -- 目录页地址
    preset         TEXT,                           -- 规则预设 key（auto / biquge / quanshuwang …）
    options        TEXT    NOT NULL,               -- 抓取参数 JSON（url, preset, rule, delayMs, respectRobots, startIndex, endIndex），重新抓取时复用
    book_name      TEXT,
    author         TEXT,
    status         TEXT    NOT NULL,               -- QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED
    progress       INTEGER NOT NULL DEFAULT 0,     -- 0~100
    message        TEXT,                           -- 进度说明 / 失败原因（≤1000 字）
    job_id         TEXT,                           -- Python 服务任务 id
    chapter_total  INTEGER,
    chapter_done   INTEGER,
    chapter_failed INTEGER,
    word_count     INTEGER,
    file_id        INTEGER,                        -- 成功后生成的 txt（file 表，逻辑关联）
    create_time    TEXT    NOT NULL,
    update_time    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_novel_crawl_status ON novel_crawl (status);
