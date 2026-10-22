# AGENTS.md — DevPilot (Barclays MDM capstone)

Two independent FastAPI services, no shared Python env or top-level package:

- `backend/` — API gateway, port 8000 (auth, projects, requirements, artifacts, audit)
- `ai-engine/` — RAG + generation service, port 8001 (LangChain, pgvector, Groq/Gemini)

There is no frontend in this repo (the 2026-10-18 React scaffold was intentionally removed; keep it that way).
The single exception is `tools/streamlit_app.py` — a minimal **dev tool** (upload/ingest/tree/generate),
never grow it into a product frontend. It runs from its own venv (`~/.venvs/devpilot-ui`) because
streamlit's starlette conflicts with the engine's `fastapi==0.115.0` pin; it talks only HTTP + DB.
`IMPLEMENTATION.draft.md` (root) is the team's
implementation plan — treat it as partially stale: several of its "immediate fixes"
are already applied in code. Verify against the code before following it.

## Commands

Backend (run from `backend/`; a working `.venv/` already exists there):

- Full suite: `pytest -q` (~96 tests, no live DB/services needed — SQLite in-memory, AI engine stubbed via `tests/conftest.py` fixtures `mock_ai_generate`/`mock_ai_ingest`)
- By group: `./run_tests.sh unit|repo|integration|contract|coverage`
- Single file/test: `pytest tests/unit/test_ai_engine_client.py::test_name -q`
- Run app: `uvicorn app.main:app --reload --port 8000` (needs `.env`; see `backend/.env.example`)
- Migrations: `alembic upgrade head` (PostgreSQL is the intended shared DB; `AUTO_CREATE_TABLES=true` is for disposable SQLite dev only). New migrations: keep revision ids ≤32 chars (alembic_version column limit) and guard every add_column/create_table with `sa.inspect()` checks + `batch_alter_table` for SQLite FK support.

AI engine (run from `ai-engine/`; use `.venv/`, an older `venv/` also exists — ignore it):

- Tests: `pytest tests/ -q` (~78 tests, fully offline: `Settings.validate()` is never called; LLM/retrieval are fake-patched in tests)
- Run app: `uvicorn app.main:app --reload --port 8001` — real generation/ingest needs `GOOGLE_API_KEY` (embeddings, always) + `GROQ_API_KEY` (if a `groq-*` alias is set) + pgvector-enabled `DATABASE_URL`. `ai-engine/.env` holds real keys — never commit it.

UI dev tool (needs db + engine + backend up): `/home/devanssh/.venvs/devpilot-ui/bin/streamlit run tools/streamlit_app.py` (browser at localhost:8501).

CI: `.github/workflows/backend-tests.yml` (Python 3.11) runs the backend suite plus a PostgreSQL job (`tests/repositories tests/integration tests/contract` against real PG after `alembic upgrade head`, driven by `TEST_DATABASE_URL`, default `sqlite://`). `.github/workflows/ai-engine-tests.yml` runs the engine's keyless offline suite. If you change models or migrations, assume the PG job must pass too.

## Gotchas

- **Docker compose Postgres is on host port 5433**, not 5432 (`ankane/pgvector` image). `.env.example` files use 5433 for host dev; compose overrides `DATABASE_URL` to `db:5432` inside the network. Enable the extension once: `CREATE EXTENSION IF NOT EXISTS vector;`.
- **Uploads are path-shared**: backend sends absolute file paths to ai-engine's `/ingest`; both services must read the same `UPLOAD_DIR` (compose mounts one `uploads` volume into both at `/shared/uploads`).
- **Ingestion is async (job pattern)**: `POST /ingest` (engine) and `POST /api/v1/projects/{id}/requirements` (backend) return **202 `{job_id, status:"processing"}`**. Poll `GET /api/v1/ingest-jobs/{id}` — the backend lazily fetches engine state and idempotently persists `chunks_indexed` + `doc_tree_nodes` on the first terminal poll. Engine jobs live in memory only (`app/main.py _INGEST_JOBS`, capped 1000); an engine restart evicts them and the client maps the engine 404 to a terminal `failed`.
- **`backend/app/config.py` and `app/security.py` are re-export shims** over `app/core/config.py` / `app/core/security.py` (like `app/database.py`). There is one `Settings` instance. Edit `app/core/*`; imports from either path work but resolve to the same object.
- **`openevals` is NOT installable here**: every version forces `langchain-core` 1.x, conflicting with the 0.3.x pins that `langchain-groq`/`langchain-google-genai`/`langchain-postgres` require. The LLM-as-Judge is implemented inline (`sop_graph.judge_score`, openevals-compatible contract). Same story for the PageIndex SDK (§2.3.2 spike). Do not `pip install openevals`.
- **ai-engine deps are tightly coupled**: docling pins (~2.5 GB torch), `numpy<2`, langgraph `>=0.2.6,<0.3`, ragas/langchain-cohere must stay in the 0.3.x-core series (`ai-engine/requirements.txt` comments explain). Never casually `pip install -U` there; verify with the full offline suite.
- **SOP generation replaces the single-shot chain**: `/generate` runs the LangGraph `retrieve→pm→qa` loop (approval threshold 0.80, max 2 retries, best draft accepted). Response/history now carry `eval_score`, `retry_count`, `model_used`; judge runs on `EVAL_JUDGE_LLM` (defaults to `FALLBACK_LLM`) and degrades to an optimistic 0.85 when unavailable. Gemini free tier rate-limits (~5 req/min) — retries are automatic.
- **Every artifact type needs both a prompt template and a schema**: `app/prompts/templates/<type>/v*.yaml` + `app/schemas/registry.py`; a smoke test asserts parity. New artifact type = new YAML dir + registry entry.
- `GET /api/v1/artifacts/{id}/export?format=csv` emits JIRA-style columns for `user_story` artifacts with `stories`; other types get the generic CSV. Backend tests stub AI engine calls; don't mock them ad hoc.

## Conventions

- Backend routes live in `app/main.py` inline (auth/projects/generate/artifacts/audit). The `app/api/v1/` routers + `app/services/` layer exist but are NOT mounted in the app — Sprint 6 decomposition target; feature work today goes in `main.py`.
- RBAC: global roles `member`/`admin` (register grants `member`; promote manually via DB); project roles `owner`/`editor`/`viewer`. Audit-logs + `/api/v1/evaluate/batch` are admin-only; generate/compare/stream/upload require editor+. Requirement uploads capped at 10 MB; tokens are JWT bearer.
- Offline eval stack: `ai-engine/eval_data/golden.jsonl` (50 rows, committed) + `batch_harness.py` (ragas runs through our provider layer) + `auditor.py`. `RETRIEVAL_MODE` stays `vector` until the §2.3.6 ship run passes.
- Multi-fork team repo (remotes `origin` + teammate forks); history shows cross-fork merges into shared branches. Check `git status` before assuming committed state.
