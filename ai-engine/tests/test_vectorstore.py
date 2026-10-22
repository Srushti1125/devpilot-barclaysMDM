"""PGVector factory: embeddings construction, engine pool config, index_chunks."""
from unittest.mock import MagicMock, patch

from app.config import settings
from app.retrieval import vectorstore


def test_get_embeddings_constructs_google_embeddings(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "test-key")
    vectorstore.get_embeddings.cache_clear()
    with patch.object(vectorstore, "GoogleGenerativeAIEmbeddings") as mock_cls:
        result = vectorstore.get_embeddings()
    mock_cls.assert_called_once_with(
        model=settings.EMBEDDING_MODEL,
        google_api_key="test-key",
    )
    assert result is mock_cls.return_value
    vectorstore.get_embeddings.cache_clear()


def test_get_engine_postgresql_pool_config(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://user:pass@host/db")
    vectorstore.get_engine.cache_clear()
    with patch.object(vectorstore, "create_engine") as mock_ce:
        vectorstore.get_engine()
    mock_ce.assert_called_once_with(
        "postgresql://user:pass@host/db",
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    vectorstore.get_engine.cache_clear()


def test_get_engine_sqlite_no_pool_kwargs(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///test.db")
    vectorstore.get_engine.cache_clear()
    with patch.object(vectorstore, "create_engine") as mock_ce:
        vectorstore.get_engine()
    mock_ce.assert_called_once_with("sqlite:///test.db", pool_pre_ping=True)
    vectorstore.get_engine.cache_clear()


def test_get_vectorstore_constructs_pgvector_with_jsonb(monkeypatch):
    vectorstore.get_vectorstore.cache_clear()
    mock_vs = MagicMock()
    mock_emb = MagicMock()
    mock_engine = MagicMock()
    with patch.object(vectorstore, "PGVector", return_value=mock_vs) as mock_pg, \
         patch.object(vectorstore, "get_embeddings", return_value=mock_emb), \
         patch.object(vectorstore, "get_engine", return_value=mock_engine):
        result = vectorstore.get_vectorstore()
    mock_pg.assert_called_once_with(
        embeddings=mock_emb,
        collection_name=settings.COLLECTION_NAME,
        connection=mock_engine,
        use_jsonb=True,
    )
    assert result is mock_vs
    vectorstore.get_vectorstore.cache_clear()


def test_index_chunks_empty_list_returns_zero():
    assert vectorstore.index_chunks([]) == 0


def test_index_chunks_adds_documents_and_returns_count():
    mock_vs = MagicMock()
    docs = [MagicMock(), MagicMock(), MagicMock()]
    with patch.object(vectorstore, "get_vectorstore", return_value=mock_vs):
        result = vectorstore.index_chunks(docs)
    mock_vs.add_documents.assert_called_once_with(docs)
    assert result == 3
