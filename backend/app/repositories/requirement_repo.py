from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Requirement
from app.repositories.base import BaseRepository


class RequirementRepository(BaseRepository[Requirement]):
    def __init__(self, db: Session):
        super().__init__(db, Requirement)

    def list_for_project(self, project_id: str) -> list[Requirement]:
        stmt = (
            select(Requirement)
            .where(Requirement.project_id == project_id)
            .order_by(Requirement.created_at.desc())
        )
        return list(self.db.scalars(stmt))
