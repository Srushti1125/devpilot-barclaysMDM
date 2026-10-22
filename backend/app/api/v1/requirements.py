"""
Requirement Ingestion API endpoints (UC-01) — decomposed router.
NOT MOUNTED YET (Sprint 6 target per AGENTS.md). Kept current with the live async
contract in app/main.py: upload → 202 job → poll ingest-jobs → terminal state persists
chunks_indexed + doc_tree_nodes via app.services.ingest_service.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_project_service
from app.config import settings
from app.core.exceptions import AuthorisationError, ResourceNotFoundError
from app.domain.models import IngestJob, Requirement, User
from app.services import ingest_service
from app.services.project_service import ProjectService

router = APIRouter(tags=["Requirements"])


@router.post("/projects/{project_id}/requirements", status_code=status.HTTP_202_ACCEPTED,
             responses={415: {"description": "Unsupported requirement file type"},
                        413: {"description": "Requirement file exceeds 10 MB"}})
async def ingest_requirement(
    project_id: str,
    file: UploadFile = File(...),
    doc_type: str = "requirement",
    db: Session = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    """§2.2.4: uploads return 202 immediately; parse+index runs as an ai-engine job.
    Poll GET /ingest-jobs/{id} for progress."""
    try:
        project_service.get_project_or_fail(project_id, user, write=True)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    data = await file.read(ingest_service.MAX_FILE_SIZE + 1)
    record, job = await ingest_service.create_ingest_job(
        db, project_id=project_id, user=user, data=data,
        filename=file.filename or "requirement.txt", doc_type=doc_type,
        upload_dir=settings.upload_dir)
    return {"id": record.id, "filename": record.filename, "project_id": project_id,
            "ingest_job_id": job.id, "status": job.status}


@router.get("/ingest-jobs/{job_id}", responses={404: {"description": "Ingest job not found"}})
async def read_ingest_job(
    job_id: str,
    db: Session = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    """Poll the ai-engine ingest job; on first terminal state persist results (idempotent)."""
    job = db.get(IngestJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingest job not found")
    requirement = db.get(Requirement, job.requirement_id)
    if not requirement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingest job not found")
    try:
        project_service.get_project_or_fail(requirement.project_id, user)
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    job = await ingest_service.poll_and_finalize(db, job)
    return {"id": job.id, "requirement_id": job.requirement_id, "status": job.status,
            "chunks_indexed": job.chunks_indexed, "error_message": job.error_message,
            "created_at": job.created_at, "updated_at": job.updated_at}


@router.get("/projects/{project_id}/requirements")
def list_requirements(
    project_id: str,
    db: Session = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    try:
        project_service.get_project_or_fail(project_id, user)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    rows = db.scalars(
        select(Requirement)
        .where(Requirement.project_id == project_id)
        .order_by(Requirement.created_at.desc())
    )
    return [
        {
            "id": r.id,
            "filename": r.filename,
            "doc_type": r.doc_type,
            "chunks_indexed": r.chunks_indexed,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/requirements/{requirement_id}")
def read_requirement(
    requirement_id: str,
    db: Session = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    requirement = db.get(Requirement, requirement_id)
    if not requirement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found")
    try:
        project_service.get_project_or_fail(requirement.project_id, user)
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    return {
        "id": requirement.id,
        "project_id": requirement.project_id,
        "filename": requirement.filename,
        "doc_type": requirement.doc_type,
        "content": requirement.content,
        "chunks_indexed": requirement.chunks_indexed,
        "created_at": requirement.created_at,
    }
