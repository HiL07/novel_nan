# CLAUDE.md

> 接手记录（2026-11-15）：用户确认项目核心为“从其他小说提取素材，并在生成自己的小说时导入使用”。后续开发先读 [项目接手与核心目标](docs/项目接手与核心目标.md)，其中区分用户目标、代码现状与待定方案；本文件保留既有技术约定。

Project guidance for AI coding assistants (Claude Code). Read this before generating or modifying code.
This file holds the overview, the core rules and the doc index; endpoint-level details live in
[`docs/claude/`](docs/claude/README.md) — **read the matching file before touching that area**.

## 1. Project Overview

**nan_novel** is an AI-assisted **novel generation** system. Users upload and manage novel/manuscript source files; a Python AI service extracts and analyzes the text and fine-tunes remote large language models (**QLoRA / Hugging Face**) to power novel generation.

| # | Component | Role | Status |
|---|-----------|------|--------|
| 1 | **Frontend** (`frontend/`) | Vue 3 + Vite SPA — upload / management UI, 书房 workspace, 素材库, 灵感墙, 角色卡, 小说抓取 | Implemented |
| 2 | **Java backend** (`backend/`) | Spring Boot — **file management is the base framework**: upload-to-disk, metadata in SQLite (`data/nan_novel.db`), download/preview APIs; system of record for tasks, materials, crawl, personas | Implemented |
| 3 | **Python AI backend** (`python-service/`) | FastAPI — extraction, text analysis, retrieval, generation, crawler, local model management + LoRA/QLoRA style fine-tuning (Hugging Face) | Extraction + **local** fine-tuning implemented; remote inference/training planned |

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
Browser ──(本地模型 page, direct)──► Python /api/local/**   (also /api/gen/** except calls needing the API key / materials)
```

Main feature areas: 文件管理 → 小说抓取 → 小说提取 (提取工作区, 实体档案) → 整理卡片 → 素材库 (检索 / 精炼合并 / 量级) →
灵感墙 / 角色卡 + 试聊 → 书房 workspace (设定 / 自动规划 / AI 构思 / 写作 / 故事账本 / 世界书) + 本地模型 / llama.cpp / 模型配置.

## 2. Documentation index

**Implementation reference** (English, endpoints / fields / tables; split from this file on 2026-11-03, original in `docs/claude/_backup/`):

| Doc | Covers |
|---|---|
| [`docs/claude/repo-layout.md`](docs/claude/repo-layout.md) | full annotated repository tree |
| [`docs/claude/java-backend.md`](docs/claude/java-backend.md) | Java commands, layering, `Result<T>`, file API, AI model config API, Python env API, storage & SQLite rules, CORS |
| [`docs/claude/extraction-materials.md`](docs/claude/extraction-materials.md) | extraction tasks (DRAFT → … states, checkpoints, 提取工作区, live), material library (categories, candidates, semantic / vector search, merge, profile), Python scan / compile / merge / evals |
| [`docs/claude/crawler.md`](docs/claude/crawler.md) | crawl tasks & lanes, sites / saved URLs, AI rule learning, site catalogs (全自动), crawl page, Python crawler / fetcher / parser |
| [`docs/claude/generation.md`](docs/claude/generation.md) | `/api/novel/gen` (AI 构思, 走向引擎), auto planning, inspiration wall, Python generation (backends, spec, context, ledger, world book, chapters, polish) |
| [`docs/claude/frontend.md`](docs/claude/frontend.md) | frontend rules, ink theme, `SettingsEditor` (schema-driven options, AI fill, material pick), workspaces / 书房 layout, IdeaPanel |
| [`docs/claude/local-models.md`](docs/claude/local-models.md) | `/api/local/**`: base models, adapters, embedding / reranker, llama.cpp, inference, training jobs |
| [`docs/claude/persona.md`](docs/claude/persona.md) | persona cards & 试聊 implementation |
| [`docs/claude/general.md`](docs/claude/general.md) | original wording of the overview, Python service intro, local dev and agent rules condensed below |
| [`docs/claude/README.md`](docs/claude/README.md) | index of this folder + **points to verify** (stale / inconsistent statements found while splitting) |

**Design deep-dives** (`docs/`, Chinese — parameters, thresholds, measurements and the reasons behind them; `README.md` in the repo root is the GitHub overview):

| Doc | Covers |
|---|---|
| `docs/素材流程.md` | extraction (scan, quote verification, two rounds, aggregation), 整理卡片, checkpoints and task states, 分章 rules, GGUF measurements |
| `docs/素材提取改造方案.md` | the per-chapter extraction redesign (§3.0 / §3.0.2 serial chapter scan) |
| `docs/素材检索.md` | vector text, bge + BM25 hybrid recall, RRF, reranking and score meaning, multi-version recall, auto-matching, StageFit, eval (§7–8) |
| `docs/灵感墙.md` | inspiration wall: need planning, local retrieval, ideas with checked material refs, the four exits |
| `docs/跨世界观角色卡.md` | persona prototypes, provenance, versions, adaptation checks, generation hooks, identity test |
| `docs/试聊.md` | 试聊: modes, anchors, summaries of old turns, drift checks, feedback |
| `docs/世界书.md` | world book: compiled entries, character situation fields and clocks, rollback rules, snapshot |
| `docs/走向引擎.md` | direction engine: drivers → review / revise → ranking; eval method and measured versions |
| `docs/自动规划.md` | auto planning (story-first only; material-first route removed 2026-11-02, kept in §2 for reference) |
| `docs/精炼合并.md` | similar groups, AI drafts and grounding checks, 共性 + 可选版本, unmerge |
| `docs/素材使用方案.md` | discussion draft (2026-11-11, not implemented): how materials should be retrieved and used in auto planning (参数 · 灵感 / 设定), retrieval research with links, material tree, retrieval test plan, open questions |
| `docs/待办.md` | open work (UI redesign steps, user issues) |
| `模型对比测试报告.md` | DeepSeek vs local GGUF / safetensors benchmark (2026-10-27) |

**Doc maintenance rules**
- When you change extraction, retrieval or merge algorithms / parameters, update the matching `docs/*.md` in the same change.
- When you change persona extraction / adaptation / checks / identity test / chat, update `docs/跨世界观角色卡.md` / `docs/试聊.md`.
- Any new frontend↔backend contract must be updated in **three** places: controller, `src/api/*.js`, and the matching `docs/claude/*.md` (this file only when a core convention changes).

## 3. Repository Layout (top level)

```
nan_novel/
├── backend/          # Spring Boot (Maven), package com.example.file: common / config / controller / entity / mapper / service
│                     #   resources: application.yml, sql/ (per-table DDL + init.sql; sql/mysql/ = rollback only), python/env_probe.py
├── frontend/         # Vue 3 + Vite: src/api, layout, router, views/{file,novel,ai,material,persona,inspire}, components/*, novel-options, styles, utils, mock
├── python-service/   # FastAPI: app/ (extraction, materials, persona), app/local/, app/generation/, app/crawler/, scripts/ (evals, self-tests), models/ (git-ignored)
├── docs/             # design deep-dives (Chinese) + docs/claude/ (implementation reference)
├── data/             # git-ignored shared data dir: nan_novel.db, upload/, extract-results/, novels/, … — see data/README.md
├── picture/          # git-ignored screenshots the user drops in to explain requests — when a request mentions an image, read it from here
├── scripts/migration/ # one-off MySQL → SQLite config import
├── start.bat / start-llama.bat   # Windows launchers (machine-specific paths)
└── README.md, CLAUDE.md, 模型对比测试报告.md
```

Full annotated tree: [`docs/claude/repo-layout.md`](docs/claude/repo-layout.md).

## 4. Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vue 3.4 (`<script setup>` Composition API), Vite 5, Vue Router 4, Element Plus 2.7 (+ `@element-plus/icons-vue`, globally registered), Axios 1.7 |
| Java backend | Java 17, Spring Boot 3.2.5, Spring Web, MyBatis-Plus 3.5.7, SQLite (`sqlite-jdbc`, WAL), Lombok, Maven |
| Python service | Python 3.10+, FastAPI, Uvicorn, Pydantic v2, httpx, `python-docx` / `pypdf`; local models: PyTorch 2.6 (CUDA 12.4 build), `transformers` 4.5x, `peft`, `accelerate`, `bitsandbytes` (QLoRA); retrieval: `BAAI/bge-small-zh-v1.5` + BM25 (jieba) + `BAAI/bge-reranker-v2-m3` |

## 5. Java Backend — core rules (`backend/`)

Details: [`docs/claude/java-backend.md`](docs/claude/java-backend.md).

```bash
mvn spring-boot:run     # http://localhost:8022 (requires JDK 17)
mvn spring-boot:run -Dspring-boot.run.arguments="--server.port=8012 --ai.service.url=http://localhost:8011"   # test instance
mvn clean package
```

- Layering `controller` → `service` → `mapper` → `entity`, no cross-layer calls. New feature = full set: entity (`@TableName`, `@TableId(type = IdType.AUTO)`) → `mapper extends BaseMapper<T>` (no hand-written SQL unless necessary) → service → controller.
- **Constructor injection only**; Lombok `@Data` on entities / DTOs; SLF4J loggers; never expose stack traces to clients.
- All JSON endpoints are under `/api/**` and **return `Result<T>`** (`Result.ok(data)` → `code 0` = success; `Result.error(code, message)`). Throw `BizException(code, message)`; controllers map it via `common/ResultResponses.handle(...)`. Binary endpoints return `ResponseEntity<byte[]>` with proper `Content-Type` / `Content-Disposition`.
- **CORS is GET/POST only** (`app.cors.allowed-origins`, default 5173 / 5174), so update / delete endpoints are POST. Adding PUT/DELETE means updating both sides.
- The file API (`/api/file/upload|list|download|preview|text`) is the base framework — extend it, don't duplicate it. Upload field name is **`file`**.
- **SQLite** `data/nan_novel.db` (WAL), opened **only by Java**. Store **metadata only**; large content (novel text, extraction results) goes into files under `data/`. Tables auto-created from per-table scripts in `resources/sql/`; **when adding or changing a table, update both its per-table script and `init.sql`**; column additions on old DBs go through `config/SchemaMigrations`. No foreign keys; LocalDateTime as text; booleans 0/1; JSON columns via `JacksonTypeHandler` (`autoResultMap = true`).
- File storage: relative `storage_path` only, resolved against the configured root and traversal-checked (`common/DataPaths`); stored name = dashless UUID + lower-case extension under `yyyy/MM/dd/`; write `.part` then atomic rename.
- Long tasks (extraction, compile, crawl, persona) run on background threads, poll Python jobs every 3 s, and persist state; errors / restarts make tasks **INTERRUPTED** (resumable via checkpoints) — follow the existing state machines described in the reference docs.
- **Secrets**: API keys live in the DB or `backend/application-secret.yml` (git-ignored) / env `DEEPSEEK_API_KEY`. `apiKey` is write-only (responses carry `apiKeyMasked`). Never put keys in tracked files or logs; **don't log AI-service error bodies** (Python 422 echoes contain the key — pass through only our own `{message}`).
- JDK 17 on Chinese Windows defaults to GBK: always pass an explicit charset when converting bytes ↔ String.
- Tag filters use parameterized queries on `material_tag` — never build SQL strings from user input.
- Python URL: `ai.service.url` (default `http://localhost:8021`). Don't hardcode or copy DB credentials into code or docs.

## 6. Frontend — core rules (`frontend/`)

Details: [`docs/claude/frontend.md`](docs/claude/frontend.md) (crawl page: [`docs/claude/crawler.md`](docs/claude/crawler.md)).

```bash
npm install
npm run dev        # http://localhost:5173 → backend 8022
npm run dev:test   # http://localhost:5174 → test backend 8012
npm run build
```

- All SFCs use **`<script setup>`**; UI text is Chinese; `@` → `src/`.
- HTTP calls only in `src/api/*.js` via the shared Axios instances `request` (Java) / `aiRequest` (Python direct calls) from `src/api/request.js`; views never create Axios instances. Helpers unwrap `res.data`; `code === 0` = success.
- Routes lazy-loaded with `meta.title` / `meta.icon` (sidebar); `meta.children` renders a sub-menu.
- `.app-wrapper` is one screen high; only `.app-main` scrolls (scroll-to-top targets `.app-main`). **Route pages need exactly one root element — no HTML comment beside it** (`<transition mode="out-in">` otherwise blanks the next page).
- **Theme** `styles/ink-theme.css` (墨色 + 朱砂红) is site-wide: **don't hard-code Element default colours** (`#409eff`, `#303133`, `#606266`, `#909399`, `#f5f7fa`, `#e4e7ed` …) — use `var(--el-…)` / `var(--ws-…)`.
- **The workspace page is kept alive and reused across workspaces**: components holding per-workspace state must be keyed by the workspace (`:key="novel.id"`) or watch `novelId`.
- Model sources everywhere AI is used: `api` (大模型 = active VERIFIED config), `local` (safetensors + LoRA, serial), `gguf` (the model running on the llama.cpp page, serial), `remote` (reserved, disabled). Generation-model pickers filter with `isGenerationModel`.
- Everything AI-generated must stay hand-editable; AI suggestions are never saved without an explicit user action (materials only enter `material` after 「保存」 on a candidate).
- Settings editor is **schema-driven** (`categories → fields → options → children`); new field types go in `novel-options/fieldTypes.js` + `OptionField.vue`. Untouched number / slider defaults never become generation constraints.

## 7. Python AI Service — core rules (`python-service/`)

Details: [`docs/claude/extraction-materials.md`](docs/claude/extraction-materials.md), [`docs/claude/generation.md`](docs/claude/generation.md), [`docs/claude/crawler.md`](docs/claude/crawler.md), [`docs/claude/local-models.md`](docs/claude/local-models.md), [`docs/claude/persona.md`](docs/claude/persona.md).

```bash
cd python-service
py -3.10 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # keep requirements.txt ASCII (old pip reads it as GBK)
.venv/Scripts/python -m uvicorn app.main:app --port 8021
# test instance (talks to test Java backend 8012):
JAVA_BACKEND_URL=http://localhost:8012 .venv/Scripts/python -m uvicorn app.main:app --port 8011
```

- FastAPI on port 8021 (test 8011), routes under `/api`, Pydantic v2 models. `requirements-local.txt` = torch CUDA + transformers / peft / bitsandbytes (torch imported lazily; extraction runs without it).
- Data dir `DATA_DIR` (default `<repo>/data`); Python writes only `data/novels/`, `data/material-index/`, `data/crawl-cache/`, `data/extract-cache/`, `data/site-catalog/<host>/toc/`. **No second file database** — read files via Java (`GET /api/file/preview/{id}`), return results over HTTP. Generation persistence goes only through `generation/store.py`.
- The model config (base URL, key, model, concurrency) comes from Java **per request**; Python never stores the key and never logs it.
- Long work (extraction, training, chapters, crawl) = background jobs with status endpoints (queued / running / succeeded / failed + logs) and checkpoints; never block a request worker. Training runs in a subprocess; one GPU job at a time.
- **Pydantic request models must declare every field Java forwards** — undeclared fields are dropped silently (happened to `IdeasReq` until 2026-10-30).
- All `httpx` calls to local services use `trust_env=False` (a system proxy turns `localhost` into 502).
- `llm_client.chat()` (structured JSON calls) disables thinking by default; fatal errors (401/403/402/404) abort jobs, 429/5xx retry.
- On Windows never probe PIDs with `os.kill(pid, 0)` (it kills the process) — use `jobs.pid_alive`.
- Keep model weights, datasets and adapters out of Git (`python-service/models/` is git-ignored; large base models are registered by path).
- Chapter-heading rules exist twice — Python `text_loader.split_book` / `detect_heading` and Java `service/ChapterCounter`: change both together. Category codes exist three times — `materials.py`, `frontend/src/api/material.js`, Java — keep them in sync.
- Analysis text is output in Simplified Chinese; names keep their original spelling.

## 8. Local Development (Windows)

- Prerequisites: **JDK 17**, Maven, Node.js. No database server (SQLite file created on first start). The pre-migration MySQL schema `test10000` is kept untouched as a rollback source only.
- `start.bat` launches backend + AI service + frontend. It contains **machine-specific hardcoded tool paths** (`JAVA17_HOME`, `MAVEN_BIN`, `NODE_DIR`) — don't "fix" them for everyone. It starts the AI service with the interpreter chosen on the **Python 环境** page (`python-service/.python-env`, GBK), else `python-service/.venv`.
- GGUF models: start them on the **llama.cpp** page (`/ai/llama`, Python-managed `llama-server` on 8001) and pick the 「GGUF」 source. Manual alternative `start-llama.bat` (same port, own console; always keep `--parallel 1 --cache-ram 0` — the defaults crash with a CUDA error after ~15 min on the RTX 4060 Laptop). `start.bat`'s `START_LLAMA` defaults to 0.
- Dev machine: RTX 4060 Laptop 8 GB, 16 GB RAM, C: nearly full — keep defaults conservative.
- Ports:

  | Service | Daily (user) | Testing (agents) |
  |---------|--------------|------------------|
  | Java backend | 8022 | 8012 |
  | Python AI service | 8021 | 8011 |
  | Vue frontend | 5173 | 5174 |
  | llama.cpp | 8001 | 8002 |

  **Agents must test only on the testing ports and never stop or occupy the user's daily ports.** Run test instances on a **copy** of `data/` (`DATA_DIR`) when the test would mutate state — a Java start marks running tasks INTERRUPTED.

## 9. Rules for Code-Generating Agents

- Preserve existing patterns: `Result<T>` + `BizException` on the backend, `src/api` Axios modules on the frontend.
- Prefer extending the current file-management framework over introducing parallel mechanisms (new storage layouts, new response wrappers, new HTTP clients).
- Frontend → Java → Python is the default path; direct frontend → Python calls are the documented exceptions (`/api/local/**`, most of `/api/gen/**`).
- Any new frontend↔backend contract: controller + `src/api/*.js` + the matching `docs/claude/*.md`.
- Never commit secrets, uploaded user files, model weights, or datasets; keep `data/` (except `README.md`/`.gitkeep`), `picture/`, `docker.zip` and Python artifacts out of version control.
- Don't copy code or images from AGPL projects (e.g. the 书房 layout was modelled on EasyWriting's design only).
