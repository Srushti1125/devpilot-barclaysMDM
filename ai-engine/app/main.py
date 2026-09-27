"""
Run locally: uvicorn app.main:app --reload --port 8001
"""
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.ingestion.loaders import load_requirement_doc
from app.ingestion.splitters import chunk_documents
from app.pipeline.chain import run_generation
from app.retrieval.vectorstore import index_chunks
from app.schemas.registry import SCHEMA_REGISTRY, get_schema
from app.tracking.usage import record_request

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger("devpilot.ai_engine")

app = FastAPI(
    title="DevPilot AI Engine",
    description="GenAI + RAG + Prompt Engineering service ",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    project_id: str
    artifact_type: str = Field(description=f"One of: {sorted(SCHEMA_REGISTRY.keys())}")
    requirement_text: str


class GenerateResponse(BaseModel):
    request_id: str
    artifact_type: str
    project_id: str
    prompt_version: str
    output: dict
    usage: dict
    latency_ms: int


class IngestRequest(BaseModel):
    file_path: str
    project_id: str
    doc_type: str = "requirement"


class IngestResponse(BaseModel):
    chunks_indexed: int
    project_id: str
    doc_type: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "default_llm": settings.DEFAULT_LLM}


@app.get("/artifact-types")
def artifact_types():
    return {"artifact_types": sorted(SCHEMA_REGISTRY.keys())}


@app.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest):
    try:
        docs = load_requirement_doc(req.file_path, req.project_id, req.doc_type)
        chunks = chunk_documents(docs)
        n = index_chunks(chunks)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Ingestion failed for project_id=%s", req.project_id)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")

    return IngestResponse(chunks_indexed=n, project_id=req.project_id, doc_type=req.doc_type)


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    try:
        schema_cls = get_schema(req.artifact_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    quota_state = record_request()
    if quota_state["quota_exceeded"]:
        logger.warning("Proceeding despite exceeded quota guardrail (soft limit, not enforced).")

    request_id = str(uuid.uuid4())
    start = time.monotonic()
    try:
        result = run_generation(req.artifact_type, req.project_id, req.requirement_text, schema_cls)
    except RuntimeError as e:
        # generate_with_quality_check exhausted retries + fallback
        raise HTTPException(status_code=502, detail=f"LLM generation failed validation: {e}")
    except Exception as e:
        logger.exception("Generation failed for project_id=%s artifact_type=%s", req.project_id, req.artifact_type)
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    latency_ms = int((time.monotonic() - start) * 1000)

    return GenerateResponse(
        request_id=request_id,
        artifact_type=result["artifact_type"],
        project_id=result["project_id"],
        prompt_version=result["prompt_version"],
        output=result["output"],
        usage=result["usage"],
        latency_ms=latency_ms,
    )
