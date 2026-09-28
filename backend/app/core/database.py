from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


# ── Connection parameters tuned per backend ─────────────────────────────────

_connect_args: dict = {}
_engine_kwargs: dict = {
    "pool_pre_ping": True,  # Detect stale connections (essential for Neon idle-compute timeouts)
}

if settings.database_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False
else:
    # PostgreSQL (Neon / self-hosted / Docker pgvector)
    _engine_kwargs.update(
        {
            "pool_size": 10,
            "max_overflow": 20,
            "pool_recycle": 300,  # 5 min – prevents Neon serverless from killing idle sockets
            "pool_timeout": 30,
        }
    )

engine = create_engine(settings.database_url, connect_args=_connect_args, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI dependency – yields a scoped DB session, auto-closed on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
