"""
FastAPI dependencies for authentication, RBAC, database sessions, and services.
"""

from collections.abc import Callable
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import token_subject
from app.repositories.user_repo import UserRepository
from app.repositories.project_repo import ProjectRepository
from app.repositories.requirement_repo import RequirementRepository
from app.repositories.artifact_repo import ArtifactRepository
from app.repositories.audit_repo import AuditRepository
from app.services.auth_service import AuthService
from app.services.project_service import ProjectService
from app.services.artifact_service import ArtifactService
from app.services.ai_engine import AIEngineClient

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Validate Bearer JWT token and return active User entity."""
    token = credentials.credentials if credentials else ""
    subject = token_subject(token)
    user = db.get(User, subject) if subject else None
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*allowed_roles: str) -> Callable[[User], User]:
    """Dependency factory checking that the current user possesses one of the allowed roles."""
    normalized_roles = {r.lower() for r in allowed_roles}

    def role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role.lower() not in normalized_roles and "admin" not in normalized_roles and user.role.lower() != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action requires one of the following roles: {', '.join(allowed_roles)}",
            )
        return user

    return role_checker


# ── Service Dependency Providers ──────────────────────────────────────────────

def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(UserRepository(db), AuditRepository(db))


def get_project_service(db: Session = Depends(get_db)) -> ProjectService:
    return ProjectService(ProjectRepository(db), UserRepository(db), AuditRepository(db))


def get_artifact_service(
    db: Session = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
) -> ArtifactService:
    return ArtifactService(
        ArtifactRepository(db),
        AuditRepository(db),
        project_service,
        AIEngineClient(),
    )
