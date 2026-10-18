"""Pydantic DTO schemas, split by domain resource."""

from app.domain.schemas.artifact import ArtifactOut, ArtifactUpdate, GenerateRequest
from app.domain.schemas.auth import LoginRequest, Token, UserCreate, UserOut
from app.domain.schemas.evaluation import EvaluationCreate
from app.domain.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate

__all__ = [
    "ArtifactOut",
    "ArtifactUpdate",
    "EvaluationCreate",
    "GenerateRequest",
    "LoginRequest",
    "ProjectCreate",
    "ProjectOut",
    "ProjectUpdate",
    "Token",
    "UserCreate",
    "UserOut",
]
