"""
Async ingestion job tests (§2.2.4). Parse/index are replaced with fakes; TestClient runs
BackgroundTasks to completion before returning, so the job is terminal on first poll.
"""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app


def _prepared(doc_id):
    node = SimpleNamespace(node_id="n-1", ordinal="1", level=1, title="Scope",
                           parent_id=None, page_start=1, page_end=2, text="t",
                           low_structure=False)
    return SimpleNamespace(chunks=["c1", "c2"], doc_id=doc_id or "gen-id",
                           content_hash="hash-1", tree_nodes=[node])


def test_ingest_returns_202_and_job_completes(monkeypatch):
    monkeypatch.setattr("app.main.prepare_document",
                        lambda path, pid, dt, did=None: _prepared(did))
    monkeypatch.setattr("app.main.index_chunks", lambda chunks: 2)
    monkeypatch.setattr("app.main.node_to_dict",
                        lambda node: {"node_id": node.node_id, "ordinal": node.ordinal,
                                      "level": node.level, "title": node.title, "parent_id": None,
                                      "page_start": node.page_start, "page_end": node.page_end,
                                      "text": node.text, "low_structure": False})
    client = TestClient(app)

    accepted = client.post("/ingest", json={"file_path": "/tmp/x.pdf", "project_id": "p1",
                                            "doc_type": "requirement", "doc_id": "req-9"})
    assert accepted.status_code == 202
    job_id = accepted.json()["job_id"]
    assert accepted.json()["status"] == "processing"

    status = client.get(f"/ingest/{job_id}").json()
    assert status["status"] == "done"
    assert status["chunks_indexed"] == 2
    assert status["doc_id"] == "req-9"
    assert status["content_hash"] == "hash-1"
    assert status["tree_nodes"][0]["node_id"] == "n-1"


def test_ingest_job_records_failure(monkeypatch):
    def boom(*a, **k):
        raise ValueError("unsupported file type")

    monkeypatch.setattr("app.main.prepare_document", boom)
    client = TestClient(app)
    job_id = client.post("/ingest", json={"file_path": "/tmp/x.exe", "project_id": "p1"}).json()["job_id"]

    status = client.get(f"/ingest/{job_id}").json()
    assert status["status"] == "failed"
    assert status["error_type"] == "invalid_input"
    assert "unsupported" in status["error"]


def test_ingest_status_unknown_job_404():
    client = TestClient(app)
    assert client.get("/ingest/does-not-exist").status_code == 404
