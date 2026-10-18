# DevPilot AI Engine — Integration & Developer Guide

**Service:** `ai-engine` (Person 3: GenAI + RAG + Prompt Engineering)  
**Port:** `8001` (HTTP REST API)  
**Status:** Tested & Production Ready ✅  

---

## 1. Quickstart (Running the AI Engine)

### Prerequisites
* Python 3.10+
* PostgreSQL with `pgvector` extension enabled
* Free API Keys: **Groq API Key** (for fast LLM inference) + **Google Gemini API Key** (for embeddings)

### Setup & Run Locally
```bash
# 1. Navigate to the ai-engine directory
cd ai-engine

# 2. Create and activate virtual environment (AGENTS.md convention: .venv)
python -m venv .venv
source .venv/bin/activate      # On Linux/macOS
# .venv\Scripts\Activate.ps1   # On Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create your .env file
copy .env.example .env

# 5. Start the FastAPI server
uvicorn app.main:app --reload --port 8001
```

### Run with Docker (For Person 6 / Deployment)
```bash
docker build -t devpilot-ai-engine .
docker run -p 8001:8001 --env-file .env devpilot-ai-engine
```

### Run the whole local stack (recommended)

From the repository root, `tools/run_stack.sh` brings up the pgvector Postgres container (host port 5433), applies migrations, starts **this engine** on `:8001` (from `ai-engine/.venv`) and the backend on `:8000`, then the Streamlit dev UI on `:8501`.

```bash
tools/run_stack.sh --no-ui    # engine + backend + db only, no UI
tools/run_stack.sh --status   # what's running
tools/run_stack.sh --stop     # stop the services the script started
```

Prerequisites: Docker running, `ai-engine/.venv` installed (`pip install -r requirements.txt`), `ai-engine/.env` filled in (see §2), and a valid `backend/.env`. Full details in `../backend/README.md`.

---

## 2. Environment Variables Configuration (`.env`)

```env
# Database (PostgreSQL RDS/Local with pgvector extension)
DATABASE_URL=postgresql+psycopg://<user>:<password>@localhost:5432/<database_name>

# LLM Providers
GROQ_API_KEY=gsk_your_groq_api_key_here
GOOGLE_API_KEY=AIzaSy_your_gemini_api_key_here

# Model Selection
DEFAULT_LLM=groq-openai/gpt-oss-120b
FALLBACK_LLM=gemini-2.5-flash

# Evaluation & retrieval extras (all optional, graceful defaults)
EVAL_JUDGE_LLM=              # online LLM-as-Judge model; defaults to FALLBACK_LLM
COHERE_API_KEY=              # cloud reranking (§2.2.3); absent = plain MMR
RETRIEVAL_MODE=vector        # vector | hybrid (flip only after §2.3.6 ship run)

# Service Config
AI_ENGINE_PORT=8001
LOG_LEVEL=INFO
COLLECTION_NAME=devpilot_requirements
```

---

## 3. Core API Endpoints

### A. Health Check
* **Endpoint:** `GET /health`
* **Description:** Liveness probe for Person 2 & Person 6.
* **Response:**
  ```json
  {
    "status": "ok",
    "default_llm": "groq-openai/gpt-oss-120b"
  }
  ```

---

### B. List Supported Artifact Types
* **Endpoint:** `GET /artifact-types`
* **Description:** Use this to dynamically populate dropdown menus on Person 1's frontend.
* **Response:**
  ```json
  {
    "artifact_types": [
      "acceptance_criteria",
      "api_spec",
      "architecture",
      "sprint_plan",
      "test_case",
      "user_story"
    ]
  }
  ```

---

### C. Ingest Document (RAG Ingestion) — ASYNC (202 + job)
* **Endpoint:** `POST /ingest` → `202 {"job_id": "...", "status": "processing"}`; poll `GET /ingest/{job_id}`
* **Description:** Person 2 saves uploaded documents (`.txt`, `.docx`, `.pdf`) and forwards the file path plus its chosen `doc_id` (the requirement id) to this endpoint. Parsing/indexing runs in a background task so the engine's event loop stays free; the terminal job result carries `tree_nodes` for the backend to persist into `doc_tree_nodes`. Jobs are in-process only — a poll after an engine restart maps to a terminal `failed`. The AI Engine parses the file, creates 768-dim embeddings (`gemini-embedding-001`), and stores chunks in PostgreSQL via `pgvector`.
* **Request:**
  ```json
  {
    "file_path": "/shared/uploads/requirements.pdf",
    "project_id": "proj_test_123",
    "doc_type": "requirement",
    "doc_id": "req-uuid-chosen-by-backend"
  }
  ```
* **Completed job (`GET /ingest/{job_id}`):**
  ```json
  {
    "job_id": "...",
    "status": "done",
    "chunks_indexed": 42,
    "project_id": "proj_test_123",
    "doc_type": "requirement",
    "doc_id": "req-uuid-chosen-by-backend",
    "content_hash": "sha256...",
    "tree_nodes": [ "...parents-first, for doc_tree_nodes persistence..." ]
  }
  ```

### D. Generate SDLC Artifact (SOP Swarm)
* **Endpoint:** `POST /generate`
* **Description:** Runs the LangGraph SOP pipeline `Retrieve (once) -> PM draft (Groq) -> QA: schema check + inline LLM-as-Judge -> revise|finalize` (≤2 revisions; best draft accepted on exhaustion). Response now carries `eval_score`, `retry_count`, `model_used`. Siblings: `POST /generate/stream` (SSE node transitions) and `POST /generate/compare` (parallel DEFAULT vs FALLBACK models), plus `POST /evaluate/batch` (offline RAGAS harness; admin-gated at the backend).
* **Request:**
  ```json
  {
    "project_id": "proj_test_123",
    "artifact_type": "api_spec",
    "requirement_text": "The system shall allow users to reset their password via email."
  }
  ```
