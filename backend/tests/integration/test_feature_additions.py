import uuid

from app.domain.models import Artifact, Project, Requirement
from app.services.ai_engine import AIEngineClient


def test_chat_persists_turns_and_stats_reports_generation(client, dev_headers, monkeypatch):
    project = client.post("/api/v1/projects", json={"name": "Assistant project"},
                          headers=dev_headers).json()

    async def fake_generate(self, project_id, artifact_type, requirement_text):
        if artifact_type == "conversational":
            output = {"answer": "There are two payment stories.", "sources": ["Payment requirements"]}
        else:
            output = {"stories": [{"title": "Payment story"}]}
        return {"output": output, "eval_score": 0.92, "retry_count": 0,
                "model_used": "groq-test", "usage": {"total_tokens": 12},
                "latency_ms": 25, "prompt_version": f"{artifact_type}_v1"}

    monkeypatch.setattr(AIEngineClient, "generate", fake_generate)
    answer = client.post(f"/api/v1/projects/{project['id']}/chat",
                         json={"message": "How many payment stories?"}, headers=dev_headers)
    assert answer.status_code == 201
    assert answer.json()["answer"] == "There are two payment stories."
    assert answer.json()["sources"] == ["Payment requirements"]
    history = client.get(f"/api/v1/projects/{project['id']}/chat", headers=dev_headers)
    assert history.status_code == 200
    assert [turn["role"] for turn in history.json()] == ["user", "assistant"]

    generated = client.post(f"/api/v1/projects/{project['id']}/generate",
        json={"artifact_type": "user_story", "requirement_text": "Payment flow"},
        headers=dev_headers)
    assert generated.status_code == 201
    stats = client.get(f"/api/v1/projects/{project['id']}/stats", headers=dev_headers)
    assert stats.status_code == 200
    assert stats.json()["artifacts_by_type"] == {"user_story": 1}
    assert stats.json()["total_tokens_used"] == 12


def test_gherkin_and_zip_exports(client, dev_user, dev_headers, db_session):
    project_id = str(uuid.uuid4())
    db_session.add(Project(id=project_id, name="Export project", description="", owner_id=dev_user.id))
    criteria = Artifact(id=str(uuid.uuid4()), project_id=project_id, created_by=dev_user.id,
        artifact_type="acceptance_criteria", title="Payment criteria",
        content={"user_story_title": "Pay an invoice", "criteria": [{
            "title": "Successful payment", "given": "an unpaid invoice",
            "when": "the payment succeeds", "then": "the invoice is marked paid",
            "case_type": "positive"}]})
    db_session.add(criteria)
    db_session.commit()

    feature = client.get(f"/api/v1/artifacts/{criteria.id}/export?format=gherkin", headers=dev_headers)
    assert feature.status_code == 200
    assert "Feature: Payment criteria" in feature.text
    assert "Given an unpaid invoice" in feature.text
    archive = client.get(f"/api/v1/projects/{project_id}/artifacts/export.zip", headers=dev_headers)
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    assert criteria.id.encode() in archive.content


def test_case_study_generates_suite_and_links_requirement(client, dev_user, dev_headers,
                                                           db_session, monkeypatch):
    project = client.post("/api/v1/projects", json={"name": "Case study"},
                          headers=dev_headers).json()
    requirement_id = str(uuid.uuid4())
    db_session.add(Requirement(id=requirement_id, project_id=project["id"], uploaded_by=dev_user.id,
        filename="payment.txt", file_path="/tmp/payment.txt", content="Support invoice payment."))
    db_session.commit()

    async def fake_generate(self, project_id, artifact_type, requirement_text):
        return {"request_id": "case-study", "output": {"items": []}, "eval_score": 0.9,
                "retry_count": 0, "model_used": "groq-test", "usage": {"total_tokens": 3},
                "latency_ms": 10, "prompt_version": f"{artifact_type}_v1"}

    monkeypatch.setattr(AIEngineClient, "generate", fake_generate)
    response = client.post(f"/api/v1/projects/{project['id']}/case-study", headers=dev_headers)
    assert response.status_code == 200
    report = response.json()
    assert report["summary"]["total_artifacts_generated"] == 6
    assert report["summary"]["avg_eval_score"] == 0.9
    assert all("artifact_id" in item for item in report["requirements"][0]["artifacts"])
    persisted = db_session.query(Artifact).filter_by(project_id=project["id"]).all()
    assert len(persisted) == 6


def test_case_study_without_requirements_returns_validation_error(client, dev_headers):
    project = client.post("/api/v1/projects", json={"name": "Empty case study"},
                          headers=dev_headers).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/case-study",
        headers=dev_headers,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "No requirements ingested for this project"}
