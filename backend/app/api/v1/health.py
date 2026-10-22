"""
Health check endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.ai_engine import AIEngineClient

router = APIRouter(tags=["Health"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/health/db", responses={503: {"description": "Database unavailable"}})
def health_db(db: Session = Depends(get_db)):
    try:
        db.execute(select(1))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {str(e)}")


@router.get("/health/ai")
async def health_ai():
    try:
        types = await AIEngineClient().artifact_types()
        return {"status": "healthy", "ai_engine": "available", "artifact_types": types}
    except Exception as e:
        return {"status": "degraded", "ai_engine": "unavailable", "detail": str(e)}
