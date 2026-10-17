# CLAUDE.md

Project guidance for AI coding assistants (Claude Code). Read this before generating or modifying code.

## 1. Project Overview

**nan_novel** is an AI-assisted **novel generation** system. Users upload and manage novel/manuscript source files; a Python AI service extracts and analyzes the text and fine-tunes remote large language models (**QLoRA / Hugging Face**) to power novel generation.

The system consists of three components:

| # | Component | Role | Status |
|---|-----------|------|--------|
| 1 | **Frontend** (`frontend/`) | Vue 3 + Vite SPA — file upload & management UI | Implemented |
| 2 | **Java backend** (`backend/`) | Spring Boot — **file management is the base framework**: upload-to-disk, metadata in MySQL, download/preview APIs | Implemented |
| 3 | **Python AI backend** (`python-service/`) | FastAPI — article/content extraction, text analysis, local model management + LoRA/QLoRA style fine-tuning (Hugging Face) | Extraction + **local** fine-tuning implemented; remote inference/training planned |

```
Browser (Vue3/Vite, :5173)
        │  HTTP
        ▼
Spring Boot (:8022) ─────► MySQL (test10000) + local disk (./upload/)
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
│   ├── src/main/resources/sql/   # Table DDL, run at startup by spring.sql.init
│   └── upload/         # Runtime file storage root (yyyy/MM/dd/<uuid>.<ext>)
├── frontend/           # Vue 3 + Vite SPA
│   └── src/
│       ├── api/        # Axios API layer (one module per backend resource)
│       ├── layout/     # App shell: Sidebar + AppMain
│       ├── router/     # Lazy-loaded routes
│       ├── views/file/ # upload.vue, manage.vue
│       ├── views/novel/ # create.vue (novel setting selector), extract.vue (extraction tasks & results)
│       ├── views/ai/    # model.vue (remote AI model configs), local.vue (本地模型: models / fine-tuning / adapters / inference)
│       ├── components/novel-options/ # schema-driven option UI (OptionField, ChoiceWidget, …)
│       ├── novel-options/ # field-type registry, schema helpers, editor context
│       └── mock/        # local placeholder data (until the DB exists)
├── python-service/     # FastAPI AI service
│   ├── app/            # main.py, extractor, llm_client, text_loader (extraction)
│   ├── app/local/      # local models: settings, hardware, registry, inference, training, download, jobs, worker, router
│   ├── models/         # git-ignored: base/<id>/model.json (+weights if downloaded), adapters/<id>/, jobs/<id>/
│   ├── scripts/local_e2e.py  # end-to-end smoke test over HTTP
│   ├── requirements.txt       # extraction service (no torch)
│   └── requirements-local.txt # local models (torch CUDA + transformers/peft/accelerate/bitsandbytes)
├── start.bat           # Windows one-click launcher for backend + AI service + frontend
└── CLAUDE.md
```

## 3. Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vue 3.4 (`<script setup>` Composition API), Vite 5, Vue Router 4, Element Plus 2.7 (+ `@element-plus/icons-vue`, globally registered), Axios 1.7 |
| Java backend | Java 17, Spring Boot 3.2.5, Spring Web, MyBatis-Plus 3.5.7, MySQL (`mysql-connector-j`), Lombok, Maven |
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

- Table `novel_extract` (DDL `sql/novel_extract.sql`, auto-created via `spring.sql.init`): `id`, `file_id`, `file_name`, `status` (QUEUED/RUNNING/SUCCEEDED/FAILED), `progress`, `message`, `job_id`, `result` (LONGTEXT JSON), `create_time`, `update_time`.
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

### File storage rules

- Root dir from `file.storage.path` in `application.yml` (default `./upload/`).
- Stored filename = **UUID without dashes** + lowercased extension; date-partitioned as `yyyy/MM/dd/`.
- DB stores only the **relative** `storage_path`; always resolve against the configured root and normalize paths (path-traversal safe).
- Upload limit: 50 MB per file / per request (see `application.yml`).
- `file` table (schema `test10000`) columns, derived from `FileInfo`: `id` (auto increment), `file_name`, `storage_path`, `file_size`, `content_type`, `file_ext`, `create_time`.

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

### Novel setting selector (`/novel/create`) — options only, no persistence yet

- **Schema-driven**: everything renders from data — `categories[] → fields[] → options[] → children(fields[])`, nestable to any depth. Field types live in `src/novel-options/fieldTypes.js` (`single`, `multi`, `text`, `textarea`, `number`, `slider`, `tags`, `group`); to add a type, register it there and map it in `OptionField.vue`.
- **Data source**: `src/api/novelOptions.js#getOptionSchema()` currently returns `src/mock/novelOptionSchema.js` (built-in categories 世界观/角色/情节推进/文风, `elementTemplates` such as 怪物/势力/种族/地点/物品/功法, `genericSuggestions`). When the DB exists, switch only this function to a backend call returning the same shape.
- **Values**: `{ [categoryKey]: { [fieldKey]: value } }`; choice value `{ selected: string[], sub: { [optionValue]: childValues } }`, group value `[{ _id, ...childValues }]`.
- **Extensibility (编辑模式)**: users can add custom options inline, add fields to any category / group / option (from suggestions or self-defined), and create custom elements (e.g. 怪物) from a template or blank. User-created items carry `custom: true` and `uid()` keys.
- **Output**: `buildSpec()` + `specToJson()` (`src/novel-options/schema.js`) give a label-keyed JSON of the chosen settings (for generation prompts); the "完整配置" export is `{ categories, values }` (for later DB storage). Nothing is saved yet — refresh loses state.

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

