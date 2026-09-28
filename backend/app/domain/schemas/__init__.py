"""Pydantic DTO schemas, split by domain resource."""

from app.domain.schemas.auth import LoginRequest, Token, UserCreate, UserOut
from app.domain.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.domain.schemas.artifact import ArtifactOut, ArtifactUpdate, GenerateRequest
from app.domain.schemas.evaluation import EvaluationCreate

__all__ = [
    "LoginRequest", "Token", "UserCreate", "UserOut",
    "ProjectCreate", "ProjectOut", "ProjectUpdate",
    "ArtifactOut", "ArtifactUpdate", "GenerateRequest",
    "EvaluationCreate",
]
