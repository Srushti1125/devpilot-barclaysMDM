"""
Retrieval must run exactly once per generation request, even when the primary
provider fails and the fallback chain takes over.
"""
import pytest
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

from app.llm.parsers import get_parser
from app.pipeline import chain as chain_mod
from app.retrieval.hybrid import RetrievalResult


class _Item(BaseModel):
    title: str


def test_retrieval_runs_once_and_fallback_receives_same_context(monkeypatch):
    calls = {"retrieve": 0, "seen_contexts": []}

    def fake_retrieve(project_id, requirement_text, doc_type="requirement"):
        calls["retrieve"] += 1
        return RetrievalResult(context="CTX-1", trace={"mode": "vector"})

    def fake_build(artifact_type, schema_cls, model_alias=None):
        def primary(x):
            calls["seen_contexts"].append(("primary", x["context"]))
            raise ConnectionError("groq 429")

        def fallback(x):
            calls["seen_contexts"].append(("fallback", x["context"]))
            return '{"title": "ok"}'

        fn = fallback if model_alias else primary
        return RunnableLambda(fn), get_parser(_Item), "v-test"

    monkeypatch.setattr(chain_mod, "retrieve_context", fake_retrieve)
    monkeypatch.setattr(chain_mod, "build_generation_chain", fake_build)
    monkeypatch.setattr(chain_mod.settings, "FALLBACK_LLM", "gemini-2.5-flash")
    monkeypatch.setattr(chain_mod.settings, "DEFAULT_LLM", "groq-openai/gpt-oss-120b")

    out = chain_mod.run_generation("user_story", "proj-1", "req text", _Item)

    assert out["output"] == {"title": "ok"}
    assert calls["retrieve"] == 1
    assert calls["seen_contexts"] == [("primary", "CTX-1"), ("fallback", "CTX-1")]


def test_chain_without_precomputed_context_fails_loudly(monkeypatch):
    """The chain must not silently retrieve; a missing context is a programming error."""
    monkeypatch.setattr(chain_mod, "get_llm", lambda alias=None: RunnableLambda(lambda x: "x"))
    built, _, _ = chain_mod.build_generation_chain("user_story", _Item)
    with pytest.raises(KeyError, match="precomputed 'context'"):
        built.invoke({"requirement": "r"})
