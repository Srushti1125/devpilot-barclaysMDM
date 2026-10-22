from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user, require_role
from app.domain.models import User
from app.services.ai_engine import AIEngineClient

router = APIRouter(prefix="/prompts", tags=["Prompts"])


@router.get("")
async def list_prompts(user: User = Depends(get_current_user)):
    return await AIEngineClient()._request("GET", "/prompts")


@router.get("/{artifact_type}")
async def read_prompt(artifact_type: str, version: str = Query("latest"),
                      user: User = Depends(get_current_user)):
    return await AIEngineClient()._request("GET", f"/prompts/{artifact_type}",
                                           params={"version": version})


@router.post("/{artifact_type}", status_code=201)
async def create_prompt_version(artifact_type: str, payload: dict,
                                user: User = Depends(require_role("admin"))):
    return await AIEngineClient()._request("POST", f"/prompts/{artifact_type}", json=payload)


@router.post("/{artifact_type}/test")
async def test_prompt(artifact_type: str, payload: dict,
                      user: User = Depends(require_role("admin"))):
    return await AIEngineClient()._request("POST", f"/prompts/{artifact_type}/test", json=payload)
