from functools import lru_cache

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_postgres import PGVector

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
def get_vectorstore() -> PGVector:
    return PGVector(
        embeddings=get_embeddings(),
        collection_name=COLLECTION_NAME,
        connection=settings.DATABASE_URL,
        use_jsonb=True,  # store metadata as jsonb -> filterable by project_id/doc_type
    )


def index_chunks(chunks) -> int:
    """Embed and upsert a batch of chunked Documents. Returns count indexed."""
    if not chunks:
        return 0
    vs = get_vectorstore()
    vs.add_documents(chunks)
    return len(chunks)
