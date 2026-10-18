"""The backend's HTTP boundary to the AI engine."""

import httpx
import pytest
from fastapi import HTTPException

from app.services.ai_engine import AIEngineClient


class FakeAsyncClient:
    def __init__(self, *, response=None, error=None, **_kwargs):
        self.response = response
        self.error = error
        self.request_args = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def request(self, method, url, **kwargs):
        self.request_args = (method, url, kwargs)
        if self.error:
            raise self.error
        return self.response


@pytest.mark.asyncio
async def test_generate_sends_contract_and_returns_json(monkeypatch):
    fake = FakeAsyncClient(response=httpx.Response(
        200, json={"output": {"title": "Example"}},
        request=httpx.Request("POST", "http://ai-engine/generate"),
    ))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: fake)
    client = AIEngineClient("http://ai-engine/")

    result = await client.generate("project-1", "user_story", "As a customer...")

    assert result == {"output": {"title": "Example"}}
    assert fake.request_args == (
        "POST",
        "http://ai-engine/generate",
        {"json": {
            "project_id": "project-1",
            "artifact_type": "user_story",
            "requirement_text": "As a customer...",
        }},
    )


@pytest.mark.asyncio
async def test_upstream_http_error_maps_to_502(monkeypatch):
    response = httpx.Response(500, text="engine failed", request=httpx.Request("GET", "http://ai/health"))
    fake = FakeAsyncClient(response=response)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: fake)

    with pytest.raises(HTTPException) as error:
        await AIEngineClient("http://ai").health()

    assert error.value.status_code == 502
    assert "500" in error.value.detail


@pytest.mark.asyncio
async def test_upstream_timeout_maps_to_503(monkeypatch):
    request = httpx.Request("GET", "http://ai/health")
    fake = FakeAsyncClient(error=httpx.ReadTimeout("timed out", request=request))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: fake)

    with pytest.raises(HTTPException) as error:
        await AIEngineClient("http://ai", timeout=0.01).health()

    assert error.value.status_code == 503
    assert error.value.detail == "AI engine is unavailable"


@pytest.mark.asyncio
async def test_invalid_upstream_json_maps_to_502(monkeypatch):
    fake = FakeAsyncClient(response=httpx.Response(
        200, text="not json", request=httpx.Request("GET", "http://ai/health")
    ))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: fake)

    with pytest.raises(HTTPException) as error:
        await AIEngineClient("http://ai").health()

    assert error.value.status_code == 502
    assert error.value.detail == "AI engine returned an invalid response"


@pytest.mark.asyncio
async def test_ingest_kicks_off_job_with_doc_id(monkeypatch):
    fake = FakeAsyncClient(response=httpx.Response(
        202, json={"job_id": "j-1", "status": "processing"},
        request=httpx.Request("POST", "http://ai/ingest"),
    ))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: fake)

    result = await AIEngineClient("http://ai/").ingest("/tmp/x.pdf", "p1", "requirement", doc_id="r-9")

    assert result == {"job_id": "j-1", "status": "processing"}
    assert fake.request_args[2]["json"]["doc_id"] == "r-9"


@pytest.mark.asyncio
async def test_ingest_status_lost_job_maps_to_failed(monkeypatch):
    """Engine restart evicts the job → surface as terminal failure, not a 502 to the poller."""
    fake = FakeAsyncClient(response=httpx.Response(
        404, text="no such job", request=httpx.Request("GET", "http://ai/ingest/j-404"),
    ))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: fake)

    state = await AIEngineClient("http://ai").ingest_status("j-404")
    assert state["status"] == "failed"
    assert state["error_type"] == "job_not_found"


@pytest.mark.asyncio
async def test_ingest_status_propagates_unreachable_engine(monkeypatch):
    fake = FakeAsyncClient(error=httpx.ConnectError("down"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: fake)

    with pytest.raises(HTTPException) as error:
        await AIEngineClient("http://ai").ingest_status("j-1")
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_evaluate_batch_sends_mode(monkeypatch):
    fake = FakeAsyncClient(response=httpx.Response(
        200, json={"n_examples": 50}, request=httpx.Request("POST", "http://ai/evaluate/batch"),
    ))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: fake)

    result = await AIEngineClient("http://ai").evaluate_batch("p1", retrieval_mode="hybrid")
    assert result == {"n_examples": 50}
    assert fake.request_args[2]["params"] == {"retrieval_mode": "hybrid", "project_id": "p1"}
