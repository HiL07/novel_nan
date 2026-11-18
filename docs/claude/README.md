# CLAUDE.md reference docs

On 2026-11-03 `CLAUDE.md` (170k chars, over Claude Code's 150k limit) was split. `CLAUDE.md` keeps the overview,
core conventions and this index; the endpoint-level reference moved here **verbatim** (nothing was rewritten or
dropped). The original file is kept at `_backup/CLAUDE.md.2026-11-03.bak`.

| File | Former CLAUDE.md section | Covers |
|---|---|---|
| [`repo-layout.md`](repo-layout.md) | §2 | full annotated repository tree |
| [`java-backend.md`](java-backend.md) | §4 commands / layering / HTTP / file API, AI model config, Python env, file storage & SQLite, configuration & CORS | Java conventions and base framework |
| [`extraction-materials.md`](extraction-materials.md) | §4 extraction API + material library API, §6 novel extraction | 小说提取 / 提取工作区, 整理卡片, 素材库, 向量检索, 精炼合并, 素材量级, Python scan / compile / merge / evals |
| [`crawler.md`](crawler.md) | §4 crawl API + auto crawler, §5 crawl page, §6 crawler | 单本 / 全自动抓取, 站点规则, 书目, 抓取进度, checkpoints |
| [`generation.md`](generation.md) | §4 generation / auto planning / inspiration wall APIs, §6 novel generation | AI 构思, 走向引擎, 自动规划, 灵感墙, chapters, context, ledger, world book |
| [`frontend.md`](frontend.md) | §5 (except the crawl page) | frontend rules, theme, settings editor, workspaces / 书房, AI 构思 panel |
| [`local-models.md`](local-models.md) | §6 local models | `/api/local/**`, embedding / reranker, llama.cpp, inference, training |
| [`persona.md`](persona.md) | §9 | persona cards & 试聊 implementation reference |
| [`general.md`](general.md) | §1, §6 intro / conventions, §7, §8 | original wording of the sections CLAUDE.md now condenses |

Design docs (Chinese, the *why*) stay in `docs/*.md`; these files are the *what* (endpoints, fields, tables).

## Points to verify (found while splitting, left unchanged)

1. `extraction-materials.md` (material flow): step ① still names `ExtractOptionsDialog`, while the same paragraph says
   it is gone; the code only has `components/material/ExtractOptionsForm.vue`.
2. CLAUDE.md §7 said "The project never starts / stops llama.cpp itself", but the llama.cpp page (`app/local/llama.py`,
   `/api/local/llama`) does manage `llama-server`. The statement only holds for `start-llama.bat`.
3. `repo-layout.md` misses existing paths: `views/novel/extractWorkspace.vue`, `components/novel/study/`,
   `components/novel/{PlanWizard,BookSkeleton,BookConfigForm,PlanCastCard}.vue`,
   `components/material/{EntityOverview,MaterialDock,ProfilePanel}.vue`, `components/crawl/HomeLinksView.vue`,
   `python-service/app/polish/`, `app/remote/`, `app/generation/planner.py`, `app/breakdown.py`, `app/chapter_scan.py`.
4. `frontend.md` «Novel workspaces»: "Workspace header switches the model source…" describes the pre-书房 header;
   those controls now live in the `StudyHeader` model chip popover.
5. The deep-dive index did not list `docs/素材提取改造方案.md` or `docs/待办.md` (now added in CLAUDE.md).
