"""
DevPilot AI Engine — FastAPI service (port 8001).

Run locally: uvicorn app.main:app --reload --port 8001

Endpoints (IMPLEMENTATION.draft.md §2, §3, §4):
  GET  /health            liveness
  GET  /artifact-types    dropdown population
  POST /ingest            async ingestion job (§2.2.4): returns 202 {job_id}
  GET  /ingest/{job_id}   job status; on success carries tree_nodes for backend persistence
  POST /generate          SOP swarm generation (§3.2) with online eval fields
  POST /generate/stream   SSE node-transition stream (§3.2.4)
  POST /generate/compare  parallel DEFAULT vs FALLBACK LLM run (§3.2.3)
  POST /evaluate/batch    offline RAGAS harness (§4.2 Layer 2)
"""
import asyncio
import json
import logging
import threading
import time
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.ingestion.pipeline import node_to_dict, prepare_document
from app.pipeline.sop_graph import SOP_GRAPH, run_sop_generation
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
    # "model_used" trips pydantic's protected "model_" namespace by design (it's data, not config).
    model_config = ConfigDict(protected_namespaces=())

    request_id: str
    artifact_type: str
    project_id: str
    prompt_version: str
    output: dict
    usage: dict
    latency_ms: int
    retrieval: dict | None = None  # which retrieval mode ran, fallbacks, selected nodes
    eval_score: float | None = None   # online LLM-as-Judge score (§3.2.2)
    retry_count: int = 0              # SOP revisions used
    model_used: str | None = None     # which LLM alias produced the accepted draft


class IngestRequest(BaseModel):
    file_path: str
    project_id: str
    doc_type: str = "requirement"
    # Requirement id chosen by the backend, so tree nodes and chunks reference the same document.
    doc_id: str | None = None


class IngestAccepted(BaseModel):
    """§2.2.4: /ingest is a 202 job-acknowledgement. Parse+index runs in the background
    so a 30-page Docling run never blocks the event loop for concurrent /generate calls."""
    job_id: str
    status: str = "processing"


# ---------------------------------------------------------------------------
# Ingest job registry (§2.2.4)
# ---------------------------------------------------------------------------
_ingest_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_MAX_JOBS = 1000


def _job_update(job_id: str, **fields):
    with _jobs_lock:
        job = _ingest_jobs.get(job_id)
        if job is not None:
            job.update(fields)


def _prune_jobs():
    """Cap the in-process registry; finished jobs are evicted oldest-first."""
    with _jobs_lock:
        if len(_ingest_jobs) <= _MAX_JOBS:
            return
        finished = [j for j, v in _ingest_jobs.items() if v.get("status") != "processing"]
        for job_id in finished[: len(_ingest_jobs) - _MAX_JOBS]:
            _ingest_jobs.pop(job_id, None)


def _run_ingest(job_id: str, req: IngestRequest):
    try:
        prepared = prepare_document(req.file_path, req.project_id, req.doc_type, req.doc_id)
        chunks = index_chunks(prepared.chunks)
        _job_update(
            job_id,
            status="done",
            chunks_indexed=chunks,
            project_id=req.project_id,
            doc_type=req.doc_type,
            doc_id=prepared.doc_id,
            content_hash=prepared.content_hash,
            tree_nodes=[node_to_dict(node) for node in prepared.tree_nodes],
        )
    except FileNotFoundError as e:
        _job_update(job_id, status="failed", error=str(e), error_type="file_not_found")
    except ValueError as e:
        _job_update(job_id, status="failed", error=str(e), error_type="invalid_input")
    except Exception as e:
        logger.exception("Ingestion job %s failed", job_id)
        _job_update(job_id, status="failed", error=str(e), error_type=type(e).__name__)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "default_llm": settings.DEFAULT_LLM}


@app.get("/artifact-types")
def artifact_types():
    return {"artifact_types": sorted(SCHEMA_REGISTRY.keys())}


