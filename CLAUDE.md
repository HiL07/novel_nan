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
│       ├── views/novel/ # create.vue (workspace list), workspace.vue (设定 + AI 构思 + 写作), extract.vue (extraction tasks & results), crawl.vue (网络小说抓取: 4 sub-pages via `/novel/crawl/:tab` — 抓取配置 / 单本 / 全自动 / 抓取进度)
│       ├── views/ai/    # model.vue (remote AI model configs), local.vue (本地模型), pyenv.vue (Python 环境 selection & check)
│       ├── views/material/ # index.vue (素材库: keyword/tag + AI semantic search, 待确认 candidates)
│       ├── components/material/ # ExtractOptionsDialog, CandidateReview (20 per page), MaterialEditor, AttributeEditor, MaterialPicker (pick-only mode for AI 构思)
│       ├── components/crawl/ # WorkspacePanel (抓取进度: per-home workspaces, 来源 单本/整站), SiteMapView (AI 解析: site root + per-layer URL patterns, 已掌握 / 未掌握), AutoCrawlPanel (全自动: 测试规律 → 决定 → 书目筛选 / 抓取)
│       ├── components/ai/ # TokenUsageBar (source tag 大模型/本地/远程, tokens incl. cache hits, cost via utils/modelPricing.js)
│       ├── utils/modelPricing.js # reference prices per 1M tokens by model name (CNY/USD) + per-model overrides in localStorage
│       ├── components/novel/ # IdeaPanel (AI 构思: 书名 / 大纲 / 章节题目 + 素材)
│       ├── components/novel-options/ # schema-driven option UI (SettingsEditor, OptionField, ChoiceWidget, …)
│       ├── novel-options/ # field-type registry, schema helpers, editor context
│       └── mock/        # local placeholder data (until the DB exists)
├── python-service/     # FastAPI AI service
│   ├── app/            # main.py, extractor, llm_client, text_loader (extraction)
│   ├── app/local/      # local models: settings, hardware, registry, inference, training, download, jobs, worker, router
│   ├── app/generation/ # novel generation: backends, spec, context, prompts, chapter (+ polish), ideas (AI 构思), store, defaults, router
│   ├── app/crawler/    # web novel crawler: rules (presets / XPath), fetcher, parser (heuristics), service (jobs), catalog (全自动书目采集 + AI 检索 / 补标签), ai_rules, router
│   ├── models/         # git-ignored: base/<id>/model.json (+weights if downloaded), adapters/<id>/, jobs/<id>/
│   ├── scripts/local_e2e.py  # end-to-end smoke test over HTTP
│   ├── scripts/crawl_site_selftest.py  # crawler self-test against a local fake book site (no network)
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
| `GET  /api/file/text/{id}?offset=0&limit=100000` | Paged text preview (same decoding, by chars, limit 1k–500k) → `{text, offset, nextOffset, totalChars, done}`; decoded text of the last 2 files is cached. The 文件管理 dialog loads 100k chars at a time (scroll / 加载更多) — rendering a whole multi-MB novel froze the page |

### Novel extraction API (`NovelExtractController`)

| Method & path | Purpose |
|---------------|---------|
| `POST /api/novel/extract/{fileId}` | Create an async extraction task for a txt/md/docx/pdf file; returns the task (`QUEUED`) |
| `GET  /api/novel/extract/list` | Tasks without `result`, `create_time` descending |
| `GET  /api/novel/extract/{id}` | Task detail; `result` is the extraction JSON string (chapters, characters, style) |
| `POST /api/novel/extract/{id}/result {chapters[], characters[], style, …}` | Save a hand-edited result (whole JSON replaced; must contain `chapters`; SUCCEEDED tasks only). Rewrites the file via `ExtractResultStore.write`, updates `result_size` / `result_sha256` / `chapter_count`, adds `editedAt` to the JSON; if the DB update fails the old file is written back |

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
| `GET /api/material/list?category=&tags=a,b&tagMode=all\|any&keyword=&sourceBook=&excludeBooks=a,b&pinned=&page=&size=` | Keyword (title/summary/subtype/detail/tags) + tag search, paged (MyBatis-Plus `Page`, needs `MybatisPlusConfig` pagination plugin). `sourceBook` (`__manual__` = no source), `excludeBooks` (pinned items still shown), `pinned=true` |
| `GET /api/material/sources` · `POST /sources/delete {book, withCandidates?}` · `POST /{id}/pin {pinned}` | Source books `[{book, count, pinned, pending}]`; delete a book's **unpinned** materials (optionally ignore its pending candidates) → `{deleted, kept, candidatesIgnored}`; pin = 保留 |
| `POST /api/material/semantic-search {query, category?, tags?, excludeBooks?, limit?}` | AI semantic search with the **active** model config: Python `/api/materials/expand` (query → keywords/tags/categories) → SQL prefilter (whole library if ≤150 items, else LIKE on expansions, cap 150) → Python `/api/materials/rerank` (score 0–100 + reason) |
| `GET /api/material/{id}` · `POST /save` (no id = create, source `manual`) · `POST /{id}/delete` · `POST /use {ids}` | Detail / CRUD / usage counter when applied to a workspace |
| `GET /api/material/candidates?status=PENDING&extractId=` · `GET /candidates/count` · `POST /candidates/save {items:[{id, ...edits}]}` · `POST /candidates/ignore {ids}` | Candidate inbox; `duplicateOf` flags a same-category same-title material already in the library |

- Categories (fixed codes, keep in sync with `python-service/app/materials.py` and `frontend/src/api/material.js`): `world` 世界观, `faction` 势力, `character` 角色, `monster` 怪物, `location` 地点, `item` 物品功法, `plot` 情节. `subtype` is free text.
- Tables (`sql/material.sql`, also in `init.sql`): `material` (`attributes` / `tags` / `source` are JSON text via `JacksonTypeHandler`, entity needs `autoResultMap = true`), `material_tag` (tag index, rewritten on every save), `material_candidate` (`payload` JSON, unique `(extract_id, candidate_key)`).
- Tag filters resolve material ids with a parameterized query on `material_tag` — never build SQL strings from user tags (`inSql`).
- **Source book & 保留**: `material.source_book` = `MaterialService.bookOf(fileName)` (extension, 书名号, site tags like `[lunarora.com]` and copy suffixes like ` (1)` stripped, so re-uploads group together); editable in `MaterialEditor` (empty = manual). `pinned` materials survive 「按来源书删除」 and stay usable when their book is blocked. Blocking is per AI request (`excludeBooks`), remembered per workspace in localStorage (`components/material/blockedBooks.js`, shared by AI 构思 and AI 填写设置, `BlockedBooksSelect`). Existing DBs get both columns from `config/SchemaMigrations` (runs after `spring.sql.init`, checks `PRAGMA table_info`, backfills `source_book` from `source.fileName`).
- Extraction: `POST /api/novel/extract/{fileId}` takes optional `{materials: {enabled, categories, maxPerChunk, focus, maxCandidates}}`; on success `NovelExtractService` calls `MaterialService.createCandidates(...)` → `CandidateStats(created, duplicates)`: candidates whose category + normalized title (`normTitle`, same rule as Python `_norm_title`) already exist among the **same book's** (`bookOf(fileName)`) PENDING candidates or saved materials (`source_book`) are skipped. The task message says how many await confirmation, how many duplicates were skipped, and — when `materialsTotal` > kept — that the limit truncated the list; `candidate_count` = candidates actually created.

### Novel crawl API (`NovelCrawlController`, `/api/novel/crawl/**`)

