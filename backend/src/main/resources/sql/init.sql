-- =====================================================================
-- nan_novel 数据库初始化脚本（MySQL 8.0+，utf8mb4）
--
-- 一键导入：
--   mysql -u root -p < backend/src/main/resources/sql/init.sql
--   或在 Navicat / MySQL Workbench 中直接运行本文件
--
-- 说明：
--   - 全部使用 IF NOT EXISTS，可在已有数据库上重复执行，不会删除或覆盖数据
--   - 不包含任何账号 / API Key；默认 DeepSeek 模型配置由后端首次启动时自动写入
--     （Key 读取自 backend/application-secret.yml 或环境变量 DEEPSEEK_API_KEY）
--   - 各表的单独建表脚本在同目录（file.sql / novel_extract.sql / ai_model_config.sql / python_env.sql），
--     后端启动时由 spring.sql.init 自动执行；修改表结构时请同步更新本文件
-- =====================================================================

CREATE DATABASE IF NOT EXISTS test10000 DEFAULT CHARACTER SET utf8mb4;
USE test10000;

-- ---------------------------------------------------------------------
-- 文件信息（文件管理：上传落盘后的元数据）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `file` (
    `id`           BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `file_name`    VARCHAR(255) NOT NULL COMMENT '原始文件名',
    `storage_path` VARCHAR(512) NOT NULL COMMENT '存储路径（相对存储根目录）',
    `file_size`    BIGINT       NOT NULL DEFAULT 0 COMMENT '文件大小（字节）',
    `content_type` VARCHAR(128) NULL COMMENT 'MIME 类型',
    `file_ext`     VARCHAR(32)  NULL COMMENT '扩展名（不含点）',
    `create_time`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '上传时间',
    PRIMARY KEY (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '文件信息表';

-- ---------------------------------------------------------------------
-- 小说提取任务（异步任务 + 结果 JSON）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `novel_extract` (
    `id`          BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `file_id`     BIGINT        NOT NULL COMMENT '源文件 id（file 表）',
    `file_name`   VARCHAR(255)  NULL     COMMENT '源文件名',
    `status`      VARCHAR(16)   NOT NULL COMMENT 'QUEUED/RUNNING/SUCCEEDED/FAILED',
    `progress`    INT           NOT NULL DEFAULT 0 COMMENT '进度 0~100',
    `message`     VARCHAR(1000) NULL     COMMENT '进度说明/失败原因',
    `job_id`      VARCHAR(64)   NULL     COMMENT 'Python 服务任务 id',
    `result`      LONGTEXT      NULL     COMMENT '提取结果 JSON',
    `create_time` DATETIME      NOT NULL,
    `update_time` DATETIME      NOT NULL,
    INDEX `idx_file_id` (`file_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '小说提取任务';

-- ---------------------------------------------------------------------
-- AI 模型配置（OpenAI 兼容接口；验证通过才能启用，同一时间只启用一个）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ai_model_config` (
    `id`             BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `name`           VARCHAR(100)  NOT NULL COMMENT '显示名称',
    `base_url`       VARCHAR(500)  NOT NULL COMMENT 'OpenAI 兼容根地址',
    `model`          VARCHAR(200)  NOT NULL COMMENT '模型名',
    `api_key`        VARCHAR(500)  NULL     COMMENT 'API Key（接口不回显明文）',
    `concurrency`    INT           NOT NULL DEFAULT 1 COMMENT '任务内并发请求数',
    `status`         VARCHAR(16)   NOT NULL COMMENT 'UNVERIFIED/VERIFIED/FAILED',
    `verify_message` VARCHAR(1000) NULL     COMMENT '最近一次验证结果',
    `verified_time`  DATETIME      NULL     COMMENT '最近一次验证通过时间',
    `active`         TINYINT(1)    NOT NULL DEFAULT 0 COMMENT '是否当前启用',
    `create_time`    DATETIME      NOT NULL,
    `update_time`    DATETIME      NOT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = 'AI 模型配置';

-- ---------------------------------------------------------------------
-- Python 环境配置（检测通过的解释器；active=1 为当前使用）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `python_env` (
    `id`             BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `env_type`       VARCHAR(16)   NOT NULL COMMENT 'SYSTEM/CONDA/VENV/CUSTOM',
    `python_path`    VARCHAR(1000) NOT NULL COMMENT 'python.exe 绝对路径',
    `conda_root`     VARCHAR(1000) NULL     COMMENT 'Conda 安装目录（CONDA 类型）',
    `conda_env`      VARCHAR(200)  NULL     COMMENT 'Conda 环境名（CONDA 类型）',
    `python_version` VARCHAR(32)   NULL,
    `cuda_available` TINYINT(1)    NOT NULL DEFAULT 0,
    `gpu_name`       VARCHAR(200)  NULL,
    `torch_version`  VARCHAR(64)   NULL,
    `status`         VARCHAR(16)   NOT NULL COMMENT '检测结论 OK/WARN',
    `check_result`   LONGTEXT      NULL     COMMENT '完整检测结果 JSON',
    `active`         TINYINT(1)    NOT NULL DEFAULT 0,
    `checked_time`   DATETIME      NOT NULL,
    `create_time`    DATETIME      NOT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = 'Python 环境配置';
