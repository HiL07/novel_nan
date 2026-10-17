-- 创作素材库（spring.sql.init 启动时执行，已存在则跳过）

-- 素材（只存用户确认过的）
CREATE TABLE IF NOT EXISTS `material` (
    `id`          BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `category`    VARCHAR(16)  NOT NULL COMMENT 'world/faction/character/monster/location/item/plot',
    `subtype`     VARCHAR(32)  NULL     COMMENT '细分类型，如 势力 / 修炼体系 / 桥段',
    `title`       VARCHAR(100) NOT NULL COMMENT '名称',
    `summary`     VARCHAR(300) NULL     COMMENT '一句话概括',
    `attributes`  TEXT         NULL     COMMENT '结构化属性 JSON：{"外形":"…","弱点":["火"]}',
    `detail`      TEXT         NULL     COMMENT '详细描述 / 备注',
    `tags`        VARCHAR(500) NULL     COMMENT '标签 JSON 数组（检索走 material_tag）',
    `source`      TEXT         NULL     COMMENT '来源 JSON：{type, extractId, fileId, fileName, chapters, excerpt}',
    `use_count`   INT          NOT NULL DEFAULT 0 COMMENT '被应用到工作区的次数',
    `create_time` DATETIME     NOT NULL,
    `update_time` DATETIME     NOT NULL,
    INDEX `idx_category` (`category`),
    INDEX `idx_update_time` (`update_time`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '创作素材';

-- 标签索引（按标签筛选 / 标签云）
CREATE TABLE IF NOT EXISTS `material_tag` (
    `id`          BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `material_id` BIGINT       NOT NULL,
    `tag`         VARCHAR(32)  NOT NULL,
    UNIQUE KEY `uk_material_tag` (`material_id`, `tag`),
    INDEX `idx_tag` (`tag`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '素材标签';

-- AI 提取出的素材候选（待用户确认）
CREATE TABLE IF NOT EXISTS `material_candidate` (
    `id`           BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `extract_id`   BIGINT       NOT NULL COMMENT '来源提取任务（novel_extract）',
    `file_id`      BIGINT       NULL,
    `file_name`    VARCHAR(255) NULL,
    `candidate_key` VARCHAR(32) NOT NULL COMMENT '提取结果中的 candidateId（同一任务内去重）',
    `category`     VARCHAR(16)  NOT NULL,
    `title`        VARCHAR(100) NOT NULL,
    `payload`      TEXT         NOT NULL COMMENT '候选内容 JSON（同素材结构）',
    `status`       VARCHAR(16)  NOT NULL COMMENT 'PENDING/SAVED/IGNORED',
    `material_id`  BIGINT       NULL     COMMENT '保存后对应的素材 id',
    `create_time`  DATETIME     NOT NULL,
    `update_time`  DATETIME     NOT NULL,
    UNIQUE KEY `uk_extract_candidate` (`extract_id`, `candidate_key`),
    INDEX `idx_status` (`status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '素材候选（待确认）';
