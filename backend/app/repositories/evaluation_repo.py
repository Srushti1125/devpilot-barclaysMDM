from sqlalchemy import func, select

from app.domain.models import Evaluation
from app.repositories.base import BaseRepository


class EvaluationRepository(BaseRepository[Evaluation]):
    def __init__(self, db):
        super().__init__(db, Evaluation)

    def list_for_artifact(self, artifact_id: str) -> list[Evaluation]:
        return list(self.db.scalars(select(Evaluation).where(
            Evaluation.artifact_id == artifact_id
        ).order_by(Evaluation.created_at.desc())))

    def avg_score_for_artifact_ids(self, artifact_ids: list[str]) -> float | None:
        if not artifact_ids:
            return None
        value = self.db.scalar(select(func.avg(Evaluation.score)).where(
            Evaluation.artifact_id.in_(artifact_ids)
        ))
        return float(value) if value is not None else None