@app.post("/ingest", response_model=IngestAccepted, status_code=202)
def ingest(req: IngestRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _ingest_jobs[job_id] = {"status": "processing", "project_id": req.project_id,
                                "doc_id": req.doc_id, "doc_type": req.doc_type}
    _prune_jobs()
    # Sync callables in BackgroundTasks run in Starlette's threadpool: the (potentially
    # minutes-long) Docling parse never occupies the event loop.
    background_tasks.add_task(_run_ingest, job_id, req)
    return IngestAccepted(job_id=job_id)


@app.get("/ingest/{job_id}")
def ingest_status(job_id: str):
    with _jobs_lock:
        job = _ingest_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown ingest job '{job_id}'")
        return {"job_id": job_id, **job}


def _checked_schema(artifact_type: str):
    try:
        return get_schema(artifact_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    schema_cls = _checked_schema(req.artifact_type)

    quota_state = record_request()
    if quota_state["quota_exceeded"]:
        logger.warning("Proceeding despite exceeded quota guardrail (soft limit, not enforced).")

    request_id = str(uuid.uuid4())
    start = time.monotonic()
    try:
        result = run_sop_generation(req.artifact_type, req.project_id, req.requirement_text, schema_cls)
    except RuntimeError as e:
        # SOP graph exhausted its budget or produced no artifact.
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
        retrieval=result.get("retrieval"),
        eval_score=result.get("eval_score"),
        retry_count=result.get("retry_count", 0),
        model_used=result.get("model_used"),
    )


@app.post("/generate/compare")
async def generate_compare(req: GenerateRequest):
    """Sprint the same requirement through DEFAULT_LLM and FALLBACK_LLM concurrently
    for the comparison dashboard (§3.2.3). One failing model never fails the request."""
    schema_cls = _checked_schema(req.artifact_type)
    record_request()

    async def _run(alias: str):
        try:
            return await asyncio.to_thread(
                run_sop_generation, req.artifact_type, req.project_id, req.requirement_text,
                schema_cls, alias,
            )
        except Exception as e:
            return {"error": str(e), "model_alias": alias}

    primary, fallback = await asyncio.gather(
        _run(settings.DEFAULT_LLM), _run(settings.FALLBACK_LLM),
    )
    return {"primary": primary, "fallback": fallback}


def _sse(payload) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


@app.post("/generate/stream")
async def generate_stream(req: GenerateRequest):
    """SSE stream of SOP node transitions (§3.2.4) — explainability in real time.
    Event order: retrieve → pm → qa [→ pm → qa ...] → finalize → done."""
    schema_cls = _checked_schema(req.artifact_type)
    record_request()

    async def event_stream():
        accumulated = {
            "artifact_type": req.artifact_type, "project_id": req.project_id,
            "requirement_text": req.requirement_text, "model_alias": settings.DEFAULT_LLM,
            "context": "", "retrieval_trace": {}, "draft_raw": "", "eval_score": 0.0,
            "critique": "", "retry_count": 0, "final_artifact": {}, "prompt_version": "",
            "usage": {}, "model_used": "",
        }
        request_id = str(uuid.uuid4())
        start = time.monotonic()
        try:
            async for update in SOP_GRAPH.astream(accumulated, stream_mode="updates"):
                for node, delta in update.items():
                    if isinstance(delta, dict):
                        accumulated.update(delta)
                    yield _sse({"node": node,
                                "retry": accumulated["retry_count"],
                                "eval_score": accumulated.get("eval_score"),
                                "critique": (delta or {}).get("critique", "") if isinstance(delta, dict) else ""})
        except Exception as e:
            logger.exception("Streaming generation failed")
            yield _sse({"error": str(e)})
            yield "data: [DONE]\n\n"
            return

        yield _sse({"node": "done", "result": GenerateResponse(
            request_id=request_id,
            artifact_type=req.artifact_type,
            project_id=req.project_id,
            prompt_version=accumulated.get("prompt_version", ""),
            output=accumulated.get("final_artifact", {}),
            usage=accumulated.get("usage", {}),
            latency_ms=int((time.monotonic() - start) * 1000),
            retrieval=accumulated.get("retrieval_trace"),
            eval_score=accumulated.get("eval_score"),
            retry_count=accumulated.get("retry_count", 0),
            model_used=accumulated.get("model_used"),
        ).model_dump()})
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/evaluate/batch")
async def evaluate_batch(project_id: str | None = None, retrieval_mode: str = "vector"):
    """Offline RAGAS harness (§4.2 Layer 2). Needs live model + DB credentials;
    exposed via the backend to admins only."""
    from app.evaluation.batch_harness import run_batch_eval

    if retrieval_mode not in ("vector", "hybrid"):
        raise HTTPException(status_code=400, detail="retrieval_mode must be vector|hybrid")
    try:
        return await asyncio.to_thread(run_batch_eval, project_id, retrieval_mode)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        # Missing provider keys / DB configuration at execution time.
        raise HTTPException(status_code=503, detail=f"Evaluation prerequisites missing: {e}")
