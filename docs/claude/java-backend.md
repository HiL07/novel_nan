# Java backend: conventions, file API, storage, model config, Python env

> Split out of `CLAUDE.md` on 2026-11-03 (content moved verbatim). `CLAUDE.md` keeps the overview and conventions; keep this file updated when the APIs / behaviour below change.

## Conventions & base file API (`backend/`)

## 4. Java Backend Conventions (`backend/`)

### Commands

```bash
mvn spring-boot:run     # run on http://localhost:8022 (requires JDK 17)
mvn spring-boot:run -Dspring-boot.run.arguments="--server.port=8012 --ai.service.url=http://localhost:8011"   # test instance
mvn clean package       # build jar (Lombok excluded from the fat jar)
```

### Layering & package rules (`com.example.file`)

- `controller` → `service` → `mapper` → `entity`. Cross-layer calls are not allowed.
- New feature = full set: `entity` (`@TableName`, `@TableId(type = IdType.AUTO)`) → `mapper extends BaseMapper<T>` (no hand-written SQL unless necessary) → `service` → `controller`.
- **Constructor injection only** (no field `@Autowired`); use `@Data`/Lombok on entities and DTOs.
- Use SLF4J `LoggerFactory` loggers; log exceptions with context, never expose stack traces to clients.

### HTTP & response conventions

- All JSON endpoints are under `/api/**` and **must return `Result<T>`** (`com.example.file.common.Result`):
  - Success: `Result.ok(data)` → `{ "code": 0, "message": "ok", "data": ... }` — **code `0` means success**.
  - Failure: `Result.error(code, message)`.
- Throw `BizException(code, message)` for business errors (e.g. 404 not found); controllers translate it to the proper HTTP status.
- Binary endpoints (download/preview) return `ResponseEntity<byte[]>` with correct `Content-Type` and `Content-Disposition` (`attachment` vs `inline`).

### Existing file API (base framework — extend, don't duplicate)

| Method & path | Purpose |
|---------------|---------|
| `POST /api/file/upload` | Multipart upload, form field name fixed to **`file`** |
| `GET  /api/file/list` | All files, `create_time` descending |
| `GET  /api/file/download/{id}` | Attachment download |
| `GET  /api/file/preview/{id}` | Inline preview (image/PDF/text). Text files are transcoded to UTF-8 (`charset=UTF-8`): BOM → strict UTF-8 → strict GB18030, so GBK novels don't show as mojibake. Download returns original bytes. |
| `GET  /api/file/text/{id}?offset=0&limit=100000` | Paged text preview (same decoding, by chars, limit 1k–500k) → `{text, offset, nextOffset, totalChars, done}`; decoded text of the last 2 files is cached. The 文件管理 dialog loads 100k chars at a time (scroll / 加载更多) — rendering a whole multi-MB novel froze the page |

## AI model config & Python environment

### AI model config API (`AiModelConfigController`)

| Method & path | Purpose |
|---------------|---------|
| `GET  /api/ai/model/list` | Configs, active first. `apiKey` is write-only; responses carry only `apiKeyMasked` |
| `POST /api/ai/model/fetch-models {id?, baseUrl, protocol, apiKey?}` | 「获取可用模型」: Python `POST /api/models/list` (`llm_client.list_models`: OpenAI `GET {baseUrl}/models`, Anthropic `GET {baseUrl}/v1/models`) → `{ok, models[{id, name}], message}` (404 = the service has no list endpoint, add names by hand); blank `apiKey` + `id` = the stored key |
| `POST /api/ai/model/save` | Create (no `id`) or update; blank `apiKey` keeps the stored key. Changing `baseUrl`/`model`/`apiKey`/`protocol` → `UNVERIFIED` + inactive. `providerType` `preset` (第三方模型提供商, `providerId` = preset key from `api/aiModel.js#PROVIDER_PRESETS`) / `custom` (自定义模型 API: `providerId` required, `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`, unique among custom rows), `protocol` `openai` / `anthropic`, `models` = 模型目录 (deduped, ≤1000, the chosen `model` always included first) |
| `POST /api/ai/model/{id}/verify` | Python sends one tiny real request; `VERIFIED` (auto-activates if nothing is active) or `FAILED` (+ deactivated); 503 if Python is down |
| `POST /api/ai/model/{id}/activate` | Only `VERIFIED` configs; deactivates all others |
| `POST /api/ai/model/{id}/delete` | Delete |

- Table `ai_model_config` (DDL `sql/ai_model_config.sql`): `id`, `name`, `provider_type`, `provider_id`, `protocol` (null = openai), `models` (JSON, `JacksonTypeHandler`; these four added by `SchemaMigrations` on old DBs — old rows have no type and the page guesses preset by base URL), `base_url`, `model`, `api_key`, `concurrency` (1–8), `status` (UNVERIFIED/VERIFIED/FAILED), `verify_message`, `verified_time`, `active`, `create_time`, `update_time`.
- Default model (`ai.default.*` in `application.yml`: DeepSeek, `https://api.deepseek.com`, `deepseek-chat`) is seeded on first start when the table is empty, then auto-verified in the background. Its key comes from `ai.default.api-key` in **`backend/application-secret.yml` (git-ignored, imported via `spring.config.import`)** or env `DEEPSEEK_API_KEY`. Never put API keys in tracked files or logs; don't log AI-service error bodies (422 echoes can contain the key).
- CORS is GET/POST only, so update/delete endpoints use POST.
- JSON endpoints use `common/ResultResponses.handle(...)` to map `BizException` → HTTP status + `Result.error`.
- JDK 17 on Chinese Windows defaults to GBK: always pass an explicit charset when converting bytes ↔ String (and `spring.sql.init.encoding: UTF-8`).

