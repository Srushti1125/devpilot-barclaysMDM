from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import AuditLog
from app.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditLog]):
    def __init__(self, db: Session):
        super().__init__(db, AuditLog)

    def record(
        self,
        user_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str | None,
        details: dict | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            id=self.new_id(),
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
        )
        self.db.add(entry)
        return entry

    def list_recent(self, limit: int = 100) -> list[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt))
