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

# 2. Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1   # On Windows
# source venv/bin/activate    # On Linux/macOS

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

### C. Ingest Document (RAG Ingestion)
* **Endpoint:** `POST /ingest`
* **Description:** Person 2 saves uploaded documents (`.txt`, `.docx`, `.pdf`) and forwards the file path to this endpoint. The AI Engine parses the file, creates 768-dim embeddings (`gemini-embedding-001`), and stores chunks in PostgreSQL via `pgvector`.
* **Request:**
  ```json
  {
    "file_path": "E:/DEVPILOT/ai-engine/sample_docs/sample_requirements.txt",
    "project_id": "proj_test_123",
    "doc_type": "requirement"
  }
  ```
* **Response:**
  ```json
  {
    "chunks_indexed": 42,
    "project_id": "proj_test_123",
    "doc_type": "requirement"
  }
  ```

---

### D. Generate SDLC Artifact
* **Endpoint:** `POST /generate`
* **Description:** Runs the complete `Requirement -> Vector RAG Context -> Prompt -> Groq LLM -> Schema Validation -> Quality Check` pipeline.
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
    "latency_ms": 8250
  }
  ```

---

## 4. Integration Instructions by Team Member

### 🎨 Person 1 (Frontend & Dashboard)
1. **Dropdown Lists:** Query your backend for `GET /artifact-types` to dynamically render artifact options.
2. **Rendering Outputs:** The `output` payload inside each `/generate` response contains structured JSON formatted according to the selected artifact type.
3. **Telemetry UI:** Render metadata badges for `latency_ms`, `usage.total_tokens`, and `prompt_version` on the artifact generation screen.

### ⚙️ Person 2 (Backend & Platform APIs)
1. **Enable pgvector:** Run `CREATE EXTENSION IF NOT EXISTS vector;` on your PostgreSQL database instance.
2. **Proxy Calls:** Forward frontend generation requests to `POST http://localhost:8001/generate`.
3. **Persistence:**
   * Store `output` in your `artifacts` table.
   * Store `request_id`, `prompt_version`, `usage.total_tokens`, and `latency_ms` in your `generation_history` / `audit_logs` table.

### 🏗️ Person 4 (SDLC Artifact Generation Engine)
1. **Schema Customization:** All Pydantic validation models live in `app/schemas/`. You can extend fields for any artifact type here.
2. **Prompt Tuning:** Prompt templates live in `app/prompts/templates/`. Modifying prompt wording automatically adjusts LLM generation behavior while retaining schema validation.

### 📊 Person 5 (Evaluation + AI Assistant + Case Study)
1. **Evaluation Metrics:** Use `app/pipeline/quality_check.py` functions (`format_compliance_score()`, `consistency_score()`) for prompt benchmark evaluations.
2. **Telemetry:** Use `prompt_version` and `usage` data from the response to measure token cost and latency trade-offs between prompt iterations.
3. **Conversational Assistant (UC-14):** Query the vector store collection (`devpilot_requirements`) filtered by `project_id` to retrieve context for user questions.

### 🔐 Person 6 (Testing + Security + DevOps)
1. **CI Smoke Tests:** Run tests without secrets using:
   ```bash
   pip install pytest
   pytest tests/ -q
   ```
2. **Dockerization:** Build and deploy using the root `Dockerfile`.
3. **Secrets:** Inject `GROQ_API_KEY`, `GOOGLE_API_KEY`, and `DATABASE_URL` via environment variables or cloud secrets management.
