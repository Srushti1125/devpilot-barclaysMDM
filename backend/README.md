# DevPilot backend

FastAPI service for users, project access, requirement uploads, generated artifacts, history, evaluation, exports and audit records. The AI engine remains a separate service.

## Run locally

From this directory, create a virtual environment and install `requirements.txt`. Copy `.env.example` to `.env`, set a strong `JWT_SECRET_KEY`, and provide a PostgreSQL URL. Create the database, then run `alembic upgrade head` and `uvicorn app.main:app --reload --port 8000`. Interactive API docs are at `/docs`.

For a disposable local SQLite setup only, set `AUTO_CREATE_TABLES=true`; production deployments should run migrations and leave it false. PostgreSQL is the intended shared application database. Enable `pgvector` in the database used by the AI engine as described in `../ai-engine/GUIDE.md` (the backend's own tables do not require the extension).

## Environment

`DATABASE_URL` (e.g. `postgresql+psycopg://user:password@localhost:5432/devpilot`), `JWT_SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `AI_ENGINE_URL` (default `http://localhost:8001`), `UPLOAD_DIR`, `CORS_ORIGINS` (comma separated), `AUTO_CREATE_TABLES`, and `LOG_LEVEL`. The AI engine separately needs its own keys and vector database configuration; consult its GUIDE.

## AI engine integration

`app/services/ai_engine.py` uses async HTTP requests to `/health`, `/artifact-types`, `/generate` and `/ingest`. Generation results are validated and stored as artifacts with request ID, prompt version, usage, latency and requirement text in history and audit tables. Requirement uploads are capped at 10 MB, stored beneath `UPLOAD_DIR`, and their absolute path is sent to the engine's `/ingest` endpoint. This assumes both services can read the same upload directory (mount it into both containers when containerized).

## API overview

- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`
- `GET /api/v1/artifact-types`
- Project CRUD: `GET/POST /api/v1/projects`, `GET/PATCH/DELETE /api/v1/projects/{id}`, and `POST /api/v1/projects/{id}/members?email=...&role=viewer|editor`
- Requirements: `POST/GET /api/v1/projects/{id}/requirements` (multipart file upload), `GET /api/v1/requirements/{id}`
- Generation and artifacts: `POST /api/v1/projects/{id}/generate`, `GET /api/v1/projects/{id}/artifacts`, `GET/PATCH /api/v1/artifacts/{id}`
- History and evaluations: `GET /api/v1/projects/{id}/history`, `POST/GET /api/v1/artifacts/{id}/evaluations`
- Export and audit: `GET /api/v1/artifacts/{id}/export?format=json`, admin-only `GET /api/v1/audit-logs`
- `GET /health`

Access tokens are bearer JWTs. Users receive the `member` global role on registration; project roles are owner, editor and viewer. Promote trusted operators to global `admin` through a controlled database/operations process.

## Tests

Install `pytest` and `httpx`, then run `pytest -q`. The API tests use an isolated in-memory SQLite database and stub the AI engine generation call.
