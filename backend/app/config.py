"""
Compatibility shim (IMPLEMENTATION.draft.md §1.2, W-6). The single Settings instance
lives in app.core.config. Re-exported so the API layer and services share one object
and one .env read.
"""
from app.core.config import Settings, settings  # noqa: F401
