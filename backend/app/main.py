import logging
import time
from collections import deque
from threading import Lock

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import Base, engine
from app.api.v1.artifacts import router as artifacts_router
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.generate import router as generate_router
from app.api.v1.health import router as health_router
from app.api.v1.projects import router as projects_router
from app.api.v1.prompts import router as prompts_router
from app.api.v1.requirements import router as requirements_router

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger("devpilot.backend")

app = FastAPI(title="DevPilot Backend API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(health_router)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(requirements_router, prefix="/api/v1")
app.include_router(artifacts_router, prefix="/api/v1")
app.include_router(generate_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(prompts_router, prefix="/api/v1")

# Rate limiting (must be defined before middleware registration)
_rate_windows: dict[tuple[str, str], deque[float]] = {}
_rate_lock = Lock()


@app.middleware("http")
async def auth_and_generation_rate_limit(request, call_next):
    path = request.url.path
    method = request.method.upper()
    limit = None
    bucket = ""
    if method == "POST" and path in {"/api/v1/auth/login", "/api/v1/auth/register"}:
        limit, bucket = 10, "auth"
    elif method == "POST" and "/generate" in path and path.startswith("/api/v1/projects/"):
        limit, bucket = 30, "generate"
    if limit is not None:
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        key = (bucket, client_ip)
        with _rate_lock:
            # Expire old buckets and bound memory during bursts from many client addresses.
            for old_key in [k for k, values in _rate_windows.items()
                            if not values or now - values[-1] >= 60]:
                _rate_windows.pop(old_key, None)
            if len(_rate_windows) > 10000:
                _rate_windows.clear()
            events = _rate_windows.setdefault(key, deque())
            while events and now - events[0] >= 60:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(60 - (now - events[0])))
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                    headers={"Retry-After": str(retry_after)},
                )
            events.append(now)
    return await call_next(request)


if settings.auto_create_tables:
    Base.metadata.create_all(bind=engine)
