# CLAUDE.md

Project guidance for AI coding assistants (Claude Code). Read this before generating or modifying code.

## 1. Project Overview

**nan_novel** is an AI-assisted **novel generation** system. Users upload and manage novel/manuscript source files; a Python AI service extracts and analyzes the text and fine-tunes remote large language models (**QLoRA / Hugging Face**) to power novel generation.

The system consists of three components:

| # | Component | Role | Status |
|---|-----------|------|--------|
| 1 | **Frontend** (`frontend/`) | Vue 3 + Vite SPA — file upload & management UI | Implemented |
| 2 | **Java backend** (`backend/`) | Spring Boot — **file management is the base framework**: upload-to-disk, metadata in SQLite (`data/nan_novel.db`), download/preview APIs | Implemented |
| 3 | **Python AI backend** (`python-service/`) | FastAPI — article/content extraction, text analysis, local model management + LoRA/QLoRA style fine-tuning (Hugging Face) | Extraction + **local** fine-tuning implemented; remote inference/training planned |

```
Browser (Vue3/Vite, :5173)
        │  HTTP
        ▼
Spring Boot (:8022) ─────► SQLite data/nan_novel.db (metadata) + data/upload/ + data/extract-results/
        │  HTTP  ▲ GET /api/file/preview/{id}
        ▼        │
Python FastAPI (:8021) ─────► OpenAI-compatible LLM (default DeepSeek; configurable, e.g. local llama.cpp)
                        ├───► local GPU: Transformers + PEFT inference / LoRA-QLoRA training (models/)
                        └───► remote inference / training (planned)
Browser ──(本地模型 page, direct)──► Python /api/local/**
```

## 2. Repository Layout

```
nan_novel/
├── backend/            # Spring Boot file-management service (Maven)
│   ├── src/main/java/com/example/file/
│   │   ├── common/     # Result<T> unified response, BizException
│   │   ├── config/     # WebConfig (CORS)
│   │   ├── controller/ # REST controllers (/api/**)
│   │   ├── entity/     # MyBatis-Plus entities
│   │   ├── mapper/     # BaseMapper interfaces
│   │   ├── service/    # Business logic
│   │   └── FileApplication.java
│   ├── src/main/resources/application.yml
│   ├── src/main/resources/sql/   # SQLite DDL: per-table scripts (run at startup by spring.sql.init) + init.sql; sql/mysql/ = pre-migration MySQL scripts (rollback only)
├── frontend/           # Vue 3 + Vite SPA
│   └── src/
│       ├── api/        # Axios API layer (one module per backend resource)
│       ├── layout/     # App shell: Sidebar + AppMain
│       ├── router/     # Lazy-loaded routes
│       ├── views/file/ # upload.vue, manage.vue
│       ├── views/novel/ # create.vue (workspace list), workspace.vue (设定 + 写作), extract.vue (extraction tasks & results)
│       ├── views/ai/    # model.vue (remote AI model configs), local.vue (本地模型), pyenv.vue (Python 环境 selection & check)
│       ├── views/material/ # index.vue (素材库: keyword/tag + AI semantic search, 待确认 candidates)
│       ├── components/material/ # ExtractOptionsDialog, CandidateReview, MaterialEditor, AttributeEditor, MaterialPicker
│       ├── components/novel-options/ # schema-driven option UI (SettingsEditor, OptionField, ChoiceWidget, …)
│       ├── novel-options/ # field-type registry, schema helpers, editor context
│       └── mock/        # local placeholder data (until the DB exists)
├── python-service/     # FastAPI AI service
│   ├── app/            # main.py, extractor, llm_client, text_loader (extraction)
│   ├── app/local/      # local models: settings, hardware, registry, inference, training, download, jobs, worker, router
│   ├── app/generation/ # novel generation: backends, spec, context, prompts, chapter, store, defaults, router
│   ├── models/         # git-ignored: base/<id>/model.json (+weights if downloaded), adapters/<id>/, jobs/<id>/
│   ├── scripts/local_e2e.py  # end-to-end smoke test over HTTP
│   ├── requirements.txt       # extraction service (no torch)
│   └── requirements-local.txt # local models (torch CUDA + transformers/peft/accelerate/bitsandbytes)
├── data/             # shared data dir (git-ignored except README.md/.gitkeep): nan_novel.db, upload/, extract-results/, novels/ — see data/README.md
├── scripts/migration/ # one-off MySQL → SQLite config import (import_mysql_config.py)
├── start.bat           # Windows one-click launcher for backend + AI service + frontend
└── CLAUDE.md
```

