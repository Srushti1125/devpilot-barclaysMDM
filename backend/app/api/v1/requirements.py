"""
Requirement Ingestion API endpoints (UC-01).
"""

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_project_service
from app.config import settings
from app.core.exceptions import AuthorisationError, ResourceNotFoundError
from app.models import AuditLog, Requirement, User
from app.services.ai_engine import AIEngineClient
from app.services.project_service import ProjectService

router = APIRouter(tags=["Requirements"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".pptx", ".xlsx", ".html"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/projects/{project_id}/requirements", status_code=status.HTTP_201_CREATED)
async def ingest_requirement(
    project_id: str,
    file: UploadFile = File(...),
    doc_type: str = "requirement",
    db: Session = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    try:
        project_service.get_project_or_fail(project_id, user, write=True)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    filename = Path(file.filename or "requirement.txt").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported requirement file type",
        )

    data = await file.read(MAX_FILE_SIZE + 1)
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Requirement file exceeds 10 MB",
        )

    os.makedirs(settings.upload_dir, exist_ok=True)
    path = Path(settings.upload_dir) / f"{uuid.uuid4()}{suffix}"
    path.write_bytes(data)

    content = data.decode("utf-8", errors="replace") if suffix in {".txt", ".md", ".csv", ".html"} else ""
    try:
        result = await AIEngineClient().ingest(str(path.resolve()), project_id, doc_type)
    except Exception:
        path.unlink(missing_ok=True)
        raise

    record = Requirement(
        id=str(uuid.uuid4()),
        project_id=project_id,
        uploaded_by=user.id,
        filename=filename,
        file_path=str(path),
        content=content,
        doc_type=doc_type,
        chunks_indexed=result.get("chunks_indexed", 0),
    )
    db.add(record)
    db.add(
        AuditLog(
            id=str(uuid.uuid4()),
            user_id=user.id,
            action="requirement.ingest",
            resource_type="requirement",
            resource_id=record.id,
            details={"filename": filename, "chunks_indexed": record.chunks_indexed},
        )
    )
    db.commit()
    return {"id": record.id, "filename": filename, "project_id": project_id, **result}


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
