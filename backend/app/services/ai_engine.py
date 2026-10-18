import asyncio
import logging

import httpx
from fastapi import HTTPException
from app.core.config import settings
from app.ports.ai_engine_port import AIEnginePort

logger = logging.getLogger("devpilot.backend.ai_client")


class AIEngineClient(AIEnginePort):
    def __init__(self, base_url: str | None = None, timeout: float = 180):
        self.base_url = (base_url or settings.ai_engine_url).rstrip("/")
        self.timeout = timeout

    async def _request(self, method: str, path: str, **kwargs):
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(method, f"{self.base_url}{path}", **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:1000]
            raise HTTPException(status_code=502, detail=f"AI engine returned {exc.response.status_code}: {detail}") from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail="AI engine is unavailable") from exc
        except ValueError as exc:
            # Successful HTTP responses can still contain invalid or non-JSON
            # bodies. Report this as an upstream failure, not an unhandled 500.
            raise HTTPException(status_code=502, detail="AI engine returned an invalid response") from exc

    async def health(self):
        return await self._request("GET", "/health")

    async def artifact_types(self):
        return await self._request("GET", "/artifact-types")

    async def generate(self, project_id: str, artifact_type: str, requirement_text: str):
        return await self._request("POST", "/generate", json={
            "project_id": project_id,
            "artifact_type": artifact_type,
            "requirement_text": requirement_text,
        })

    async def generate_compare(self, project_id: str, artifact_type: str, requirement_text: str):
        """Parallel DEFAULT vs FALLBACK LLM generation (§3.2.3)."""
        return await self._request("POST", "/generate/compare", json={
            "project_id": project_id,
            "artifact_type": artifact_type,
            "requirement_text": requirement_text,
        })

    async def stream_generate(self, project_id: str, artifact_type: str, requirement_text: str):
        """Yield raw SSE bytes from the engine's node-transition stream (§3.2.4)."""
        url = f"{self.base_url}/generate/stream"
        payload = {"project_id": project_id, "artifact_type": artifact_type,
                   "requirement_text": requirement_text}
        client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, read=None))
        try:
            request = client.build_request("POST", url, json=payload)
            response = await client.send(request, stream=True)
            if response.status_code >= 400:
                await response.aread()
                raise HTTPException(status_code=502,
                                    detail=f"AI engine stream failed: {response.status_code}")
        except httpx.RequestError as exc:
            await client.aclose()
            raise HTTPException(status_code=503, detail="AI engine is unavailable") from exc

        async def _stream():
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        return _stream()

    async def ingest(self, file_path: str, project_id: str, doc_type: str, doc_id: str | None = None):
        """Kick off an async ingestion job (§2.2.4). Returns {job_id, status}."""
        payload = {"file_path": file_path, "project_id": project_id, "doc_type": doc_type}
        if doc_id:
            payload["doc_id"] = doc_id  # the requirement id; ai-engine tags tree nodes and chunks with it
        return await self._request("POST", "/ingest", json=payload)

    async def ingest_status(self, engine_job_id: str):
        """Poll the engine ingest job. A 404 (engine restarted, job evicted) is
        returned to the caller as a terminal failure dict instead of raising."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request("GET", f"{self.base_url}/ingest/{engine_job_id}")
                if response.status_code == 404:
                    return {"status": "failed",
                            "error": "ingestion job unknown (engine restarted?)",
                            "error_type": "job_not_found"}
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:1000]
            raise HTTPException(status_code=502,
                                detail=f"AI engine returned {exc.response.status_code}: {detail}") from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail="AI engine is unavailable") from exc
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="AI engine returned an invalid response") from exc

    async def evaluate_batch(self, project_id: str | None = None, retrieval_mode: str = "vector"):
        """Admin-triggered offline RAGAS run (§4.2 Layer 2)."""
        params = {"retrieval_mode": retrieval_mode}
        if project_id:
            params["project_id"] = project_id
        return await self._request("POST", "/evaluate/batch", params=params)
