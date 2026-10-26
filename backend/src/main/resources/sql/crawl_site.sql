-- 小说抓取页「小说网站爬取」（SQLite）：用户指定的小说网站，一个首页一行。新增时任何站内地址都归一为首页
-- （scheme://host[:port]/），原地址留作 AI 解析的样例书地址；解析状态 / 书目按首页关联 crawl_site_rule / crawl_site_catalog。
CREATE TABLE IF NOT EXISTS crawl_site (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    home_url    TEXT    NOT NULL,                -- 首页，如 https://www.example.com/
    host        TEXT    NOT NULL,                -- 域名（小写）
    name        TEXT,                            -- 显示名，可空（空时界面显示域名）
    sample_url  TEXT,                            -- 新增时填的原地址（书籍页 / 目录页时可直接拿去 AI 解析）
    note        TEXT,
    create_time TEXT    NOT NULL,
    update_time TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_crawl_site_home ON crawl_site (home_url);
