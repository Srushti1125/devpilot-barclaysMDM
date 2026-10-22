"""LLM factory builders: each provider, prefix stripping, error paths."""
import pytest

from app.config import settings
from app.llm import factory


def test_build_gemini_returns_chat_google_generative_ai(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "test-key")
    factory.get_llm.cache_clear()
    llm = factory._build_gemini("gemini-2.5-flash", 0.3)
    assert type(llm).__name__ == "ChatGoogleGenerativeAI"
    factory.get_llm.cache_clear()


def test_build_mistral_returns_chat_mistral_ai(monkeypatch):
    monkeypatch.setattr(settings, "MISTRAL_API_KEY", "test-key")
    factory.get_llm.cache_clear()
    llm = factory._build_mistral("mistral-large-latest", 0.2)
    assert type(llm).__name__ == "ChatMistralAI"
    factory.get_llm.cache_clear()


def test_build_ollama_strips_prefix(monkeypatch):
    pytest.importorskip("langchain_ollama")
    monkeypatch.setattr(settings, "MISTRAL_API_KEY", "unused")
    factory.get_llm.cache_clear()
    llm = factory._build_ollama("ollama-llama3.2", 0.1)
    assert type(llm).__name__ == "ChatOllama"
    factory.get_llm.cache_clear()


def test_build_openai_success(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    factory.get_llm.cache_clear()
    llm = factory._build_openai("openai-gpt-4o", 0.0)
    assert type(llm).__name__ == "ChatOpenAI"
    factory.get_llm.cache_clear()


def test_build_openai_without_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    factory.get_llm.cache_clear()
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        factory._build_openai("openai-gpt-4o", 0.0)
    factory.get_llm.cache_clear()


def test_build_unrecognized_alias_raises():
    factory.get_llm.cache_clear()
    with pytest.raises(ValueError, match="Unrecognized model alias"):
        factory._build("claude-sonnet-4", 0.2)
    factory.get_llm.cache_clear()


def test_get_llm_defaults_to_settings_default(monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_LLM", "gemini-2.5-flash")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "test-key")
    factory.get_llm.cache_clear()
    llm = factory.get_llm()
    assert type(llm).__name__ == "ChatGoogleGenerativeAI"
    factory.get_llm.cache_clear()


def test_provider_get_default_llm(monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_LLM", "gemini-2.5-flash")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "test-key")
    factory.get_llm.cache_clear()
    from app.llm.provider import get_default_llm
    llm = get_default_llm()
    assert type(llm).__name__ == "ChatGoogleGenerativeAI"
    factory.get_llm.cache_clear()


def test_provider_get_fallback_llm(monkeypatch):
    monkeypatch.setattr(settings, "FALLBACK_LLM", "gemini-2.0-flash")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "test-key")
    factory.get_llm.cache_clear()
    from app.llm.provider import get_fallback_llm
    llm = get_fallback_llm()
    assert type(llm).__name__ == "ChatGoogleGenerativeAI"
    factory.get_llm.cache_clear()
