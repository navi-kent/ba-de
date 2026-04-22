# Repository Guidelines

## Project Structure & Module Organization
`backend/app.py` is the Flask entrypoint that serves both `/api/*` endpoints and static pages from `frontend/`. Scrapers live in `scrapers/` and share helpers in `scrapers/utils.py`. Database setup is in `db/schema.sql` and `db/init_db.py`. Runtime configuration lives in `config/search_config.yaml` and `.env` (copy from `.env.example`). `mockups/` holds reference HTML and is not part of the running app.

## Build, Test, and Development Commands
Create a local environment with `python3 -m venv venv && source venv/bin/activate` and install dependencies via `pip install -r requirements.txt`. Initialize or migrate the database with `python db/init_db.py`. Run the app locally with `python backend/app.py` or production-style with `gunicorn backend.app:app`. Run scrapers manually from the repo root, for example `python scrapers/news_rss.py` and `python scrapers/ptt_scraper.py`.

## Coding Style & Naming Conventions
Use 4-space indentation and keep Python code PEP 8 aligned. Prefer `snake_case` for functions, variables, and module names; keep constants uppercase, as in `ADMIN_TOKEN` and `UPLOAD_DIR`. Follow the existing pattern of short docstrings on public helpers and routes. Keep frontend filenames lowercase with hyphens, matching existing pages such as `news-feed.html`.

## Testing Guidelines
There is no dedicated `tests/` directory yet. Before opening a PR, run `python db/init_db.py` against a local PostgreSQL instance, start the Flask app, and smoke-test key flows: homepage, `/news`, `/news-feed`, `/admin`, and at least one scraper run. For lightweight code checks, use `python -m compileall backend scrapers db`.

## Commit & Pull Request Guidelines
Recent history uses Conventional Commit prefixes such as `feat:`, `fix:`, `docs:`, and `chore:`. Keep commit subjects short and imperative, for example `fix: handle empty scraper results`. PRs should explain user-visible changes, note any schema or `.env` updates, and include screenshots when `frontend/` or `admin.html` changes. Link related issues and list the manual verification steps you ran.

## Security & Configuration Tips
Do not commit `.env`, database credentials, admin tokens, or uploaded files under `frontend/uploads/`. Treat `config/search_config.yaml` changes as behavior changes for scraper scope and document them in the PR.
