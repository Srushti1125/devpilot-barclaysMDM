from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.project_stats_service import ProjectStatsService


class FakeArtifactRepository:
    def counts_by_type(self, project_id):
        assert project_id == "project-1"
        return {"user_story": 2, "test_case": 1}


class FakeHistoryRepository:
    def __init__(self, rows):
        self.rows = rows

    def list_chronological_for_project(self, project_id):
        assert project_id == "project-1"
        return self.rows


def test_project_stats_summarizes_scores_tokens_and_recent_trend():
    now = datetime.now(timezone.utc)
    histories = [
        SimpleNamespace(
            created_at=now - timedelta(days=1),
            eval_score=0.8,
            usage={"total_tokens": 12},
        ),
        SimpleNamespace(
            created_at=(now - timedelta(days=2)).replace(tzinfo=None),
            eval_score=1.0,
            usage={"total_tokens": 8},
        ),
        SimpleNamespace(
            created_at=now - timedelta(days=10),
            eval_score=None,
            usage={},
        ),
    ]
    service = ProjectStatsService(
        FakeArtifactRepository(), FakeHistoryRepository(histories)
    )

    stats = service.get_project_stats("project-1")

    assert stats["artifacts_by_type"] == {"user_story": 2, "test_case": 1}
    assert stats["total_artifacts"] == 3
    assert stats["total_generations"] == 3
    assert stats["avg_eval_score"] == 0.9
    assert stats["total_tokens_used"] == 20
    assert sum(stats["generation_trend_7d"].values()) == 2


def test_project_stats_handles_empty_data():
    class EmptyArtifactRepository:
        def counts_by_type(self, project_id):
            return {}

    service = ProjectStatsService(
        EmptyArtifactRepository(), FakeHistoryRepository([])
    )

    assert service.get_project_stats("project-1") == {
        "artifacts_by_type": {},
        "total_artifacts": 0,
        "total_generations": 0,
        "avg_eval_score": None,
        "total_tokens_used": 0,
        "generation_trend_7d": {},
    }
