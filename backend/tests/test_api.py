import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.services.ai_engine import AIEngineClient

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base.metadata.create_all(engine)


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def auth(client):
    client.post("/api/v1/auth/register", json={"email": "dev@example.com", "full_name": "Dev User", "password": "correct-horse-123"})
    response = client.post("/api/v1/auth/login", json={"email": "dev@example.com", "password": "correct-horse-123"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_register_login_and_reject_bad_credentials(client):
    response = client.post("/api/v1/auth/register", json={"email": "dev@example.com", "full_name": "Dev", "password": "password123"})
    assert response.status_code == 201
    assert "password_hash" not in response.text
    assert client.post("/api/v1/auth/login", json={"email": "dev@example.com", "password": "wrong-password"}).status_code == 401


def test_project_access_and_artifact_editing(client):
    headers = auth(client)
    project = client.post("/api/v1/projects", json={"name": "Payments"}, headers=headers).json()
    assert client.get("/api/v1/projects", headers=headers).json()[0]["id"] == project["id"]
    client.post("/api/v1/auth/register", json={"email": "other@example.com", "full_name": "Other", "password": "password123"})
    outsider_login = client.post("/api/v1/auth/login", json={"email": "other@example.com", "password": "password123"}).json()
    denied = client.get(f"/api/v1/projects/{project['id']}", headers={"Authorization": f"Bearer {outsider_login['access_token']}"})
    assert denied.status_code == 403


def test_generation_persists_artifact_and_history(client, monkeypatch):
    headers = auth(client)
    project = client.post("/api/v1/projects", json={"name": "Payments"}, headers=headers).json()
    async def fake_generate(self, project_id, artifact_type, requirement_text):
        return {"request_id": "engine-1", "project_id": project_id, "artifact_type": artifact_type,
                "prompt_version": "user_story_v1", "output": {"stories": []},
                "usage": {"total_tokens": 10}, "latency_ms": 15}
    monkeypatch.setattr(AIEngineClient, "generate", fake_generate)
    response = client.post(f"/api/v1/projects/{project['id']}/generate",
                           json={"artifact_type": "user_story", "requirement_text": "As a user..."}, headers=headers)
    assert response.status_code == 201
    artifact_id = response.json()["id"]
    assert response.json()["content"] == {"stories": []}
    assert client.get(f"/api/v1/projects/{project['id']}/history", headers=headers).json()[0]["engine_request_id"] == "engine-1"
    edited = client.patch(f"/api/v1/artifacts/{artifact_id}", json={"title": "Edited"}, headers=headers)
    assert edited.json()["version"] == 2
    assert client.get(f"/api/v1/artifacts/{artifact_id}/export", headers=headers).status_code == 200


def test_evaluation_validation(client):
    headers = auth(client)
    project = client.post("/api/v1/projects", json={"name": "Payments"}, headers=headers).json()
    assert client.post("/api/v1/artifacts/missing/evaluations", json={"score": 5}, headers=headers).status_code == 404
    assert client.post("/api/v1/projects/missing/generate", json={"artifact_type": "user_story", "requirement_text": "valid"}, headers=headers).status_code == 404
