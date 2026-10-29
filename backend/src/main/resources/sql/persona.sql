-- 跨世界观角色卡（SQLite）：原型卡、原型版本（只追加）、适配版本、试聊会话。内容都是 JSON 文本，单条几十 KB 以内
CREATE TABLE IF NOT EXISTS persona_card (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    aliases         TEXT,                          -- JSON 数组
    source          TEXT,                          -- JSON：{type: text|file|extract, fileIds?, extractId?, entityKey?, whole, textChars}
    tags            TEXT,                          -- JSON 数组
    kind            TEXT,                          -- 分类，如 学者 / 战士
    summary         TEXT,
    current_version INTEGER,                       -- 当前版本号（persona_card_version.version_no）
    status          TEXT    NOT NULL,              -- EXTRACTING / INTERRUPTED / READY / FAILED
    progress        INTEGER NOT NULL DEFAULT 0,
    message         TEXT,
    job_id          TEXT,
    options         TEXT,                          -- 提取参数 JSON（继续时复用，不含密钥）
    create_time     TEXT    NOT NULL,
    update_time     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS persona_card_version (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id     INTEGER NOT NULL,
    version_no  INTEGER NOT NULL,
    content     TEXT    NOT NULL,                  -- 原型卡 JSON（traits / rules / expertise / voice / arc / signature / memories / lines / uncertain / holdout）
    author      TEXT    NOT NULL,                  -- ai / user
    note        TEXT,
    create_time TEXT    NOT NULL,
    UNIQUE (card_id, version_no)
);

CREATE TABLE IF NOT EXISTS persona_adaptation (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id       INTEGER NOT NULL,
    base_version  INTEGER NOT NULL,                -- 基于原型的哪个版本
    name          TEXT    NOT NULL,
    novel_id      TEXT,                            -- 目标世界观来自的工作区（可空 = 手写的世界观）
    content       TEXT    NOT NULL,                -- 适配版本 JSON（core / rules / voice / forbidden / unknowns / examples / card / checks / brief / history）
    status        TEXT    NOT NULL,                -- DRAFT / CONFIRMED
    applied       TEXT,                            -- JSON：[{novelId, version, at}] 用于了哪些工作区
    tests         TEXT,                            -- JSON：辨识度测试报告（最近 10 次）
    test_status   TEXT,                            -- RUNNING / SUCCEEDED / FAILED / null
    test_progress INTEGER,
    test_message  TEXT,
    test_job_id   TEXT,
    create_time   TEXT    NOT NULL,
    update_time   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_persona_adaptation_card ON persona_adaptation (card_id);

CREATE TABLE IF NOT EXISTS persona_chat (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id         INTEGER,                       -- 和原型试聊
    adaptation_id   INTEGER,                       -- 和适配版本试聊
    novel_id        TEXT,                          -- 工作区里的角色
    character_name  TEXT    NOT NULL,
    character       TEXT,                          -- JSON：工作区角色卡字段 / 对方身份
    mode            TEXT    NOT NULL,              -- free / scene / interview
    scene           TEXT,                          -- JSON：{description, others[{name, motive}], narrator}
    inner_on        INTEGER NOT NULL DEFAULT 1,    -- 显示内心
    messages        TEXT    NOT NULL,              -- JSON：[{role, content, inner?, at, rating?, reason?}]
    summary         TEXT,                          -- 更早对话的摘要
    summarized_upto INTEGER NOT NULL DEFAULT 0,
    drift           TEXT,                          -- JSON：最近一次走偏检查 {drift, issues, at}
    create_time     TEXT    NOT NULL,
    update_time     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_persona_chat_owner ON persona_chat (adaptation_id, card_id, novel_id);
