"""Provider factory kept behind the existing get_llm call contract."""
from functools import lru_cache
from typing import Callable

from app.config import settings


ProviderBuilder = Callable[[str, float], object]


def _build_gemini(alias: str, temperature: float):
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=alias, temperature=temperature, google_api_key=settings.GOOGLE_API_KEY
    )


def _build_groq(alias: str, temperature: float):
    from langchain_groq import ChatGroq

    if not settings.GROQ_API_KEY:
        raise ValueError(f"GROQ_API_KEY is not set; cannot use model alias '{alias}'.")
    return ChatGroq(
        model=alias.removeprefix("groq-"),
        temperature=temperature,
        api_key=settings.GROQ_API_KEY,
    )


def _build_mistral(alias: str, temperature: float):
    from langchain_mistralai import ChatMistralAI

    return ChatMistralAI(
        model=alias, temperature=temperature, api_key=settings.MISTRAL_API_KEY
    )


def _build_ollama(alias: str, temperature: float):
    from langchain_ollama import ChatOllama

    return ChatOllama(model=alias.removeprefix("ollama-"), temperature=temperature)


def _build_openai(alias: str, temperature: float):
    from langchain_openai import ChatOpenAI

    key = getattr(settings, "OPENAI_API_KEY", "")
    if not key:
        raise ValueError("OPENAI_API_KEY is required for OpenAI model aliases")
    return ChatOpenAI(
        model=alias.removeprefix("openai-"), temperature=temperature, api_key=key
    )


_PROVIDER_BUILDERS: dict[str, ProviderBuilder] = {
    "gemini": _build_gemini,
    "groq": _build_groq,
    "mistral": _build_mistral,
    "ollama-": _build_ollama,
    "openai-": _build_openai,
}


def _build(alias: str, temperature: float):
    builder = next(
        (build for prefix, build in _PROVIDER_BUILDERS.items() if alias.startswith(prefix)),
        None,
    )
    if builder is None:
        raise ValueError(f"Unrecognized model alias '{alias}'")
    return builder(alias, temperature)


@lru_cache(maxsize=16)
def get_llm(model_alias: str | None = None, temperature: float = 0.2):
    return _build(model_alias or settings.DEFAULT_LLM, temperature)
