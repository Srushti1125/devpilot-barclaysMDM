"""
End-to-end on the real code paths, with only the embedding store and the LLM stubbed:
  /ingest (real pipeline) -> tree rows persisted (as the backend would) -> retrieve_context in
  hybrid mode (real tree store, real selector, real RRF fusion).
"""
import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from sqlalchemy import create_engine, insert
from sqlalchemy.pool import StaticPool

import app.main as main
from app.pipeline import chain
from app.retrieval import tree_search, tree_store

DOC = (
    "# 1 Authentication\n## 1.1 Password Reset\n"
    "Customers reset their password with a one-time code sent to their registered email.\n"
    "## 1.2 Multi-Factor Authentication\nAdministrator logins require TOTP or SMS.\n"
    "# 2 Payments\n## 2.1 Transfer Limits\nRetail customers may transfer 5000 GBP per day.\n"
)


@pytest.fixture
def ingested(tmp_path, monkeypatch):
    """Ingest a document through the real endpoint; capture chunks instead of embedding them.
    §2.2.4: /ingest returns 202 with a job id; the terminal state carries the tree payload."""
    stored: list[Document] = []
    monkeypatch.setattr("app.retrieval.vectorstore.index_chunks", lambda chunks: (stored.extend(chunks), len(chunks))[1])
    path = tmp_path / "reqs.md"
    path.write_text(DOC, encoding="utf-8")
    client = TestClient(main.app)
    resp = client.post("/ingest", json={
        "file_path": str(path), "project_id": "p1", "doc_type": "requirement", "doc_id": "req-1"})
    assert resp.status_code == 202, resp.text
    payload = client.get(f"/ingest/{resp.json()['job_id']}").json()
    assert payload["status"] == "done", payload
    return payload, stored


def _persist_as_backend_would(payload, project_id, engine):
    """The backend writes these rows at upload. Mirrors the columns the ai-engine reads."""
    store = tree_store
    store._md.create_all(engine)
    with engine.begin() as c:
        c.execute(insert(store.requirements_t), [
            {"id": payload["doc_id"], "project_id": project_id, "doc_type": "requirement"}])
        c.execute(insert(store.doc_tree_nodes_t), [{
            "id": n["node_id"], "project_id": project_id, "doc_id": payload["doc_id"],
            "parent_id": n["parent_id"], "ordinal": n["ordinal"], "level": n["level"],
            "title": n["title"], "page_start": n["page_start"], "page_end": n["page_end"],
            "text": n["text"], "low_structure": n["low_structure"],
            "content_hash": payload["content_hash"]} for n in payload["tree_nodes"]])


def test_ingest_returns_tree_and_every_chunk_is_node_linked(ingested):
    payload, chunks = ingested
    node_ids = {n["node_id"] for n in payload["tree_nodes"]}
    assert payload["doc_id"] == "req-1"
    assert chunks and all(c.metadata["node_id"] in node_ids for c in chunks)
    titles = {n["title"]: n for n in payload["tree_nodes"]}
    assert titles["1.1 Password Reset"]["parent_id"] == titles["1 Authentication"]["node_id"]


def test_hybrid_retrieval_end_to_end(ingested, monkeypatch):
    payload, chunks = ingested
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    _persist_as_backend_would(payload, "p1", engine)
    monkeypatch.setattr(tree_store, "get_engine", lambda: engine)
    tree_search._cache = tree_search._SelectionCache()

    # Tree leg: the selector LLM picks the payments section (validated against the outline).
    pay = next(n for n in payload["tree_nodes"] if n["title"] == "2 Payments")
    llm_calls = []

    class FakeLLM:
        def invoke(self, prompt):
            llm_calls.append(prompt)
            return json.dumps({"node_ids": [pay["node_id"], "not-in-outline"]})

    monkeypatch.setattr("app.llm.provider.get_llm", lambda *a, **k: FakeLLM())
    # Vector leg: the auth chunk ranks first, the payments chunk second.
    auth_chunk = next(c for c in chunks if c.metadata["title"] == "1.1 Password Reset")
    pay_chunk = next(c for c in chunks if c.metadata["title"] == "2.1 Transfer Limits")

    class FakeRetriever:
        def invoke(self, q):
            return [auth_chunk, pay_chunk]

    monkeypatch.setattr(chain, "get_retriever", lambda *a, **k: FakeRetriever())
    monkeypatch.setattr(chain.settings, "RETRIEVAL_MODE", "hybrid")

    res = chain.retrieve_context("p1", "transfer limits and resets")

    assert res.trace["mode"] == "hybrid" and res.trace["fallback"] is None
    assert res.trace["tree_selected"] == [pay["node_id"]]     # invalid id dropped
    assert "5000 GBP" in res.context                            # tree-selected section present
    assert "one-time code" in res.context                       # vector hit present
    sources = {i["node_id"]: i["sources"] for i in res.trace["items"]}
    # Payments section (selected by tree, body empty) resolves to its subsection's text.
    assert sources[pay["node_id"]] == ["tree"]
    assert sources[pay_chunk.metadata["node_id"]] == ["vector"]
    # The selector never saw body text, only ids/titles/pages.
    assert "5000 GBP" not in llm_calls[0] and "one-time code" not in llm_calls[0]


def test_other_project_cannot_be_selected(ingested, monkeypatch):
    payload, _ = ingested
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    _persist_as_backend_would(payload, "p1", engine)
    monkeypatch.setattr(tree_store, "get_engine", lambda: engine)
    assert tree_store.load_outline("p-other", "requirement", engine=engine) == []
    assert tree_store.load_node_texts("p-other", [n["node_id"] for n in payload["tree_nodes"]], engine=engine) == {}
