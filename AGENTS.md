# Repository Guidelines

## Project Structure & Module Organization

- `frontend/src/`: Vue 3 application; pages in `views/`, shared UI in `components/`, HTTP clients in `api/`, and theme assets in `styles/`.
- `backend/src/main/`: Java 17 Spring Boot application, resources, and SQL schemas. Follow controller → service → mapper → entity layering.
- `python-service/app/`: FastAPI extraction, generation, retrieval, crawling, and local-model modules. Regression and evaluation scripts live in `python-service/scripts/`.
- `docs/` and `docs/claude/`: design and implementation references; `docker/`: deployment files; `skills/`: bundled writing tools.
- `data/`: local SQLite database and runtime files. Java owns database access and metadata persistence.

## Build, Test, and Development Commands

Run commands from the indicated directory:

- `frontend/`: `npm ci` installs locked dependencies; `npm run dev` starts Vite; `npm run build` produces the production bundle.
- `backend/`: `mvn spring-boot:run` starts Java; `mvn clean package` compiles and packages it.
- `python-service/`: `py -3.10 -m venv .venv`, then `.venv/Scripts/python -m pip install -r requirements.txt` prepares the environment. `.venv/Scripts/python -m uvicorn app.main:app --port 8011` starts an agent test instance.
- `frontend/`: `npm run dev:test` uses port 5174 and the test backend. Configure Java on 8012 and its AI-service URL on 8011.

## Coding Style & Naming Conventions

Match surrounding code: two-space JavaScript/Vue indentation and four-space Python/Java indentation. Use PascalCase Java classes and Vue components, camelCase JavaScript/Java members, and snake_case Python functions/modules. Vue components use `<script setup>`; UI text is Chinese. Use shared `src/api/` clients and theme CSS variables. Java endpoints use `Result<T>`, `BizException`, and constructor injection. No formatter or linter is configured in the frontend package.

## Testing Guidelines

Python uses standalone `scripts/*_test.py`, `*_selftest.py`, and evaluation scripts. From `python-service/`, run `.venv/Scripts/python scripts/dataset_split_test.py` for dataset checks without GPU/models/services. Read other scripts' requirements first. No coverage threshold, frontend test command, or Java test suite is configured. Build affected components and verify changed workflows. Use test ports 8012/8011/5174 (llama.cpp: 8002), with a separate data copy for state-changing checks; never interrupt daily services.

## Commit & Pull Request Guidelines

Recent commits use short Chinese descriptions of the changed feature, without a mandatory prefix. Keep commits focused. PRs should describe behavior changes, relevant issues, validation commands/results, and screenshots for UI changes. Update matching `docs/claude/` references when contracts change.

## Configuration & Agent Guidance

Read `CLAUDE.md` and the relevant `docs/claude/` reference before code changes. Keep secrets, user uploads, datasets, and model weights out of Git. Store API keys through model configuration or ignored `backend/application-secret.yml`; never log them. Preserve machine-specific launcher paths.
