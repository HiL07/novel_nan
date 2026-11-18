-- 卡片（卡片整理工作区，2026-11-03）：对一个提取工作区的提取结果的总结，属于这个工作区、不是素材；
-- 在「素材选择」里挑过才写进 material。实体卡 / 体系卡 / 剧情段来自整理任务（material_compile），以后加写法卡、世界观卡。
CREATE TABLE IF NOT EXISTS extract_card (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    extract_id     INTEGER NOT NULL,              -- 所属提取工作区（novel_extract，逻辑关联）
    card_key       TEXT    NOT NULL,              -- 工作区内唯一：实体卡 = 实体键的哈希，重新整理时对上同一张
    kind           TEXT    NOT NULL,              -- entity（实体卡）/ system（体系卡）/ arc（剧情段）/ craft（写法卡）/ world（世界观卡）
    category       TEXT    NOT NULL,              -- 素材分类码（存进素材库时用）
    title          TEXT    NOT NULL,
    data           TEXT    NOT NULL,              -- 卡片内容 JSON（同素材候选的结构：summary / detail / attributes / tags / facts / tier …）
    history        TEXT,                          -- 旧版本 JSON [{version, by: ai|user, time, data}]，最多 5 个
    version        INTEGER NOT NULL DEFAULT 1,
    edited         INTEGER NOT NULL DEFAULT 0,    -- 1 = 手改过（重新整理不覆盖，AI 新版本放进 history）
    status         TEXT    NOT NULL,              -- NEW（未处理）/ SAVED（已存进素材库）/ SKIPPED（跳过）
    material_id    INTEGER,                       -- 最近一次存进 / 更新到的素材
    saved_version  INTEGER,                       -- 存进素材库时卡片的版本（卡片之后又改过 = 可以再同步）
    compile_id     INTEGER,                       -- 最近一次产出它的整理任务
    create_time    TEXT    NOT NULL,
    update_time    TEXT    NOT NULL,
    UNIQUE (extract_id, card_key)
);
CREATE INDEX IF NOT EXISTS idx_extract_card_extract ON extract_card (extract_id);
