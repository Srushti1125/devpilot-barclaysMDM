"""
Generation, streaming, comparison, chat, case-study, traceability, and stats endpoints.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    get_case_study_service,
    get_chat_service,
    get_current_user,
    get_db,
    get_project_service,
    get_project_stats_service,
)
from app.core.exceptions import AIEngineError, ValidationError
from app.domain.models import Artifact, GenerationHistory, Requirement, User
from app.domain.schemas import GenerateRequest
from app.services.ai_engine import AIEngineClient
from app.services.case_study_service import CaseStudyService
from app.services.chat_service import ChatService
from app.services.project_service import ProjectService
from app.services.project_stats_service import ProjectStatsService

router = APIRouter(tags=["Generation"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)

    @field_validator("message")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message cannot be blank")
        return value.strip()


@router.post("/projects/{project_id}/requirements/text", status_code=202)
async def ingest_requirement_text(
    project_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    from app.config import settings
    from app.services import ingest_service

    content = payload.get("content")
    if not isinstance(content, str) or not 10 <= len(content) <= 50_000:
        raise HTTPException(status_code=422, detail="content must contain 10 to 50000 characters")
    doc_type = payload.get("doc_type", "requirement")
    if not isinstance(doc_type, str) or not doc_type.strip():
        raise HTTPException(status_code=422, detail="doc_type must be a non-empty string")
    try:
        project_service.get_project_or_fail(project_id, user, write=True)
    except Exception:
        raise HTTPException(status_code=403, detail="Access denied")
    record, job = await ingest_service.create_ingest_job(
        db, project_id=project_id, user=user, data=content.encode("utf-8"),
        filename="requirement.txt", doc_type=doc_type, upload_dir=settings.upload_dir)
    return {"id": record.id, "filename": record.filename, "project_id": project_id,
            "ingest_job_id": job.id, "status": job.status}


@router.get("/projects/{project_id}/stats")
def project_stats(
    project_id: str,
    stats_service: ProjectStatsService = Depends(get_project_stats_service),
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    try:
        project_service.get_project_or_fail(project_id, user)
    except Exception:
        raise HTTPException(status_code=403, detail="Access denied")
    return stats_service.get_project_stats(project_id)


@router.post("/projects/{project_id}/generate/stream", responses={502: {"description": "AI engine stream failed"}})
async def generate_stream(
    project_id: str,
    payload: GenerateRequest,
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    """Proxy the SOP graph's SSE node-transition stream."""
    try:
        project_service.get_project_or_fail(project_id, user, write=True)
    except Exception:
        raise HTTPException(status_code=403, detail="Access denied")
    stream = await AIEngineClient().stream_generate(project_id, payload.artifact_type, payload.requirement_text)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/projects/{project_id}/compare", responses={502: {"description": "AI engine returned an invalid response"}})
async def compare_llms(
    project_id: str,
    payload: GenerateRequest,
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    """Multi-LLM comparison for the dashboard. Transient by design."""
    try:
        project_service.get_project_or_fail(project_id, user, write=True)
    except Exception:
        raise HTTPException(status_code=403, detail="Access denied")
    return await AIEngineClient().generate_compare(project_id, payload.artifact_type, payload.requirement_text)


@router.post("/projects/{project_id}/chat", status_code=201)
async def chat(
    project_id: str,
    payload: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service),
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    try:
        project_service.get_project_or_fail(project_id, user, write=True)
    except Exception:
        raise HTTPException(status_code=403, detail="Access denied")
    try:
        return await chat_service.send_message(project_id, payload.message, user)
    except AIEngineError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/projects/{project_id}/chat")
def chat_history(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    chat_service: ChatService = Depends(get_chat_service),
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    try:
        project_service.get_project_or_fail(project_id, user)
    except Exception:
        raise HTTPException(status_code=403, detail="Access denied")
    return chat_service.history(project_id, limit)


@router.post("/projects/{project_id}/case-study")
async def run_case_study(
    project_id: str,
    limit: int = Query(10, ge=1, le=10),
    case_study_service: CaseStudyService = Depends(get_case_study_service),
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    """Generate the six supported artifact types for each selected requirement."""
    try:
        project_service.get_project_or_fail(project_id, user, write=True)
    except Exception:
        raise HTTPException(status_code=403, detail="Access denied")
    try:
        return await case_study_service.generate(project_id, limit, user)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/projects/{project_id}/case-study/compare")
async def compare_case_study(
    project_id: str,
    requirement_id: str,
    artifact_type: str = "user_story",
    db: Session = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    try:
        project_service.get_project_or_fail(project_id, user, write=True)
    except Exception:
        raise HTTPException(status_code=403, detail="Access denied")
    requirement = db.get(Requirement, requirement_id)
    if not requirement or requirement.project_id != project_id:
        raise HTTPException(status_code=404, detail="Requirement not found")
    text_value = (requirement.content or "").strip() or requirement.filename
    return await AIEngineClient().generate_compare(project_id, artifact_type, text_value)


@router.get("/projects/{project_id}/traceability")
def traceability_matrix(
    project_id: str,
    db: Session = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    """React Flow-compatible nodes+edges: requirement -> artifact chains."""
    try:
        project_service.get_project_or_fail(project_id, user)
    except Exception:
        raise HTTPException(status_code=403, detail="Access denied")

    requirements = db.scalars(
        select(Requirement).where(Requirement.project_id == project_id)
    ).all()
    artifacts = db.scalars(
        select(Artifact).where(Artifact.project_id == project_id)
    ).all()
    histories = db.scalars(
        select(GenerationHistory).where(GenerationHistory.project_id == project_id)
    ).all()

    nodes = (
        [
            {
                "id": f"req-{r.id}",
                "type": "requirement",
                "data": {"label": r.filename, "doc_type": r.doc_type},
                "position": {"x": 0, "y": 0},
            }
            for r in requirements
        ]
        + [
            {
                "id": f"art-{a.id}",
                "type": a.artifact_type,
                "data": {"label": a.title, "version": a.version},
                "position": {"x": 0, "y": 0},
            }
            for a in artifacts
        ]
    )
    edges = [
        {
            "id": f"e-{h.requirement_id}-{h.artifact_id}",
            "source": f"req-{h.requirement_id}",
            "target": f"art-{h.artifact_id}",
        }
        for h in histories
        if h.requirement_id
    ]
    return {"nodes": nodes, "edges": edges}


@router.get("/artifacts/{artifact_id}/sprint-analysis")
def sprint_analysis(
    artifact_id: str,
    db: Session = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    from app.services.sprint_analysis import analyze_sprint_plan

    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        project_service.get_project_or_fail(artifact.project_id, user)
    except Exception:
        raise HTTPException(status_code=403, detail="Access denied")
    if artifact.artifact_type != "sprint_plan":
        raise HTTPException(status_code=422, detail="Artifact is not a sprint plan")
    return analyze_sprint_plan(artifact.content or {})
