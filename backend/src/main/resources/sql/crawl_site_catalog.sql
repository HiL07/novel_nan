-- 全自动爬虫的站点书目（SQLite）：一个站点首页一行。按 AI 解析学到的规律（crawl_site_rule）测试能否找到多本书、
-- 取到目录 / 简介 / 标签 / 正文，测试报告存 report；用户决定是否使用（decision），使用后可扩充书目、筛选并抓取。
-- 同一首页的数据放在一起：data/site-catalog/<host>/（toc/<key>.json 每本书的目录，catalog.json 书目导出）。
CREATE TABLE IF NOT EXISTS crawl_site_catalog (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    host           TEXT    NOT NULL,
    home_url       TEXT    NOT NULL,                     -- 站点首页（规则的 home_url）
    site_name      TEXT,
    rule_id        INTEGER,                              -- 使用的站点规则（crawl_site_rule.id，逻辑关联）
    catalog_dir    TEXT    NOT NULL,                     -- 相对 data/ 的目录，如 site-catalog/www.example.com
    decision       TEXT    NOT NULL DEFAULT 'PENDING',   -- PENDING 待决定 / USED 使用 / REJECTED 不使用
    status         TEXT    NOT NULL DEFAULT 'IDLE',      -- 最近一次采集：IDLE / RUNNING / SUCCEEDED / FAILED / CANCELLED
    phase          TEXT,                                 -- test 测试 / scan 扩充书目
    job_id         TEXT,                                 -- Python 书目采集任务
    progress       INTEGER NOT NULL DEFAULT 0,
    message        TEXT,
    report         TEXT,                                 -- 最近一次「测试」的报告 JSON（见 python-service/app/crawler/catalog.py#_report）
    last_report    TEXT,                                 -- 最近一次采集（测试或扩充）的报告 JSON
    book_count     INTEGER NOT NULL DEFAULT 0,
    last_scan_time TEXT,
    create_time    TEXT    NOT NULL,
    update_time    TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_crawl_site_catalog_home ON crawl_site_catalog (home_url);
