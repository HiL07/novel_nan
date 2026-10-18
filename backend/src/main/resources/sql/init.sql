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
    use_count   INTEGER NOT NULL DEFAULT 0,
    create_time TEXT    NOT NULL,
    update_time TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_material_category ON material (category);
CREATE INDEX IF NOT EXISTS idx_material_update_time ON material (update_time);

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
