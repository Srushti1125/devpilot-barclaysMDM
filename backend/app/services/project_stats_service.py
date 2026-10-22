from datetime import datetime, timedelta, timezone

from app.repositories.artifact_repo import ArtifactRepository
from app.repositories.history_repo import GenerationHistoryRepository


class ProjectStatsService:
    def __init__(
        self,
        artifact_repo: ArtifactRepository,
        history_repo: GenerationHistoryRepository,
    ):
        self.artifact_repo = artifact_repo
        self.history_repo = history_repo

    def get_project_stats(self, project_id: str) -> dict:
        by_type = self.artifact_repo.counts_by_type(project_id)
        histories = self.history_repo.list_chronological_for_project(project_id)
        scores = [row.eval_score for row in histories if row.eval_score is not None]
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        trend: dict[str, int] = {}
        for row in histories:
            created_at = row.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if created_at >= cutoff:
                day = row.created_at.strftime("%Y-%m-%d")
                trend[day] = trend.get(day, 0) + 1
        return {
            "artifacts_by_type": by_type,
            "total_artifacts": sum(by_type.values()),
            "total_generations": len(histories),
            "avg_eval_score": round(sum(scores) / len(scores), 3) if scores else None,
            "total_tokens_used": sum((row.usage or {}).get("total_tokens", 0) for row in histories),
            "generation_trend_7d": trend,
        }
