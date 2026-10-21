-- AI 解析地址学到的站点抓取规则（SQLite）。每个域名一行，同域名再次学习成功会覆盖；
-- 之后单本 / 整站抓取选「按域名自动选择」时自动套用（rule 合并到请求里）。
CREATE TABLE IF NOT EXISTS crawl_site_rule (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    host                TEXT    NOT NULL,          -- 域名（小写），按它匹配
    site_name           TEXT,
    preset              TEXT,                      -- 规则基于的内置预设 key（auto / biquge …）
    rule                TEXT,                      -- CrawlRule JSON，只含非空字段；{} 表示内置规则即可
    summary             TEXT,                      -- 大模型总结的地址规律与规则说明
    book_url_pattern    TEXT,
    toc_url_pattern     TEXT,
    chapter_url_pattern TEXT,
    sample_url          TEXT,                      -- 学习时输入的书籍地址
    toc_url             TEXT,                      -- 学习时实际使用的目录页
    book_name           TEXT,
    strategy            TEXT,                      -- learned / preset / ai：哪种尝试成功的
    attempts            INTEGER,                   -- 第几次尝试成功
    chapter_count       INTEGER,
    create_time         TEXT    NOT NULL,
    update_time         TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_crawl_site_rule_host ON crawl_site_rule (host);
