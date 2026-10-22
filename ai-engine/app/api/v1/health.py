"""
Health and artifact-types endpoints.
"""

from fastapi import APIRouter

from app.config import settings
from app.schemas.registry import SCHEMA_REGISTRY

router = APIRouter(tags=["Health"])


@router.get("/health")
def health():
    return {"status": "ok", "default_llm": settings.DEFAULT_LLM}


@router.get("/artifact-types")
def artifact_types():
    return {"artifact_types": sorted(SCHEMA_REGISTRY.keys())}
