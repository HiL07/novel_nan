-- =====================================================================
-- nan_novel 数据库初始化脚本（SQLite 3.35+）。只存元数据，大内容在 data/ 下的文件中（见 data/README.md）
--
-- 一键初始化（在项目根目录）：
--   sqlite3 data/nan_novel.db < backend/src/main/resources/sql/init.sql
--
-- 说明：
--   - 全部使用 IF NOT EXISTS，可重复执行，不会删除或覆盖数据
--   - 不含任何账号 / API Key；默认 DeepSeek 模型配置由后端首次启动时自动写入
--   - 后端启动时也会按同目录的分表脚本自动建表；本文件由分表脚本拼接而成，修改表结构时请同步更新
--   - 迁移到 SQLite 之前的 MySQL 版脚本在 sql/mysql/（仅供回滚）
-- =====================================================================
PRAGMA journal_mode = WAL;

-- 文件元数据（SQLite；spring.sql.init 启动时执行，已存在则跳过）。文件本体在 data/upload/，storage_path 为相对路径
CREATE TABLE IF NOT EXISTS file (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name    TEXT    NOT NULL,                 -- 原始文件名
    storage_path TEXT    NOT NULL,                 -- 相对上传根目录的路径 yyyy/MM/dd/<uuid>.<ext>
    file_size    INTEGER NOT NULL DEFAULT 0,       -- 字节
    content_type TEXT,                             -- MIME 类型
    file_ext     TEXT,                             -- 扩展名（不含点）
    create_time  TEXT    NOT NULL                  -- yyyy-MM-dd HH:mm:ss
);
CREATE INDEX IF NOT EXISTS idx_file_create_time ON file (create_time);

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

-- 整站抓取任务下的书籍明细（SQLite）。整站模式按「一本一个 txt」逐本抓取，每本一行
CREATE TABLE IF NOT EXISTS novel_crawl_book (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    crawl_id       INTEGER NOT NULL,               -- 所属整站任务（novel_crawl.id，逻辑关联）
    book_name      TEXT,
    author         TEXT,
    category       TEXT,                           -- 发现时所在的分类名
    toc_url        TEXT    NOT NULL,               -- 目录页地址（真正抓取的入口）
    status         TEXT    NOT NULL,               -- QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED
    progress       INTEGER NOT NULL DEFAULT 0,
    message        TEXT,
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

-- AI 模型配置（SQLite）
CREATE TABLE IF NOT EXISTS ai_model_config (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,               -- 显示名称
    base_url       TEXT    NOT NULL,               -- OpenAI 兼容根地址
    model          TEXT    NOT NULL,               -- 模型名
    api_key        TEXT,                           -- API Key（接口不回显明文）
    concurrency    INTEGER NOT NULL DEFAULT 1,     -- 任务内并发请求数
    status         TEXT    NOT NULL,               -- UNVERIFIED/VERIFIED/FAILED
    verify_message TEXT,
    verified_time  TEXT,
    active         INTEGER NOT NULL DEFAULT 0,     -- 0/1 是否当前启用
    create_time    TEXT    NOT NULL,
    update_time    TEXT    NOT NULL
);

-- Python 环境配置（SQLite）。只保存检测通过的配置，active=1 为当前使用；check_result 为有上限的检测结果 JSON（约 4 KB）
CREATE TABLE IF NOT EXISTS python_env (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    env_type       TEXT    NOT NULL,               -- SYSTEM/CONDA/VENV/CUSTOM
    python_path    TEXT    NOT NULL,               -- python.exe 绝对路径
    conda_root     TEXT,
    conda_env      TEXT,
    python_version TEXT,
    cuda_available INTEGER NOT NULL DEFAULT 0,
    gpu_name       TEXT,
    torch_version  TEXT,
    status         TEXT    NOT NULL,               -- OK/WARN
    check_result   TEXT,
    active         INTEGER NOT NULL DEFAULT 0,
    checked_time   TEXT    NOT NULL,
    create_time    TEXT    NOT NULL
);

-- 创作素材库（SQLite）：素材卡片（概括 ≤300 字、属性为小 JSON）、标签索引、AI 提取的待确认候选
CREATE TABLE IF NOT EXISTS material (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT    NOT NULL,                  -- world/faction/character/monster/location/item/plot
    subtype     TEXT,
    title       TEXT    NOT NULL,
    summary     TEXT,
    attributes  TEXT,                              -- JSON：{"外形":"…","弱点":["火"]}
    detail      TEXT,
    tags        TEXT,                              -- JSON 数组（检索走 material_tag）
    source      TEXT,                              -- JSON：{type, extractId, fileId, fileName, chapters, excerpt}
    source_book TEXT,                              -- 来源书名（文件名去扩展名；手动添加可自填），按书筛选 / 屏蔽 / 删除
    pinned      INTEGER NOT NULL DEFAULT 0,        -- 1 = 保留：按书删除、屏蔽来源书都不影响它
    use_count   INTEGER NOT NULL DEFAULT 0,
    create_time TEXT    NOT NULL,
    update_time TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_material_category ON material (category);
CREATE INDEX IF NOT EXISTS idx_material_update_time ON material (update_time);
CREATE INDEX IF NOT EXISTS idx_material_source_book ON material (source_book);

CREATE TABLE IF NOT EXISTS material_tag (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL,
    tag         TEXT    NOT NULL,
    UNIQUE (material_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_material_tag_tag ON material_tag (tag);

CREATE TABLE IF NOT EXISTS material_candidate (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    extract_id    INTEGER NOT NULL,                -- 来源提取任务（novel_extract，逻辑关联）
    file_id       INTEGER,
    file_name     TEXT,
    candidate_key TEXT    NOT NULL,                -- 提取结果中的 candidateId（同一任务内去重）
    category      TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    payload       TEXT    NOT NULL,                -- 候选内容 JSON（约 1 KB）
    status        TEXT    NOT NULL,                -- PENDING/SAVED/IGNORED
    material_id   INTEGER,
    create_time   TEXT    NOT NULL,
    update_time   TEXT    NOT NULL,
    UNIQUE (extract_id, candidate_key)
);
CREATE INDEX IF NOT EXISTS idx_material_candidate_status ON material_candidate (status);

-- AI 解析地址学到的站点抓取规则（每个域名一行）
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
