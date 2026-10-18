"""Backward-compatible provider module; implementation lives in factory."""
from app.llm.factory import get_llm
from app.config import settings


def get_default_llm():
    return get_llm(settings.DEFAULT_LLM)


def get_fallback_llm():
    return get_llm(settings.FALLBACK_LLM)
