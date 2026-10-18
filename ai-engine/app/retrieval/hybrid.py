"""
Hybrid retrieval: tree leg + vector leg, fused with Reciprocal Rank Fusion (IMPLEMENTATION.draft.md §2.3.4).

Policy:
  - Both legs start together. Each has its own deadline measured from the start of the request.
  - Vector leg failure or timeout is a hard error. Retrieval never silently returns nothing.
  - Tree leg failure, timeout, skip, or empty selection degrades to vector-only, and the reason
    is recorded in the trace.
  - Vector hits carry node_id, so the same section from both legs collapses to one entry.
  - Items are ordered by RRF score and cut to a token budget, lowest-ranked dropped first.
  - Every item keeps provenance: which leg found it, its title, and its page range.

The legs are injected as callables so the policy is testable without a database or an LLM.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from langchain_core.documents import Document

from app.retrieval.tree_search import TreeSkipped

logger = logging.getLogger("devpilot.hybrid")

RRF_K = 60
NO_CONTEXT = "(no matching context retrieved for this project)"
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="retrieval")


class RetrievalError(RuntimeError):
    """Vector leg failed or timed out. Surfaced to the caller; never swallowed."""


@dataclass
class RetrievalResult:
    context: str
    trace: dict = field(default_factory=dict)


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """score(key) = sum over rankings of 1 / (k + rank), rank starting at 1."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return scores


def _chunk_key(doc: Document, position: int) -> str:
    node_id = doc.metadata.get("node_id")
    return node_id if node_id else f"chunk:{doc.metadata.get('chunk_index', position)}"


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _format_item(item: dict) -> str:
    pages = ""
    if item.get("page_start") is not None:
        pages = f" | pages {item['page_start']}-{item.get('page_end', item['page_start'])}"
    header = f"[source: {'+'.join(sorted(item['sources']))} | {item['title'] or 'untitled'}{pages}]"
    return f"{header}\n{item['text']}"


def hybrid_retrieve(
    *,
    vector_search: Callable[[], list[Document]],
    tree_select: Callable[[], list[str]],
    load_nodes: Callable[[list[str]], dict[str, dict]],
    vector_timeout_s: float,
    tree_timeout_s: float,
    context_token_budget: int,
) -> RetrievalResult:
    t0 = time.monotonic()
    tree_future = _pool.submit(tree_select)
    vector_future = _pool.submit(vector_search)

    # Vector leg: hard deadline.
    done, _ = wait([vector_future], timeout=vector_timeout_s)
    if vector_future not in done:
        raise RetrievalError(f"vector retrieval timed out after {vector_timeout_s}s")
    try:
        docs = vector_future.result()
    except Exception as e:
        raise RetrievalError(f"vector retrieval failed: {e}") from e
    t_vector = time.monotonic() - t0

    # Tree leg: soft deadline. Its failure degrades to vector-only.
    fallback = None
    tree_ids: list[str] = []
    remaining = max(0.0, tree_timeout_s - (time.monotonic() - t0))
    done, _ = wait([tree_future], timeout=remaining)
    if tree_future not in done:
        fallback = "tree_timeout"
        tree_future.cancel()
    else:
        try:
            tree_ids = tree_future.result()
            if not tree_ids:
                fallback = "tree_empty_selection"
        except TreeSkipped as e:
            fallback = f"tree_skipped:{e}"
        except Exception as e:  # selector / LLM errors: degrade, never fail the request
            fallback = "tree_error"
            logger.warning("Tree leg failed; using vector-only context: %s", e)
    t_total = time.monotonic() - t0

    # Vector ranking: first occurrence per key, so multiple chunks of one node count once.
    vector_keys: list[str] = []
    vector_docs: dict[str, Document] = {}
    for position, doc in enumerate(docs):
        key = _chunk_key(doc, position)
        if key not in vector_docs:
            vector_docs[key] = doc
            vector_keys.append(key)

    scores = rrf_fuse([vector_keys, tree_ids])
    ordered = sorted(scores, key=lambda k: (-scores[k], (vector_keys + tree_ids).index(k)))

    # Parent resolution: node keys take the node's text from the tree store when available.
    try:
        node_rows = load_nodes([k for k in ordered if not k.startswith("chunk:")])
    except Exception as e:
        logger.warning("Node text lookup failed; using chunk text: %s", e)
        node_rows = {}

    items: list[dict] = []
    tokens = 0
    for key in ordered:
        row = node_rows.get(key)
        doc = vector_docs.get(key)
        if row is not None:
            text, title = row.get("text") or (doc.page_content if doc else ""), row.get("title")
            page_start, page_end = row.get("page_start"), row.get("page_end")
        elif doc is not None:
            text, title = doc.page_content, doc.metadata.get("title")
            page_start = doc.metadata.get("page_start")
            page_end = doc.metadata.get("page_end")
        else:
            continue  # tree-only id whose text we could not load: nothing to show
        if not text or not text.strip():
            continue
        item = {
            "node_id": key if not key.startswith("chunk:") else None,
            "sources": sorted(({"vector"} if key in vector_docs else set())
                              | ({"tree"} if key in tree_ids else set())),
            "title": title, "text": text.strip(),
            "page_start": page_start, "page_end": page_end, "score": round(scores[key], 5),
        }
        cost = _estimate_tokens(_format_item(item))
        if tokens + cost > context_token_budget:
            break  # lowest-ranked items are dropped first
        tokens += cost
        items.append(item)

    context = "\n\n".join(_format_item(i) for i in items) if items else NO_CONTEXT
    trace = {
        "mode": "hybrid",
        "fallback": fallback,
        "vector_hits": len(docs),
        "tree_selected": tree_ids,
        "items": [{"node_id": i["node_id"], "sources": i["sources"], "score": i["score"],
                   "pages": [i["page_start"], i["page_end"]]} for i in items],
        "tokens_est": tokens,
        "latency_ms": {"vector": int(t_vector * 1000), "retrieval_total": int(t_total * 1000)},
    }
    if fallback:
        logger.info("Hybrid retrieval fell back to vector-only: %s", fallback)
    return RetrievalResult(context=context, trace=trace)
