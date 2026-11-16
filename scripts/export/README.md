# 素材实验快照导出

在项目根目录的 PowerShell 7 中运行（Java 17+，使用本项目已缓存的 Maven 依赖，不需要 Python 或启动服务）：

```powershell
./scripts/export/export-materials.ps1
# 指定 Java、数据库或输出目录：
./scripts/export/export-materials.ps1 -Java 'D:/path/to/jdk/bin/java.exe' -Database './data/nan_novel.db' -OutputDirectory './data/exports/my-snapshot'
```

默认生成 `data/exports/materials-时间戳/`，已有输出目录会被拒绝，不覆盖历史快照。

- `materials.jsonl`：UTF-8 无 BOM，每行一个素材，字段名与 Java API 一样使用 camelCase。保留原 ID、分类、细分类型、名称、概括、详细描述、属性、标签、完整 source/profile、来源书、合并指向、保留状态、使用次数和时间。原有空值保留。
- `manifest.json`：格式版本、时间、分类与来源类型计数、记录数、检索候选数和 JSONL 的 SHA-256。只有两个最终文件齐全才算成功。

导出全部已确认入库素材，包括已合并成员，方便还原版本和关联。`retrievalEligible=false` 表示已并入主条目的成员：普通检索不应作为独立结果，仍可用于主条目的版本检索。架空版保留在独立记录及其原始 source 关联中。未入库卡片、候选箱、小说正文文件、配置表和密钥表不读取。不会生成树或向量，也不重新计算素材内容。

程序通过 SQLite `mode=ro` 和 `query_only` 只读访问；单个查询读取一致的 WAL 快照，不复制数据库，不停止服务。程序不修改业务数据；运行中的服务后续更新不会进入本次快照。

回归验证：`python scripts/export/test_export.py`（Python 3，仅标准库）。测试临时数据库的中文和 JSON、合并关系、计数和校验和、源库不变、禁止覆盖和损坏 JSON 拒绝导出，不读取真实数据库。

**这是本地私有快照，不是脱敏数据**：可能包含原文摘抄、来源书名和用户手写内容。只选择素材表的明确字段，不保证用户自行写入素材内容的敏感信息已被清理。默认输出被现有 Git 规则忽略。复制到新实验仓库的 `data/private/` 后，先在新仓库 `.gitignore` 加上 `/data/private/`，再进行 Git 操作。

`source` 内可能引用未导出的提取任务、文件和工作区，不能将这些 ID 当成快照内可解析对象。完整素材库的相对关系得以保留；导出数据不是可以恢复整个主项目的备份。
