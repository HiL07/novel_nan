# Repository layout (full)

> Split out of `CLAUDE.md` on 2026-11-03 (content moved verbatim). `CLAUDE.md` keeps the overview and conventions; keep this file updated when the APIs / behaviour below change.


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
│       ├── views/material/ # index.vue (素材库: keyword/tag + AI semantic search, 精炼合并, 待确认 candidates)
│       ├── views/persona/  # index.vue (角色卡: prototypes, versions, adaptations, identity test, 试聊); components/persona/
│       ├── views/inspire/  # index.vue (灵感墙: walls, 构思 three steps, 墙上, 逛素材, 构思记录); components/inspire/ IdeaCard, ApplyDialog (写进工作区)
│       ├── components/material/ # ExtractOptionsForm (提取设置, used by the extraction workspace) + extractLive.js (逐章 data composable) + BreakdownView (拆书视图), CompileDialog (整理卡片), EntityArchive (实体档案), FactList, MergePanel (精炼合并), CandidateReview (20 per page), MaterialEditor, AttributeEditor, MaterialPicker (pick-only mode for AI 构思)
│       ├── components/crawl/ # WorkspacePanel (抓取进度: per-home workspaces, 来源 单本/整站), SiteMapView (AI 解析: site root + per-layer URL patterns, 已掌握 / 未掌握), AutoCrawlPanel (全自动: 测试规律 → 决定 → 书目筛选 / 抓取)
│       ├── components/ai/ # TokenUsageBar (source tag 大模型/本地/远程, tokens incl. cache hits, cost via utils/modelPricing.js)
│       ├── utils/modelPricing.js # reference prices per 1M tokens by model name (CNY/USD) + per-model overrides in localStorage
│       ├── components/novel/ # IdeaPanel (AI 构思: 书名 / 大纲 / 章节题目 + 素材), FactsPanel (故事账本), ChapterInsight (本章规划 / 一致性检查 / 本章事实)
│       ├── components/novel-options/ # schema-driven option UI (SettingsEditor, OptionField, ChoiceWidget, …)
│       ├── novel-options/ # field-type registry, schema helpers, editor context
│       └── mock/        # local placeholder data (until the DB exists)
├── python-service/     # FastAPI AI service
│   ├── app/            # main.py, extractor, llm_client, text_loader (extraction)
│   ├── app/persona.py  # cross-world persona cards: extract prototype, adapt, chat, identity test (routes in main.py)
│   ├── app/local/      # local models: settings, hardware, registry, inference, training, download, jobs, worker, router
│   ├── app/generation/ # novel generation: backends, spec, context, prompts, chapter (+ polish), ideas (AI 构思), inspire (灵感墙), worldbook (世界书), directions (走向引擎), facts (故事账本), store, defaults, router
│   ├── app/crawler/    # web novel crawler: rules (presets / XPath), fetcher, parser (heuristics), service (jobs), catalog (全自动书目采集 + AI 检索 / 补标签), ai_rules, router
│   ├── models/         # git-ignored: base/<id>/model.json (+weights if downloaded), adapters/<id>/, jobs/<id>/
│   ├── scripts/local_e2e.py  # end-to-end smoke test over HTTP
│   ├── scripts/crawl_site_selftest.py  # crawler self-test against a local fake book site (no network)
│   ├── requirements.txt       # extraction service (no torch)
│   └── requirements-local.txt # local models (torch CUDA + transformers/peft/accelerate/bitsandbytes)
├── docs/             # deep-dive docs of the core logic (素材流程 / 素材检索 / 精炼合并), see the section above
├── README.md         # GitHub overview: features, architecture, tech stack, quick start
├── data/             # shared data dir (git-ignored except README.md/.gitkeep): nan_novel.db, upload/, extract-results/, novels/ — see data/README.md
├── picture/          # git-ignored: screenshots / reference images the user drops in to explain requests — when a request mentions an image, read it from here (Read tool)
├── scripts/migration/ # one-off MySQL → SQLite config import (import_mysql_config.py)
├── start.bat           # Windows one-click launcher for backend + AI service + frontend
├── start-llama.bat     # manual llama.cpp launcher (normally use the llama.cpp page)
├── 模型对比测试报告.md  # DeepSeek vs local GGUF / safetensors benchmark (2026-10-27)
└── CLAUDE.md
```
