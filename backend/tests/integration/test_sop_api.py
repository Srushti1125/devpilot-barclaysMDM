"""
Integration tests for the Sprint 3–6 gateway features:
- SOP telemetry persisted on generation (§3.2.2/§6.1)
- Traceability matrix (§5.3)
- Multi-LLM compare proxy (§3.2.3)
- SSE stream proxy (§3.2.4)
- JIRA-style CSV export (§5.5)
- Admin-only batch evaluation proxy (§4.2 Layer 2)
"""
import io

import pytest
from sqlalchemy import select

from app.domain.models import Artifact, User
from app.services.ai_engine import AIEngineClient


def _make_project(client, headers, name="SOP Project"):
    return client.post("/api/v1/projects", json={"name": name}, headers=headers).json()


def test_generate_persists_sop_telemetry(client, dev_headers, mock_ai_generate):
    project = _make_project(client, dev_headers)
    res = client.post(f"/api/v1/projects/{project['id']}/generate",
                      json={"artifact_type": "user_story", "requirement_text": "reset password via OTP"},
                      headers=dev_headers)
    assert res.status_code == 201

    history = client.get(f"/api/v1/projects/{project['id']}/history", headers=dev_headers).json()
    assert len(history) == 1
    entry = history[0]
    # Values come from mock_ai_generate in conftest.
    assert entry["eval_score"] == pytest.approx(0.91)
    assert entry["retry_count"] == 1
    assert entry["model_used"] == "groq-test-model"
    assert entry["requirement_id"] is None


def test_generate_links_requirement_for_traceability(client, dev_headers, mock_ai_generate, mock_ai_ingest):
    project = _make_project(client, dev_headers)
    files = {"file": ("reqs.md", io.BytesIO(b"# 1 Scope\nOTP reset."), "text/markdown")}
    upload = client.post(f"/api/v1/projects/{project['id']}/requirements", files=files,
                         headers=dev_headers).json()
    client.get(f"/api/v1/ingest-jobs/{upload['ingest_job_id']}", headers=dev_headers)

    res = client.post(f"/api/v1/projects/{project['id']}/generate",
                      json={"artifact_type": "user_story", "requirement_text": "reset password",
                            "requirement_id": upload["id"]}, headers=dev_headers)
    assert res.status_code == 201
    artifact_id = res.json()["id"]

    # Unknown / foreign requirement ids are rejected.
    bad = client.post(f"/api/v1/projects/{project['id']}/generate",
                      json={"artifact_type": "user_story", "requirement_text": "x",
                            "requirement_id": "nope"}, headers=dev_headers)
    assert bad.status_code == 404

    matrix = client.get(f"/api/v1/projects/{project['id']}/traceability", headers=dev_headers).json()
    node_ids = {n["id"] for n in matrix["nodes"]}
    assert f"req-{upload['id']}" in node_ids and f"art-{artifact_id}" in node_ids
    edge = matrix["edges"][0]
    assert edge["source"] == f"req-{upload['id']}"
    assert edge["target"] == f"art-{artifact_id}"


