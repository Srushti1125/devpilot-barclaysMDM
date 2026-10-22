from functools import lru_cache

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_postgres import PGVector
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.config import settings

EMBEDDING_MODEL = settings.EMBEDDING_MODEL  # "models/text-embedding-004" -> 768 dims
COLLECTION_NAME = settings.COLLECTION_NAME


@lru_cache(maxsize=1)
def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL,
        google_api_key=settings.GOOGLE_API_KEY,
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Shared pool-tuned engine behind PGVector.

    The single lru_cache'd PGVector instance is shared across every thread
    (async ingestion jobs in BackgroundTasks + concurrent /generate retrievals),
    so the pool must be sized for that fan-out (IMPLEMENTATION.draft.md §11 W-2).
    SQLite dev URLs fall back to SQLAlchemy defaults (no pool kwargs).
    """
    kwargs = {"pool_pre_ping": True}
    if settings.DATABASE_URL.startswith("postgresql"):
        kwargs.update(pool_size=10, max_overflow=20)
    return create_engine(settings.DATABASE_URL, **kwargs)


@lru_cache(maxsize=1)
def get_vectorstore() -> PGVector:
    return PGVector(
        embeddings=get_embeddings(),
        collection_name=COLLECTION_NAME,
        connection=get_engine(),
        use_jsonb=True,  # store metadata as jsonb -> filterable by project_id/doc_type
    )


def index_chunks(chunks) -> int:
    """Embed and upsert a batch of chunked Documents. Returns count indexed."""
    if not chunks:
        return 0
    vs = get_vectorstore()
    vs.add_documents(chunks)
    return len(chunks)