## 3. Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vue 3.4 (`<script setup>` Composition API), Vite 5, Vue Router 4, Element Plus 2.7 (+ `@element-plus/icons-vue`, globally registered), Axios 1.7 |
| Java backend | Java 17, Spring Boot 3.2.5, Spring Web, MyBatis-Plus 3.5.7, SQLite (`sqlite-jdbc`, WAL), Lombok, Maven |
| Python service | Python 3.10+, FastAPI, Uvicorn, Pydantic v2, httpx, `python-docx` / `pypdf`; local models: PyTorch 2.6 (CUDA 12.4 build), `transformers` 4.5x, `peft`, `accelerate`, `bitsandbytes` (QLoRA) |

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

### Novel extraction API (`NovelExtractController`)

| Method & path | Purpose |
|---------------|---------|
| `POST /api/novel/extract/{fileId}` | Create an async extraction task for a txt/md/docx/pdf file; returns the task (`QUEUED`) |
| `GET  /api/novel/extract/list` | Tasks without `result`, `create_time` descending |
| `GET  /api/novel/extract/{id}` | Task detail; `result` is the extraction JSON string (chapters, characters, style) |

- Table `novel_extract` (DDL `sql/novel_extract.sql`, auto-created via `spring.sql.init`): `id`, `file_id`, `file_name`, `status` (QUEUED/RUNNING/SUCCEEDED/FAILED), `progress`, `message`, `job_id`, `result_path`, `result_size`, `result_sha256`, `word_count`, `chapter_count`, `candidate_count`, `create_time`, `update_time`. **The full result JSON is not stored in the DB**: `ExtractResultStore` writes `data/extract-results/<id>.json` (temp file → fsync → atomic rename, SHA-256 recorded) before the row is marked SUCCEEDED (write failure → FAILED, no path; DB failure → file removed). `GET /api/novel/extract/{id}` reads it back into the transient `result` field (same API shape); a missing / tampered / out-of-tree file yields `result: null` and an explanation appended to `message`.
- `NovelExtractService` runs tasks on a single background thread using the **active, verified** model config (snapshot taken at submit; none → 400): submits to Python `POST /api/extract/jobs`, polls `GET /api/extract/jobs/{jobId}` every 3s, and persists progress/result. Tasks left QUEUED/RUNNING at restart are marked FAILED.
- Python URL: `ai.service.url` in `application.yml` (default `http://localhost:8021`).

### AI model config API (`AiModelConfigController`)

| Method & path | Purpose |
|---------------|---------|
| `GET  /api/ai/model/list` | Configs, active first. `apiKey` is write-only; responses carry only `apiKeyMasked` |
| `POST /api/ai/model/save` | Create (no `id`) or update; blank `apiKey` keeps the stored key. Changing `baseUrl`/`model`/`apiKey` → `UNVERIFIED` + inactive |
| `POST /api/ai/model/{id}/verify` | Python sends one tiny real request; `VERIFIED` (auto-activates if nothing is active) or `FAILED` (+ deactivated); 503 if Python is down |
| `POST /api/ai/model/{id}/activate` | Only `VERIFIED` configs; deactivates all others |
| `POST /api/ai/model/{id}/delete` | Delete |

