-- 文件信息表（spring.sql.init 启动时执行，已存在则跳过）
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
