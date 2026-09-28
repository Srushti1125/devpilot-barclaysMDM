"""
Artifact generation, update, evaluation, and export API endpoints.
"""

import json
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
import yaml

from app.api.deps import get_artifact_service, get_current_user
from app.core.exceptions import AuthorisationError, ResourceNotFoundError, ValidationError
from app.models import User
from app.schemas import ArtifactOut, ArtifactUpdate, EvaluationCreate, GenerateRequest
from app.services.ai_engine import AIEngineClient
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
    user: User = Depends(get_current_user),
):
    try:
        return await artifact_service.generate(
            project_id=project_id,
            artifact_type=payload.artifact_type,
            requirement_text=payload.requirement_text,
            user=user,
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
    format: str = Query("json", pattern="^(?i)(json|markdown|md|csv|yaml|yml)$"),
    artifact_service: ArtifactService = Depends(get_artifact_service),
    user: User = Depends(get_current_user),
):
    try:
        artifact = artifact_service.get(artifact_id, user)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    fmt = format.lower()
    if fmt == "json":
        body = json.dumps(
            {
                "id": artifact.id,
                "project_id": artifact.project_id,
                "artifact_type": artifact.artifact_type,
                "title": artifact.title,
                "version": artifact.version,
                "content": artifact.content,
            },
            indent=2,
        )
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{artifact.artifact_type}-{artifact.id}.json"'},
        )
    elif fmt in ("markdown", "md"):
        title = artifact.title or artifact.artifact_type
        md_lines = [f"# {title}", f"**Version:** {artifact.version}", f"**Type:** {artifact.artifact_type}", ""]
        if isinstance(artifact.content, dict):
            for k, v in artifact.content.items():
                md_lines.append(f"## {k.replace('_', ' ').title()}")
                md_lines.append(json.dumps(v, indent=2) if isinstance(v, (dict, list)) else str(v))
        body = "\n".join(md_lines)
        return Response(
            content=body,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{artifact.artifact_type}-{artifact.id}.md"'},
        )
    elif fmt == "csv":
        body = f"id,project_id,artifact_type,title,version\n{artifact.id},{artifact.project_id},{artifact.artifact_type},{artifact.title},{artifact.version}\n"
        return Response(
            content=body,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{artifact.artifact_type}-{artifact.id}.csv"'},
        )
    elif fmt in ("yaml", "yml"):
        body = yaml.dump(
            {
                "id": artifact.id,
                "project_id": artifact.project_id,
                "artifact_type": artifact.artifact_type,
                "title": artifact.title,
                "version": artifact.version,
                "content": artifact.content,
            }
        )
        return Response(
            content=body,
            media_type="application/x-yaml",
            headers={"Content-Disposition": f'attachment; filename="{artifact.artifact_type}-{artifact.id}.yaml"'},
        )
