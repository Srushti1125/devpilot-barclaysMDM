# DevPilot backend

FastAPI service for users, project access, requirement uploads, generated artifacts, history, evaluation, exports and audit records. The AI engine remains a separate service.

## Run locally

From this directory, create a virtual environment and install `requirements.txt`. Copy `.env.example` to `.env`, set a strong `JWT_SECRET_KEY`, and provide a PostgreSQL URL. Create the database, then run `alembic upgrade head` and `uvicorn app.main:app --reload --port 8000`. Interactive API docs are at `/docs`.

For a disposable local SQLite setup only, set `AUTO_CREATE_TABLES=true`; production deployments should run migrations and leave it false. PostgreSQL is the intended shared application database. Enable `pgvector` in the database used by the AI engine as described in `../ai-engine/GUIDE.md` (the backend's own tables do not require the extension).

## Run the whole local stack

One script starts the database, applies migrations, launches this API and the AI engine, and opens the dev UI. Run it from the repository root:

```bash
tools/run_stack.sh            # services + Streamlit UI at http://localhost:8501
tools/run_stack.sh --no-ui    # services only (db :5433, engine :8001, backend :8000)
tools/run_stack.sh --status   # show what is running
tools/run_stack.sh --stop     # stop the services the script started
```

It performs the following steps:

1. starts the `pgvector` Postgres container via `docker compose up -d db` (host port **5433**),
2. runs `alembic upgrade head` when the database is not already at the current revision,
3. starts the AI engine on `:8001` from `ai-engine/.venv` (first cold start loads torch/docling — allow ~2 minutes),
4. starts the backend on `:8000` from `backend/.venv` against the **local compose database** (it overrides the Neon URL in `backend/.env`),
5. starts the Streamlit UI on `:8501` unless `--no-ui` is passed.

Prerequisites: Docker running; `backend/.venv` and `ai-engine/.venv` installed (`pip install -r requirements.txt`); `backend/.env` and `ai-engine/.env` filled in; and the UI venv `~/.venvs/devpilot-ui` created with `pip install -r tools/requirements.txt`. Override defaults with `DB_URL`, `ENGINE_VENV` and `UI_VENV`. Logs are written to `/tmp/devpilot_stack/`.

## Environment

`DATABASE_URL` (e.g. `postgresql+psycopg://user:password@localhost:5432/devpilot`), `JWT_SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `AI_ENGINE_URL` (default `http://localhost:8001`), `UPLOAD_DIR`, `CORS_ORIGINS` (comma separated), `AUTO_CREATE_TABLES`, and `LOG_LEVEL`. The AI engine separately needs its own keys and vector database configuration; consult its GUIDE.

## AI engine integration

`app/services/ai_engine.py` uses async HTTP requests to `/health`, `/artifact-types`, `/generate`, `/generate/stream`, `/generate/compare`, `/ingest` (+`GET /ingest/{job_id}`) and `/evaluate/batch`. Generation runs the engine's LangGraph SOP swarm (retrieve → pm draft → qa judge, ≤2 revisions); results are validated and stored as artifacts with request ID, prompt version, usage, latency, requirement text — plus `eval_score`, `retry_count`, `model_used` and optional `requirement_id` provenance — in history and audit tables. Requirement uploads are capped at 10 MB, stored beneath `UPLOAD_DIR`, and their absolute path is sent to the engine's `/ingest` endpoint as an async job: the API returns 202 immediately and clients poll `GET /api/v1/ingest-jobs/{id}`, which persists tree nodes and chunk counts on the first terminal poll. This assumes both services can read the same upload directory (mount it into both containers when containerized — see root `docker-compose.yml`).

## API overview

- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`
- `GET /api/v1/artifact-types`
- Project CRUD: `GET/POST /api/v1/projects`, `GET/PATCH/DELETE /api/v1/projects/{id}`, and `POST /api/v1/projects/{id}/members?email=...&role=viewer|editor`
- Requirements: `POST /api/v1/projects/{id}/requirements` (multipart; **202** `{id, ingest_job_id, status}`), `GET /api/v1/projects/{id}/requirements`, `GET /api/v1/requirements/{id}`, `GET /api/v1/ingest-jobs/{job_id}` (poll until `done`/`failed`)
- Generation: `POST /api/v1/projects/{id}/generate`, `POST /api/v1/projects/{id}/generate/stream` (SSE proxy of SOP node transitions), `POST /api/v1/projects/{id}/compare` (parallel DEFAULT/FALLBACK LLMs)
- Artifacts: `GET /api/v1/projects/{id}/artifacts`, `GET/PATCH /api/v1/artifacts/{id}`, `GET /api/v1/artifacts/{id}/export?format=json|markdown|csv|yaml` (user_story CSV uses JIRA columns)
- History, evaluations, traceability: `GET /api/v1/projects/{id}/history` (includes eval telemetry), `POST/GET /api/v1/artifacts/{id}/evaluations`, `GET /api/v1/projects/{id}/traceability` (React Flow nodes/edges)
- Admin-only: `GET /api/v1/audit-logs`, `POST /api/v1/evaluate/batch?retrieval_mode=vector|hybrid`
- `GET /health`, `GET /health/db`, `GET /health/ai`

Access tokens are bearer JWTs. Users receive the `member` global role on registration; project roles are owner, editor and viewer. Promote trusted operators to global `admin` through a controlled database/operations process.

## Tests

Install the development dependencies with `pip install -r requirements-dev.txt`, then run `./run_tests.sh` (or `pytest -q`) for the complete backend suite. The suite is split into `unit`, `repo`, `integration`, and `contract` groups; `./run_tests.sh coverage` writes a coverage report under `var/coverage_html`.

`./run_tests.sh` takes an optional mode and forwards any remaining arguments to pytest:

```bash
./run_tests.sh                 # whole suite
./run_tests.sh unit            # tests/unit only
./run_tests.sh repo            # tests/repositories only
./run_tests.sh integration     # tests/integration only
./run_tests.sh contract        # tests/contract only
./run_tests.sh coverage        # whole suite + HTML coverage in var/coverage_html
./run_tests.sh all -q          # extra pytest args go after the mode
```

API tests use an isolated in-memory SQLite database, reset process-local rate-limit state between tests, and stub AI engine calls (`mock_ai_generate`, `mock_ai_ingest`, `mock_ai_ingest_failed` in `tests/conftest.py` — the ingest mocks implement the 202-job contract). Unit tests cover the backend's AI client HTTP contract without contacting a running AI engine.

GitHub Actions runs the backend suite on every push and pull request, publishes JUnit and coverage XML as an artifact, and summarizes test and line-coverage results in the workflow run. A separate PostgreSQL job applies Alembic migrations and runs repository, API integration, and contract tests against a disposable PostgreSQL database. The workflow reports validation status; whether a passing check is required before merge is controlled separately by repository branch-protection settings.
