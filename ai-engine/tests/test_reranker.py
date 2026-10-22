"""Cohere reranking wrapper: graceful fallback, successful wrap, import-error fallback."""
import sys
from unittest.mock import MagicMock, patch

from app.config import settings
from app.retrieval.reranker import with_reranking


def test_no_api_key_returns_base_retriever_untouched(monkeypatch):
    monkeypatch.setattr(settings, "COHERE_API_KEY", "")
    base = object()
    assert with_reranking(base) is base


def test_with_api_key_wraps_in_contextual_compression_retriever(monkeypatch):
    monkeypatch.setattr(settings, "COHERE_API_KEY", "test-key")
    monkeypatch.setattr(settings, "RERANK_TOP_N", 5)
    base = MagicMock()

    mock_compressor = MagicMock()
    mock_compressor.top_n = 5
    mock_cc_instance = MagicMock()

    with patch.dict(sys.modules, {
        "langchain_cohere": MagicMock(CohereRerank=MagicMock(return_value=mock_compressor)),
        "langchain.retrievers": MagicMock(
            ContextualCompressionRetriever=MagicMock(return_value=mock_cc_instance)
        ),
    }):
        result = with_reranking(base)

    assert result is mock_cc_instance


def test_import_error_falls_back_to_base_retriever(monkeypatch):
    monkeypatch.setattr(settings, "COHERE_API_KEY", "test-key")
    base = MagicMock()
    # Setting a sys.modules entry to None forces ImportError on 'from x import y'
    with patch.dict(sys.modules, {"langchain_cohere": None}):
        result = with_reranking(base)
    assert result is base
