"""
Project lifecycle business logic.

Owns project CRUD, membership management, and access-control checks.
Raises domain exceptions – never touches FastAPI directly.
"""

from app.core.exceptions import AuthorisationError, ResourceNotFoundError, ValidationError
from app.domain.models import Project, ProjectMember, User
from app.repositories.audit_repo import AuditRepository
from app.repositories.project_repo import ProjectRepository
from app.repositories.user_repo import UserRepository


class ProjectService:
    def __init__(
        self,
        project_repo: ProjectRepository,
        user_repo: UserRepository,
        audit_repo: AuditRepository,
    ):
        self.project_repo = project_repo
        self.user_repo = user_repo
        self.audit_repo = audit_repo

    # ── Access helpers ──────────────────────────────────────────────────

    def get_project_or_fail(
        self, project_id: str, user: User, *, write: bool = False
    ) -> Project:
        """
        Retrieve a project the *user* has access to.

        Raises ResourceNotFoundError (404) or AuthorisationError (403).
        """
        project = self.project_repo.get(project_id)
        if not project:
            raise ResourceNotFoundError("Project", project_id)

        # Owner and admin always pass
        if project.owner_id == user.id or user.role == "admin":
            return project

        member = self.project_repo.get_membership(project_id, user.id)
        if not member or (write and member.role not in ("owner", "editor")):
            raise AuthorisationError("You do not have access to this project")

        return project

    def _assert_owner_or_admin(self, project: Project, user: User) -> None:
        if user.role != "admin" and project.owner_id != user.id:
            raise AuthorisationError("Only the project owner can perform this action")

    # ── CRUD ────────────────────────────────────────────────────────────

    def create(self, name: str, description: str, user: User) -> Project:
        project = Project(
            id=self.project_repo.new_id(),
            name=name.strip(),
            description=description,
            owner_id=user.id,
        )
        self.project_repo.add(project)
        self.project_repo.flush()

        self.project_repo.add_member(
            ProjectMember(
                id=self.project_repo.new_id(),
                project_id=project.id,
                user_id=user.id,
                role="owner",
            )
        )
        self.audit_repo.record(user.id, "project.create", "project", project.id)
        self.project_repo.commit()
        return self.project_repo.refresh(project)

    def list_for_user(self, user: User) -> list[Project]:
        return self.project_repo.list_for_user(user.id)

    def update(
        self, project_id: str, user: User, updates: dict
    ) -> Project:
        project = self.get_project_or_fail(project_id, user, write=True)
        self._assert_owner_or_admin(project, user)

        for key, value in updates.items():
            setattr(project, key, value)

        self.audit_repo.record(user.id, "project.update", "project", project.id)
        self.project_repo.commit()
        return self.project_repo.refresh(project)

    def delete(self, project_id: str, user: User) -> None:
        project = self.get_project_or_fail(project_id, user, write=True)
        self._assert_owner_or_admin(project, user)

        self.audit_repo.record(user.id, "project.delete", "project", project.id)
        self.project_repo.delete(project)
        self.project_repo.commit()

    # ── Membership ──────────────────────────────────────────────────────

    def set_member(
        self, project_id: str, email: str, role: str, user: User
    ) -> dict:
        project = self.get_project_or_fail(project_id, user, write=True)
        self._assert_owner_or_admin(project, user)

        if role not in {"editor", "viewer"}:
            raise ValidationError("Role must be editor or viewer")

        member_user = self.user_repo.get_by_email(email.lower())
        if not member_user:
            raise ResourceNotFoundError("User")

        existing = self.project_repo.get_membership(project_id, member_user.id)
        if existing:
            existing.role = role
            membership = existing
        else:
            membership = ProjectMember(
                id=self.project_repo.new_id(),
                project_id=project_id,
                user_id=member_user.id,
                role=role,
            )
            self.project_repo.add_member(membership)

        self.audit_repo.record(
            user.id,
            "project.member.set",
            "project",
            project_id,
            {"member_id": member_user.id, "role": role},
        )
        self.project_repo.commit()
        return {
            "project_id": project_id,
            "user_id": member_user.id,
            "role": membership.role,
        }
