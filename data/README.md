# data/ — 共享数据目录

Java（Spring Boot）与 Python（FastAPI）共用的数据根目录。**本目录下除本说明与 `.gitkeep` 外全部被 git 忽略**，其中是用户数据，切勿提交。

- 位置：项目根目录 `data/`。两端都可用环境变量 `DATA_DIR` 覆盖（Docker 中为 `/data`）。
- 模型权重 / LoRA 适配器**不在这里**：仍在 `python-service/models/`（可用 `LOCAL_MODELS_DIR` 覆盖）及其登记的外部路径。

## 目录与职责

| 路径 | 内容 | 创建 / 修改 | 读取 | 删除 | 与数据库的对应 |
|------|------|-------------|------|------|----------------|
| `nan_novel.db`（及 `-wal` / `-shm`） | SQLite：**只存元数据**、业务状态、文件相对路径 | Java（唯一打开者） | Java | —— | —— |
| `upload/yyyy/MM/dd/<uuid>.<ext>` | 上传的原始文件 | Java（`FileService`） | Java；Python 只通过 Java 的 `/api/file/preview/{id}` 读取 | 暂无删除功能 | `file.storage_path` = 相对 `upload/` 的路径 |
| `extract-results/<taskId>.json` | 小说提取的完整结果 JSON | Java（`ExtractResultStore`，提取任务成功时写入） | Java（`GET /api/novel/extract/{id}` 读出后原样返回） | 暂无 | `novel_extract.result_path`（相对 `data/`）、`result_size`、`result_sha256` |
| `novels/<novelId>/novel.json`、`chapters/NNNN.json` | AI 生成的小说工作区与正文 | Python（`app/generation/store.py`） | Python；Java 按本约定只读（本轮无 Java 读取接口） | Python（删除工作区 / 最后一章） | 不入数据库 |
| `crawl-cache/<resumeKey>/meta.json`、`chapters.jsonl` | 小说抓取断点：章节清单 + 已抓章节正文（逐章追加），用于「继续抓取」 | Python（`app/crawler/checkpoint.py`） | Python | Python（Java 保存 txt 后 release 时删除；失败 / 取消的保留） | `resumeKey` 由任务 id 推出：单本 `c<novel_crawl.id>`，整站 `c<novel_crawl.id>b<novel_crawl_book.id>` |
| `site-catalog/<host>[_端口]/toc/<key>.json`、`catalog.json` | 全自动爬虫的站点书目（同一首页的数据放在一起）：每本书的完整目录（`key` = 书籍地址 SHA-1 前 16 位）+ 书目导出（简介 / 标签 / 测试报告）。**不含正文** | `toc/` Python（`app/crawler/catalog.py`，采集时写入）；`catalog.json` Java（`CrawlCatalogService`，每次采集结束 / 决定 / AI 补标签后导出） | Java（`GET /api/novel/crawl/catalogs/books/{id}/toc`） | Java（删除书目时整个目录） | `crawl_site_catalog.catalog_dir`、`crawl_catalog_book.toc_path`（相对 `data/`）；数据库为准 |
| `crawl-rules/<host>_<id>.json` | AI 解析地址得到的站点抓取规则（整条记录：状态 待确认 / 已确认、XPath 规则、地址规律、总结、学习样例），方便查找 / 备份 | Java（`CrawlRuleService`：解析成功、确认时写入；启动时补写缺失的） | 人工查看；程序以数据库为准 | Java（不确认 / 删除规则、确认替换旧规则时） | `crawl_site_rule` 一行一个文件 |

## 格式约定

- 编码：**UTF-8，无 BOM**；JSON 不转义中文（Java `ObjectMapper` 默认 / Python `ensure_ascii=False`）。
- 数据库中的路径一律为**相对路径、`/` 分隔**，由各自服务拼接到 `DATA_DIR` 并校验必须落在对应子目录内（防路径穿越）。
- 写文件一律「同目录临时文件 → 刷盘 → 原子改名」，不会留下半截文件；数据库记录只在文件写成功后写入（上传失败或写库失败会删除已写文件）。
- `extract-results/*.json`：Python 提取服务返回的 `result` 对象原样序列化；`result_sha256` 为文件字节的 SHA-256，读取时校验。文件缺失或校验不符时接口返回 `result: null` 并在 `message` 中提示，任务状态不变。
- `novels/`：结构见 `python-service/app/generation/store.py` 文件头注释（`novel.json` 工作区设定与统计、`chapters/0001.json` 章节正文、摘要与 token 明细）。

## 备份

停止 Java 服务后整体复制本目录即可（SQLite 处于 WAL 模式，运行中复制需同时复制 `-wal` 文件或使用 `sqlite3 nan_novel.db ".backup ..."`）。**不要把含明文 API Key 的数据库副本放到可被提交或共享的位置。**
