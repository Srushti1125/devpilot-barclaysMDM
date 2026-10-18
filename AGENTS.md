# AGENTS.md — DevPilot (Barclays MDM capstone)

Two independent FastAPI services, no shared Python env or top-level package:

- `backend/` — API gateway, port 8000 (auth, projects, requirements, artifacts, audit)
- `ai-engine/` — RAG + generation service, port 8001 (LangChain, pgvector, Groq/Gemini)

There is no frontend in this repo. `IMPLEMENTATION.draft.md` (root) is the team's
implementation plan — treat it as partially stale: several of its "immediate fixes"
are already applied in code. Verify against the code before following it.

## Commands

Backend (run from `backend/`; a working `.venv/` already exists there):

- Full suite: `pytest -q` (~82 tests, no live DB/services needed — SQLite in-memory, AI engine stubbed)
- By group: `./run_tests.sh unit|repo|integration|contract|coverage`
- Single file/test: `pytest tests/unit/test_ai_engine_client.py::test_name -q`
- Run app: `uvicorn app.main:app --reload --port 8000` (needs `.env`; see `backend/.env.example`)
- Migrations: `alembic upgrade head` (PostgreSQL is the intended shared DB; `AUTO_CREATE_TABLES=true` is for disposable SQLite dev only)

AI engine (run from `ai-engine/`; use `.venv/`, an older `venv/` also exists — ignore it):

- Tests: `pytest tests/ -q` — passes with zero API keys (`Settings.validate()` in `app/config.py` is defined but never called, so import-time tests hit no provider checks)
- Run app: `uvicorn app.main:app --reload --port 8001` — real generation/ingest calls need `GOOGLE_API_KEY` (embeddings, always) and `GROQ_API_KEY` if a `groq-*` model alias is set, plus a pgvector-enabled `DATABASE_URL`

CI (`.github/workflows/backend-tests.yml`, Python 3.11) also runs `tests/repositories/ tests/integration/ tests/contract/` against real PostgreSQL after `alembic upgrade head`, driven by `TEST_DATABASE_URL` (default: `sqlite://`). If you change models or migrations, assume the PG job must pass too.

## Gotchas

- **Docker compose Postgres is on host port 5433**, not 5432 (`ankane/pgvector` image). The `.env.example` uses 5432 — adjust the URL when pointing at the compose DB.
- **Uploads are path-shared**: backend sends absolute file paths to ai-engine's `/ingest`; both services must read the same `UPLOAD_DIR` (compose mounts one `uploads` volume into both at `/shared/uploads`).
- **Backend config/security is mid-refactor with live duplicates**: `app/config.py` + `app/security.py` (legacy, still imported by `main.py`, `api/deps.py`, `api/v1/requirements.py`) vs `app/core/config.py` + `app/core/security.py` (imported by services/repositories). `app/database.py` is an intentional re-export shim of `app.core.database`. Both Settings instances read the same `.env`, but if you add a setting, add it in **both** or know which layer reads it. Canonical ORM models: `app/domain/models.py`.
- **ai-engine deps are tightly coupled**: `docling` pulls in ~2.5 GB of torch, and docling/docling-core/numpy/opencv pins must stay in lockstep (comments in `ai-engine/requirements.txt`). Never casually `pip install -U` there.
- **Every artifact type needs both a prompt template and a schema**: `app/prompts/templates/<type>/v*.yaml` + `app/schemas/registry.py`; a smoke test asserts parity. New artifact type = new YAML dir + registry entry.
- Backend integration tests stub `AIEngineClient.generate/ingest` via fixtures in `backend/tests/conftest.py` (also role fixtures: admin/pm/ba/dev/tester headers) — don't mock them ad hoc.
- Prompt versions, request_id, usage, and latency are persisted with each generation (history/audit) — preserve those fields when changing the generate flow.

## Conventions

- RBAC: global roles `member`/`admin` (register grants `member`; promote manually via DB); project roles `owner`/`editor`/`viewer`. Audit-log endpoint is admin-only. Requirement uploads capped at 10 MB.
- Multi-fork team repo (remotes `origin` + teammate forks like `sayali`); history shows cross-fork merges into shared branches (e.g. `backend-core`), and large uncommitted refactors may sit in the working tree — check `git status` before assuming a file's committed state is current.