- Table `ai_model_config` (DDL `sql/ai_model_config.sql`): `id`, `name`, `base_url`, `model`, `api_key`, `concurrency` (1–8), `status` (UNVERIFIED/VERIFIED/FAILED), `verify_message`, `verified_time`, `active`, `create_time`, `update_time`.
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

### Material library API (`MaterialController`, `/api/material/**`)

Reusable creative material extracted from novels or added by hand. **Nothing enters `material` without explicit confirmation**: AI output is stored as `material_candidate` (PENDING) and only "保存" turns it into a material.

| Method & path | Purpose |
|---------------|---------|
| `GET  /api/material/categories` · `GET /tags?category=` | Fixed categories with counts; tag cloud `[{tag, count}]` |
| `GET  /api/material/list?category=&tags=a,b&tagMode=all\|any&keyword=&page=&size=` | Keyword (title/summary/subtype/detail/tags) + tag search, paged (MyBatis-Plus `Page`, needs `MybatisPlusConfig` pagination plugin) |
| `POST /api/material/semantic-search {query, category?, tags?, limit?}` | AI semantic search with the **active** model config: Python `/api/materials/expand` (query → keywords/tags/categories) → SQL prefilter (whole library if ≤150 items, else LIKE on expansions, cap 150) → Python `/api/materials/rerank` (score 0–100 + reason) |
| `GET /api/material/{id}` · `POST /save` (no id = create, source `manual`) · `POST /{id}/delete` · `POST /use {ids}` | Detail / CRUD / usage counter when applied to a workspace |
| `GET /api/material/candidates?status=PENDING&extractId=` · `GET /candidates/count` · `POST /candidates/save {items:[{id, ...edits}]}` · `POST /candidates/ignore {ids}` | Candidate inbox; `duplicateOf` flags a same-category same-title material already in the library |

- Categories (fixed codes, keep in sync with `python-service/app/materials.py` and `frontend/src/api/material.js`): `world` 世界观, `faction` 势力, `character` 角色, `monster` 怪物, `location` 地点, `item` 物品功法, `plot` 情节. `subtype` is free text.
- Tables (`sql/material.sql`, also in `init.sql`): `material` (`attributes` / `tags` / `source` are JSON text via `JacksonTypeHandler`, entity needs `autoResultMap = true`), `material_tag` (tag index, rewritten on every save), `material_candidate` (`payload` JSON, unique `(extract_id, candidate_key)`).
- Tag filters resolve material ids with a parameterized query on `material_tag` — never build SQL strings from user tags (`inSql`).
- Extraction: `POST /api/novel/extract/{fileId}` takes optional `{materials: {enabled, categories, maxPerChunk, focus}}`; on success `NovelExtractService` calls `MaterialService.createCandidates(...)` and the task message says how many candidates await confirmation.

### File storage rules

- Root dir from `file.storage.path` in `application.yml` (`${app.data-dir}/upload`, i.e. `data/upload/`). Uploads are written to `<name>.part` then atomically renamed; if the DB insert fails the file is deleted. `read()` rejects storage paths that resolve outside the upload root.
- Stored filename = **UUID without dashes** + lowercased extension; date-partitioned as `yyyy/MM/dd/`.
- DB stores only the **relative** `storage_path`; always resolve against the configured root and normalize paths (path-traversal safe).
- Upload limit: 50 MB per file / per request (see `application.yml`).
- **Database (SQLite)**: `jdbc:sqlite:${app.data-dir}/nan_novel.db` (WAL, `busy_timeout=10000`, Hikari pool 4). Only Java opens it. `app.data-dir` = `DATA_DIR` or auto-detected `<repo>/data` (`DataDirEnvironmentPostProcessor`); `common/DataPaths` resolves and traversal-checks paths under it. LocalDateTime is stored as text `yyyy-MM-dd HH:mm:ss` (`LocalDateTimeTextTypeHandler`); booleans as 0/1; no foreign keys (logical links only, handled in code). Pagination dialect `DbType.SQLITE`. Tables are auto-created at startup from the per-table scripts; `sqlite3 data/nan_novel.db < backend/src/main/resources/sql/init.sql` creates them manually. **Store metadata only** — large content (novel text, full extraction results) goes into files under `data/`. **When adding or changing a table, update both its per-table script and `init.sql`.**
- `file` table columns, derived from `FileInfo`: `id` (auto increment), `file_name`, `storage_path`, `file_size`, `content_type`, `file_ext`, `create_time`.

