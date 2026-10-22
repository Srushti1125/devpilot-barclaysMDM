"""
Compatibility shim. The single SQLAlchemy Base, engine and session factory live in
app.core.database. Re-exported here so legacy imports share one metadata object.
(Previously this module defined a second Base, so create_all() on it created no domain tables.)
"""
from app.core.database import Base, SessionLocal, engine, get_db  # noqa: F401

