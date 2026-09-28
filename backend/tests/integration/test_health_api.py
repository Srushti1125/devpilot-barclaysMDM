"""
Integration tests for Health and Operational endpoints.

Verifies:
- GET /health: Application process liveness check
- GET /health/db: Database connectivity check
- GET /health/ai: AI Engine connectivity check
- Resilience on AI Engine failure or timeout
"""

from app.services.ai_engine import AIEngineClient


def test_health_endpoints(client, monkeypatch):
    # Liveness check
    r1 = client.get("/health")
    assert r1.status_code == 200
    assert r1.json()["status"] == "ok"

    # Database connectivity check
    r2 = client.get("/health/db")
    assert r2.status_code == 200
    assert r2.json()["database"] == "connected"

    # AI engine check with mock available
    async def mock_types(self):
        return ["user_story", "test_case", "api_spec"]
    monkeypatch.setattr(AIEngineClient, "artifact_types", mock_types)

    r3 = client.get("/health/ai")
    assert r3.status_code == 200
    assert r3.json()["status"] == "healthy"


def test_health_ai_degraded_when_engine_down(client, monkeypatch):
    async def mock_down(self):
        raise ConnectionError("AI Engine unreachable on port 8001")
    monkeypatch.setattr(AIEngineClient, "artifact_types", mock_down)

    r = client.get("/health/ai")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
    assert "unavailable" in r.json()["ai_engine"]
