import httpx
from fastapi import HTTPException
from app.config import settings


class AIEngineClient:
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

    async def ingest(self, file_path: str, project_id: str, doc_type: str):
        return await self._request("POST", "/ingest", json={
            "file_path": file_path,
            "project_id": project_id,
            "doc_type": doc_type,
        })

