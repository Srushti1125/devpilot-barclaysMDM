"""
Database repository tests for ArtifactRepository.

Verifies:
- Artifact entity persistence and versioning
- Project-scoped artifact queries
- GenerationHistory recording and retrieval
- Evaluation records linked to artifacts
"""

from app.domain.models import Artifact, Evaluation, GenerationHistory, Project


def test_artifact_repo_crud(artifact_repo, project_repo, dev_user):
    project = Project(id=project_repo.new_id(), name="Auth Service", owner_id=dev_user.id)
    project_repo.add(project)
    project_repo.commit()

    art_id = artifact_repo.new_id()
    artifact = Artifact(
        id=art_id,
        project_id=project.id,
        created_by=dev_user.id,
        artifact_type="user_story",
        title="User Stories for Login",
        content={"stories": ["As a user..."]},
        version=1,
    )
    artifact_repo.add(artifact)
    artifact_repo.commit()

    retrieved = artifact_repo.get(art_id)
    assert retrieved is not None
    assert retrieved.title == "User Stories for Login"
    assert retrieved.version == 1

    artifacts = artifact_repo.list_for_project(project.id)
    assert len(artifacts) == 1
    assert artifacts[0].id == art_id


def test_artifact_repo_generation_history(artifact_repo, project_repo, dev_user):
    project = Project(id=project_repo.new_id(), name="Payments", owner_id=dev_user.id)
    project_repo.add(project)
    project_repo.commit()

    artifact = Artifact(
        id=artifact_repo.new_id(),
        project_id=project.id,
        created_by=dev_user.id,
        artifact_type="api_spec",
        title="OpenAPI Spec",
        content={},
    )
    artifact_repo.add(artifact)
    artifact_repo.flush()

    history = GenerationHistory(
        id=artifact_repo.new_id(),
        project_id=project.id,
        artifact_id=artifact.id,
        user_id=dev_user.id,
        engine_request_id="eng-987",
        artifact_type="api_spec",
        prompt_version="openapi_v2",
        usage={"prompt_tokens": 120, "completion_tokens": 300},
        latency_ms=145,
        requirement_text="Generate OpenAPI 3.0 spec for payments",
    )
    artifact_repo.add_history(history)
    artifact_repo.commit()

    history_records = artifact_repo.list_history(project.id)
    assert len(history_records) == 1
    assert history_records[0].engine_request_id == "eng-987"
    assert history_records[0].usage["prompt_tokens"] == 120


def test_artifact_repo_evaluations(artifact_repo, project_repo, dev_user, tester_user):
    project = Project(id=project_repo.new_id(), name="Auditing", owner_id=dev_user.id)
    project_repo.add(project)
    project_repo.commit()

    artifact = Artifact(
        id=artifact_repo.new_id(),
        project_id=project.id,
        created_by=dev_user.id,
        artifact_type="test_case",
        title="Test Suite",
        content={},
    )
    artifact_repo.add(artifact)
    artifact_repo.flush()

    evaluation = Evaluation(
        id=artifact_repo.new_id(),
        artifact_id=artifact.id,
        user_id=tester_user.id,
        score=4,
        feedback="Good boundary coverage",
        metrics={"accuracy": 0.88},
    )
    artifact_repo.add_evaluation(evaluation)
    artifact_repo.commit()

    evals = artifact_repo.list_evaluations(artifact.id)
    assert len(evals) == 1
    assert evals[0].score == 4
    assert evals[0].metrics["accuracy"] == 0.88
