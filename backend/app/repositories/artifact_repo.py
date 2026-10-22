from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.models import Artifact, Evaluation, GenerationHistory
from app.repositories.base import BaseRepository


class ArtifactRepository(BaseRepository[Artifact]):
    def __init__(self, db: Session):
        super().__init__(db, Artifact)

    def list_for_project(self, project_id: str) -> list[Artifact]:
        stmt = (
            select(Artifact)
            .where(Artifact.project_id == project_id)
            .order_by(Artifact.created_at.desc())
        )
        return list(self.db.scalars(stmt))

    def counts_by_type(self, project_id: str) -> dict[str, int]:
        rows = self.db.execute(
            select(Artifact.artifact_type, func.count(Artifact.id))
            .where(Artifact.project_id == project_id)
            .group_by(Artifact.artifact_type)
        ).all()
        return dict(rows)

    def add_history(self, entry: GenerationHistory) -> GenerationHistory:
        self.db.add(entry)
        return entry

    def list_history(self, project_id: str) -> list[GenerationHistory]:
        stmt = (
            select(GenerationHistory)
            .where(GenerationHistory.project_id == project_id)
            .order_by(GenerationHistory.created_at.desc())
        )
        return list(self.db.scalars(stmt))

    def add_evaluation(self, evaluation: Evaluation) -> Evaluation:
        self.db.add(evaluation)
        return evaluation

    def list_evaluations(self, artifact_id: str) -> list[Evaluation]:
        stmt = (
            select(Evaluation)
            .where(Evaluation.artifact_id == artifact_id)
            .order_by(Evaluation.created_at.desc())
        )
        return list(self.db.scalars(stmt))