Fetches web novels and stores them as normal **txt files in file management**, so they can be extracted like uploads. Re-implementation of the idea in `copybook/` (scrapy spider for the now-dead quanshuwang.com: hardcoded XPath, whole-site crawl, writes Django's sqlite): configurable rules, rate-limited, Java is the only DB writer. **Two modes**, chosen by `options.mode` (default `book`) and surfaced as a switch on the crawl page:

- **`book`** — one table-of-contents URL → one txt (the original behaviour).
- **`site`** (UI: 全自动) — the book list comes from a **site catalog** built with an AI-learned rule (see *Auto crawler* below); Java crawls **one book at a time** through the same single-book pipeline, so each novel becomes its own txt (`novel_crawl_book` rows). One Java task, N Python jobs. (The old copybook-style `/discover` endpoint was removed; old site tasks still retry / resume from their stored book list.)

| Method & path | Purpose |
|---------------|---------|
| `GET  /api/novel/crawl/presets` | Rule presets from Python (`auto` heuristics, `biquge`, `wikisource`, `quanshuwang` = copybook's original XPath incl. its category/book/list-next/TOC links) |
| `POST /api/novel/crawl/preview {url, preset?, rule?, delayMs?, respectRobots?}` | book mode, sync: parse TOC (+ pagination) and test-fetch chapter 1 → `{bookName, author, intro, chapters[{title,url}], chapterCount, tocPages, preset, rule, sample}` |
| `POST /api/novel/crawl/submit {…}` | Async task (QUEUED), dispatches on `mode`; options whitelisted and stored as JSON in `options` |
| `POST /api/novel/crawl/site/submit {url (site home), preset: learned:<ruleId>, delayMs?, respectRobots?, maxChaptersPerBook?, books[{tocUrl, bookName?, author?, category?}]}` | Async **site** task (books picked from a site catalog); a book list with at least one `tocUrl` is required |
| `GET /workspaces` · `GET /workspaces/books?home=&status=&keyword=&source=book\|site&page=&size=` · `POST /workspaces/cancel\|resume\|delete {home}` | **抓取进度** — all crawl tasks (single-book **and** site) grouped by home URL (`homeOf` = `scheme://host[:port]/`), one workspace per home: `[{homeUrl, host, siteName (crawl_site name → rule siteName → host), status RUNNING\|IDLE, activeTaskId, taskCount, sources{book, site}, resumable, words, books{total, queued, running, succeeded, failed, cancelled}, current{bookName, source, message (「抓取第 i/n 章：标题」), chapterDone, chapterTotal, progress}}]`. `books` = unified rows (`progressRows`, filtered / sorted / paged in memory: RUNNING first, then newest): one per site-task book (`source: site`, `bookId`) and one per single-book task (`source: book`, carries `task` = the decorated task incl. `options` for 继续 / 重抓 / 改参数) → `{key, source, crawlId, bookName, author, category, url, status, progress, message, chapterDone, chapterTotal, chapterFailed, wordCount, fileId, createTime, updateTime}`. cancel = every QUEUED/RUNNING task of the home → `{cancelled}`; resume = every resumable task (single-book FAILED/CANCELLED, site task with unsucceeded books; oldest first, they queue in the home's lane) → `{resumed}`; delete = all finished tasks of the home (txt kept). **Submitting a site task for a home that already has a QUEUED/RUNNING site task appends the new books to it** (`joinActiveWorkspace`, tocUrls already in the task skipped, `message` 「已加入…新增 N 本」); `runSite` picks the next book dynamically (`nextSiteBook`) and finishes under `workspaceLock`, so a join never lands on a finished task |
| `GET /list?page=&size=&status=&mode=book\|site` · `POST /delete {ids}` · `GET /{id}` · `GET /{id}/books` · `POST /{id}/cancel` · `POST /{id}/retry` | Tasks, paged newest first (`status` empty = all, `ACTIVE` = QUEUED + RUNNING) → `{records, total, page, size, active}` (`active` = running tasks overall, drives polling). `delete` removes finished tasks only (running ones are `skipped`) with their `novel_crawl_book` rows and Python checkpoints (`c<id>`, `c<id>b<bookId>` via `/api/crawl/checkpoints/{key}/delete`; failures counted in `checkpointErrors`); saved txt files stay. `books` = per-book detail (site only); retry = new task from scratch with the stored options (site retries the **stored book list**) |
| `GET /sites` · `POST /sites/save {id?, url, name?, note?}` · `POST /sites/{id}/delete` | 小说网站 (`CrawlSiteService`, table `crawl_site`, `sql/crawl_site.sql`, unique `home_url`): any in-site URL is normalised to its home page `scheme://host[:port]/` (lower-case, default port dropped); saving the same home updates that row (name kept when blank); a non-home URL is kept as `sample_url` (the AI 解析 entry). The list is decorated with `rule` (best matching rule by host incl. `www.`/`m.`/`wap.`: CONFIRMED > PENDING > FAILED → `{id, status, siteName, mastered, total, error}`) and `catalog` (`crawl_site_catalog` by home: `{id, decision, status, bookCount}`). Deleting a site never touches rules / catalogs |
| `GET /saved-urls` · `POST /saved-urls/save {id?, url, name?, mode?: book\|site, note?}` · `POST /saved-urls/{id}/use` · `POST /saved-urls/{id}/delete` | 常用地址: user-bookmarked crawlable URLs (table `crawl_saved_url`, unique `url`; saving an existing url updates it; `use` bumps `use_count` / `last_used_time`, list = recently used first) |
| `POST /ai/analyze {url, maxAttempts?(1–10), delayMs?, respectRobots?, hint?, useKnown?}` · `GET /ai/jobs/{jobId}` · `POST /ai/jobs/{jobId}/cancel` | AI 解析地址 (`CrawlRuleService`, active verified model; Python `/api/crawl/ai/jobs`): tries the host's **confirmed** rule, then presets / heuristics, then LLM-written XPath, each a real trial crawl (TOC + 2 chapters). After the book works, `ai_rules._explore` maps the **site structure** from the root (`homeUrl` = `scheme://host/`): 站点首页 / **站内搜索** (`_probe_search`: `parser.find_search_forms` picks real `<form>`s with a text input — login forms skipped, hidden / select / named-button fields kept — then `Fetcher.submit_form` submits the analysed book's name GET or POST, URL-encoded in the page charset (GBK sites get GBK bytes); ok = the results contain the book or jump straight to it, partial = submitted but not found, failed = robots / blocked / 限频 / 验证码 / 登录 prompts, na = no form; the learned method is saved as `siteMap.search {action, method, field, params, charset, pattern, testKeyword, works}`) / 分类页 / 书籍页 (same-format book links found on home + first category) / 目录页 (relation to the book page) / 目录分页 / 章节页 (share of chapter URLs matching the template) / 正文分页 / 书名作者简介 / **换一本书验证** (another book crawled with the same rule), each `{status: ok\|partial\|failed\|na\|skipped, pattern, example, detail}` → `result.siteMap {homeUrl, items, mastered, failed, total, otherBooks, categories, search, homeLinks}`; **`homeLinks`** (`ai_rules.home_link_rules`, home-centred) = every `<a>` on the home page grouped by role (分类导航 / 书籍 by the book-URL pattern / 章节 / 列表分页 / 站内其他 / 站外 / 脚本链接) + URL pattern (`url_pattern`, digits → `{n}`, last segment → `{slug}` keeping the extension) → `{total, groups[{role, label, pattern, count, textRule (length range, common prefix / suffix, 「第N章」 format, truncated 「…」, image links), areas, examples[{text, url}]}]}`, also fed to the LLM summary and shown by `components/crawl/HomeLinksView.vue` (解析详情 tab 首页链接规律 + the live AI 解析 result); the LLM summary is told what was / wasn't mastered. Java watches the job in the background and on success saves the rule as **PENDING** (`savedRuleId` on the job) with `home_url` + `site_map`; a **failed** job is saved as a **FAILED** record (`error`, never applied, can't be confirmed, no rule file). Both store `attempt_log` = `{attempts[strategy, ok, error, reason, tocUrl, rule, chapterCount, sampleChars, tokens, seconds], usage, message, sample, chapterTitles}` |
| `GET /rules?status=PENDING\|CONFIRMED\|FAILED` · `POST /rules/{id}/confirm` · `POST /rules/{id}/reject` (pending or failed) · `POST /rules/{id}/delete` | 解析管理 (pending first, then confirmed, failed). Table `crawl_site_rule` (`sql/crawl_site_rule.sql`, also in `init.sql`): per host at most one CONFIRMED + one PENDING (a new success overwrites the pending one); confirm replaces the host's confirmed rule, reject deletes a pending one. **Only CONFIRMED rules are auto-applied** (`preset` empty + host match, ignoring `www.`/`m.`/`wap.`); `preset: learned:<id>` uses any rule explicitly (incl. pending = 试用). Each rule is mirrored to `data/crawl-rules/<host>_<id>.json` (`ruleFile`, DB is authoritative; missing files rewritten at startup). Old DBs: `SchemaMigrations` adds `status` (DEFAULT CONFIRMED) / `confirm_time` / `home_url` / `site_map` (JSON, `JacksonTypeHandler`) and drops the old unique index `uk_crawl_site_rule_host` |
| `POST /{id}/resume {newOrigin?}` · `GET /{id}/checkpoint` | **Resume the same task from its checkpoint** (FAILED / CANCELLED / interrupted, or a site task with unfinished books): fetched chapters are reused, site mode skips SUCCEEDED books. `newOrigin` (`http(s)://host[:port]`) rewrites the task URL, stored book TOC URLs and the checkpoint's chapter URLs when the site moved domain / IP. `checkpoint` → `{chapterSaved, chapterTotal, booksWithCheckpoint, booksPending, url}` |

- `rule` = XPath overrides; non-empty fields override the preset, empty → heuristics. Site fields (catalog scans): `categoryLinks`, `bookLinks`, `listNext`, `tocLink`; book fields: `bookName`, `author`, `intro`, `tags` (catalog only; default = `og:novel:category/status`, tag-like class blocks, 「标签 / 类别 / 状态：」 text), `chapterLinks`, `tocNext`, `content`, `contentNext`, `encoding`, `removePatterns[]`.

**Auto crawler / site catalogs** (`CrawlCatalogController` + `CrawlCatalogService`, `/api/novel/crawl/catalogs/**`). Based on an AI-learned rule (`crawl_site_rule`: `homeUrl`, `sampleUrl`, `rule`, `siteMap.categories`), one catalog per site home URL:
1. **测试** (`phase: test`, default 8 books, 3 first-chapter samples): Python `catalog.py` reads the home page, finds books on home + category list pages (with pagination) by the **book-URL pattern** of the learned sample (`ai_rules.path_regex`; falls back to `bookLinks` / list-page heuristics), then per book: detail page → name / author / intro / tags / TOC link → TOC (≤ `tocPages`), and test-fetches the first chapter of the first N books → report `{verdict: usable|partial|unusable, summary, problems[], counts, rates, categoriesVisited, bookPattern}`.
2. User decides (`decision`: PENDING → USED / REJECTED).
3. **USED**: 扩充 (`phase: scan`, skips `knownUrls` already in the catalog unless `refresh: true` = 「重新采集已有的书」, which re-reads existing books and updates name / author / category / intro / tags, AI tags kept; `tocMode` = **`async`** (default: only book pages first — name / author / intro / tags + TOC URL, `tocSkipped` — then the **same job** fills every skipped TOC (`tocAsync`), streamed to Java as `tocUpdates`) / `sync` (each book's TOC fetched right away) / `skip` (= old quick mode, `tocPages: 0`; TOC parsed when the book is crawled). A skipped TOC never overwrites a TOC the row already has (`saveBooks` `keepToc`)). **补全目录** (`phase: toc`, optional `bookIds`): fills TOCs of books with `toc_ok = 0` and a `toc_url` (none → 400). Same-site requests share one `delayMs`, so async doesn't shorten the total — the book list just appears first, filter, pick books → `site/submit`. Speed is bounded by `delayMs` (≥300 ms, default 1000) × requests per book — TOCs go straight to files and books are pulled incrementally, so memory is not the limit.

| Method & path | Purpose |
|---------------|---------|
| `GET /catalogs` · `GET /catalogs/{id}` · `POST /catalogs/{id}/cancel` · `POST /catalogs/{id}/decide {decision}` · `POST /catalogs/{id}/delete` | Catalogs (`rule` = summary of the learned rule); status IDLE/RUNNING/SUCCEEDED/FAILED/CANCELLED, `report` = last **test** report, `lastReport` = last run. Delete removes rows + `data/<catalogDir>/` |
| `POST /catalogs/start {ruleId, phase: test\|scan\|toc, maxBooks?, maxCategories?, maxListPages?, contentSamples?, tocPages?, tocMode?: async\|sync\|skip, bookIds? (toc), refresh?, delayMs?, respectRobots?}` | Python `POST /api/crawl/catalog/jobs`; Java watches it in the background (`GET …?since=N&tocSince=M`, books saved incrementally, upsert by `(catalog_id, book_url)`, AI tags kept; `tocUpdates` written back by `saveTocUpdates`). Book rows carry `tocPending` (not stored) = catalog RUNNING and the row has no TOC / error yet; `GET /catalogs/{id}/tags` also returns `tocMissing` |
| `GET /catalogs/{id}/books?keyword=&author=&tagKeyword=&category=&tags=a,b&tagMode=any\|all&usable=&page=&size=` | `CrawlCatalogService.BookFilter`: 书名 / 作者 LIKE (keyword: space = AND), `tagKeyword` = 类型 (any word LIKE inside site tags / AI tags / category, so 「修仙」 also hits 「修仙流」), tags match site or AI tags exactly (`"tag"` quoted LIKE on the JSON); each row has `crawl {status, fileId, crawlId}` = latest `novel_crawl_book` with the same `toc_url` |
| `GET /catalogs/{id}/tags` · `GET /catalogs/books/{bookId}/toc` | Tag cloud `{tags[{tag, count, site, ai}], categories, total, aiTagged}`; full saved TOC |
| `POST /catalogs/{id}/plot-tags {query}` · `POST /catalogs/{id}/intro-match {query, filter?, threshold?(50), estimate?}` · `POST /catalogs/{id}/ai-tags {limit?, retag?}` | 具体情节 search, active model. **plot-tags** (cheap, 1 call): Python `/api/crawl/catalog/plot-tags` picks only **existing** tags (vocabulary ≤600, rewritten tags mapped back by containment) → `{tags, suggested (not in catalog), reason, usage}`; the UI then filters by those tags (任一, chips removable). **intro-match** (expensive): every book's intro (≤300 chars) read by the model, 25 per call, parallel up to the config's `concurrency`, ≤1000 books; `filter` = current list filter (same `BookFilter`) to save tokens; `estimate: true` returns `{books, matched, batches, promptTokens, completionTokens, model, modelId}` without calling the model (UI confirms with a cost estimate from `utils/modelPricing.js`); result `{results[book + score + reason] ≥ threshold, analyzed, batches, failedBatches, errors, usage}` (a failed batch doesn't fail the search; fatal config errors do). Java uses a 15-min client for it. AI tags: `/catalog/tag`, 20 books per call, stored in `ai_tags` |

- Tables `crawl_site_catalog` (`sql/crawl_site_catalog.sql`, unique `home_url`; `catalog_dir` = `site-catalog/<host>[_port]`) and `crawl_catalog_book` (`sql/crawl_catalog_book.sql`; `tags` / `ai_tags` JSON, `toc_path`, `toc_ok`, `content_ok`), both in `init.sql`. **Body text is never stored** — only intro / tags / TOC: Python writes `data/<catalogDir>/toc/<sha1(bookUrl)[:16]>.json`, Java exports `data/<catalogDir>/catalog.json` after each run / decision. RUNNING catalogs are marked FAILED at startup (saved books kept).
- Tables: `novel_crawl` (`sql/novel_crawl.sql`, also in `init.sql`): `id`, `url`, `preset`, `options`, `book_name`, `author`, `status` (QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED), `progress`, `message`, `job_id`, `chapter_total/done/failed`, `word_count`, `file_id`, times. `novel_crawl_book` (`sql/novel_crawl_book.sql`, also in `init.sql`): one row per book of a site task — `crawl_id`, `book_name`, `author`, `category`, `toc_url`, `status`, `progress`, `message`, `job_id`, `chapter_total/done/failed`, `word_count`, `file_id`, times. Full text is never stored in the DB. **Existing DBs need no migration**: the site table is created by `CREATE TABLE IF NOT EXISTS`, and `mode` lives in `options` (crawled rows without it are treated as `book`), with `book_total/done/failed` computed from the child table and exposed as entity fields via `@TableField(exist = false)`.
- **Checkpoints**: every Python job gets a `resumeKey` (`c<taskId>` book mode, `c<taskId>b<bookId>` per site book); Python appends each fetched chapter to `data/crawl-cache/<key>/` and removes it only after Java saved the txt (`release`). Restart / Python crash / cancel / network loss keep it, and the task message says it can be resumed. Resuming a key whose job is still running in Python (Java restarted) adopts that job instead of starting a second one.
- 常用地址 defaults: `CrawlSavedUrlService.DEFAULTS` (biquh.com / xinbiqug.com sample books) are inserted once per data dir at startup (marker line `crawl-saved-urls-v1` in `data/.defaults-applied`), so new users have them and a user's deletion sticks; change the marker version when the list changes.
- `NovelCrawlService` runs tasks in **per-home lanes** (`enqueue` / `laneBusy`, key = `homeOf(url)`): tasks of the same home page — single-book and 整站 alike — run one after another (a waiting task's message says 「同一网站（host）还有任务在抓」), different homes run in parallel on a cached pool. Each task submits to Python `POST /api/crawl/jobs`, polls every 3 s, on success downloads `GET /api/crawl/jobs/{id}/text` → `FileService.saveBytes("<书名>.txt")` → `file_id`, then `POST /api/crawl/jobs/{id}/release`. Site mode repeats that per book, aggregating chapter/word counts and progress (`bookDone/bookTotal`); cancel sets a flag, cancels the in-flight Python job, and marks not-yet-started books CANCELLED. Python 4xx messages are passed through as 400 (no API key involved).

### File storage rules

- Root dir from `file.storage.path` in `application.yml` (`${app.data-dir}/upload`, i.e. `data/upload/`). Uploads are written to `<name>.part` then atomically renamed; if the DB insert fails the file is deleted. `read()` rejects storage paths that resolve outside the upload root.
- Stored filename = **UUID without dashes** + lowercased extension; date-partitioned as `yyyy/MM/dd/`.
- DB stores only the **relative** `storage_path`; always resolve against the configured root and normalize paths (path-traversal safe).
- Upload limit: 50 MB per file / per request (see `application.yml`).
- **Database (SQLite)**: `jdbc:sqlite:${app.data-dir}/nan_novel.db` (WAL, `busy_timeout=10000`, Hikari pool 4). Only Java opens it. `app.data-dir` = `DATA_DIR` or auto-detected `<repo>/data` (`DataDirEnvironmentPostProcessor`); `common/DataPaths` resolves and traversal-checks paths under it. LocalDateTime is stored as text `yyyy-MM-dd HH:mm:ss` (`LocalDateTimeTextTypeHandler`); booleans as 0/1; no foreign keys (logical links only, handled in code). Pagination dialect `DbType.SQLITE`. Tables are auto-created at startup from the per-table scripts; `sqlite3 data/nan_novel.db < backend/src/main/resources/sql/init.sql` creates them manually. **Store metadata only** — large content (novel text, full extraction results) goes into files under `data/`. **When adding or changing a table, update both its per-table script and `init.sql`.**
- `file` table columns, derived from `FileInfo`: `id` (auto increment), `file_name`, `storage_path`, `file_size`, `content_type`, `file_ext`, `chapter_count`, `create_time`. `chapter_count` (txt/md only; `service/ChapterCounter` = same heading rules as Python `text_loader.split_chapters`, headings without body not counted; 0 = no chapters found, -1 = unreadable, NULL = not counted / docx·pdf) is set on save; old rows are backfilled in a background thread at startup (`FileService.backfillChapterCounts`, column added by `SchemaMigrations`). 文件管理 shows it under each card (「N 章」) together with an 「已提取」 badge (extract tasks matched by `bookOf(fileName)`, display only — re-extraction is allowed).

### Novel generation API (`NovelGenController`, `/api/novel/gen/**`)

Only the generation calls that need the **API model's key** or the **material library** go through Java; everything else under `/api/gen/**` is called by the frontend directly.

| Method & path | Purpose |
|---------------|---------|
| `POST /api/novel/gen/{novelId}/chapters {goal, title?, targetChars?, polish?{enabled, baseId, adapterId}}` | 大模型 workspace: attaches the active verified config (`requireActive`, none → 400) as `api` and forwards to Python `/api/gen/novels/{id}/chapters`; returns the Python job |
| `POST /api/novel/gen/{novelId}/ideas {kind: title\|outline\|chapter\|fill\|direction\|hint_polish\|chat, source?: api\|local, baseId?, adapterId?, hint?, tone?, rejected?[], chosenDirections?[], chapterContext?{current, past}, count?, purpose?, materialIds?[], autoMaterials?, query?, excludeBooks?[], fill?, chat?, spec?}` | AI 构思. `direction` = 构思方向 suggestions `{directions[{label, direction}]}` (seeded by `hint`, `purpose` says what they are for); `hint_polish` = expand the author's 构思方向 (`hint` only — no settings / chapters / materials) into a full 构思 → `{text, changes}`; `chat` = character roleplay `{reply}`. `excludeBooks` drops blocked books' materials from both picked and auto-matched ones (pinned kept; `blockedMaterials` = how many picked were dropped). Java loads the picked materials (`MaterialService.listByIds`, ≤ 20) and, with `autoMaterials`, adds `semanticSearch(query or hint)` results scoring ≥ 50 (always uses the API model). `source=api` attaches the config; `local` forwards `{baseId, adapterId}` instead. Returns `{kind, nextIndex, result, usage, model, usedMaterials[{id, category, title, score, reason, auto}]}` — suggestions only, nothing saved |

- Fields are whitelisted before forwarding. Python's 422 bodies echo the request (incl. the key): `NovelGenService.pythonMessage` passes through only our own `{message}` and never logs response bodies.

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
- Routes are lazy-loaded (`() => import(...)`) with `meta.title` / `meta.icon` consumed by the sidebar; register new pages in `src/router/index.js`. A menu entry with `meta.children: [{path, title, icon}]` renders as an `el-sub-menu` (`layout/Sidebar.vue`); the parent route only redirects (e.g. 小说抓取 → `/novel/crawl/config`).
- Element Plus and all its icons are registered globally in `main.js`.
- Layout: `.app-wrapper` is fixed to one screen (`height: 100vh; overflow: hidden`); only `.app-main` scrolls, so the sidebar stays put. Scroll-to-top must target `.app-main`, not `window`.

### Novel settings editor (`SettingsEditor.vue`, used inside each workspace)

- **Schema-driven**: everything renders from data — `categories[] → fields[] → options[] → children(fields[])`, nestable to any depth. Field types live in `src/novel-options/fieldTypes.js` (`single`, `multi`, `text`, `textarea`, `number`, `slider`, `tags`, `group`); to add a type, register it there and map it in `OptionField.vue`.
- **Data source**: `src/api/novelOptions.js#getOptionSchema()` currently returns `src/mock/novelOptionSchema.js` (built-in categories 世界观/角色/情节推进/文风, `elementTemplates` such as 怪物/势力/种族/地点/物品/功法, `genericSuggestions`). When the DB exists, switch only this function to a backend call returning the same shape.
- **Values**: `{ [categoryKey]: { [fieldKey]: value } }`; choice value `{ selected: string[], sub: { [optionValue]: childValues } }`, group value `[{ _id, ...childValues }]`.
- **Extensibility (编辑模式)**: users can add custom options inline, add fields to any category / group / option (from suggestions or self-defined), and create custom elements (e.g. 怪物) from a template or blank. User-created items carry `custom: true` and `uid()` keys.
- **Confirmed vs default**: `number` / `slider` fields always hold a value, so they count only after the user changes them (`markTouched` → `container.__touched[fieldKey]`); untouched defaults never reach `buildSpec()` and therefore never become generation constraints.
- **角色卡** (`characters.cast` has `display: 'characterCards'` → `CharacterCards.vue`): character.ai-style cards (avatar, 一句话人设, role / gender / age, collapsed preview of personality / speech / greeting), fields paged by `section` (基本信息 / 性格与说话 / 内心 / 经历与能力 / 其他). 「AI 创建角色」 from a one-line concept (`genItems(..., concept)`), 「AI 补全」 one card (`ai.fillItem`), 「试聊」 (`CharacterChat.vue`, `kind: chat`; greeting opens the chat, optional scene / user role, regenerate, 「存为示例对话」 appends to the card's 示例对话). Saved configs carry `schemaVersion`; `schema.js#upgradeConfig` adds new built-in group sub-fields to older workspaces once.
- **AI 填写** (when the workspace passes `novel-id` + `ai`): text / textarea fields have two buttons — 「AI 润色」 (`fill.action: polish`, `seed` = the box text, required: keep everything written and expand it, textarea ~2–3× up to 400 chars) and 「AI 生成」 (`action: generate`, `seed` = optional rough direction, writes new content) — explained in hover titles and in `AiFillSettings`; tags only have 「AI 生成」; **single / multi fields have no header AI button** (picking an existing option was useless) — their AI lives in `ChoiceWidget`'s 「自定义」 panel: option name input + optional description (shown as the option tooltip) + 「选素材」 (`MaterialPicker` pick-only; these materials apply **only** to this custom option: sent as the request's `materialIds` with `autoMaterials: false`, the 「AI 填写设置」 materials are not used) + 「AI 润色」 / 「AI 生成」, both enabled only when the input has text or materials are picked → `ai.customOption` → `fill {mode: option, action, seed}` → Python `_custom_option` returns a draft `{option: {label (≤12 chars asked), desc}}` the author edits, then 「添加并选中」, 「AI 生成 N 个{itemLabel}」on groups (e.g. 关键情节节点 with 节点名称 / 所处阶段 / 情节描述), 「AI 补全本分类」for the unfilled fields of a category. Number / slider fields are generation parameters and never AI-filled. Shared settings in the header popover `AiFillSettings.vue` (model: 大模型 / 本地 + adapter, 补充要求 with 「AI 给几个方向」, materials picked or AI-matched, blocked source books). Requests go to Java `/api/novel/gen/{id}/ideas` with `kind: fill` and `fill {mode: field|items|category|option, path, fields (schema + option labels), current (filled siblings), itemLabel, count, existing}` plus the editor's **unsaved** `spec`. `novel-options/aiFill.js#applyValue` writes results back (choice labels → option values; unknown labels become custom options via `addOption`). Concurrency (`aiRunning` key → scope path, `ai.loading(key)` / `ai.locked(scope)`): **local model = one request at a time** (one model on the GPU, generation serialised); **API model = parallel**, only buttons whose scope overlaps a running one are locked (`aiFill.scopesOverlap`: one path is a prefix of the other — e.g. 「AI 补全」 on a character card locks that card's fields and 补全本分类 of 角色, not other cards; new-item generation uses `[...group, NEW_ITEMS]` so it doesn't block existing items). Overwriting a filled choice / tags field asks first; text writes show a notification with 「撤销」.
- **Output**: `buildSpec()` → `[{key,label,type,value,display,children}]` (`type: 'option'` for sub-option containers, `'groupItem'` + `name` for group entries) is what the workspace saves as `settings.spec` and the backend turns into constraints; `getConfig()` (`{categories, values}`) is saved as `settings.config` to restore the editor.

### Novel workspaces (`/novel/create` → `/novel/workspace/:id`)

- **Model sources** everywhere AI is used (workspace, AI 构思, polishing): `api` = 大模型 (Java「模型配置」active + VERIFIED config, auto-detected via `/api/ai/model/list`; none → prompt with a link to 模型配置), `local` = 本地模型 (base + optional LoRA adapter), `remote` = 远程模型 (remote GPU base + adapter) — **reserved**, shown disabled「即将支持」and rejected by the backend.
- List page creates a workspace with just a title and context window (8192 / 32768); the model is **not** chosen there — it defaults to the configured 大模型, else the default local model (Qwen2.5-1.5B-Instruct), and is switched freely inside the workspace. It shows the default-model check with a one-click download (`/api/local/models/download` → `models/base/<id>/weights/`) and Hugging Face / hf-mirror links.
- **Using materials**: `SettingsEditor` → 「从素材库添加」 opens `MaterialPicker` (category / keyword / tag filters, preview of where each item goes). `novel-options/materialApply.js#APPLY_TARGETS` maps categories to settings (monster/faction/location/item → custom element from template, auto-created if missing → its list; character → 角色·主要角色; plot → 情节推进·关键情节节点; world → 世界观补充). Applying **copies** the data (later library edits don't change the story); group items get `_fromMaterial` (shown as「来自素材库」, never exported by `buildSpec`), unmapped attributes go into an added 备注 field.
- Workspace header switches the model source (大模型 / 本地模型) at any time, also after chapters exist (each chapter records the model that wrote it), and, for local, the base model (clears the adapter). It also has an adapter select (only adapters with `compat: ok` and `matchedBaseId` = the base) (saved as `model.adapterId`; 「加载模型」 then loads base + adapter, or only switches the adapter when the same base is resident). `modelReady` requires the loaded `adapterId` to equal the workspace's.
- Workspace page: 设定 tab = `SettingsEditor` (保存设定), **AI 构思** tab = `components/novel/IdeaPanel.vue`, 写作 tab = chapter list, next-chapter form (title, goal, target chars, 润色), 预览上下文, live segmented generation with cancel, per-call token table, workspace totals. Unsaved settings are saved automatically before preview/generation.
- **AI 构思** (`IdeaPanel`): a 「使用说明」 popover (top right, `MANUAL_COLS` / `MANUAL_ROWS` — keep in sync with what each request sends) lists which inputs every AI action uses. Inputs: model (大模型 / 本地模型 + adapter); **设定** categories (every category of the settings editor incl. custom elements, re-read via the workspace's `readSettings()` each time the tab opens; none selected by default, remembered in localStorage `nan_novel.ideaSettings.<id>`; requests send `spec` = the editor's current spec filtered to the selected categories, empty categories never sent, nothing selected → `spec: []`); **章节** 当前章节 (latest chapter: summary + last 400 chars) / 过去章节 (older summaries + 前情概要), default off, remembered in `nan_novel.ideaChapters.<id>`, sent as `chapterContext {current, past}` (absent = both, for AI 填写; `kind: chapter` always gets both); **基调** (`tone`, ≤200 chars); **构思方向** (`hint`, ≤3000 chars) with an in-box 「AI 润色」 button = `kind: hint_polish`, which sends **only** the box text (no settings / tone / chapters / materials) and expands the rough plot into a full 300–1500-char 构思 → `{text, changes}` shown with 替换原文 / 放弃; **后续走向** 「AI 构思后续走向」 (`kind: direction`, 5 per click, appended so it can be repeated; uses hint + tone + selected settings / chapters + adopted outline, materials only with the 「参考素材库」 switch (default off); everything already shown plus rejected ones go in `rejected[]` (≤30) so new ones differ) — each card 支持 (choose only this) / 追加 (choose as well) / 拒绝 (remove + avoid), unchosen ones are never used; the chosen texts go as `chosenDirections[]` (≤10) with 生成书名 / 生成大纲 / 生成第 N 章题目 (prompt: 「作者选定的后续走向（必须沿着这些走向展开）」); materials, blocked source books (`MaterialPicker` with `pick-only`, and/or「AI 自动匹配素材」which needs the API model; query = 基调 + 构思方向, ≤500 chars). Titles → 采用 updates the title; chapter options → fill the 写作 form; the outline is an editable draft until「采用大纲」saves it as `novel.outline`. With an outline, the next chapter's title/goal are filled in automatically (「按大纲填入」).
- **Everything AI-generated is hand-editable**: chapters (「修改本章」: title / goal / summary / body), 前情概要 (「修改」 next to it), AI 构思 title / chapter suggestions (inline inputs before 采用), outline drafts, AI-filled settings (ordinary fields), material candidates (`CandidateReview`) and saved materials (`MaterialEditor`), extraction results (小说提取 drawer →「修改结果」: style, characters, per-chapter title / summary / characters / events / foreshadowing).
- **润色** (polish): 不润色 / 本地 QLoRA (base + adapter) / 远程 QLoRA (reserved). After generation, or「用本地模型润色」on a finished chapter; the chapter view toggles 润色后 / 原文 and can 恢复原文.

### Web novel crawl page (`/novel/crawl` → `views/novel/crawl.vue`)

- **Four sub-pages** (sidebar 小说抓取 submenu; route `/novel/crawl/:tab(config|book|auto|progress)` (old `tasks` / `workspace` redirect to `progress``, all the same keep-alive `crawl.vue` instance showing one section with `v-show`, so AI jobs / polling / drafts survive switching; `goSection(tab)`, `openConfig(configTab)`, `setMode('book'|'site')`):
  1. **抓取配置** (`config`): tabs 小说网站 (site blocks spaced apart: name, home URL, 样例书, 站点规律 / 书目 status, AI 解析 / 全自动 / 解析详情 / 修改 / 删除; 「新增地址」 dialog previews the normalised home; empty → 「目前没有指定网站地址」) / 常用地址 / AI 解析地址 / 解析管理 / 抓取设置 (请求间隔 + robots, shared by all sub-pages);
  2. **单本抓取** (`book`): the original flow (目录页地址 → 解析目录 → 试抓首章样本 → 选范围 → 开始抓取), XPath 高级选项, a one-line 请求设置 summary linking to 抓取设置;
  3. **全自动抓取** (`auto`) = `components/crawl/AutoCrawlPanel.vue`;
  4. **抓取进度** (`progress`) = `components/crawl/WorkspacePanel.vue` (the former 整本抓取进度 + 整站工作区, merged): one workspace per home page holding both single-book and site crawls — cards on the left (status, progress, 正在抓《X》 + chapter), detail on the right (单本 / 整站 submission counts, stats, live 「正在抓《X》：第 i/n 章 · 章节名」 banner, table with **来源** (单本抓取 / 整站抓取) / status / chapter progress / message / words, filters status + 来源 + 书名, paging; workspace actions 取消抓取 / 继续未完成的 / 删除工作区; single-book rows also have 取消 / 继续 (crawl.vue's resume dialog, optional new site address) / 更多 → 从头重抓 · 改参数 · 删除; 小说提取 on finished rows); polls every 3 s only while visible and running. Submitting a single-book or 全自动 crawl jumps here on that home's workspace.
- **No pre-filled inputs**: 单本地址, AI 解析入口地址 / 补充说明, custom XPath and the 全自动 site rule all start empty; only explicit row actions (网站卡片 / 常用地址 / 解析管理 「AI 解析」「使用」「全自动」) carry an address or rule over. URL fields are plain inputs (no history dropdown; the old `nan_novel.crawl.recentUrls` key is deleted on load and nothing is recorded — saving an address is an explicit 常用地址 action). localStorage keeps only settings (请求间隔, robots, AI 最多尝试 / 先试已学规则 / 成功后直接抓) and a **running** AI job (to keep showing progress after a refresh); finished AI results are not restored and can be 清空.
- 全自动: pick a learned rule (clearable select; confirmed first; pending = 试用; nothing preselected unless opened from a 「全自动」 action, which applies once — while empty only a prompt is shown, no steps / test form) → steps 测试规律 (test limits incl. its own 请求间隔, live progress, report with verdict / per-field rates / problems / sample books) → 是否使用 (使用 / 不使用 / 撤销) → 书目: 采集更多书目 (请求间隔, 目录 = 后台补全 (default) / 当场获取 / 不取, live time estimate split into 「书目先出来 / 目录再补」; 目录 column: 「N 章」 / 「补全中…」 (`tocPending`) / 「未取 · 补全」 (one book) / 红色「未取到」 with the reason; toolbar 「补全目录（N 本）」 = `phase: toc`), every non-obvious parameter has an ⓘ hover explanation (`HelpLabel` + `TIPS`, e.g. 分类「N 个 × M 页」 = visit up to N categories, page through up to M list pages each), one search box with a type select — 书名 / 作者 (fuzzy) / 类型 (tag fuzzy, autocompletes existing tags) / 具体情节 (radio: 「AI 选标签 · 省 token」 → tags written into the tag filter with removable chips + AI's reading + suggested tags; 「AI 读简介 · 耗 token」 → estimate + confirm (tokens and cost), optional 「只分析当前筛选出的书」, results replace the table with a 相关度 column and `TokenUsageBar`); plus filters 分类, 标签 multi-select 任一/全部, 只看目录可用 and 「AI 补标签」 (AI tags shown dashed), table with expandable intro, 目录 dialog, 抓取 status, cross-page selection (`reserve-selection`), 每本最多 N 章, 「开始抓取（已选 N 本）」 → `site/submit` with `preset: learned:<ruleId>`. 解析管理 「全自动抓取」, 地址管理 entries saved as 整站, and 改参数 on a site task open this panel on the matching rule.
- AI 解析 (now tabs of 抓取配置; the 单本 / 全自动 pages link there via 「AI 解析」) — 「AI 解析地址」 (its own 入口地址, 最多尝试, 先试已学规则 = `useKnown`, 成功后直接抓全书, 补充说明, then the live progress / attempts / tokens / result) and 「解析管理」 (待确认 / 已确认 / 解析失败 / 全部 filter + search; rows show 解析结果 (attempt N succeeded + 规律掌握, or the failure reason) and one ✓/✗ dot per attempt; **clicking a row opens `RuleDetailDialog`**: success/failure banner, stats, entry / home / TOC, tabs 每次尝试 (`AttemptTable`, shared with the analyze tab) / 站点结构 (`SiteMapView`) / 规则与地址规律 / 抓取样本, footer actions per status — pending: 确认 / 不确认 / 试用 / 全自动, confirmed: 使用 / 全自动抓取 / 删除, failed: 重新解析 / 删除记录; badge = pending count, also on the AI 解析 button). Failed records never appear in rule pickers. The page itself keeps only a one-line AI status strip. 常用地址 (tab of 抓取配置; 「常用地址」 button on 单本抓取): 添加地址 (地址 + 描述 inputs, 单本/整站), 修改, 删除, 使用 (goes to 单本 with the URL, or to 全自动 on the matching rule), **AI 解析** (prefilled); it replaced the old 常用地址 select / 收藏当前地址 / 管理 row and the local 保存目录 picker (Java still honours a stored `saveDir` on old tasks).
- `RULE_FIELDS` holds the single-book XPath fields (shown only in book mode; 全自动 uses the learned rule as is); empty fields fall back to the preset then heuristics.
- The old task table / 书籍明细 dialog are gone (everything is in 抓取进度). `GET /list` / `/{id}/books` remain for API use. 「继续」 opens the resume dialog (saved progress + optional new site address); 「从头重抓」 re-runs the stored options as a new task; 改参数 refills the 单本 form (site tasks open the 全自动 panel on their rule).
- 「AI 解析地址」 is the only crawl step that spends tokens (rule-based crawling uses none): the job carries `usage {source: api|local, model, host, calls, promptTokens, completionTokens, cacheHitTokens}` (accumulated live by `llm_client.chat(..., usage=)`; `local` = OpenAI-compatible service on localhost) and each attempt `promptTokens/completionTokens`; the panel shows it with `TokenUsageBar` (price = built-in reference or the user's override).

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

Shared data dir: `DATA_DIR` (`app/config.py`, default `<repo>/data`); Python writes only `data/novels/`, `data/crawl-cache/` (crawl checkpoints) and `data/site-catalog/<host>/toc/` (catalog TOCs). The model (base URL, key, model name, concurrency) is **not** configured here — Java sends the active config with each request and Python never stores the key. Env vars (`app/config.py`): `JAVA_BACKEND_URL`, `CHUNK_CHARS` (default 6000), `LLM_MAX_TOKENS`, `LLM_TIMEOUT`. No torch/CUDA needed for extraction.

### Novel extraction (implemented)

- `POST /api/models/verify` `{baseUrl, apiKey, model}` → `{ok, latencyMs, message, reply}`.
- `POST /api/extract/jobs` `{fileId, fileExt, model:{baseUrl, apiKey, model, concurrency}}` → job; `GET /api/extract/jobs/{jobId}` → `queued/running/succeeded/failed`, `progress`, `message`, `error`, `result`; `GET /api/health`.
- `app/llm_client.py`: OpenAI-compatible `POST {baseUrl}/chat/completions` with `Bearer` key. Friendly errors (401/403 key, 402 balance, 404 model/URL are *fatal* and abort the job; 429/5xx/timeouts retry ×2). Falls back without `response_format` if a provider rejects JSON mode. Local hosts skip the system proxy; remote hosts use it.
- Jobs are in-memory and run one at a time; Java is responsible for persisting results.
- Languages: Chinese (primary) and English novels. Analysis text is always output in Simplified Chinese; character/place names keep the original spelling.
- All `httpx` calls to local services use `trust_env=False` — a system proxy (Clash etc.) otherwise turns `localhost` requests into 502.
- **Material candidates** (`app/materials.py`): when `ExtractRequest.materials.enabled`, `prompt_fragment()` adds a `"materials"` field to each chunk's JSON (selected categories, ≤ `maxPerChunk`, optional `focus`, abstracted wording + ≤60-char excerpt; ~+600 max tokens per chunk). `merge_candidates()` dedupes by category + normalized title across chunks (attributes/tags unioned, chapters recorded), most-chapters first; the extractor keeps the first `maxCandidates` (default 500, 20–3000, set in `ExtractOptionsDialog` 「候选上限」) as `result.materials[]` with a stable `candidateId` and reports `materialsTotal`. `POST /api/materials/expand` and `/api/materials/rerank` back the semantic search (model config passed from Java, never stored).
- Pipeline: fetch bytes via Java `GET /api/file/preview/{id}` → decode (BOM → strict UTF-8 → strict GB18030 → fewest replacement chars) or parse docx/pdf → split chapters (`第X章/回/节/卷`, `Chapter 12/IV/One`, 楔子/尾声/后记/Prologue; fallback `1.标题` / `一、标题` only when ≥3 found) → chunk ≤ `CHUNK_CHARS` at paragraph boundaries → LLM JSON per chunk, `concurrency` requests in parallel (`response_format: json_object`, temperature 0.2) → merge (per-chapter summary/characters/events/foreshadowing, deduped characters, dialog ratio computed in code).

### Web novel crawler (`app/crawler/`, `/api/crawl/**`, called by Java)

- `POST /api/crawl/preview` (book), `POST /api/crawl/jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel`, `GET /jobs/{id}/text` (UTF-8 txt), `POST /jobs/{id}/release`, `GET /presets`; responses `{code, message, data}`. Jobs are in memory; different sites run in parallel (≤ `MAX_PARALLEL_SITES` 6), the same site (`scheme://netloc`) one at a time via a per-site lock (`_run_in_lane`, cancellable while waiting); ≤8 unreleased texts kept.
- **Catalog** (`catalog.py`, bounded — never the whole site): `POST /api/crawl/catalog/jobs` (`CatalogRequest`: `homeUrl`, `rule`, `sampleUrl`, `categories`, `knownUrls`, `phase`, `maxBooks` ≤500, `maxCategories`, `maxListPages`, `contentSamples`, `tocPages`, `tocAsync`, `tocTargets[{bookUrl, tocUrl, bookName}]` (phase `toc`), `catalogDir` = `site-catalog/<name>`), `GET /catalog/jobs/{id}?since=N&tocSince=M` (books after N, `booksTotal`, `tocUpdates` after M `{bookUrl, tocUrl, chapterCount, firstChapter, latestChapter, tocPages, tocPath, tocOk, error}`, `tocUpdatesTotal`, `report`; `_fill_tocs` falls back to the book page as TOC, one failed book doesn't stop it, 5 consecutive network failures do), `POST /catalog/jobs/{id}/cancel`; sync AI endpoints `POST /catalog/plot-tags`, `/catalog/intro-match`, `/catalog/tag` (model passed by Java). Books are recognised by the learned sample's URL pattern, else `bookLinks` / heuristics (retried with heuristics when the pattern finds nothing). **Name / author / category always come from the book's own page** (`parser._detail_book_name` / `_detail_author` / `_detail_category`, also used for TOC pages): `og:novel:book_name|author|category` first; otherwise name candidates (rule XPath, every h1/h2) must match the first segment of `<title>` (「书名最新章节_书名全文阅读_站名」, site name excluded), author = 「作者：」 in the title's block or the text right after it (never an earlier header / sidebar one), category = breadcrumb (`path|bread|crumb|location` class or 「当前位置」 text with `>` separators; nav bars ignored) → 「类别 / 分类：」 near the title (「玄幻小说」→「玄幻」); the list-page link text and the list category are only fallbacks (sidebars list other genres' books). A book page redirected away (home / other host / book id gone, `_redirected_away`) is an error. Book names are cleaned of SEO tails (`parser.clean_book_name`: 「…小说全文阅读顶点」「…最新章节无弹窗免费阅读」「…txt下载」; only compound tails with 阅读 / 下载 / 最新章节 / 无弹窗). Some sites put the real title in the author field — that is shown as the page states. Detail page wins over the TOC page (its `<title>` often has a「目录」suffix); `<meta name=description>` ranks after the page's intro block (it is often site-wide). 5 consecutive network failures or a TOC write error stop the job; collected books are still returned with a report.
- `fetcher.py`: anti-bot pages raise `BlockedError` with a plain reason (Cloudflare challenge = 403/429/503 + `server: cloudflare` or「Just a moment」markers; script-jump token pages = tiny 200 page with only a `location=` script and no links) — the crawler never executes or solves them; AI 解析 stops at once (no model calls). http/https only, **public addresses only** (loopback/private rejected unless `CRAWL_ALLOW_PRIVATE=1`, for local fixture tests; domains resolving into `198.18.0.0/15` are allowed — Clash fake-ip/TUN mode), non-ASCII URLs percent-encoded, robots.txt respected by default, min delay 300 ms (default 1000), retries on 5xx/network, encoding from header/meta (gbk → gb18030) else `text_loader.decode_text`. Env `CRAWL_USER_AGENT`.
- `parser.py` heuristics: chapter links = links matching `第X章/Chapter N/1.` in the container holding most of them, deduped keeping the **last** occurrence (drops the "最新章节" block); content = block with most direct text (id/class like content ×1.5); `下一页` pagination for TOC and in-chapter (`123.html → 123_2.html` only); default ad-line filters apply to lines ≤ 80 chars. Site heuristics: categories (`_guess_categories`) = groups of ≥3 short same-host links in one container, **book-pattern links excluded** (`parse_site(..., book_re)`), scored by size + 3 × category-word hits (`CATEGORY_WORDS`: 玄幻 / 武侠 / 都市 / 言情 / 历史 / 科幻 / 女频 …) × 2 when ≥60 % share a non-numeric first path segment (e.g. `/class/`) — previously the largest group won and a home-page book list was taken for the categories; book links = largest group of non-chapter links on a list page (falls back to all candidates when the page only has 1–2 books), TOC link = link text matching 开始阅读/全部章节/目录, and the detail page doubles as TOC when it already contains chapter links.
- Failed chapters get a placeholder and the job continues; 10 consecutive failures or > 50 % failed → job fails. Output txt keeps chapter titles so `text_loader.split_chapters` works.
- **Resume** (`checkpoint.py`, `CrawlRequest.resumeKey` / `newOrigin`): `meta.json` stores the chosen chapter list (so a dead TOC page does not block resuming), `chapters.jsonl` one fsynced line per fetched chapter (a torn last line is skipped; failed chapters are not stored and are retried). Network-type errors (`fetcher.NetworkError`: DNS failure, timeouts, 5xx after retries) do not count as chapter failures: the job waits `NETWORK_WAITS` (≈ 5 min, cancellable) and retries the same chapter, then fails with the checkpoint kept. `GET /api/crawl/checkpoints/{key}`, `POST /api/crawl/checkpoints/{key}/delete`.
- **Resume self-test** (no network): `.venv/Scripts/python scripts/crawl_resume_selftest.py` — cancel mid-book, restart the fake site on another port, resume with `newOrigin`, assert only missing chapters are fetched and the TOC is not.
- **Self-test** (no network): `.venv/Scripts/python scripts/crawl_site_selftest.py` builds a fake book site in a temp dir, serves it on 127.0.0.1, then asserts the AI-parse site exploration's 站内搜索 probe (GET form with a hidden field → results contain the book; a login-only form is not taken for search), a catalog test (3 categories, 分类翻页, TOC / intro / tags / content samples, TOC files, verdict `usable`), a `scan` that only adds new books, and a full single-book crawl. `.venv/Scripts/python scripts/crawl_fixture_server.py [port]` (default 8899) keeps that fake site up so the crawl page can be exercised end to end — start the AI service with `CRAWL_ALLOW_PRIVATE=1` and AI-parse `http://127.0.0.1:8899/book/jw/`, confirm, then 全自动抓取.

### Local models & style fine-tuning (`app/local/`, `/api/local/**`)

Local-only for now; remote inference/training must plug into the existing extension points (`source` on registry records, `backend` on jobs + `worker.RUNNERS[(kind, backend)]`). The frontend calls these endpoints **directly** (CORS: `CORS_ORIGINS`, default 5173/5174) — an explicit exception to "frontend → Java → Python", because model files live next to the Python service. Responses use `{code, message, data}` (code 0 = success; `LocalError` → HTTP status).

| Method & path | Purpose |
|---------------|---------|
| `GET  /api/local/system` | GPU (nvidia-smi), RAM, disk, dependency versions, inference state, active job |
| `GET  /api/local/models` · `POST /models/register {name, path}` · `POST /models/download {repoId, name, source?, targetDir?}` · `POST /models/download/check {repoId, source?, targetDir?}` · `GET /fs/dirs?path=` · `GET /models/download/sources` · `POST /models/{id}/delete` | Base models. Register = record path only (no copying); download = background job into `models/base/<id>/weights/` — or `<targetDir>/<repo name>/` (absolute, not under `%SystemRoot%`, must be empty or a previous unfinished download marked by `.nan_novel_downloading`; recorded `ownsFiles`, so deleting the record deletes those files) — then auto-register. `check` = source / size / free space of the target disk (sync, network); `fs/dirs` = read-only directory browser for the 保存位置 picker (empty path = drives). 7B (≈15 GB) is in the recommended list and defaults to a custom location. `source`: `auto` (default, tries `MODEL_DOWNLOAD_AUTO_ORDER` = modelscope → hf-mirror → huggingface, falling through on failure) / `modelscope` (HTTP API, per-file size + SHA-256 check, no `modelscope` package) / `hf-mirror` / `huggingface`; HF sources are pre-checked with `config.json` metadata because a mirror that 308-redirects to huggingface.co otherwise surfaces as `LocalEntryNotFoundError`. Env: `MODEL_DOWNLOAD_SOURCE`, `MODEL_DOWNLOAD_AUTO_ORDER`, `HF_MIRROR_ENDPOINT`, `HF_ENDPOINT`, `MODELSCOPE_ENDPOINT`; legacy `useMirror` still accepted |
| `POST /api/local/estimate {baseModelId, mode: infer\|train, quantization: 4bit\|none, maxSeqLen, batchSize, loraR, adapterId?}` | Conservative VRAM/RAM estimate → `level` ok/warn/exceed + messages. `infer` accounts for the adapter's weights and for what this service already holds: same base + quantization resident → only the adapter delta (`resident: true`); another resident model → its VRAM counts as free (unloaded before loading) |
| `GET  /api/local/adapters` · `GET /adapters/{id}` · `POST /adapters/{id}/rename` · `POST /adapters/{id}/delete` | LoRA adapters (ids must match `[A-Za-z0-9][A-Za-z0-9_-]*`, never paths); each has `compat` + `matchedBaseId` (the local base it may load on). Local adapters: ok/changed/missing vs the base id + config hash; if that base record was deleted, any registered base with the same path or config bytes matches (re-registration keeps adapters usable). Loading always requires `matchedBaseId == baseId`. Remote-trained (`source: remote`): ok only when a local base has the same config (raw or `configCanonicalHash`, CRLF-safe) **and** the same official weights fingerprint (local side computed by `registry.verify_base_weights`, cached in `model.json`), else unverified/changed/remote-only |
| `GET  /api/local/inference` · `POST /inference/load {baseId, adapterId?, quantization: auto\|4bit\|none}` · `POST /inference/unload` · `POST /inference/generate {prompt, maxNewTokens, temperature, topP, repetitionPenalty, useChatTemplate, useAdapter?, seed?}` · `POST /inference/compare {same body}` · `POST /inference/evaluate {text, maxTokens?}` | One model resident in VRAM; load is async (`idle/loading/loaded/error`). Same base + quantization already loaded → `load` only enables/disables/attaches the adapter (`switched: true`, no base reload); `attachedAdapterId` = adapter weights resident, `adapterId` = active (disabled → output inside `disable_adapter()` = pure base). `compare` = base then adapter with the same seed (needs an attached adapter). `evaluate` = mean token loss / perplexity of the same text with the adapter off vs on (`lossDelta`, `pplChangePct`; 本地模型 page「困惑度评估」) |
| `POST /api/local/train` (`TrainReq` in `router.py`) · `GET /jobs` · `GET /jobs/{id}` · `GET /jobs/{id}/log?lines=` · `POST /jobs/{id}/cancel` | Fine-tuning jobs; 409 + estimate when resources would be exceeded (resend with `force: true`) |

- **Storage** (`app/local/settings.py`, override root with `LOCAL_MODELS_DIR`): `models/base/<id>/model.json` (path, modelType, arch, numParams, sizeBytes, `configHash`), `models/adapters/<id>/` (PEFT files + tokenizer + `meta.json`: exact base model fingerprint, training config, dataset stats, metrics, post-training sample), `models/jobs/<id>/` (`job.json`, `progress.json`, `job.log`, `samples.txt`, `cancel` flag). Adapters are written to `<id>.partial` and renamed only on success.
- **Jobs** run as separate subprocesses (`python -m app.local.worker <jobId>`) so the API stays responsive and VRAM/RAM are released when they end. One job at a time; starting training unloads the inference model and loading is refused while training. On Windows never probe PIDs with `os.kill(pid, 0)` (it kills the process) — use `jobs.pid_alive`.
- **Training** (`training.py`): samples (pasted text and/or Java file ids via `text_loader`) are packed into `maxSeqLen` blocks for causal-LM continued training; PEFT LoRA on `all-linear`, gradient checkpointing, cosine LR, `paged_adamw_8bit` for QLoRA (nf4 + double quant, bf16 compute on RTX 40xx). Cancel = flag checked every step (force-kill after 90 s).
- **Hardware assumptions** (dev machine): RTX 4060 Laptop 8 GB (≈6.3 GB free with the display), 16 GB RAM (often only ~2 GB free), C: nearly full. Defaults are conservative (`maxSeqLen` 512, batch 1, grad-accum 4, r 16). 0.5B–1.5B (3B borderline) are the intended QLoRA sizes; 7B QLoRA is reported as *exceed*. GGUF files cannot be trained.
- **Install**: torch's CUDA wheel is not on PyPI — see the header of `requirements-local.txt` (Aliyun mirror / resumable download). The extraction service still runs without these packages; torch is imported lazily.
- **E2E test**: `.venv/Scripts/python scripts/local_e2e.py --model-path <HF model dir> --port 8011 [--samples my.txt]`.
- **Adapter effect check** (no training): `.venv/Scripts/python scripts/adapter_eval.py --adapter <id> --port 8011 [--model-path <base dir to register if none matches>] [--style-file x.txt] [--control-file y.txt] [--skip-novel]` → perplexity base vs adapter on style text (default: middle of the training job's `samples.txt`, i.e. in-sample) and a built-in unrelated control text, same-seed continuations, then a temporary workspace generating one short chapter with the adapter. Exit 0 = style loss drops > 0.05 and more than on the control.

### Novel generation (`app/generation/`, `/api/gen/**`)

`novel.model` = `{source: local, baseId, adapterId?}` (adapter validated with `inference.check_adapter` on create/update) | `{source: api, apiName}` (display name only; the config comes from Java per request) | `{source: remote}` (reserved, rejected). Called directly by the frontend like `/api/local/**`, except 大模型 chapter starts and AI 构思, which come through Java (`/api/novel/gen/**`) carrying `api` (the key lives only in that request / job's memory, never in job status or files).

| Method & path | Purpose |
|---------------|---------|
| `GET  /api/gen/status` | Default model check (`Qwen/Qwen2.5-1.5B-Instruct`: found / download links / target dir), inference state, active job, allowed windows |
| `GET/POST /api/gen/novels` · `GET /novels/{id}` · `POST /novels/{id}/update {title?, model?{source, baseId, adapterId?}, contextWindow?, params?, settings?{config, spec}}` · `POST /novels/{id}/delete` | Workspaces |
| `POST /api/gen/novels/{id}/model/load` | Load the workspace's base model + adapter (same base resident → adapter switch only) |
| `POST /api/gen/novels/{id}/preview {goal, title, targetChars}` | Assemble next chapter's first-segment context without generating (tokenizer only) → layer token report + full messages |
| `POST /api/gen/novels/{id}/chapters {goal, title, targetChars, polish?{enabled, baseId, adapterId}, api?}` · `GET /jobs/{jobId}` · `POST /jobs/{jobId}/cancel` | Background chapter job (`kind: chapter`); job response includes the chapter (live text, calls). `api` is required for 大模型 workspaces (sent by Java). API generation is allowed while a training job holds the GPU; local generation / polishing is not |
| `POST /api/gen/novels/{id}/chapters/{n}/polish {baseId, adapterId?}` · `POST .../polish/revert` | Polish a finished chapter with the local model (`kind: polish` job, progress `polishDone/polishTotal`, live `chapter.polishDraft`); revert restores `originalText` |
| `POST /api/gen/novels/{id}/ideas {kind, hint?, count?, materials[], api? \| local?{baseId, adapterId}, fill?, spec?}` | AI 构思 and AI 填写设定 (`kind: fill`, `ideas._fill`) (`ideas.py`), via Java. Prompt = workspace settings (core + cards) + adopted outline + recent chapter summaries + materials. API: JSON mode, temperature 0.9; local: auto-loads base + adapter (refused while a chapter job or training runs), JSON parsed leniently (`_parse`: code fences, trailing commas, bare arrays → `items`; `_salvage`: per-key regex rescue), readable error when the small model breaks the format. Local single text field fills skip JSON entirely (`FILL_PLAIN_SYSTEM`, `_plain_value` strips prefixes / echoed 【…】 headers, trims a cut-off answer to the last full sentence); local fills use temperature 0.5; local **JSON** fills (category / items / non-text field) run with the adapter disabled (`_run_local(..., use_adapter=False)` — style adapters keep writing after the JSON until the token cap) and a per-field-type token budget (`FILL_TOKEN_BUDGET`, e.g. 世界观 6 fields ≈ 675 instead of 2100 tokens; local speed is ~10–16 tok/s), only plain single-text fills keep the adapter |
| `GET /api/gen/novels/{id}/chapters/{n}` · `POST .../chapters/{n}/delete` | Chapter detail; only the last chapter can be deleted |
| `POST /api/gen/novels/{id}/chapters/{n}/update {title?, goal?, text?, summary?}` | Hand edit of a (non-generating) chapter; records `edited[]` + `editedAt`. Edited summaries / text feed later chapters' context; a polished chapter keeps `originalText` (「恢复原文」 discards hand edits) |
| `POST /api/gen/novels/{id}/update {…, outline?, clearOutline?, arcSummary?}` | `outline` = `{logline, synopsis, chapters[{index, title, goal, materials}], materials}` (validated by `ideas.validate_outline`, `savedAt` added) |

- **Model interface** (`backends.py`): everything goes through `TextGenerator` (`count_messages`, `count_text`, `tail_tokens`, `context_limit`, `ensure_ready`, `generate(messages, GenParams) → GenResult`). `LocalHFGenerator` wraps `app.local.inference.chat_generate` (chat template + system message, token-level cancel via `StoppingCriteria`, exact `finishReason`). `ensure_ready` requires the loaded adapter to equal the workspace's. `GenParams.use_adapter=False` runs a call inside `disable_adapter()`: chapter summaries and arc merges always use the pure base (continued-pretraining style adapters weaken instruction following); segments use the adapter. Each chapter records `model` (`{source: local, baseId, adapterId}` or `{source: api, name}`). `ApiChatGenerator` = OpenAI-compatible API via `llm_client.complete` (token counts estimated from characters for context assembly; real `usage` recorded; cancel between calls). `source: remote` raises "暂未接入" — a remote GPU backend implements `TextGenerator` and registers there.
- **Polish** (`chapter._polish`): ~300-char paragraph chunks rewritten with the local base + adapter (chat prompt `prompts.POLISH_SYSTEM`, temp 0.4); a chunk is kept unchanged if the output was truncated or its length ratio is outside 0.7–1.4. `originalText` holds the pre-polish text (re-polishing always starts from it); `polish {baseId, adapterId, adapterName, chunks, changed, kept, at}`. The model is loaded with `inference.load(..., from_generation=True)` (bypasses the generation-busy guard for the job's own load); in a local workspace polished with different settings, the workspace adapter is switched back afterwards.
- **Output cleanup** (`chapter._clean`): strips preambles (「好的，以下是…：」, also after a short leading sentence), chapter headings (incl.【第一章 …】), and cuts at echoed prompt section headers (`PROMPT_ECHO`: 【本次任务】【核心设定】…) that small local models sometimes repeat.
- **Constraints** (`spec.py`): world / plot / style plain fields + the protagonist (role contains 主角) + a character roster → **core** (system message, never trimmed); other characters, plot milestones, custom elements (category overview + one card per item, keyed by names) → **retrievable cards**; missing built-in categories → "尚未设定" (open, may be invented without contradiction). `plot.chapters` / `plot.wordsPerChapter` are parameters, not facts (the latter is the default target length).
- **Layered context** (`context.py`, real tokenizer): L0 core + L4 task are mandatory (error if they exceed `window − maxNewTokens − 64`); then L3 recent text minimum (256 tokens of the chapter so far, or the previous chapter's ending), L2 latest chapter summary, L1 cards with keyword relevance > 0 (irrelevant cards are never sent), arc summary, older summaries, then L3 is extended (≤ `params.recentTokens`, 900). The final chat-template count is verified and pieces are rolled back in reverse priority until it fits.
- **Segmented chapters** (`chapter.py`): each segment ≤ `params.segmentTokens` (768, capped at window/4) and only sees the chapter tail, never the whole chapter. Stops at ~95% of target chars, natural end on the last segment, cancel, or a segment cap. Then a summary call (≤150字, temp 0.3); when > 8 unmerged chapter summaries exist the oldest 5 are merged into `arcSummary`. Every call (type, prompt/completion tokens, finish reason, seconds, layer report) is stored on the chapter and added to the workspace totals. One generation job at a time; refused during training; model load/unload/training are refused while a chapter is generating.
- **Storage** (`store.py`): `data/novels/<id>/novel.json` (incl. `outline`) + `chapters/NNNN.json` (`${DATA_DIR}/novels`; `NOVELS_DIR` still overrides). Python is the only writer; Java may read per `data/README.md`. All persistence goes through `store.py` so the planned MySQL migration replaces only that module.

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
