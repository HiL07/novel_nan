-- Python 环境配置（spring.sql.init 启动时执行，已存在则跳过）。只保存检测通过的配置，active=1 为当前使用
CREATE TABLE IF NOT EXISTS python_env (
    id             BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    env_type       VARCHAR(16)   NOT NULL COMMENT 'SYSTEM/CONDA/VENV/CUSTOM',
    python_path    VARCHAR(1000) NOT NULL COMMENT 'python.exe 绝对路径',
    conda_root     VARCHAR(1000) NULL     COMMENT 'Conda 安装目录（CONDA 类型）',
    conda_env      VARCHAR(200)  NULL     COMMENT 'Conda 环境名（CONDA 类型）',
    python_version VARCHAR(32)   NULL,
    cuda_available TINYINT(1)    NOT NULL DEFAULT 0,
    gpu_name       VARCHAR(200)  NULL,
    torch_version  VARCHAR(64)   NULL,
    status         VARCHAR(16)   NOT NULL COMMENT '检测结论 OK/WARN',
    check_result   LONGTEXT      NULL     COMMENT '完整检测结果 JSON',
    active         TINYINT(1)    NOT NULL DEFAULT 0,
    checked_time   DATETIME      NOT NULL,
    create_time    DATETIME      NOT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = 'Python 环境配置';
