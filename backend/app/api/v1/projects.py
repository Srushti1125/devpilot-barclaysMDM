"""
Project management API endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import get_artifact_service, get_current_user, get_project_service
from app.core.exceptions import AuthorisationError, ResourceNotFoundError, ValidationError
from app.models import User
from app.schemas import ProjectCreate, ProjectOut, ProjectUpdate
from app.services.artifact_service import ArtifactService
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    return project_service.create(
        name=payload.name,
        description=payload.description,
        user=user,
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    return project_service.list_for_user(user)


@router.get("/{project_id}", response_model=ProjectOut)
def read_project(
    project_id: str,
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    try:
        return project_service.get_project_or_fail(project_id, user)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    try:
        updates = payload.model_dump(exclude_unset=True)
        return project_service.update(project_id, user, updates)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: str,
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    try:
        project_service.delete(project_id, user)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post("/{project_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(
    project_id: str,
    email: str = Query(...),
    role: str = Query("viewer"),
    project_service: ProjectService = Depends(get_project_service),
    user: User = Depends(get_current_user),
):
    try:
        return project_service.set_member(project_id, email, role, user)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.get("/{project_id}/history")
def generation_history(
    project_id: str,
    artifact_service: ArtifactService = Depends(get_artifact_service),
    user: User = Depends(get_current_user),
):
    try:
        return artifact_service.list_history(project_id, user)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorisationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