The model (base URL, key, model name, concurrency) is **not** configured here — Java sends the active config with each request and Python never stores the key. Env vars (`app/config.py`): `JAVA_BACKEND_URL`, `CHUNK_CHARS` (default 6000), `LLM_MAX_TOKENS`, `LLM_TIMEOUT`. No torch/CUDA needed for extraction.

### Novel extraction (implemented)

- `POST /api/models/verify` `{baseUrl, apiKey, model}` → `{ok, latencyMs, message, reply}`.
- `POST /api/extract/jobs` `{fileId, fileExt, model:{baseUrl, apiKey, model, concurrency}}` → job; `GET /api/extract/jobs/{jobId}` → `queued/running/succeeded/failed`, `progress`, `message`, `error`, `result`; `GET /api/health`.
- `app/llm_client.py`: OpenAI-compatible `POST {baseUrl}/chat/completions` with `Bearer` key. Friendly errors (401/403 key, 402 balance, 404 model/URL are *fatal* and abort the job; 429/5xx/timeouts retry ×2). Falls back without `response_format` if a provider rejects JSON mode. Local hosts skip the system proxy; remote hosts use it.
- Jobs are in-memory and run one at a time; Java is responsible for persisting results.
- Languages: Chinese (primary) and English novels. Analysis text is always output in Simplified Chinese; character/place names keep the original spelling.
- All `httpx` calls to local services use `trust_env=False` — a system proxy (Clash etc.) otherwise turns `localhost` requests into 502.
- Pipeline: fetch bytes via Java `GET /api/file/preview/{id}` → decode (BOM → strict UTF-8 → strict GB18030 → fewest replacement chars) or parse docx/pdf → split chapters (`第X章/回/节/卷`, `Chapter 12/IV/One`, 楔子/尾声/后记/Prologue; fallback `1.标题` / `一、标题` only when ≥3 found) → chunk ≤ `CHUNK_CHARS` at paragraph boundaries → LLM JSON per chunk, `concurrency` requests in parallel (`response_format: json_object`, temperature 0.2) → merge (per-chapter summary/characters/events/foreshadowing, deduped characters, dialog ratio computed in code).

### Local models & style fine-tuning (`app/local/`, `/api/local/**`)

Local-only for now; remote inference/training must plug into the existing extension points (`source` on registry records, `backend` on jobs + `worker.RUNNERS[(kind, backend)]`). The frontend calls these endpoints **directly** (CORS: `CORS_ORIGINS`, default 5173/5174) — an explicit exception to "frontend → Java → Python", because model files live next to the Python service. Responses use `{code, message, data}` (code 0 = success; `LocalError` → HTTP status).

| Method & path | Purpose |
|---------------|---------|
| `GET  /api/local/system` | GPU (nvidia-smi), RAM, disk, dependency versions, inference state, active job |
| `GET  /api/local/models` · `POST /models/register {name, path}` · `POST /models/download {repoId, name, useMirror}` · `POST /models/{id}/delete` | Base models. Register = record path only (no copying); download = background job into `models/base/<id>/weights/` then auto-register |
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

### Conventions

- FastAPI app served by Uvicorn on **port 8021** (test 8011), all routes prefixed with `/api`, Pydantic v2 models for request/response.
- Do **not** re-implement file storage or a second file database. Consume files via the Java backend (by file id / relative storage path) or a shared volume, and return extracted/analyzed results over HTTP.
- Fine-tuning is long-running: run training as **background/async jobs with a status endpoint** (queued/running/succeeded/failed + logs), never block a request worker.
- Keep model weights, datasets, and LoRA adapters out of Git: `python-service/models/` is git-ignored; large base models are registered by path instead of copied.
- Add `requirements.txt` (or `pyproject.toml`) and document the Python version and CUDA/torch assumptions.

## 7. Local Development (Windows)

- Prerequisites: **JDK 17** (the project does not compile on JDK 8), Maven, Node.js, and a running MySQL with schema `test10000`.
- `start.bat` launches the services with one click. It contains **machine-specific hardcoded tool paths** (`JAVA17_HOME`, `MAVEN_BIN`, `NODE_DIR` under `D:\workplace\...`) — edit them to match the current machine; do not "fix" them for everyone.
- `start.bat` also starts the AI service if `python-service/.venv` exists. To use the local Qwen llama.cpp server instead of DeepSeek, start it (see the `qwen` skill) and add a config with base URL `http://127.0.0.1:8001/v1`, concurrency 1.
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
- Never commit secrets, uploaded user files, model weights, or datasets; keep `backend/upload/` and Python artifacts out of version control.
