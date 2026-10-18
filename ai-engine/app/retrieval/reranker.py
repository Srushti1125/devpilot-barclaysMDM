"""
Cloud reranking via Cohere Rerank (IMPLEMENTATION.draft.md §2.2.3).

Replaces NexusRAG's local PyTorch cross-encoder: milliseconds, ~fractions of a cent,
zero VRAM — which is what keeps the 30s NFR reachable on student hardware.

Source pattern: https://github.com/LeDat98/NexusRAG (reranking module)
API docs: https://docs.cohere.com/reference/rerank

Graceful degradation is the contract: without COHERE_API_KEY (or if langchain-cohere
is not installed) the base retriever is returned untouched and the system behaves
exactly as in Sprint 2.
"""
from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger("devpilot.reranker")


def with_reranking(base_retriever, top_n: int | None = None):
    """Wrap any retriever with Cohere reranking; falls back to the raw retriever."""
    api_key = settings.COHERE_API_KEY
    if not api_key:
        return base_retriever
    try:
        from langchain.retrievers import ContextualCompressionRetriever
        from langchain_cohere import CohereRerank
    except ImportError:  # pragma: no cover - optional dependency
        logger.warning("langchain-cohere not installed; skipping reranking")
        return base_retriever
    compressor = CohereRerank(model="rerank-v3.5",
                              top_n=top_n or settings.RERANK_TOP_N,
                              cohere_api_key=api_key)
    logger.info("Cohere reranking enabled (top_n=%d)", compressor.top_n if hasattr(compressor, "top_n") else top_n)
    return ContextualCompressionRetriever(base_compressor=compressor, base_retriever=base_retriever)
