"""
Docling end-to-end on a real multi-page PDF fixture. Skipped when docling is not installed.
First run downloads Docling layout models (~3 min); later runs take ~10 s.
"""
from pathlib import Path

import pytest

pytest.importorskip("docling")

from app.ingestion.docling_parser import parse_to_blocks  # noqa: E402
from app.retrieval.tree_index import build_tree  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "requirements_multi.pdf"


@pytest.fixture(scope="module")
def tree():
    return {n.title: n for n in build_tree("doc-fixture", parse_to_blocks(str(FIXTURE)))}


def test_headings_form_numbered_hierarchy(tree):
    assert tree["1.1 Password Reset"].parent_id == tree["1 Authentication"].node_id
    assert tree["2.2 Fraud Checks"].parent_id == tree["2 Payments"].node_id
    assert tree["2 Payments"].parent_id is None


def test_section_page_ranges_match_pdf_layout(tree):
    # Fixture layout: section 1 on pages 1-2, section 2 on pages 3-4, section 3 on page 5.
    assert tree["3 Audit and Logging"].page_start == 5
    assert tree["2 Payments"].page_start == 3
    assert tree["1 Authentication"].page_start == 1


def test_body_text_is_attached_to_its_section(tree):
    assert "one-time code" in tree["1.1 Password Reset"].text
    assert "5000 GBP" in tree["2.1 Transfer Limits"].text
    assert "7 years" in tree["3.1 Audit Trail"].text


def test_pdf_through_ingestion_pipeline_keeps_pages_and_links(tmp_path):
    """Real PDF -> prepare_document: Docling blocks (with pages) drive the tree; chunks link to it."""
    from app.ingestion.pipeline import prepare_document

    prep = prepare_document(str(FIXTURE), "p-pdf", "requirement", doc_id="doc-pdf")
    by_title = {n.title: n for n in prep.tree_nodes}
    assert by_title["1.1 Password Reset"].parent_id == by_title["1 Authentication"].node_id
    assert by_title["3 Audit and Logging"].page_start == 5
    node_ids = {n.node_id for n in prep.tree_nodes}
    assert prep.chunks and all(c.metadata["node_id"] in node_ids for c in prep.chunks)
    audit = [c for c in prep.chunks if c.metadata["title"] == "3.1 Audit Trail"]
    assert audit and audit[0].metadata["page_start"] == 5
    assert "_blocks" not in audit[0].metadata