* **Sample Verified Output (`api_spec`):**
  ```json
  {
    "request_id": "d2ce901b-34cc-42fa-80ca-c7fbaacb9afc",
    "artifact_type": "api_spec",
    "project_id": "proj_test_123",
    "prompt_version": "api_spec_v1",
    "output": {
      "endpoints": [
        {
          "method": "POST",
          "path": "/auth/password-reset/request",
          "description": "Initiate a password reset by sending a reset token to the user's email address.",
          "request_schema": [
            {
              "name": "email",
              "type": "string",
              "required": true,
              "description": "User's registered email address"
            }
          ],
          "response_schema": [
            {
              "name": "message",
              "type": "string",
              "required": true,
              "description": "Result message indicating email was sent"
            }
          ],
          "error_codes": [
            { "code": 400, "reason": "Invalid email format" },
            { "code": 404, "reason": "User not found" },
            { "code": 500, "reason": "Internal server error" }
          ]
        },
        {
          "method": "POST",
          "path": "/auth/password-reset/confirm",
          "description": "Complete password reset using the token received via email.",
          "request_schema": [
            { "name": "token", "type": "string", "required": true, "description": "Password reset token" },
            { "name": "new_password", "type": "string", "required": true, "description": "New password" },
            { "name": "confirm_password", "type": "string", "required": true, "description": "Confirmation of the new password" }
          ],
          "response_schema": [
            { "name": "message", "type": "string", "required": true, "description": "Result message indicating password reset success" }
          ],
          "error_codes": [
            { "code": 400, "reason": "Invalid token or password does not meet policy" },
            { "code": 401, "reason": "Token expired or unauthorized" },
            { "code": 404, "reason": "User not found" },
            { "code": 500, "reason": "Internal server error" }
          ]
        }
      ]
    },
    "usage": {
      "prompt_tokens": 727,
      "completion_tokens": 1196,
      "total_tokens": 1923,
      "total_cost_usd": 0.0
    },
    "latency_ms": 8250,
    "eval_score": 0.92,
    "retry_count": 0,
    "model_used": "groq-openai/gpt-oss-120b"
  }
  ```

---

## 4. Integration Instructions by Team Member

### 🎨 Person 1 (Frontend & Dashboard)
1. **Dropdown Lists:** Query your backend for `GET /artifact-types` to dynamically render artifact options.
2. **Rendering Outputs:** The `output` payload inside each `/generate` response contains structured JSON formatted according to the selected artifact type.
3. **Telemetry UI:** Render metadata badges for `latency_ms`, `usage.total_tokens`, `prompt_version`, `eval_score`, `retry_count` and `model_used` on the artifact generation screen. Live agent progress via the backend's SSE proxy (`POST /api/v1/projects/{id}/generate/stream`, fetch + ReadableStream with the bearer header).

### ⚙️ Person 2 (Backend & Platform APIs)
1. **Enable pgvector:** Run `CREATE EXTENSION IF NOT EXISTS vector;` on your PostgreSQL database instance.
2. **Proxy Calls:** Generation is proxied via `POST http://localhost:8001/generate` (SOP swarm); uploads go to `POST /ingest` (202 job) and are polled via `GET /ingest/{job_id}`; the backend tracks state per requirement in `ingest_jobs`.
3. **Persistence:**
   * Store `output` in your `artifacts` table.
   * Store `request_id`, `prompt_version`, `usage.total_tokens`, `latency_ms`, `eval_score`, `retry_count`, `model_used` and optional `requirement_id` in `generation_history` / `audit_logs`.

### 🏗️ Person 4 (SDLC Artifact Generation Engine)
1. **Schema Customization:** All Pydantic validation models live in `app/schemas/`. You can extend fields for any artifact type here.
2. **Prompt Tuning:** Prompt templates live in `app/prompts/templates/`. Modifying prompt wording automatically adjusts LLM generation behavior while retaining schema validation.

### 📊 Person 5 (Evaluation + AI Assistant + Case Study)
1. **Evaluation Metrics:** Use `app/pipeline/quality_check.py` functions (`format_compliance_score()`, `consistency_score()`) for prompt benchmark evaluations.
2. **Telemetry:** Use `prompt_version` and `usage` data from the response to measure token cost and latency trade-offs between prompt iterations.
3. **Conversational Assistant (UC-14):** Query the vector store collection (`devpilot_requirements`) filtered by `project_id` to retrieve context for user questions.

### 🔐 Person 6 (Testing + Security + DevOps)
1. **CI Tests:** `.github/workflows/ai-engine-tests.yml` runs the offline suite on every push/PR — no secrets needed (key validation never executes at import; LLM/retrieval are fake-patched). From `ai-engine/`, install development dependencies first (`pip install -r requirements-dev.txt`), then:

   ```bash
   ./run_tests.sh                              # whole offline suite (pytest tests/ -q)
   ./run_tests.sh coverage                     # whole suite + HTML coverage in var/coverage_html
   ./run_tests.sh tests/test_sop_graph.py -q   # pass-through: any pytest args after the script name
   ```
2. **Dockerization:** Build and deploy using the root `Dockerfile`.
3. **Secrets:** Inject `GROQ_API_KEY`, `GOOGLE_API_KEY`, and `DATABASE_URL` via environment variables or cloud secrets management.