### Configuration & CORS

- Config lives in `backend/src/main/resources/application.yml`. **Do not hardcode or copy DB credentials into code or docs**; read them from the yml.
- `WebConfig` allows CORS only from `app.cors.allowed-origins` (default `http://localhost:5173,http://localhost:5174`; GET/POST on `/api/**`). If the frontend adds methods (PUT/DELETE), update both sides.

## 5. Frontend Conventions (`frontend/`)

### Commands

```bash
npm install
npm run dev        # http://localhost:5173 → backend 8022 (.env.development)
npm run dev:test   # http://localhost:5174 → test backend 8012 (.env.test)
npm run build      # production build
npm run preview
```

### Rules

- All SFCs use **`<script setup>`** (Composition API); UI text is Chinese, identifiers/comments may be Chinese or English.
- `@` alias → `src/` (configured in `vite.config.js`).
- Keep HTTP calls inside `src/api/*.js` using the shared Axios instances: `request` (Java) and `aiRequest` (Python, `VITE_AI_BASE_URL`, fallback `http://localhost:8021`, 180s timeout — only for `/api/local/**`) (`src/api/request.js`; Java `baseURL` from `VITE_API_BASE_URL`, fallback `http://localhost:8022`, 60s timeout). Views must not create their own Axios instances.
- API helpers unwrap `res.data`; callers treat `response.code === 0` as success.
- Routes are lazy-loaded (`() => import(...)`) with `meta.title` / `meta.icon` consumed by the sidebar; register new pages in `src/router/index.js`.
- Element Plus and all its icons are registered globally in `main.js`.

### Novel settings editor (`SettingsEditor.vue`, used inside each workspace)

- **Schema-driven**: everything renders from data — `categories[] → fields[] → options[] → children(fields[])`, nestable to any depth. Field types live in `src/novel-options/fieldTypes.js` (`single`, `multi`, `text`, `textarea`, `number`, `slider`, `tags`, `group`); to add a type, register it there and map it in `OptionField.vue`.
- **Data source**: `src/api/novelOptions.js#getOptionSchema()` currently returns `src/mock/novelOptionSchema.js` (built-in categories 世界观/角色/情节推进/文风, `elementTemplates` such as 怪物/势力/种族/地点/物品/功法, `genericSuggestions`). When the DB exists, switch only this function to a backend call returning the same shape.
- **Values**: `{ [categoryKey]: { [fieldKey]: value } }`; choice value `{ selected: string[], sub: { [optionValue]: childValues } }`, group value `[{ _id, ...childValues }]`.
- **Extensibility (编辑模式)**: users can add custom options inline, add fields to any category / group / option (from suggestions or self-defined), and create custom elements (e.g. 怪物) from a template or blank. User-created items carry `custom: true` and `uid()` keys.
- **Confirmed vs default**: `number` / `slider` fields always hold a value, so they count only after the user changes them (`markTouched` → `container.__touched[fieldKey]`); untouched defaults never reach `buildSpec()` and therefore never become generation constraints.
- **Output**: `buildSpec()` → `[{key,label,type,value,display,children}]` (`type: 'option'` for sub-option containers, `'groupItem'` + `name` for group entries) is what the workspace saves as `settings.spec` and the backend turns into constraints; `getConfig()` (`{categories, values}`) is saved as `settings.config` to restore the editor.

### Novel workspaces (`/novel/create` → `/novel/workspace/:id`)

