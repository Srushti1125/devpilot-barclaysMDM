"""
Routing tests: Groq primary, Gemini fallback.

No network calls. Chains are fake RunnableLambdas; provider construction is checked
without invoking the API.
"""
import pytest
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

from app.config import Settings
from app.llm import provider
from app.llm.parsers import get_parser
from app.pipeline.quality_check import generate_with_quality_check


class _Item(BaseModel):
    title: str


def _chain(fn):
    return RunnableLambda(fn)


def _ok(_inputs):
    return '{"title": "from-fallback"}'


def test_provider_error_skips_to_fallback_without_primary_retries():
    calls = {"primary": 0}

    def primary(_):
        calls["primary"] += 1
        raise ConnectionError("groq 429 rate limited")

    parsed, _ = generate_with_quality_check(
        _chain(primary), {"requirement": "x"}, get_parser(_Item),
        max_retries=3, fallback_chain=_chain(_ok),
    )
    assert parsed.title == "from-fallback"
    assert calls["primary"] == 1, "provider errors must not burn primary retries"


def test_parse_error_retries_primary_then_succeeds_without_fallback():
    calls = {"primary": 0}

    def primary(_):
        calls["primary"] += 1
        return "not json" if calls["primary"] == 1 else '{"title": "fixed"}'

    def fallback(_):
        raise AssertionError("fallback must not run when primary repairs itself")

    parsed, _ = generate_with_quality_check(
        _chain(primary), {"requirement": "x"}, get_parser(_Item),
        max_retries=2, fallback_chain=_chain(fallback),
    )
    assert parsed.title == "fixed"
    assert calls["primary"] == 2


def test_both_providers_failing_raises_runtime_error():
    def boom(_):
        raise TimeoutError("down")

    with pytest.raises(RuntimeError, match="Generation failed"):
        generate_with_quality_check(
            _chain(boom), {"requirement": "x"}, get_parser(_Item),
            max_retries=2, fallback_chain=_chain(boom),
        )


def test_groq_alias_without_key_fails_fast(monkeypatch):
    monkeypatch.setattr(provider.settings, "GROQ_API_KEY", "")
    provider.get_llm.cache_clear()
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        provider.get_llm("groq-openai/gpt-oss-120b")


def test_groq_alias_builds_chat_groq_with_prefix_stripped(monkeypatch):
    monkeypatch.setattr(provider.settings, "GROQ_API_KEY", "gsk_test")
    provider.get_llm.cache_clear()
    llm = provider.get_llm("groq-openai/gpt-oss-120b")
    assert type(llm).__name__ == "ChatGroq"
    assert llm.model_name == "openai/gpt-oss-120b"
    provider.get_llm.cache_clear()


def test_validate_requires_groq_key_when_groq_is_default(monkeypatch):
    s = Settings()
    monkeypatch.setattr(s, "GOOGLE_API_KEY", "g-key")
    monkeypatch.setattr(s, "DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(s, "DEFAULT_LLM", "groq-openai/gpt-oss-120b")
    monkeypatch.setattr(s, "GROQ_API_KEY", "")
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        s.validate()
