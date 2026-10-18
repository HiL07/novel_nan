-- 整站抓取任务下的书籍明细（SQLite）。一个整站任务按「一本一个 txt」逐本抓取，每本一行；
-- 全文同样不入库：成功后存为文件管理中的 txt（file 表 + data/upload/），这里只记任务元数据。
CREATE TABLE IF NOT EXISTS novel_crawl_book (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    crawl_id       INTEGER NOT NULL,               -- 所属整站任务（novel_crawl.id，逻辑关联）
    book_name      TEXT,
    author         TEXT,
    category       TEXT,                           -- 发现时所在的分类名
    toc_url        TEXT    NOT NULL,               -- 目录页地址（真正抓取的入口）
    status         TEXT    NOT NULL,               -- QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED
    progress       INTEGER NOT NULL DEFAULT 0,     -- 0~100
    message        TEXT,                           -- 进度说明 / 失败原因（≤1000 字）
    job_id         TEXT,                           -- Python 服务任务 id（每本书一个）
    chapter_total  INTEGER,
    chapter_done   INTEGER,
    chapter_failed INTEGER,
    word_count     INTEGER,
    file_id        INTEGER,                        -- 成功后生成的 txt（file 表，逻辑关联）
    create_time    TEXT    NOT NULL,
    update_time    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_novel_crawl_book_crawl ON novel_crawl_book (crawl_id);
