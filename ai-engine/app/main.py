"""
DevPilot AI Engine — FastAPI service (port 8001).

Run locally: uvicorn app.main:app --reload --port 8001
"""

import logging

from fastapi import FastAPI

from app.api.v1.generate import router as generate_router
from app.api.v1.health import router as health_router
from app.api.v1.ingest import router as ingest_router
from app.api.v1.prompts import router as prompts_router
from app.config import settings

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger("devpilot.ai_engine")

app = FastAPI(
    title="DevPilot AI Engine",
    description="GenAI + RAG + Prompt Engineering service ",
    version="1.0.0",
)

# Mount routers
app.include_router(health_router)
app.include_router(ingest_router)
app.include_router(generate_router)
app.include_router(prompts_router)
