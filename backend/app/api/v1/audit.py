"""
Audit log and evaluation endpoints (admin only).
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.domain.models import AuditLog, User
from app.services.ai_engine import AIEngineClient

router = APIRouter(tags=["Audit"])


@router.get("/audit-logs", responses={403: {"description": "Administrator role required"}})
def audit_logs(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Administrator role required")
    rows = db.scalars(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    )
    return [
        {
            "id": row.id,
            "user_id": row.user_id,
            "action": row.action,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "details": row.details,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/evaluate/batch", responses={403: {"description": "Admin only"}})
async def batch_evaluate(
    project_id: str | None = None,
    retrieval_mode: str = Query("vector", pattern="^(vector|hybrid)$"),
    user: User = Depends(get_current_user),
):
    """Admin-only offline RAGAS evaluation, proxied to the engine."""
    if user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return await AIEngineClient().evaluate_batch(project_id, retrieval_mode)
