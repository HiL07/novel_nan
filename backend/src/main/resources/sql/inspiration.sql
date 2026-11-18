-- 灵感墙（SQLite）：多面墙，可关联一个写作工作区；墙上放收藏的思路和钉的素材；每次构思存一条构思记录
CREATE TABLE IF NOT EXISTS inspiration_wall (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    note          TEXT,
    novel_id      TEXT,                            -- 关联的工作区（Python novel id，可空）
    exclude_books TEXT,                            -- JSON 数组：构思时屏蔽的来源书
    create_time   TEXT    NOT NULL,
    update_time   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS inspiration_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    wall_id     INTEGER NOT NULL,                  -- 所属墙（逻辑关联）
    type        TEXT    NOT NULL,                  -- idea（收藏的思路）/ material（钉的素材）
    material_id INTEGER,                           -- type=material：钉的素材 id
    title       TEXT    NOT NULL,
    content     TEXT,                              -- JSON：思路 {pitch, sections, elements, twist, questions, detail, history, target}
    sources     TEXT,                              -- JSON：[{materialId, title, book, variant?}]
    note        TEXT,
    sort        INTEGER NOT NULL DEFAULT 0,
    create_time TEXT    NOT NULL,
    update_time TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inspiration_item_wall ON inspiration_item (wall_id);

CREATE TABLE IF NOT EXISTS inspiration_run (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    wall_id     INTEGER NOT NULL,
    request     TEXT,                              -- JSON：{request, target, conditions, count, model}
    plan        TEXT,                              -- JSON：{summary, needs, explore}
    materials   TEXT,                              -- JSON：[{materialId, title, book, category, variant, need}]
    ideas       TEXT,                              -- JSON：生成的思路（细化 / 修改后可更新）
    usage       TEXT,                              -- JSON：token 用量
    create_time TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inspiration_run_wall ON inspiration_run (wall_id);
