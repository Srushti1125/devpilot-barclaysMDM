from functools import lru_cache

from app.config import settings


@lru_cache(maxsize=8)
def get_llm(model_alias: str | None = None, temperature: float = 0.2):
    """
    Returns a LangChain chat model instance for the given alias.

    Keep temperature low (0-0.3) for artifact generation — consistency and
    schema compliance matter far more than creative variation here.
    """
    model_alias = model_alias or settings.DEFAULT_LLM

    if model_alias.startswith("gemini"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model_alias,
            temperature=temperature,
            google_api_key=settings.GOOGLE_API_KEY,
        )

    if model_alias.startswith("mistral"):
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI(
            model=model_alias,
            temperature=temperature,
            api_key=settings.MISTRAL_API_KEY,
        )

    if model_alias.startswith("groq"):
        from langchain_groq import ChatGroq
        # Strip "groq-" prefix to get the actual Groq model name
        groq_model = model_alias.removeprefix("groq-")
        return ChatGroq(
            model=groq_model,
            temperature=temperature,
            api_key=settings.GROQ_API_KEY,
        )

    # Add more branches here later (OpenAI, Anthropic, etc.) without
    # touching any call site — they all just call get_llm(alias).
    raise ValueError(f"Unrecognized model alias '{model_alias}' — no provider branch matches it.")


def get_default_llm():
    return get_llm(settings.DEFAULT_LLM)


def get_fallback_llm():
    """Used only when primary generation exhausts its retries (Step 9)."""
    return get_llm(settings.FALLBACK_LLM)
