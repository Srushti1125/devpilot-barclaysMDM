"""
Artifact generation, update, evaluation, and export API endpoints.
"""

import io
import json
import zipfile
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_artifact_service, get_current_user, get_db
from app.core.exceptions import AuthorisationError, ResourceNotFoundError, ValidationError
from app.domain.models import Requirement, User
from app.domain.schemas import ArtifactOut, ArtifactUpdate, EvaluationCreate, GenerateRequest
from app.services.ai_engine import AIEngineClient
from app.services.artifact_export import render_artifact_export
from app.services.artifact_service import ArtifactService

router = APIRouter(tags=["Artifacts"])


@router.get("/artifact-types")
async def artifact_types(user: User = Depends(get_current_user)):
    return await AIEngineClient().artifact_types()


@router.post("/projects/{project_id}/generate", response_model=ArtifactOut, status_code=status.HTTP_201_CREATED)
async def generate(
    project_id: str,
    payload: GenerateRequest,
    artifact_service: ArtifactService = Depends(get_artifact_service),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        if payload.requirement_id:
            requirement = db.get(Requirement, payload.requirement_id)
            if not requirement or requirement.project_id != project_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found in this project")
        return await artifact_service.generate(
            project_id=project_id,
            artifact_type=payload.artifact_type,
            requirement_text=payload.requirement_text,
            user=user,
            requirement_id=payload.requirement_id,
        )
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/projects/{project_id}/artifacts", response_model=list[ArtifactOut])
def list_artifacts(
    project_id: str,
    artifact_service: ArtifactService = Depends(get_artifact_service),
    user: User = Depends(get_current_user),
):
    try:
        return artifact_service.list_for_project(project_id, user)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get("/artifacts/{artifact_id}", response_model=ArtifactOut)
def read_artifact(
    artifact_id: str,
    artifact_service: ArtifactService = Depends(get_artifact_service),
    user: User = Depends(get_current_user),
):
    try:
        return artifact_service.get(artifact_id, user)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.patch("/artifacts/{artifact_id}", response_model=ArtifactOut)
def update_artifact(
    artifact_id: str,
    payload: ArtifactUpdate,
    artifact_service: ArtifactService = Depends(get_artifact_service),
    user: User = Depends(get_current_user),
):
    try:
        updates = payload.model_dump(exclude_unset=True)
        return artifact_service.update(artifact_id, updates, user)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post("/artifacts/{artifact_id}/evaluations", status_code=status.HTTP_201_CREATED)
def evaluate_artifact(
    artifact_id: str,
    payload: EvaluationCreate,
    artifact_service: ArtifactService = Depends(get_artifact_service),
    user: User = Depends(get_current_user),
):
    try:
        item = artifact_service.evaluate(
            artifact_id=artifact_id,
            score=payload.score,
            feedback=payload.feedback,
            metrics=payload.metrics,
            user=user,
        )
        return {
            "id": item.id,
            "artifact_id": item.artifact_id,
            "score": item.score,
            "feedback": item.feedback,
            "metrics": item.metrics,
            "created_at": item.created_at,
        }
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get("/artifacts/{artifact_id}/evaluations")
def artifact_evaluations(
    artifact_id: str,
    artifact_service: ArtifactService = Depends(get_artifact_service),
    user: User = Depends(get_current_user),
):
    try:
        return artifact_service.list_evaluations(artifact_id, user)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get("/artifacts/{artifact_id}/export")
def export_artifact(
    artifact_id: str,
    format: str = Query("json", pattern="^(?i)(json|markdown|md|csv|yaml|yml|gherkin)$"),
    artifact_service: ArtifactService = Depends(get_artifact_service),
    user: User = Depends(get_current_user),
):
    try:
        artifact = artifact_service.get(artifact_id, user)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    response = render_artifact_export(artifact, format)
    if response is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Gherkin export is only supported for acceptance_criteria artifacts",
        )
    return response


@router.get("/projects/{project_id}/artifacts/export.zip")
def export_project_artifacts_zip(
    project_id: str,
    artifact_service: ArtifactService = Depends(get_artifact_service),
    user: User = Depends(get_current_user),
):
    try:
        artifacts = artifact_service.list_for_project(project_id, user)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for artifact in artifacts:
            filename = f"{artifact.artifact_type}-{artifact.id}.json"
            archive.writestr(filename, json.dumps({
                "id": artifact.id, "project_id": artifact.project_id,
                "artifact_type": artifact.artifact_type, "title": artifact.title,
                "version": artifact.version, "content": artifact.content,
            }, indent=2))
    return Response(content=buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="project-{project_id}-artifacts.zip"'})
