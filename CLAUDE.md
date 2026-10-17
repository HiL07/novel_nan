# CLAUDE.md

Project guidance for AI coding assistants (Claude Code). Read this before generating or modifying code.

## 1. Project Overview

**nan_novel** is an AI-assisted **novel generation** system. Users upload and manage novel/manuscript source files; a Python AI service extracts and analyzes the text and fine-tunes remote large language models (**QLoRA / Hugging Face**) to power novel generation.

The system consists of three components:

| # | Component | Role | Status |
|---|-----------|------|--------|
| 1 | **Frontend** (`frontend/`) | Vue 3 + Vite SPA — file upload & management UI | Implemented |
| 2 | **Java backend** (`backend/`) | Spring Boot — **file management is the base framework**: upload-to-disk, metadata in MySQL, download/preview APIs | Implemented |
| 3 | **Python AI backend** (planned, e.g. `python-service/`) | FastAPI — article/content extraction, text analysis, remote LLM QLoRA & Hugging Face fine-tuning | **Not scaffolded yet** |

```
Browser (Vue3/Vite, :5173)
        │  HTTP
        ▼
Spring Boot (:8080) ─────► MySQL (test10000) + local disk (./upload/)
        │  HTTP (planned)
        ▼
Python FastAPI (:8000 proposed) ─────► remote LLM / Hugging Face training (QLoRA)
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
│   └── upload/         # Runtime file storage root (yyyy/MM/dd/<uuid>.<ext>)
├── frontend/           # Vue 3 + Vite SPA
│   └── src/
│       ├── api/        # Axios API layer (one module per backend resource)
│       ├── layout/     # App shell: Sidebar + AppMain
│       ├── router/     # Lazy-loaded routes
│       └── views/file/ # upload.vue, manage.vue
├── start.bat           # Windows one-click launcher for backend + frontend
└── CLAUDE.md
```

## 3. Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vue 3.4 (`<script setup>` Composition API), Vite 5, Vue Router 4, Element Plus 2.7 (+ `@element-plus/icons-vue`, globally registered), Axios 1.7 |
| Java backend | Java 17, Spring Boot 3.2.5, Spring Web, MyBatis-Plus 3.5.7, MySQL (`mysql-connector-j`), Lombok, Maven |
| Python service (planned) | Python 3.10+, FastAPI, Uvicorn, Pydantic v2; `transformers` + `peft` (QLoRA), `datasets`, `accelerate`, `bitsandbytes`, PyTorch; extraction libs such as `python-docx` / `pypdf` |

## 4. Java Backend Conventions (`backend/`)

### Commands

```bash
mvn spring-boot:run     # run on http://localhost:8080 (requires JDK 17)
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
| `GET  /api/file/preview/{id}` | Inline preview (image/PDF/text) |

### File storage rules

- Root dir from `file.storage.path` in `application.yml` (default `./upload/`).
- Stored filename = **UUID without dashes** + lowercased extension; date-partitioned as `yyyy/MM/dd/`.
- DB stores only the **relative** `storage_path`; always resolve against the configured root and normalize paths (path-traversal safe).
- Upload limit: 50 MB per file / per request (see `application.yml`).
- `file` table (schema `test10000`) columns, derived from `FileInfo`: `id` (auto increment), `file_name`, `storage_path`, `file_size`, `content_type`, `file_ext`, `create_time`.

### Configuration & CORS

- Config lives in `backend/src/main/resources/application.yml`. **Do not hardcode or copy DB credentials into code or docs**; read them from the yml.
- `WebConfig` allows CORS only from `http://localhost:5173` (GET/POST on `/api/**`). If the frontend adds methods (PUT/DELETE), update both sides.

## 5. Frontend Conventions (`frontend/`)

### Commands

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # production build
npm run preview
```

### Rules

- All SFCs use **`<script setup>`** (Composition API); UI text is Chinese, identifiers/comments may be Chinese or English.
- `@` alias → `src/` (configured in `vite.config.js`).
- Keep HTTP calls inside `src/api/*.js` using the shared Axios instance (`baseURL: http://localhost:8080`, 60s timeout). Views must not create their own Axios instances.
- API helpers unwrap `res.data`; callers treat `response.code === 0` as success.
- Routes are lazy-loaded (`() => import(...)`) with `meta.title` / `meta.icon` consumed by the sidebar; register new pages in `src/router/index.js`.
- Element Plus and all its icons are registered globally in `main.js`.

## 6. Python AI Service (planned — `python-service/`)

This service is the **AI/ML layer**; the Spring Boot service remains the system of record for files and metadata.

Responsibilities:
1. **Content extraction** — parse uploaded novel/manuscript files (txt/md/docx/pdf…) into clean plain text and structured chapters.
2. **Content analysis** — e.g. chapter segmentation, characters, plotlines, style statistics; results returned as JSON.
3. **LLM fine-tuning** — dataset preparation and **QLoRA fine-tuning with Hugging Face** (`transformers` + `peft`) against remote GPU/LLM resources; manage training jobs and LoRA adapters.

Conventions to follow when scaffolding:
- FastAPI app served by Uvicorn on **port 8000 (proposed)**, all routes prefixed with `/api`, Pydantic v2 models for request/response.
- Do **not** re-implement file storage or a second file database. Consume files via the Java backend (by file id / relative storage path) or a shared volume, and return extracted/analyzed results over HTTP.
- Fine-tuning is long-running: run training as **background/async jobs with a status endpoint** (queued/running/succeeded/failed + logs), never block a request worker.
- Keep model weights, datasets, and LoRA adapters outside the Git working tree (configurable paths / env vars).
- Add `requirements.txt` (or `pyproject.toml`) and document the Python version and CUDA/torch assumptions.

## 7. Local Development (Windows)

- Prerequisites: **JDK 17** (the project does not compile on JDK 8), Maven, Node.js, and a running MySQL with schema `test10000`.
- `start.bat` launches both services with one click. It contains **machine-specific hardcoded tool paths** (`JAVA17_HOME`, `MAVEN_BIN`, `NODE_DIR` under `D:\workplace\...`) — edit them to match the current machine; do not "fix" them for everyone.
- Service URLs: backend http://localhost:8080, frontend http://localhost:5173.

## 8. Rules for Code-Generating Agents

- Preserve existing patterns: `Result<T>` + `BizException` on the backend, `src/api` Axios modules on the frontend.
- Prefer extending the current file-management framework over introducing parallel mechanisms (new storage layouts, new response wrappers, new HTTP clients).
- Any new frontend↔backend contract must be updated in **three** places: controller, `src/api/*.js`, and this document if endpoints/conventions change.
- Never commit secrets, uploaded user files, model weights, or datasets; keep `backend/upload/` and Python artifacts out of version control.
