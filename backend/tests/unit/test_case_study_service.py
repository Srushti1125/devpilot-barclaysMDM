from types import SimpleNamespace

import pytest

from app.core.exceptions import ValidationError
from app.services.case_study_service import CaseStudyService


class FakeRequirementRepository:
    def __init__(self, requirements):
        self.requirements = requirements
        self.query = None

    def list_for_project(self, project_id, *, limit, oldest_first):
        self.query = (project_id, limit, oldest_first)
        return self.requirements[:limit]


class FakeHistoryRepository:
    def __init__(self):
        self.histories = {}
        self.commits = 0
        self.rollbacks = 0

    def get_for_artifact(self, artifact_id):
        return self.histories.get(artifact_id)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeAuditRepository:
    def __init__(self):
        self.events = []
        self.commits = 0

    def record(self, *args):
        self.events.append(args)

    def commit(self):
        self.commits += 1


class FakeArtifactService:
    def __init__(self, history_repo, fail_on=None):
        self.history_repo = history_repo
        self.fail_on = fail_on
        self.calls = []

    async def generate(self, project_id, artifact_type, requirement_text, user):
        self.calls.append((project_id, artifact_type, requirement_text, user))
        if artifact_type == self.fail_on:
            raise RuntimeError("generation unavailable")
        artifact = SimpleNamespace(id=f"artifact-{artifact_type}")
        self.history_repo.histories[artifact.id] = SimpleNamespace(
            eval_score=0.9 if artifact_type == "user_story" else 0.7,
            latency_ms=25,
            retry_count=1,
            model_used="test-model",
            requirement_id=None,
        )
        return artifact


def make_service(requirements, fail_on=None):
    requirement_repo = FakeRequirementRepository(requirements)
    history_repo = FakeHistoryRepository()
    audit_repo = FakeAuditRepository()
    artifact_service = FakeArtifactService(history_repo, fail_on)
    service = CaseStudyService(
        requirement_repo, history_repo, audit_repo, artifact_service
    )
    return service, requirement_repo, history_repo, audit_repo, artifact_service


@pytest.mark.asyncio
async def test_case_study_returns_partial_failures_and_links_history(dev_user):
    requirements = [
        SimpleNamespace(
            id="req-1", content="", filename="requirements.md"
        )
    ]
    service, requirements_repo, history_repo, audit_repo, artifact_service = make_service(
        requirements, fail_on="test_case"
    )

    report = await service.generate("project-1", 4, dev_user)

    assert requirements_repo.query == ("project-1", 4, True)
    assert len(artifact_service.calls) == 6
    assert artifact_service.calls[0][2] == "Requirement document: requirements.md"
    assert report["summary"]["total_artifacts_generated"] == 5
    assert report["summary"]["avg_eval_score"] == 0.74
    assert report["summary"]["pass_rate_80pct"] == 0.2
    assert report["requirements"][0]["artifacts"][2] == {
        "artifact_type": "test_case",
        "error": "generation unavailable",
    }
    assert history_repo.histories["artifact-user_story"].requirement_id == "req-1"
    assert history_repo.rollbacks == 1
    assert audit_repo.events[0][-1] == {"requirements": 1, "generated": 5}
    assert audit_repo.commits == 1


@pytest.mark.asyncio
async def test_case_study_rejects_empty_requirements_without_generation(dev_user):
    service, _, _, audit_repo, artifact_service = make_service([])

    with pytest.raises(ValidationError, match="No requirements ingested"):
        await service.generate("project-1", 10, dev_user)

    assert artifact_service.calls == []
    assert audit_repo.events == []
