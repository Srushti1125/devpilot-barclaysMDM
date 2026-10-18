"""MMR retriever construction: project/doc_type filters, custom search params."""
from unittest.mock import MagicMock, patch

from app.retrieval.retriever import DEFAULT_FETCH_K, DEFAULT_K, DEFAULT_LAMBDA_MULT, get_retriever


def test_get_retriever_builds_mmr_with_project_filter():
    mock_vs = MagicMock()
    with patch("app.retrieval.retriever.get_vectorstore", return_value=mock_vs):
        get_retriever("proj-1")
    mock_vs.as_retriever.assert_called_once_with(
        search_type="mmr",
        search_kwargs={
            "k": DEFAULT_K,
            "fetch_k": DEFAULT_FETCH_K,
            "lambda_mult": DEFAULT_LAMBDA_MULT,
            "filter": {"project_id": "proj-1"},
        },
    )


def test_get_retriever_with_doc_type_adds_filter():
    mock_vs = MagicMock()
    with patch("app.retrieval.retriever.get_vectorstore", return_value=mock_vs):
        get_retriever("proj-1", doc_type="requirement")
    filt = mock_vs.as_retriever.call_args[1]["search_kwargs"]["filter"]
    assert filt == {"project_id": "proj-1", "doc_type": "requirement"}


def test_get_retriever_custom_search_params():
    mock_vs = MagicMock()
    with patch("app.retrieval.retriever.get_vectorstore", return_value=mock_vs):
        get_retriever("p", doc_type="sop", k=10, fetch_k=50, lambda_mult=0.7)
    kwargs = mock_vs.as_retriever.call_args[1]["search_kwargs"]
    assert kwargs["k"] == 10
    assert kwargs["fetch_k"] == 50
    assert kwargs["lambda_mult"] == 0.7
