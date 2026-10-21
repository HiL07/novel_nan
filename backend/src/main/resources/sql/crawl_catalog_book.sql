-- 站点书目里的一本书（SQLite）：只存简介 / 标签 / 目录概况等元数据，完整目录在 data/<toc_path>，正文不保存
-- （选中后走普通抓取任务，每本一个 txt 进文件管理）。同一书目里按 book_url 去重，扩充时更新已有行。
CREATE TABLE IF NOT EXISTS crawl_catalog_book (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog_id     INTEGER NOT NULL,                     -- crawl_site_catalog.id（逻辑关联）
    book_name      TEXT,
    author         TEXT,
    category       TEXT,                                 -- 在哪个分类页找到的
    tags           TEXT,                                 -- 站点上的标签 JSON 数组（含分类）
    ai_tags        TEXT,                                 -- 「AI 补标签」生成的标签 JSON 数组
    intro          TEXT,
    book_url       TEXT    NOT NULL,                     -- 书籍页
    toc_url        TEXT,                                 -- 目录页（抓取时用）
    chapter_count  INTEGER NOT NULL DEFAULT 0,
    first_chapter  TEXT,
    latest_chapter TEXT,
    toc_path       TEXT,                                 -- 目录 JSON，相对 data/
    toc_ok         INTEGER NOT NULL DEFAULT 0,
    content_ok     INTEGER,                              -- 首章正文抽检：1 合格 / 0 不合格 / NULL 未抽检
    content_chars  INTEGER,
    error          TEXT,
    create_time    TEXT    NOT NULL,
    update_time    TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_crawl_catalog_book_url ON crawl_catalog_book (catalog_id, book_url);
