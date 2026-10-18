"""
SOP LangGraph tests (§3.2). Everything runs offline: the draft chain, retrieval and the
judge are replaced with fakes, so no API keys or database are needed.
"""
import json
from types import SimpleNamespace

import pytest

from app.pipeline import sop_graph
from app.pipeline.chain import RetrievalResult
from app.pipeline.sop_graph import run_sop_generation
from app.schemas.registry import get_schema

VALID_STORY = {
    "stories": [{
        "title": "Password reset via OTP",
        "story": "As a customer, I want to reset my password via OTP so that I can regain access.",
        "priority": "High",
        "category": "Authentication",
        "dependencies": [],
    }],
}


class FakeChain:
    """Records the inputs each invoke receives; optionally fails the first call."""

    def __init__(self, reply: str, fail_times: int = 0):
        self.reply = reply
        self.fail_times = fail_times
        self.calls: list[dict] = []

    def invoke(self, inputs):
        self.calls.append(inputs)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("groq 429 rate limit")
        return SimpleNamespace(content=self.reply,
                               usage_metadata={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30})


@pytest.fixture
def harness(monkeypatch):
    """Wires fakes into the sop_graph namespace and records call counts."""
    state = {"retrievals": 0, "builds": 0, "judge": [0.9]}
    chain = FakeChain(json.dumps(VALID_STORY))

    def fake_retrieve(project_id, requirement_text, doc_type="requirement"):
        state["retrievals"] += 1
        return RetrievalResult(context="CTX", trace={"mode": "vector", "vector_hits": 2})

    def fake_build(artifact_type, schema_cls, model_alias=None):
        state["builds"] += 1
        built = chain if chain.fail_times == 0 else FakeChain(json.dumps(VALID_STORY), fail_times=0)
        # First built chain carries the provider failure, if any.
        return built, None, f"{artifact_type}_v1"

    def fake_judge(requirement, artifact_json):
        score = state["judge"].pop(0) if len(state["judge"]) > 1 else state["judge"][0]
        return score, "judge says ok"

    monkeypatch.setattr(sop_graph, "retrieve_context", fake_retrieve)
    monkeypatch.setattr(sop_graph, "build_generation_chain", fake_build)
    monkeypatch.setattr(sop_graph, "judge_score", fake_judge)
    return SimpleNamespace(chain=chain, state=state)


def run(artifact_type="user_story"):
    return run_sop_generation(artifact_type, "proj_1", "reset password via OTP", get_schema(artifact_type))


def test_one_cycle_approval(harness):
    result = run()
    assert result["output"] == VALID_STORY
    assert result["eval_score"] == 0.9
    assert result["retry_count"] == 0
    assert result["prompt_version"] == "user_story_v1"
    assert result["retrieval"] == {"mode": "vector", "vector_hits": 2}
    assert result["usage"]["total_tokens"] == 30
    assert result["model_used"]  # records which alias produced the draft
    # §2.3.1 invariant 2: retrieval ran exactly once for the whole run.
    assert harness.state["retrievals"] == 1


def test_revisions_reuse_context_and_retrieve_once(harness):
    harness.state["judge"] = [0.5, 0.9]
    result = run()
    assert result["eval_score"] == 0.9
    assert result["retry_count"] == 1
    assert harness.state["retrievals"] == 1
    # Second draft receives the QA critique as repair_note with the same context.
    second_call = harness.chain.calls[1]
    assert second_call["context"] == "CTX"
    assert "judge says ok" in second_call["repair_note"]


def test_exhausted_retries_accepts_best_draft(harness):
    harness.state["judge"] = [0.5]
    result = run()
    assert result["eval_score"] == 0.5
    assert result["retry_count"] == sop_graph.MAX_RETRIES
    assert result["output"] == VALID_STORY  # best (only parseable) draft survives
    assert harness.state["retrievals"] == 1


def test_schema_violation_feeds_repair_note(harness, monkeypatch):
    bad = FakeChain("not json at all")
    good = FakeChain(json.dumps(VALID_STORY))
    chains = iter([bad, good])
    monkeypatch.setattr(sop_graph, "build_generation_chain",
                        lambda *a, **k: (next(chains), None, "user_story_v1"))

    def judge_always_pass(req, art):
        return 0.9, "fine"

    monkeypatch.setattr(sop_graph, "judge_score", judge_always_pass)
    result = run()
    assert result["retry_count"] == 1  # first draft failed format compliance
    assert good.calls[0]["repair_note"].startswith("QA review found issues")
    assert result["output"] == VALID_STORY


def test_provider_failure_switches_to_fallback_once(monkeypatch):
    """quality_check-style degradation preserved: provider error → FALLBACK_LLM draft."""
    failing = FakeChain(json.dumps(VALID_STORY), fail_times=1)
    built_aliases = []

    def fake_build(artifact_type, schema_cls, model_alias=None):
        built_aliases.append(model_alias)
        return (failing if len(built_aliases) == 1 else FakeChain(json.dumps(VALID_STORY))), None, "v1"

    monkeypatch.setattr(sop_graph, "retrieve_context",
                        lambda *a, **k: RetrievalResult("CTX", {}))
    monkeypatch.setattr(sop_graph, "build_generation_chain", fake_build)
    monkeypatch.setattr(sop_graph, "judge_score", lambda *a: (0.9, "ok"))

    result = run()
    assert len(failing.calls) == 1  # invoked once, then its provider error was caught
    assert built_aliases[0] != built_aliases[1]
    assert result["model_used"] == built_aliases[1]


def test_state_is_json_serializable_warning_W4():
    """W-4: LangGraph serializes state between nodes — no classes may appear in it."""
    from app.pipeline.sop_graph import _initial_state

    state = _initial_state("user_story", "p", "req", None)
    json.dumps(state)  # raises TypeError if a non-serializable value sneaks in
    assert "schema_cls" not in state


def test_unparseable_always_raises(harness, monkeypatch):
    monkeypatch.setattr(sop_graph, "build_generation_chain",
                        lambda *a, **k: (FakeChain("```garbage```"), None, "v1"))
    with pytest.raises(RuntimeError):
        run()
