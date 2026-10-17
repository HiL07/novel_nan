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
