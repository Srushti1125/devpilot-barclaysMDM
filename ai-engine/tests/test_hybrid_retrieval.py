"""Hybrid retrieval policy: RRF fusion, dedupe by node_id, degradation rules, token budget."""
import time

import pytest
from langchain_core.documents import Document

from app.retrieval.hybrid import RetrievalError, hybrid_retrieve, rrf_fuse
from app.retrieval.tree_search import TreeSkipped


def _doc(node_id, text, title="T", ps=1, pe=1, idx=0):
    md = {"node_id": node_id, "title": title, "page_start": ps, "page_end": pe, "chunk_index": idx}
    return Document(page_content=text, metadata=md)


def _run(vector=None, tree=None, nodes=None, vt=2.0, tt=2.0, budget=3000):
    return hybrid_retrieve(
        vector_search=vector or (lambda: []),
        tree_select=tree or (lambda: []),
        load_nodes=nodes or (lambda ids: {}),
        vector_timeout_s=vt, tree_timeout_s=tt, context_token_budget=budget,
    )


def test_rrf_rewards_agreement_between_rankings():
    scores = rrf_fuse([["a", "b", "c"], ["b", "a", "d"]])
    assert scores["a"] > scores["c"] and scores["b"] > scores["d"]
    assert scores["a"] == pytest.approx(1 / 61 + 1 / 62)


def test_same_node_from_both_legs_collapses_and_records_both_sources():
    d = _doc("n1", "Limits apply.", title="2 Payments", ps=3, pe=4)
    res = _run(vector=lambda: [d], tree=lambda: ["n1"],
               nodes=lambda ids: {"n1": {"title": "2 Payments", "text": "Full section body.",
                                         "page_start": 3, "page_end": 4}})
    assert res.trace["items"][0]["sources"] == ["tree", "vector"]
    assert len(res.trace["items"]) == 1
    assert "Full section body." in res.context
    assert "[source: tree+vector | 2 Payments | pages 3-4]" in res.context


def test_tree_timeout_degrades_to_vector_only_with_reason():
    d = _doc("n1", "vector text")

    def slow_tree():
        time.sleep(1.0)
        return ["n1"]

    res = _run(vector=lambda: [d], tree=slow_tree, tt=0.1)
    assert res.trace["fallback"] == "tree_timeout"
    assert res.trace["items"][0]["sources"] == ["vector"]


def test_tree_skipped_and_tree_error_degrade_without_failing():
    d = _doc("n1", "vector text")

    def skipped():
        raise TreeSkipped("no_structured_documents")

    def broken():
        raise ValueError("LLM 503")

    assert _run(vector=lambda: [d], tree=skipped).trace["fallback"] == "tree_skipped:no_structured_documents"
    res = _run(vector=lambda: [d], tree=broken)
    assert res.trace["fallback"] == "tree_error"
    assert "vector text" in res.context


def test_empty_tree_selection_is_recorded():
    res = _run(vector=lambda: [_doc("n1", "x")], tree=lambda: [])
    assert res.trace["fallback"] == "tree_empty_selection"


def test_vector_failure_is_a_hard_error_not_silent_empty_context():
    def boom():
        raise ConnectionError("pgvector down")

    with pytest.raises(RetrievalError, match="pgvector down"):
        _run(vector=boom)


def test_vector_timeout_is_a_hard_error():
    def slow():
        time.sleep(1.0)
        return []

    with pytest.raises(RetrievalError, match="timed out"):
        _run(vector=slow, vt=0.1)


def test_token_budget_drops_lowest_ranked_first():
    docs = [_doc(f"n{i}", "word " * 200, idx=i) for i in range(5)]  # ~250 tokens each
    res = _run(vector=lambda: docs, budget=400)
    kept = [i["node_id"] for i in res.trace["items"]]
    assert kept == ["n0"]  # best-ranked item survives; later ones are dropped, never reordered
    assert res.trace["tokens_est"] <= 400


def test_no_items_gives_explicit_no_context_marker():
    res = _run(vector=lambda: [], tree=lambda: [])
    assert "no matching context" in res.context
