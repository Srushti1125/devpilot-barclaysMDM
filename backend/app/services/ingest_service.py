"""
Shared async requirement-ingestion logic (IMPLEMENTATION.draft.md §2.2.4).

Used by the live routes in app/main.py so both endpoints speak one contract:
upload -> 202 {ingest_job_id} -> poll -> on first terminal state persist chunks
count + doc_tree_nodes (idempotent).

The engine contract (ai-engine/app/main.py):
  POST /ingest            -> {job_id, status:"processing"}
  GET  /ingest/{job_id}   -> {..., status: done|failed, chunks_indexed, content_hash, tree_nodes}
"""
import logging
import os
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.domain.models import AuditLog, DocTreeNode, IngestJob, Requirement, User
from app.services.ai_engine import AIEngineClient

logger = logging.getLogger("devpilot.backend.ingest")

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".pptx", ".xlsx", ".html"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".html"}


async def create_ingest_job(db: Session, *, project_id: str, user: User,
                            data: bytes, filename: str, doc_type: str, upload_dir: str):
    """Validate, persist the upload, start the engine job, register Requirement + IngestJob.

    Raises HTTPException 415/413 for bad input; on engine failure the stored file is
    cleaned up and the error propagates (same behavior as the routes before extraction).
    Commits on success and returns (requirement, job).
    """
    clean_name = Path(filename or "requirement.txt").name
    suffix = Path(clean_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported requirement file type")
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Requirement file exceeds 10 MB")

    os.makedirs(upload_dir, exist_ok=True)
    path = Path(upload_dir) / f"{uuid.uuid4()}{suffix}"
    path.write_bytes(data)
    content = data.decode("utf-8", errors="replace") if suffix in TEXT_SUFFIXES else ""

    requirement_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    try:
        accepted = await AIEngineClient().ingest(str(path.resolve()), project_id, doc_type,
                                                 doc_id=requirement_id)
    except Exception:
        path.unlink(missing_ok=True)
        raise

    record = Requirement(id=requirement_id, project_id=project_id, uploaded_by=user.id,
                         filename=clean_name, file_path=str(path), content=content,
                         doc_type=doc_type, chunks_indexed=0)
    db.add(record)
    db.flush()  # parent row first: ingest_jobs.requirement_id FK (enforced on PostgreSQL)
    job = IngestJob(id=job_id, requirement_id=requirement_id,
                    engine_job_id=accepted.get("job_id", ""), status="processing")
    db.add(job)
    db.add(AuditLog(id=str(uuid.uuid4()), user_id=user.id, action="requirement.ingest",
                    resource_type="requirement", resource_id=record.id,
                    details={"filename": clean_name, "ingest_job_id": job_id, "status": "processing"}))
    db.commit()
    return record, job


def finalize_ingest_job(db: Session, job: IngestJob, state: dict) -> IngestJob:
    """Persist a finished engine job: chunks count + tree nodes (parents-first order,
    matching the engine, so the parent_id self-FK inserts cleanly). Idempotent:
    re-running with the same terminal payload changes nothing."""
    requirement = db.get(Requirement, job.requirement_id)
    if state.get("status") == "done" and requirement is not None:
        job.status = "done"
        job.chunks_indexed = int(state.get("chunks_indexed", 0))
        requirement.chunks_indexed = job.chunks_indexed
        for node in state.get("tree_nodes", []):
            if db.get(DocTreeNode, node["node_id"]) is not None:
                continue
            db.add(DocTreeNode(
                id=node["node_id"], project_id=requirement.project_id, doc_id=requirement.id,
                parent_id=node.get("parent_id"), ordinal=node["ordinal"], level=node["level"],
                title=node["title"][:512], page_start=node.get("page_start"),
                page_end=node.get("page_end"), text=node.get("text", ""),
                low_structure=bool(node.get("low_structure", False)),
                content_hash=state.get("content_hash", ""),
            ))
    elif state.get("status") == "failed":
        job.status = "failed"
        job.error_message = str(state.get("error", "unknown ingestion error"))[:2000]
        if requirement and requirement.file_path:
            Path(requirement.file_path).unlink(missing_ok=True)
    return job


async def poll_and_finalize(db: Session, job: IngestJob) -> IngestJob:
    """Refresh a processing job from the engine; persist results on first terminal state."""
    if job.status == "processing":
        state = await AIEngineClient().ingest_status(job.engine_job_id)
        finalize_ingest_job(db, job, state)
        db.commit()
        db.refresh(job)
    return job
