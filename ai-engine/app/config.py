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

    # --- LLM routing: Groq first (generation), Gemini as fallback ---
    # Aliases: "groq-<model>" -> Groq; "gemini-<model>" -> Google Gemini.
    # Groq has no embedding API, so embeddings always use Gemini (GOOGLE_API_KEY).
    DEFAULT_LLM: str = os.environ.get("DEFAULT_LLM", "groq-openai/gpt-oss-120b")
    FALLBACK_LLM: str = os.environ.get("FALLBACK_LLM", "gemini-3.6-flash")  # 2.5-* returns 404 for new keys
    GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
    GOOGLE_API_KEY: str = os.environ.get("GOOGLE_API_KEY", "")

    # --- Embeddings (locked dimension — Person 2 sizes the pgvector column on this) ---
    EMBEDDING_MODEL: str = "models/gemini-embedding-001"
    EMBEDDING_DIM: int = 768

    # --- Optional fallback provider ---
    MISTRAL_API_KEY: str = os.environ.get("MISTRAL_API_KEY", "")
    OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")

    # --- Cloud reranking (IMPLEMENTATION.draft.md §2.2.3; graceful without key) ---
    COHERE_API_KEY: str = os.environ.get("COHERE_API_KEY", "")
    RERANK_TOP_N: int = int(os.environ.get("RERANK_TOP_N", "4"))

    # --- Online evaluation / LLM-as-Judge (§3.2.1) — fast model per warning W-3 ---
    EVAL_JUDGE_LLM: str = os.environ.get("EVAL_JUDGE_LLM", os.environ.get("FALLBACK_LLM", "gemini-3.6-flash"))

    # --- Ingestion parser (IMPLEMENTATION.draft.md §2.2.1) ---
    DOCLING_ENABLED: bool = os.environ.get("DOCLING_ENABLED", "true").lower() == "true"

    # --- Hybrid retrieval (IMPLEMENTATION.draft.md §2.3) ---
    # "vector" (default until §2.3.6 criteria pass) or "hybrid" (tree leg + vector leg, RRF fusion)
    RETRIEVAL_MODE: str = os.environ.get("RETRIEVAL_MODE", "vector")
    TREE_TIMEOUT_S: float = float(os.environ.get("TREE_TIMEOUT_S", "8"))
    VECTOR_TIMEOUT_S: float = float(os.environ.get("VECTOR_TIMEOUT_S", "5"))
    TREE_SELECT_TOKEN_BUDGET: int = int(os.environ.get("TREE_SELECT_TOKEN_BUDGET", "3000"))
    TREE_CONCURRENCY: int = int(os.environ.get("TREE_CONCURRENCY", "4"))
    RETRIEVAL_CONTEXT_TOKENS: int = int(os.environ.get("RETRIEVAL_CONTEXT_TOKENS", "3000"))

    # --- Vector store ---
    COLLECTION_NAME: str = os.environ.get("COLLECTION_NAME", "devpilot_requirements")

    # --- Service ---
    PORT: int = int(os.environ.get("AI_ENGINE_PORT", "8001"))
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

    # --- Quota guardrail (Gemini free tier daily cap — configurable, not hardcoded) ---
    DAILY_REQUEST_QUOTA: int = int(os.environ.get("DAILY_REQUEST_QUOTA", "1500"))

    def validate(self):
        # Gemini key is always needed for embeddings, regardless of LLM routing.
        _require("GOOGLE_API_KEY")
        for alias in (self.DEFAULT_LLM, self.FALLBACK_LLM):
            if alias and alias.startswith("groq") and not self.GROQ_API_KEY:
                raise RuntimeError(f"GROQ_API_KEY is required because '{alias}' is configured.")
        if not self.DATABASE_URL:
            raise RuntimeError("DATABASE_URL is required (shared RDS Postgres instance).")


settings = Settings()
