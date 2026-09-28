from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.models import Project, ProjectMember
from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    def __init__(self, db: Session):
        super().__init__(db, Project)

    def list_for_user(self, user_id: str) -> list[Project]:
        """Return projects the user owns or is a member of, newest first."""
        stmt = (
            select(Project)
            .outerjoin(ProjectMember, ProjectMember.project_id == Project.id)
            .where(or_(Project.owner_id == user_id, ProjectMember.user_id == user_id))
            .order_by(Project.created_at.desc())
        )
        return list(self.db.scalars(stmt).unique())

    def get_membership(self, project_id: str, user_id: str) -> ProjectMember | None:
        return self.db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )

    def add_member(self, member: ProjectMember) -> ProjectMember:
        self.db.add(member)
        return member
