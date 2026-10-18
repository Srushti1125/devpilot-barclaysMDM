"""
Evaluation stack tests (§4.2 Layers 2–3, W-5). Offline: the SOP run and ragas are faked
or skipped; only dataset integrity, auditor math and the endpoint wiring are asserted.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.evaluation.auditor import audit_artifact
from app.evaluation.batch_harness import GOLDEN_PATH, load_golden_rows
from app.main import app
from app.schemas.registry import SCHEMA_REGISTRY


# ── Golden dataset integrity (W-5) ───────────────────────────────────────────

def test_golden_file_committed_with_50_valid_rows():
    rows = load_golden_rows()
    assert len(rows) == 50
    for row in rows:
        assert row["artifact_type"] in SCHEMA_REGISTRY
        assert row["question"].strip() and row["ground_truth"].strip()
        assert row["project_id"].strip()


def test_load_golden_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_golden_rows(tmp_path / "nope.jsonl")


# ── Layer 3 auditor ──────────────────────────────────────────────────────────

def test_auditor_identical_outputs_pass():
    out = {"stories": [{"id": "US-1", "story": "As a user I want X"}]}
    report = audit_artifact(out, json.loads(json.dumps(out)), "user_story")
    assert report["overall_similarity"] == 1.0
    assert report["passes_70pct_threshold"] is True


def test_auditor_field_scores_on_divergence():
    report = audit_artifact({"a": "same text", "b": "x" * 50},
                            {"a": "same text", "b": "y" * 50}, "test_case")
    assert report["field_scores"]["a"] == 1.0
    assert report["field_scores"]["b"] < 0.1
    assert report["passes_70pct_threshold"] == (report["overall_similarity"] >= 0.70)
    assert report["overall_similarity"] < 0.70  # half the payload diverged


# ── Layer 2 harness (no ragas, no keys) ──────────────────────────────────────

def test_batch_harness_reports_modes_and_latency(monkeypatch, tmp_path):
    from app.evaluation import batch_harness

    fake_result = {
        "artifact_type": "user_story", "project_id": "p", "prompt_version": "user_story_v1",
        "output": {"stories": [{"title": "t", "story": "As a user, I want a reset flow.",
                                 "priority": "High", "category": "Auth", "dependencies": []}]},
        "context": "retrieved context text", "retrieval": {"mode": "vector", "fallback": None},
        "usage": {"total_tokens": 5}, "eval_score": 0.9, "retry_count": 0,
        "model_used": "fake",
    }
    monkeypatch.setattr("app.pipeline.sop_graph.run_sop_generation", lambda *a, **k: fake_result)

    report = batch_harness.run_batch_eval(retrieval_mode="hybrid", use_ragas=False,
                                          limit=3, report_path=tmp_path / "report.json")
    assert report["retrieval_mode"] == "hybrid"
    assert report["n_examples"] == 3
    assert report["latency_ms"]["p95"] >= report["latency_ms"]["p50"]
    assert report["tree_fallback_rate"] == 0.0
    assert "ragas" not in report
    # §2.3.6: the mode is restored after the run.
    from app.config import settings
    assert settings.RETRIEVAL_MODE in ("vector", "hybrid")
    assert (tmp_path / "report.json").exists()


def test_evaluate_batch_endpoint(monkeypatch):
    import app.evaluation.batch_harness as bh

    monkeypatch.setattr(bh, "run_batch_eval",
                        lambda project_id=None, retrieval_mode="vector": {"n_examples": 50,
                                                                          "retrieval_mode": retrieval_mode})
    client = TestClient(app)
    resp = client.post("/evaluate/batch?retrieval_mode=hybrid")
    assert resp.status_code == 200
    assert resp.json()["retrieval_mode"] == "hybrid"
    assert client.post("/evaluate/batch?retrieval_mode=bogus").status_code == 400


def test_evaluate_batch_missing_golden_503(monkeypatch):
    from app.evaluation import batch_harness

    def missing(*a, **k):
        raise FileNotFoundError(str(GOLDEN_PATH))

    monkeypatch.setattr(batch_harness, "run_batch_eval", missing)
    client = TestClient(app)
    assert client.post("/evaluate/batch").status_code == 503
