# General: overview, Python service intro, local dev, agent rules (original text)

> Split out of `CLAUDE.md` on 2026-11-03 (content moved verbatim). `CLAUDE.md` now carries a condensed version of these sections; this file keeps the original wording. Note: the §7 sentence "The project never starts / stops llama.cpp itself" predates the llama.cpp page (see `README.md` here, point 2).

## Original overview & deep-dive index

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

## Deep-dive docs (`docs/`)

Design and implementation details of the core logic — parameters, thresholds, measurements and the reasons behind them —
live in [`docs/`](docs/README.md) (Markdown, Chinese); `README.md` in the repo root is the GitHub overview (features,
architecture, tech stack, quick start). This file stays the reference for APIs, tables and conventions.

| Doc | Covers |
|---|---|
| `docs/素材流程.md` | extraction (scan, quote verification, two rounds, aggregation), 整理卡片, checkpoints and task states, GGUF measurements |
| `docs/素材检索.md` | vector text, bge + BM25 hybrid recall, RRF, reranking and score meaning, multi-version recall of merged masters, auto-matching rules |
| `docs/灵感墙.md` | inspiration wall: need planning, local retrieval (per-book cap, random exploration, pinned first), ideas with checked material refs, the four exits |
| `docs/跨世界观角色卡.md` | persona prototypes: locating mentions, evidence notes, provenance decided in code, versions, adaptation checks (locked traits, core coverage, term leaks), generation hooks, identity test |
| `docs/试聊.md` | 试聊: modes (free / scene / interview), anchors, summaries of old turns, drift checks, feedback |
| `docs/世界书.md` | world book: compiling settings + persona snapshots + ledger into entries, character situation fields (goal / obstacle / relations / knows) and clocks, rollback rules, the situation snapshot |
| `docs/走向引擎.md` | direction engine: drivers → review / revise → ranking; eval method (real novels cut into test workspaces) and measured versions |
| `docs/自动规划.md` | auto planning (story-first only; the material-first route was removed 2026-11-02, how materials join story-first is being designed): book config + ideas → settings (each block regenerable four ways) → book skeleton of volumes / stages built on the settings (volume directions, pace, single-volume regen) + cast → apply; optional material enrichment / stage-aware outline / review endpoints kept; works with an empty library; opening rules and code checks; planned foreshadows shared by ledger / outline / world book; the removed route's flow and evals are kept in §2 for reference |
| `docs/精炼合并.md` | finding similar groups (content + title scores, anti-chaining), AI drafts and grounding checks, 共性 + 可选版本, unmerge, how AI uses multi-version materials |

**When you change extraction, retrieval or merge algorithms / parameters, update the matching doc in the same change.**

## Original Python service intro & conventions

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

Shared data dir: `DATA_DIR` (`app/config.py`, default `<repo>/data`); Python writes only `data/novels/`, `data/material-index/` (material vectors + search feedback), `data/crawl-cache/` (crawl checkpoints), `data/extract-cache/<key>/` (v2 material-extraction checkpoints) and `data/site-catalog/<host>/toc/` (catalog TOCs). The model (base URL, key, model name, concurrency) is **not** configured here — Java sends the active config with each request and Python never stores the key. Env vars (`app/config.py`): `JAVA_BACKEND_URL`, `CHUNK_CHARS` (default 6000), `LLM_MAX_TOKENS`, `LLM_TIMEOUT`. No torch/CUDA needed for extraction.

### Conventions

- FastAPI app served by Uvicorn on **port 8021** (test 8011), all routes prefixed with `/api`, Pydantic v2 models for request/response.
- Do **not** re-implement file storage or a second file database. Consume files via the Java backend (by file id / relative storage path) or a shared volume, and return extracted/analyzed results over HTTP.
- Fine-tuning is long-running: run training as **background/async jobs with a status endpoint** (queued/running/succeeded/failed + logs), never block a request worker.
- Keep model weights, datasets, and LoRA adapters out of Git: `python-service/models/` is git-ignored; large base models are registered by path instead of copied.
- Add `requirements.txt` (or `pyproject.toml`) and document the Python version and CUDA/torch assumptions.

## Original local development & agent rules

## 7. Local Development (Windows)

- Prerequisites: **JDK 17** (the project does not compile on JDK 8), Maven, Node.js. **No database server is needed** (SQLite file `data/nan_novel.db` is created on first start). The pre-migration MySQL schema `test10000` is kept untouched as a rollback source only.
- `start.bat` launches the services with one click. It contains **machine-specific hardcoded tool paths** (`JAVA17_HOME`, `MAVEN_BIN`, `NODE_DIR` under `D:\workplace\...`) — edit them to match the current machine; do not "fix" them for everyone.
- `start.bat` also starts the AI service with the interpreter saved on the **Python 环境** page (`python-service/.python-env`), else `python-service/.venv`. To use a local GGUF model, start it on the **llama.cpp** page (`/ai/llama`, see the `/api/local/llama` row) and pick the 「GGUF」 model source; manual alternative: **`start-llama.bat`** (llama.cpp `llama-server` on `127.0.0.1:8001`, in its own console window — closing it stops the server; double-click = default model, drag a `.gguf` onto it = that model, `start-llama.bat [gguf] [ctx]`; machine-specific `LLAMA_DIR` / `DEFAULT_MODEL` at the top, falls back to the old Qwen2.5-7B GGUF; when 8001 is already listening it says so and closes after 5 s; keeps `--parallel 1 --cache-ram 0`, the defaults crash with a CUDA error after ~15 min on the RTX 4060 Laptop) and add a config with base URL `http://127.0.0.1:8001/v1`, concurrency 1. The project never starts / stops llama.cpp itself — it is just an OpenAI-compatible endpoint to `llm_client.py`. `start.bat` can run it as a 4th window (`START_LLAMA` at its top, **default 0**) — normally start GGUF models from the 「llama.cpp」 page instead (same port, only one of the two at a time).
- **Model comparison report** (DeepSeek vs local GGUF vs safetensors: extraction / chapter / AI fill, speed + quality, test method): `模型对比测试报告.md` in the repo root.
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
- Never commit secrets, uploaded user files, model weights, or datasets; keep `data/` (except `README.md`/`.gitkeep`), `picture/`, `docker.zip` and Python artifacts out of version control.

