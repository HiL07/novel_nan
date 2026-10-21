-- 小说抓取页「常用地址」（SQLite）：用户收藏的可抓取网址（目录页 / 书籍详情页 / 站点首页），一个地址一行。
CREATE TABLE IF NOT EXISTS crawl_saved_url (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    url            TEXT    NOT NULL,
    name           TEXT,                      -- 显示名，如书名 / 站点名
    mode           TEXT    NOT NULL DEFAULT 'book',   -- book 单本 / site 整站：选用时切到对应模式
    note           TEXT,
    use_count      INTEGER NOT NULL DEFAULT 0,
    last_used_time TEXT,
    create_time    TEXT    NOT NULL,
    update_time    TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_crawl_saved_url_url ON crawl_saved_url (url);
