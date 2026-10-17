-- AI 模型配置表（spring.sql.init 启动时执行，已存在则跳过）
CREATE TABLE IF NOT EXISTS ai_model_config (
    id             BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name           VARCHAR(100)  NOT NULL COMMENT '显示名称',
    base_url       VARCHAR(500)  NOT NULL COMMENT 'OpenAI 兼容根地址',
    model          VARCHAR(200)  NOT NULL COMMENT '模型名',
    api_key        VARCHAR(500)  NULL     COMMENT 'API Key（接口不回显明文）',
    concurrency    INT           NOT NULL DEFAULT 1 COMMENT '任务内并发请求数',
    status         VARCHAR(16)   NOT NULL COMMENT 'UNVERIFIED/VERIFIED/FAILED',
    verify_message VARCHAR(1000) NULL     COMMENT '最近一次验证结果',
    verified_time  DATETIME      NULL     COMMENT '最近一次验证通过时间',
    active         TINYINT(1)    NOT NULL DEFAULT 0 COMMENT '是否当前启用',
    create_time    DATETIME      NOT NULL,
    update_time    DATETIME      NOT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = 'AI 模型配置';
