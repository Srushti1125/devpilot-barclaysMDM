from sqlalchemy import select

from app.domain.models import GenerationHistory
from app.repositories.base import BaseRepository


class GenerationHistoryRepository(BaseRepository[GenerationHistory]):
    def __init__(self, db):
        super().__init__(db, GenerationHistory)

    def list_for_project(self, project_id: str) -> list[GenerationHistory]:
        return list(self.db.scalars(select(GenerationHistory).where(
            GenerationHistory.project_id == project_id
        ).order_by(GenerationHistory.created_at.desc())))

    def list_chronological_for_project(self, project_id: str) -> list[GenerationHistory]:
        return list(self.db.scalars(select(GenerationHistory).where(
            GenerationHistory.project_id == project_id
        ).order_by(GenerationHistory.created_at.asc())))

    def get_for_artifact(self, artifact_id: str) -> GenerationHistory | None:
        return self.db.scalar(select(GenerationHistory).where(
            GenerationHistory.artifact_id == artifact_id
        ))

    def stats_for_project(self, project_id: str) -> dict:
        rows = self.list_for_project(project_id)
        by_type: dict[str, int] = {}
        scores = []
        for row in rows:
            by_type[row.artifact_type] = by_type.get(row.artifact_type, 0) + 1
            if row.eval_score is not None:
                scores.append(row.eval_score)
        return {
            "total_generations": len(rows), "by_type": by_type,
            "avg_eval_score": round(sum(scores) / len(scores), 3) if scores else None,
        }
