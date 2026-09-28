"""
Unit tests for ArtifactService business logic.

Verifies:
- Artifact generation calling AI client and persisting artifact + history
- Artifact versioning on update
- Evaluation creation with scores and metrics
- Multi-format exports (JSON, Markdown)
- Validation when AI payload is malformed
"""

import pytest
from app.core.exceptions import ResourceNotFoundError, ValidationError


@pytest.mark.asyncio
async def test_generate_artifact_success(artifact_service, project_service, dev_user, mock_ai_generate, artifact_repo):
    project = project_service.create("Billing", "Billing system", dev_user)

    artifact = await artifact_service.generate(
        project_id=project.id,
        artifact_type="user_story",
        requirement_text="As a customer, I want to view my monthly statements.",
        user=dev_user,
    )

    assert artifact.id is not None
    assert artifact.project_id == project.id
    assert artifact.artifact_type == "user_story"
    assert artifact.version == 1
    assert "items" in artifact.content

    # Check generation history recorded
    history = artifact_repo.list_history(project.id)
    assert len(history) == 1
    assert history[0].engine_request_id == "test-req-123"
    assert history[0].artifact_id == artifact.id


@pytest.mark.asyncio
async def test_generate_artifact_invalid_ai_payload_raises_validation_error(
    artifact_service, project_service, dev_user, monkeypatch
):
    project = project_service.create("Fraud Detection", "Fraud service", dev_user)

    # Mock invalid output payload (string instead of dict)
    async def bad_generate(self, project_id, artifact_type, requirement_text):
        return {"output": "invalid-string-not-dict"}

    from app.services.ai_engine import AIEngineClient
    monkeypatch.setattr(AIEngineClient, "generate", bad_generate)

    with pytest.raises(ValidationError) as exc_info:
        await artifact_service.generate(project.id, "api_spec", "Req text", dev_user)

    assert "invalid artifact payload" in str(exc_info.value).lower()


def test_update_artifact_increments_version(artifact_service, project_service, dev_user, artifact_repo):
    project = project_service.create("Reports", "Reporting", dev_user)

    # Seed an artifact
    from app.domain.models import Artifact
    artifact = Artifact(
        id=artifact_repo.new_id(),
        project_id=project.id,
        created_by=dev_user.id,
        artifact_type="user_story",
        title="Initial Title",
        content={"v": 1},
    )
    artifact_repo.add(artifact)
    artifact_repo.commit()

    updated = artifact_service.update(
        artifact_id=artifact.id,
        updates={"title": "Updated Title", "content": {"v": 2}},
        user=dev_user,
    )

    assert updated.version == 2
    assert updated.title == "Updated Title"
    assert updated.content == {"v": 2}


def test_add_evaluation_persists_feedback(artifact_service, project_service, dev_user, tester_user, artifact_repo):
    project = project_service.create("Identity", "Identity service", dev_user)

    from app.domain.models import Artifact
    artifact = Artifact(
        id=artifact_repo.new_id(),
        project_id=project.id,
        created_by=dev_user.id,
        artifact_type="test_case",
        title="Test Cases",
        content={"cases": []},
    )
    artifact_repo.add(artifact)
    artifact_repo.commit()

    # Add tester as project member so they can evaluate
    project_service.set_member(project.id, tester_user.email, "editor", dev_user)

    evaluation = artifact_service.evaluate(
        artifact_id=artifact.id,
        score=5,
        feedback="Excellent coverage of boundary cases",
        metrics={"completeness": 0.95, "accuracy": 0.90},
        user=tester_user,
    )

    assert evaluation.id is not None
    assert evaluation.score == 5
    assert evaluation.metrics["completeness"] == 0.95


def test_export_artifact_json(artifact_service, project_service, dev_user, artifact_repo):
    project = project_service.create("Exports", "Export test", dev_user)

    from app.domain.models import Artifact
    artifact = Artifact(
        id=artifact_repo.new_id(),
        project_id=project.id,
        created_by=dev_user.id,
        artifact_type="architecture",
        title="Microservices Architecture",
        content={"overview": "Event-driven system with Kafka"},
    )
    artifact_repo.add(artifact)
    artifact_repo.commit()

    # JSON export
    json_str = artifact_service.export_json(artifact.id, dev_user)
    assert "Microservices Architecture" in json_str
    assert "architecture" in json_str
