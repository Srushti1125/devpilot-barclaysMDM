"""
Async ingestion endpoints (§2.2.4).
"""

import logging
import threading
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.ingestion import pipeline
from app.retrieval import vectorstore

logger = logging.getLogger("devpilot.ai_engine")

router = APIRouter(tags=["Ingest"])


class IngestRequest(BaseModel):
    file_path: str
    project_id: str
    doc_type: str = "requirement"
    doc_id: str | None = None


class IngestAccepted(BaseModel):
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
        prepared = pipeline.prepare_document(req.file_path, req.project_id, req.doc_type, req.doc_id)
        chunks = vectorstore.index_chunks(prepared.chunks)
        _job_update(
            job_id,
            status="done",
            chunks_indexed=chunks,
            project_id=req.project_id,
            doc_type=req.doc_type,
            doc_id=prepared.doc_id,
            content_hash=prepared.content_hash,
            tree_nodes=[pipeline.node_to_dict(node) for node in prepared.tree_nodes],
        )
    except FileNotFoundError as e:
        _job_update(job_id, status="failed", error=str(e), error_type="file_not_found")
    except ValueError as e:
        _job_update(job_id, status="failed", error=str(e), error_type="invalid_input")
    except Exception as e:
        logger.exception("Ingestion job %s failed", job_id)
        _job_update(job_id, status="failed", error=str(e), error_type=type(e).__name__)


@router.post("/ingest", response_model=IngestAccepted, status_code=202)
def ingest(req: IngestRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _ingest_jobs[job_id] = {"status": "processing", "project_id": req.project_id,
                                "doc_id": req.doc_id, "doc_type": req.doc_type}
    _prune_jobs()
    background_tasks.add_task(_run_ingest, job_id, req)
    return IngestAccepted(job_id=job_id)


@router.get("/ingest/{job_id}")
def ingest_status(job_id: str):
    with _jobs_lock:
        job = _ingest_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown ingest job '{job_id}'")
        return {"job_id": job_id, **job}
