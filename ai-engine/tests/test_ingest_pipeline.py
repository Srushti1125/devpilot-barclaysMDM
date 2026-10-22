"""One parse feeds both indexes: every chunk maps to exactly one tree node."""
from app.ingestion.pipeline import node_to_dict, prepare_document


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_every_chunk_maps_to_a_tree_node(tmp_path):
    md = "Front matter.\n\n# 1 Auth\n## 1.1 Reset\n" + ("Customers reset via OTP. " * 60) + "\n# 2 Pay\nLimits apply.\n"
    prep = prepare_document(_write(tmp_path, "r.md", md), "p1", "requirement", doc_id="doc-x")
    node_ids = {n.node_id for n in prep.tree_nodes}
    assert prep.chunks, "expected chunks"
    for c in prep.chunks:
        assert c.metadata["node_id"] in node_ids
        assert c.metadata["doc_id"] == "doc-x"
        assert c.metadata["project_id"] == "p1"
    long_section = [c for c in prep.chunks if c.metadata["title"] == "1.1 Reset"]
    assert len(long_section) >= 2, "a long section must be split into several child chunks"


def test_chunks_carry_heading_context_and_page_range(tmp_path):
    prep = prepare_document(_write(tmp_path, "r.md", "# 1 Auth\n## 1.1 Reset\nOTP within 10 minutes.\n"),
                            "p1", doc_id="d")
    reset = [c for c in prep.chunks if c.metadata["title"] == "1.1 Reset"]
    assert reset and reset[0].page_content.startswith("1.1 Reset\n")
    assert "OTP within 10 minutes." in reset[0].page_content


def test_preamble_is_indexed_without_heading_prefix(tmp_path):
    prep = prepare_document(_write(tmp_path, "r.md", "Intro text here.\n# Real\nbody\n"), "p1", doc_id="d")
    pre = [c for c in prep.chunks if c.metadata["title"] == "(preamble)"]
    assert pre and pre[0].page_content == "Intro text here."


def test_flat_text_becomes_low_structure_nodes(tmp_path):
    text = "\n\n".join(f"Requirement number {i} says the system shall do thing {i}." for i in range(200))
    prep = prepare_document(_write(tmp_path, "flat.txt", text), "p1", doc_id="d")
    assert prep.tree_nodes and all(n.low_structure for n in prep.tree_nodes)
    assert all("Section" not in c.page_content.split("\n")[0] for c in prep.chunks)


def test_node_to_dict_is_json_ready(tmp_path):
    import json
    prep = prepare_document(_write(tmp_path, "r.md", "# A\nbody\n"), "p1", doc_id="d")
    json.dumps([node_to_dict(n) for n in prep.tree_nodes])  # must not raise


def test_empty_document_is_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        prepare_document(_write(tmp_path, "empty.txt", "   \n\n  "), "p1", doc_id="d")