def test_viewer_cannot_generate(client, dev_headers, mock_ai_ingest):
    project = _make_project(client, dev_headers)
    viewer = client.post("/api/v1/auth/register",
                         json={"email": "view@example.com", "full_name": "V", "password": "Passw0rd!"}).json()
    client.post(f"/api/v1/projects/{project['id']}/members?email=view@example.com&role=viewer",
                headers=dev_headers)
    token = client.post("/api/v1/auth/login",
                        json={"email": "view@example.com", "password": "Passw0rd!"}).json()["access_token"]
    res = client.post(f"/api/v1/projects/{project['id']}/generate",
                      json={"artifact_type": "user_story", "requirement_text": "x"},
                      headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


def test_compare_proxy(client, dev_headers, monkeypatch):
    async def fake_compare(self, project_id, artifact_type, requirement_text):
        return {"primary": {"output": {"stories": []}, "eval_score": 0.9, "model_used": "groq-x"},
                "fallback": {"error": "429", "model_alias": "gemini-y"}}
    monkeypatch.setattr(AIEngineClient, "generate_compare", fake_compare)

    project = _make_project(client, dev_headers)
    res = client.post(f"/api/v1/projects/{project['id']}/compare",
                      json={"artifact_type": "user_story", "requirement_text": "reset via OTP"},
                      headers=dev_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["primary"]["model_used"] == "groq-x"
    assert body["fallback"]["error"] == "429"


def test_stream_proxy_forwards_sse(client, dev_headers, monkeypatch):
    async def fake_stream(self, project_id, artifact_type, requirement_text):
        async def gen():
            yield b'data: {"node": "pm"}\n\n'
            yield b'data: {"node": "qa"}\n\n'
            yield b"data: [DONE]\n\n"
        return gen()
    monkeypatch.setattr(AIEngineClient, "stream_generate", fake_stream)

    project = _make_project(client, dev_headers)
    with client.stream("POST", f"/api/v1/projects/{project['id']}/generate/stream",
                       json={"artifact_type": "user_story", "requirement_text": "x"},
                       headers=dev_headers) as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        body = "".join(chunk for chunk in res.iter_text())
    assert '"node": "pm"' in body and "[DONE]" in body


def test_export_user_story_uses_jira_columns(client, dev_headers, db_session):
    project = _make_project(client, dev_headers)
    user = db_session.scalar(select(User).where(User.role == "developer"))
    artifact = Artifact(id="art-jira", project_id=project["id"], created_by=user.id,
                        artifact_type="user_story", title="Stories",
                        content={"stories": [
                            {"title": "Reset flow", "story": "As a user, I want OTP reset",
                             "priority": "High", "category": "Auth", "dependencies": []},
                        ]})
    db_session.add(artifact)
    db_session.commit()

    res = client.get("/api/v1/artifacts/art-jira/export?format=csv", headers=dev_headers)
    assert res.status_code == 200
    lines = res.text.splitlines()
    assert lines[0] == (
        "Issue ID,Summary,Description,Priority,Category,Story Points,Sprint,Issue Type"
    )
    assert lines[1] == 'US-1,Reset flow,"As a user, I want OTP reset",High,Auth,,,Story'


def test_export_csv_escapes_commas(client, dev_headers, db_session):
    from sqlalchemy import select

    from app.domain.models import Artifact, User

    project = _make_project(client, dev_headers)
    user = db_session.scalar(select(User))
    artifact = Artifact(id="art-csv", project_id=project["id"], created_by=user.id,
                        artifact_type="architecture", title="Core, Banking",
                        content={"components": []})
    db_session.add(artifact)
    db_session.commit()
    res = client.get("/api/v1/artifacts/art-csv/export?format=csv", headers=dev_headers)
    assert '"Core, Banking"' in res.text  # properly quoted, not split


def test_gherkin_export_rejects_unsupported_artifact_type(client, dev_headers, db_session):
    project = _make_project(client, dev_headers)
    user = db_session.scalar(select(User).where(User.role == "developer"))
    artifact = Artifact(
        id="art-not-gherkin",
        project_id=project["id"],
        created_by=user.id,
        artifact_type="architecture",
        title="Architecture",
        content={},
    )
    db_session.add(artifact)
    db_session.commit()

    response = client.get(
        f"/api/v1/artifacts/{artifact.id}/export?format=gherkin",
        headers=dev_headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Gherkin export is only supported for acceptance_criteria artifacts"
    )


def test_batch_evaluate_is_admin_only(client, dev_headers, admin_headers, monkeypatch):
    async def fake_eval(self, project_id=None, retrieval_mode="vector"):
        return {"retrieval_mode": retrieval_mode, "n_examples": 50}
    monkeypatch.setattr(AIEngineClient, "evaluate_batch", fake_eval)

    denied = client.post("/api/v1/evaluate/batch", headers=dev_headers)
    assert denied.status_code == 403

    ok = client.post("/api/v1/evaluate/batch?retrieval_mode=hybrid", headers=admin_headers)
    assert ok.status_code == 200
    assert ok.json()["retrieval_mode"] == "hybrid"
