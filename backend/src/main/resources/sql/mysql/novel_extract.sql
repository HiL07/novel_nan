-- 小说提取任务表（spring.sql.init 启动时执行，已存在则跳过）
CREATE TABLE IF NOT EXISTS novel_extract (
    id          BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    file_id     BIGINT       NOT NULL COMMENT '源文件 id（file 表）',
    file_name   VARCHAR(255) NULL     COMMENT '源文件名',
    status      VARCHAR(16)  NOT NULL COMMENT 'QUEUED/RUNNING/SUCCEEDED/FAILED',
    progress    INT          NOT NULL DEFAULT 0 COMMENT '进度 0~100',
    message     VARCHAR(1000) NULL    COMMENT '进度说明/失败原因',
    job_id      VARCHAR(64)  NULL     COMMENT 'Python 服务任务 id',
    result      LONGTEXT     NULL     COMMENT '提取结果 JSON',
    create_time DATETIME     NOT NULL,
    update_time DATETIME     NOT NULL,
    INDEX idx_file_id (file_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '小说提取任务';
