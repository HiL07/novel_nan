-- AI 解析地址学到的站点抓取规则（SQLite）。AI 解析成功后先存为「待确认」，用户确认后才在
-- 单本 / 整站抓取选「按域名自动选择」时自动套用（rule 合并到请求里）；确认会替换该域名原来已确认的规则。
CREATE TABLE IF NOT EXISTS crawl_site_rule (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    host                TEXT    NOT NULL,          -- 域名（小写），按它匹配
    home_url            TEXT,                      -- 站点根地址（首页），如 https://www.example.com/
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
    site_map            TEXT,                      -- 站点结构实测 JSON：每层跳转规律（首页/分类/书籍/目录/章节/分页/换书验证）及是否掌握
    status              TEXT    NOT NULL DEFAULT 'PENDING',  -- PENDING 待确认 / CONFIRMED 已确认（只有已确认的自动套用）/ FAILED 解析失败（只作记录）
    error               TEXT,                      -- 解析失败的原因（FAILED）
    attempt_log         TEXT,                      -- 解析过程 JSON：{attempts[每次尝试的方式 / 结果 / 原因 / 规则 / token], usage, message, sample}
    confirm_time        TEXT,
    create_time         TEXT    NOT NULL,
    update_time         TEXT    NOT NULL
);
-- 同一域名最多一条已确认 + 一条待确认（由代码保证）；规则另存一份 JSON：data/crawl-rules/<host>_<id>.json
CREATE INDEX IF NOT EXISTS idx_crawl_site_rule_host ON crawl_site_rule (host);