### Python environment API (`PythonEnvController`)

Detection runs **in Java**: `PythonEnvService` executes the selected `python.exe` with the stdlib-only probe `src/main/resources/python/env_probe.py` (version, arch, venv/conda, `torch.cuda` + GPU/VRAM, and status of every line in `python-service/requirements.txt` / `requirements-local.txt`). The backend therefore never depends on the Python being checked.

| Method & path | Purpose |
|---------------|---------|
| `GET  /api/python-env/discover` | `system` (PATH `python`, Store `WindowsApps` stub flagged/skipped), `conda` (`conda env list --json`), `venv` (default `python-service/.venv`), `anyUsable`, `miniconda` guide links (official + Tsinghua), `current` |
| `GET  /api/python-env/conda/envs?condaPath=` | Conda envs; `condaPath` = install dir or `conda.exe`; blank → `CONDA_EXE` → PATH → common dirs |
| `GET  /api/python-env/browse?path=` | Server-side file browser for the "浏览" button (dirs + `python*.exe`; blank = drive roots) |
| `POST /api/python-env/check {envType: SYSTEM\|CONDA\|VENV\|CUSTOM, pythonPath, condaRoot?, condaEnv?}` | Run the probe (≤150 s). `level` OK / WARN / ERROR + `problems[{level,title,detail,fix}]`. ERROR = invalid path, Store stub, Python < `python-env.min-version` (3.10), 32-bit, or missing **service** deps. WARN = torch/CUDA/local deps missing. OK/WARN → saved as the active row in `python_env` and written to `python-service/.python-env` |
| `GET  /api/python-env/current` | Active config + `lastResult`, `exists` |

- `python-service/.python-env` (git-ignored): one line, the interpreter path, written in the **native charset (GBK)** so `start.bat`'s `set /p` reads Chinese paths correctly; re-synced from the DB on every backend start. `start.bat` uses it for the AI service, falling back to `python-service/.venv`.
- Project root is auto-detected (works when started from `backend/` or the repo root); override with `python-env.project-root`.

## Storage & database

### File storage rules

- Root dir from `file.storage.path` in `application.yml` (`${app.data-dir}/upload`, i.e. `data/upload/`). Uploads are written to `<name>.part` then atomically renamed; if the DB insert fails the file is deleted. `read()` rejects storage paths that resolve outside the upload root.
- Stored filename = **UUID without dashes** + lowercased extension; date-partitioned as `yyyy/MM/dd/`.
- DB stores only the **relative** `storage_path`; always resolve against the configured root and normalize paths (path-traversal safe).
- Upload limit: 50 MB per file / per request (see `application.yml`).
- **Database (SQLite)**: `jdbc:sqlite:${app.data-dir}/nan_novel.db` (WAL, `busy_timeout=10000`, Hikari pool 4). Only Java opens it. `app.data-dir` = `DATA_DIR` or auto-detected `<repo>/data` (`DataDirEnvironmentPostProcessor`); `common/DataPaths` resolves and traversal-checks paths under it. LocalDateTime is stored as text `yyyy-MM-dd HH:mm:ss` (`LocalDateTimeTextTypeHandler`); booleans as 0/1; no foreign keys (logical links only, handled in code). Pagination dialect `DbType.SQLITE`. Tables are auto-created at startup from the per-table scripts; `sqlite3 data/nan_novel.db < backend/src/main/resources/sql/init.sql` creates them manually. **Store metadata only** — large content (novel text, full extraction results) goes into files under `data/`. **When adding or changing a table, update both its per-table script and `init.sql`.**
- `file` table columns, derived from `FileInfo`: `id` (auto increment), `file_name`, `storage_path`, `file_size`, `content_type`, `file_ext`, `chapter_count`, `create_time`. `chapter_count` (txt/md only; `service/ChapterCounter` = same heading rules as Python `text_loader.split_book` / `detect_heading` (change both together; rules in `docs/素材流程.md` §2 分章), headings without body not counted, volume headings only count when ≥200 chars sit under them; bumping `FileService.CHAPTER_RULES_MARK` (marker line in `data/.defaults-applied`) recounts every txt / md at startup; 0 = no chapters found, -1 = unreadable, NULL = not counted / docx·pdf) is set on save; old rows are backfilled in a background thread at startup (`FileService.backfillChapterCounts`, column added by `SchemaMigrations`). 文件管理 shows it under each card (「N 章」) together with an 「已提取」 badge (extract tasks matched by `bookOf(fileName)`, display only — re-extraction is allowed).

## Configuration & CORS

### Configuration & CORS

- Config lives in `backend/src/main/resources/application.yml`. **Do not hardcode or copy DB credentials into code or docs**; read them from the yml.
- `WebConfig` allows CORS only from `app.cors.allowed-origins` (default `http://localhost:5173,http://localhost:5174`; GET/POST on `/api/**`). If the frontend adds methods (PUT/DELETE), update both sides.
