from sqlalchemy import select

from app.domain.models import IngestJob
from app.repositories.base import BaseRepository


class IngestJobRepository(BaseRepository[IngestJob]):
    def __init__(self, db):
        super().__init__(db, IngestJob)

    def get_by_requirement(self, requirement_id: str) -> list[IngestJob]:
        return list(self.db.scalars(select(IngestJob).where(
            IngestJob.requirement_id == requirement_id
        ).order_by(IngestJob.created_at.desc())))

    def get_pending(self) -> list[IngestJob]:
        return list(self.db.scalars(select(IngestJob).where(IngestJob.status == "processing")))