- List page creates a workspace: title, model source (local; remote shown but not wired yet), base model (default Qwen2.5-1.5B-Instruct), adapter (disabled at this stage), context window 8192 / 32768. It shows the default-model check with a one-click download (`/api/local/models/download` → `models/base/<id>/weights/`) and Hugging Face / hf-mirror links.
- **Using materials**: `SettingsEditor` → 「从素材库添加」 opens `MaterialPicker` (category / keyword / tag filters, preview of where each item goes). `novel-options/materialApply.js#APPLY_TARGETS` maps categories to settings (monster/faction/location/item → custom element from template, auto-created if missing → its list; character → 角色·主要角色; plot → 情节推进·关键情节节点; world → 世界观补充). Applying **copies** the data (later library edits don't change the story); group items get `_fromMaterial` (shown as「来自素材库」, never exported by `buildSpec`), unmapped attributes go into an added 备注 field.
- Workspace page: 设定 tab = `SettingsEditor` (保存设定), 写作 tab = chapter list, next-chapter form (title, goal, target chars), 预览上下文, live segmented generation with cancel, per-call token table, workspace totals. Unsaved settings are saved automatically before preview/generation.

## 6. Python AI Service (`python-service/`)

This service is the **AI/ML layer**; the Spring Boot service remains the system of record for files and metadata.

Responsibilities:
1. **Content extraction** — parse uploaded novel/manuscript files (txt/md/docx/pdf…) into clean plain text and structured chapters.
2. **Content analysis** — e.g. chapter segmentation, characters, plotlines, style statistics; results returned as JSON.
3. **LLM fine-tuning** — dataset preparation and **QLoRA fine-tuning with Hugging Face** (`transformers` + `peft`) against remote GPU/LLM resources; manage training jobs and LoRA adapters.

### Commands

```bash
cd python-service
py -3.10 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # keep requirements.txt ASCII (old pip reads it as GBK)
.venv/Scripts/python -m uvicorn app.main:app --port 8021
# test instance (talks to test Java backend 8012):
JAVA_BACKEND_URL=http://localhost:8012 .venv/Scripts/python -m uvicorn app.main:app --port 8011
```

Shared data dir: `DATA_DIR` (`app/config.py`, default `<repo>/data`); Python writes only `data/novels/`. The model (base URL, key, model name, concurrency) is **not** configured here — Java sends the active config with each request and Python never stores the key. Env vars (`app/config.py`): `JAVA_BACKEND_URL`, `CHUNK_CHARS` (default 6000), `LLM_MAX_TOKENS`, `LLM_TIMEOUT`. No torch/CUDA needed for extraction.

### Novel extraction (implemented)

- `POST /api/models/verify` `{baseUrl, apiKey, model}` → `{ok, latencyMs, message, reply}`.
- `POST /api/extract/jobs` `{fileId, fileExt, model:{baseUrl, apiKey, model, concurrency}}` → job; `GET /api/extract/jobs/{jobId}` → `queued/running/succeeded/failed`, `progress`, `message`, `error`, `result`; `GET /api/health`.
- `app/llm_client.py`: OpenAI-compatible `POST {baseUrl}/chat/completions` with `Bearer` key. Friendly errors (401/403 key, 402 balance, 404 model/URL are *fatal* and abort the job; 429/5xx/timeouts retry ×2). Falls back without `response_format` if a provider rejects JSON mode. Local hosts skip the system proxy; remote hosts use it.
- Jobs are in-memory and run one at a time; Java is responsible for persisting results.
- Languages: Chinese (primary) and English novels. Analysis text is always output in Simplified Chinese; character/place names keep the original spelling.
- All `httpx` calls to local services use `trust_env=False` — a system proxy (Clash etc.) otherwise turns `localhost` requests into 502.
- **Material candidates** (`app/materials.py`): when `ExtractRequest.materials.enabled`, `prompt_fragment()` adds a `"materials"` field to each chunk's JSON (selected categories, ≤ `maxPerChunk`, optional `focus`, abstracted wording + ≤60-char excerpt; ~+600 max tokens per chunk). `merge_candidates()` dedupes by category + normalized title across chunks (attributes/tags unioned, chapters recorded) into `result.materials[]` with a stable `candidateId`. `POST /api/materials/expand` and `/api/materials/rerank` back the semantic search (model config passed from Java, never stored).
- Pipeline: fetch bytes via Java `GET /api/file/preview/{id}` → decode (BOM → strict UTF-8 → strict GB18030 → fewest replacement chars) or parse docx/pdf → split chapters (`第X章/回/节/卷`, `Chapter 12/IV/One`, 楔子/尾声/后记/Prologue; fallback `1.标题` / `一、标题` only when ≥3 found) → chunk ≤ `CHUNK_CHARS` at paragraph boundaries → LLM JSON per chunk, `concurrency` requests in parallel (`response_format: json_object`, temperature 0.2) → merge (per-chapter summary/characters/events/foreshadowing, deduped characters, dialog ratio computed in code).

### Local models & style fine-tuning (`app/local/`, `/api/local/**`)

Local-only for now; remote inference/training must plug into the existing extension points (`source` on registry records, `backend` on jobs + `worker.RUNNERS[(kind, backend)]`). The frontend calls these endpoints **directly** (CORS: `CORS_ORIGINS`, default 5173/5174) — an explicit exception to "frontend → Java → Python", because model files live next to the Python service. Responses use `{code, message, data}` (code 0 = success; `LocalError` → HTTP status).

| Method & path | Purpose |
|---------------|---------|
| `GET  /api/local/system` | GPU (nvidia-smi), RAM, disk, dependency versions, inference state, active job |
| `GET  /api/local/models` · `POST /models/register {name, path}` · `POST /models/download {repoId, name, source?}` · `GET /models/download/sources` · `POST /models/{id}/delete` | Base models. Register = record path only (no copying); download = background job into `models/base/<id>/weights/` then auto-register. `source`: `auto` (default, tries `MODEL_DOWNLOAD_AUTO_ORDER` = modelscope → hf-mirror → huggingface, falling through on failure) / `modelscope` (HTTP API, per-file size + SHA-256 check, no `modelscope` package) / `hf-mirror` / `huggingface`; HF sources are pre-checked with `config.json` metadata because a mirror that 308-redirects to huggingface.co otherwise surfaces as `LocalEntryNotFoundError`. Env: `MODEL_DOWNLOAD_SOURCE`, `MODEL_DOWNLOAD_AUTO_ORDER`, `HF_MIRROR_ENDPOINT`, `HF_ENDPOINT`, `MODELSCOPE_ENDPOINT`; legacy `useMirror` still accepted |
| `POST /api/local/estimate {baseModelId, mode: infer\|train, quantization: 4bit\|none, maxSeqLen, batchSize, loraR}` | Conservative VRAM/RAM estimate → `level` ok/warn/exceed + messages |
| `GET  /api/local/adapters` · `GET /adapters/{id}` · `POST /adapters/{id}/rename` · `POST /adapters/{id}/delete` | LoRA adapters; each has `compat` ok/changed/missing vs its base model fingerprint |
| `GET  /api/local/inference` · `POST /inference/load {baseId, adapterId?, quantization: auto\|4bit\|none}` · `POST /inference/unload` · `POST /inference/generate {prompt, maxNewTokens, temperature, topP, repetitionPenalty, useChatTemplate}` | One model resident in VRAM; load is async (`idle/loading/loaded/error`) |
| `POST /api/local/train` (`TrainReq` in `router.py`) · `GET /jobs` · `GET /jobs/{id}` · `GET /jobs/{id}/log?lines=` · `POST /jobs/{id}/cancel` | Fine-tuning jobs; 409 + estimate when resources would be exceeded (resend with `force: true`) |

- **Storage** (`app/local/settings.py`, override root with `LOCAL_MODELS_DIR`): `models/base/<id>/model.json` (path, modelType, arch, numParams, sizeBytes, `configHash`), `models/adapters/<id>/` (PEFT files + tokenizer + `meta.json`: exact base model fingerprint, training config, dataset stats, metrics, post-training sample), `models/jobs/<id>/` (`job.json`, `progress.json`, `job.log`, `samples.txt`, `cancel` flag). Adapters are written to `<id>.partial` and renamed only on success.
- **Jobs** run as separate subprocesses (`python -m app.local.worker <jobId>`) so the API stays responsive and VRAM/RAM are released when they end. One job at a time; starting training unloads the inference model and loading is refused while training. On Windows never probe PIDs with `os.kill(pid, 0)` (it kills the process) — use `jobs.pid_alive`.
- **Training** (`training.py`): samples (pasted text and/or Java file ids via `text_loader`) are packed into `maxSeqLen` blocks for causal-LM continued training; PEFT LoRA on `all-linear`, gradient checkpointing, cosine LR, `paged_adamw_8bit` for QLoRA (nf4 + double quant, bf16 compute on RTX 40xx). Cancel = flag checked every step (force-kill after 90 s).
- **Hardware assumptions** (dev machine): RTX 4060 Laptop 8 GB (≈6.3 GB free with the display), 16 GB RAM (often only ~2 GB free), C: nearly full. Defaults are conservative (`maxSeqLen` 512, batch 1, grad-accum 4, r 16). 0.5B–1.5B (3B borderline) are the intended QLoRA sizes; 7B QLoRA is reported as *exceed*. GGUF files cannot be trained.
- **Install**: torch's CUDA wheel is not on PyPI — see the header of `requirements-local.txt` (Aliyun mirror / resumable download). The extraction service still runs without these packages; torch is imported lazily.
- **E2E test**: `.venv/Scripts/python scripts/local_e2e.py --model-path <HF model dir> --port 8011 [--samples my.txt]`.

### Novel generation (`app/generation/`, `/api/gen/**`)

Base model only (no LoRA at this stage). Called directly by the frontend like `/api/local/**`.

| Method & path | Purpose |
|---------------|---------|
| `GET  /api/gen/status` | Default model check (`Qwen/Qwen2.5-1.5B-Instruct`: found / download links / target dir), inference state, active job, allowed windows |
| `GET/POST /api/gen/novels` · `GET /novels/{id}` · `POST /novels/{id}/update {title?, model?, contextWindow?, params?, settings?{config, spec}}` · `POST /novels/{id}/delete` | Workspaces |
| `POST /api/gen/novels/{id}/model/load` | Load the workspace's base model (no adapter) |
| `POST /api/gen/novels/{id}/preview {goal, title, targetChars}` | Assemble next chapter's first-segment context without generating (tokenizer only) → layer token report + full messages |
| `POST /api/gen/novels/{id}/chapters {goal, title, targetChars}` · `GET /jobs/{jobId}` · `POST /jobs/{jobId}/cancel` | Background chapter job; job response includes the chapter (live text, calls) |
| `GET /api/gen/novels/{id}/chapters/{n}` · `POST .../chapters/{n}/delete` | Chapter detail; only the last chapter can be deleted |

- **Model interface** (`backends.py`): everything goes through `TextGenerator` (`count_messages`, `count_text`, `tail_tokens`, `context_limit`, `ensure_ready`, `generate(messages, GenParams) → GenResult`). `LocalHFGenerator` wraps `app.local.inference.chat_generate` (chat template + system message, token-level cancel via `StoppingCriteria`, exact `finishReason`). Remote backends implement the same class and register in `get_generator` (currently raises "not wired").
- **Constraints** (`spec.py`): world / plot / style plain fields + the protagonist (role contains 主角) + a character roster → **core** (system message, never trimmed); other characters, plot milestones, custom elements (category overview + one card per item, keyed by names) → **retrievable cards**; missing built-in categories → "尚未设定" (open, may be invented without contradiction). `plot.chapters` / `plot.wordsPerChapter` are parameters, not facts (the latter is the default target length).
- **Layered context** (`context.py`, real tokenizer): L0 core + L4 task are mandatory (error if they exceed `window − maxNewTokens − 64`); then L3 recent text minimum (256 tokens of the chapter so far, or the previous chapter's ending), L2 latest chapter summary, L1 cards with keyword relevance > 0 (irrelevant cards are never sent), arc summary, older summaries, then L3 is extended (≤ `params.recentTokens`, 900). The final chat-template count is verified and pieces are rolled back in reverse priority until it fits.
- **Segmented chapters** (`chapter.py`): each segment ≤ `params.segmentTokens` (768, capped at window/4) and only sees the chapter tail, never the whole chapter. Stops at ~95% of target chars, natural end on the last segment, cancel, or a segment cap. Then a summary call (≤150字, temp 0.3); when > 8 unmerged chapter summaries exist the oldest 5 are merged into `arcSummary`. Every call (type, prompt/completion tokens, finish reason, seconds, layer report) is stored on the chapter and added to the workspace totals. One generation job at a time; refused during training; model load/unload/training are refused while a chapter is generating.
- **Storage** (`store.py`): `data/novels/<id>/novel.json` + `chapters/NNNN.json` (`${DATA_DIR}/novels`; `NOVELS_DIR` still overrides). Python is the only writer; Java may read per `data/README.md`. All persistence goes through `store.py` so the planned MySQL migration replaces only that module.

### Conventions

- FastAPI app served by Uvicorn on **port 8021** (test 8011), all routes prefixed with `/api`, Pydantic v2 models for request/response.
- Do **not** re-implement file storage or a second file database. Consume files via the Java backend (by file id / relative storage path) or a shared volume, and return extracted/analyzed results over HTTP.
- Fine-tuning is long-running: run training as **background/async jobs with a status endpoint** (queued/running/succeeded/failed + logs), never block a request worker.
- Keep model weights, datasets, and LoRA adapters out of Git: `python-service/models/` is git-ignored; large base models are registered by path instead of copied.
- Add `requirements.txt` (or `pyproject.toml`) and document the Python version and CUDA/torch assumptions.

## 7. Local Development (Windows)

- Prerequisites: **JDK 17** (the project does not compile on JDK 8), Maven, Node.js. **No database server is needed** (SQLite file `data/nan_novel.db` is created on first start). The pre-migration MySQL schema `test10000` is kept untouched as a rollback source only.
- `start.bat` launches the services with one click. It contains **machine-specific hardcoded tool paths** (`JAVA17_HOME`, `MAVEN_BIN`, `NODE_DIR` under `D:\workplace\...`) — edit them to match the current machine; do not "fix" them for everyone.
- `start.bat` also starts the AI service with the interpreter saved on the **Python 环境** page (`python-service/.python-env`), else `python-service/.venv`. To use the local Qwen llama.cpp server instead of DeepSeek, start it (see the `qwen` skill) and add a config with base URL `http://127.0.0.1:8001/v1`, concurrency 1.
- Ports:

  | Service | Daily (user) | Testing (agents) |
  |---------|--------------|------------------|
  | Java backend | 8022 | 8012 |
  | Python AI service | 8021 | 8011 |
  | Vue frontend | 5173 | 5174 |

  Agents must test only on the testing ports and never stop or occupy the user's daily ports.

## 8. Rules for Code-Generating Agents

- Preserve existing patterns: `Result<T>` + `BizException` on the backend, `src/api` Axios modules on the frontend.
- Prefer extending the current file-management framework over introducing parallel mechanisms (new storage layouts, new response wrappers, new HTTP clients).
- Any new frontend↔backend contract must be updated in **three** places: controller, `src/api/*.js`, and this document if endpoints/conventions change.
- Never commit secrets, uploaded user files, model weights, or datasets; keep `data/` (except `README.md`/`.gitkeep`), `docker.zip` and Python artifacts out of version control.
