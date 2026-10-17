-- 文件元数据（SQLite；spring.sql.init 启动时执行，已存在则跳过）。文件本体在 data/upload/，storage_path 为相对路径
CREATE TABLE IF NOT EXISTS file (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name    TEXT    NOT NULL,                 -- 原始文件名
    storage_path TEXT    NOT NULL,                 -- 相对上传根目录的路径 yyyy/MM/dd/<uuid>.<ext>
    file_size    INTEGER NOT NULL DEFAULT 0,       -- 字节
    content_type TEXT,                             -- MIME 类型
    file_ext     TEXT,                             -- 扩展名（不含点）
    create_time  TEXT    NOT NULL                  -- yyyy-MM-dd HH:mm:ss
);
CREATE INDEX IF NOT EXISTS idx_file_create_time ON file (create_time);
