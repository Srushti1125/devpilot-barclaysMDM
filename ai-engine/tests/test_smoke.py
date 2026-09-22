import pytest
from langchain_core.documents import Document
from pydantic import BaseModel

from app.ingestion.splitters import chunk_documents
from app.prompts.registry import list_artifact_types, load_prompt
from app.schemas.registry import SCHEMA_REGISTRY, get_schema


def test_all_artifact_types_have_a_prompt_and_a_schema():
    prompt_types = set(list_artifact_types())
    schema_types = set(SCHEMA_REGISTRY.keys())
    assert prompt_types == schema_types, (
        f"Mismatch between prompt templates {prompt_types} and "
        f"schema registry {schema_types} — every artifact type needs both."
    )


@pytest.mark.parametrize("artifact_type", list(SCHEMA_REGISTRY.keys()))
def test_prompt_loads_and_has_required_placeholders(artifact_type):
    prompt, version_id = load_prompt(artifact_type)
    assert version_id.startswith(artifact_type)
    rendered = prompt.format(
        requirement="dummy requirement",
        context="dummy context",
        repair_note="",
        format_instructions="dummy schema",
    )
    assert "dummy requirement" in rendered
    assert "dummy context" in rendered


def test_get_schema_unknown_type_raises():
    with pytest.raises(ValueError):
        get_schema("not_a_real_artifact_type")


def test_chunk_documents_preserves_metadata_and_adds_chunk_index():
    docs = [
        Document(
            page_content="Section one. " * 100,
            metadata={"project_id": "p1", "doc_type": "requirement", "source": "req.txt"},
        )
    ]
    chunks = chunk_documents(docs, chunk_size=100, chunk_overlap=10)
    assert len(chunks) > 1
    for i, c in enumerate(chunks):
        assert c.metadata["project_id"] == "p1"
        assert c.metadata["doc_type"] == "requirement"
        assert c.metadata["chunk_index"] == i


def test_quality_check_retries_then_succeeds():
    from app.pipeline.quality_check import generate_with_quality_check

    class Dummy(BaseModel):
        title: str

    class FakeParser:
        def parse(self, text):
            if "retry" not in text:
                raise ValueError("missing retry marker")
            return Dummy(title="ok")

    calls = {"n": 0}

    class FakeMsg:
        def __init__(self, content):
            self.content = content

    class FakeChain:
        def invoke(self, inputs):
            calls["n"] += 1
            if calls["n"] == 1:
                return FakeMsg("bad output, no marker")
            return FakeMsg("retry marker present")

    result, raw = generate_with_quality_check(FakeChain(), {"requirement": "x"}, FakeParser(), max_retries=2)
    assert result.title == "ok"
    assert calls["n"] == 2


def test_quality_check_uses_fallback_when_retries_exhausted():
    from app.pipeline.quality_check import generate_with_quality_check

    class Dummy(BaseModel):
        title: str

    class FakeParser:
        def parse(self, text):
            if text != "fallback-ok":
                raise ValueError("bad")
            return Dummy(title="from-fallback")

    class FakeMsg:
        def __init__(self, content):
            self.content = content

    class AlwaysFailsChain:
        def invoke(self, inputs):
            return FakeMsg("still bad")

    class FallbackChain:
        def invoke(self, inputs):
            return FakeMsg("fallback-ok")

    result, raw = generate_with_quality_check(
        AlwaysFailsChain(), {"requirement": "x"}, FakeParser(),
        max_retries=2, fallback_chain=FallbackChain(),
    )
    assert result.title == "from-fallback"
