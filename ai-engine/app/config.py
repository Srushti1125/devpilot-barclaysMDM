"""
Centralized configuration for the AI engine.

Everything that changes between environments (dev laptop -> AWS) or between
providers (Gemini free tier today -> paid / different provider later) lives
here as an env var, never hardcoded in pipeline code. This is what makes the
"model-agnostic LLM layer" requirement actually true in practice.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val or val == "CHANGE_ME":
        raise RuntimeError(
            f"Missing required env var: {name}. Copy .env.example to .env and fill it in."
        )
    return val


class Settings:
    # --- Database (shared RDS Postgres instance with pgvector enabled) ---
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")

    # --- LLM provider (Google Gemini, hosted, free tier) ---
    GOOGLE_API_KEY: str = os.environ.get("GOOGLE_API_KEY", "")
    DEFAULT_LLM: str = os.environ.get("DEFAULT_LLM", "gemini-3.6-flash")
    FALLBACK_LLM: str = os.environ.get("FALLBACK_LLM", "gemini-2.5-pro")

    # --- Embeddings (locked dimension — Person 2 sizes the pgvector column on this) ---
    EMBEDDING_MODEL: str = "models/gemini-embedding-001"
    EMBEDDING_DIM: int = 768

    # --- Optional fallback provider ---
    MISTRAL_API_KEY: str = os.environ.get("MISTRAL_API_KEY", "")
    GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")

    # --- Vector store ---
    COLLECTION_NAME: str = os.environ.get("COLLECTION_NAME", "devpilot_requirements")

    # --- Service ---
    PORT: int = int(os.environ.get("AI_ENGINE_PORT", "8001"))
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

    # --- Quota guardrail (Gemini free tier daily cap — configurable, not hardcoded) ---
    DAILY_REQUEST_QUOTA: int = int(os.environ.get("DAILY_REQUEST_QUOTA", "1500"))

    def validate(self):
        _require("GOOGLE_API_KEY")
        if not self.DATABASE_URL:
            raise RuntimeError("DATABASE_URL is required (shared RDS Postgres instance).")


settings = Settings()
