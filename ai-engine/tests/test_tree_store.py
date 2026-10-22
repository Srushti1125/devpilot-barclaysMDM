"""doc_tree_nodes reads: project isolation, low_structure exclusion, doc_type filter."""
from sqlalchemy import create_engine, insert
from sqlalchemy.pool import StaticPool

from app.retrieval import tree_store as store


def _engine():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    store._md.create_all(eng)
    with eng.begin() as c:
        c.execute(insert(store.requirements_t), [
            {"id": "r1", "project_id": "p1", "doc_type": "requirement"},
            {"id": "r2", "project_id": "p2", "doc_type": "requirement"},
            {"id": "r3", "project_id": "p1", "doc_type": "policy"},
            {"id": "r4", "project_id": "p1", "doc_type": "requirement"},
        ])
        base = dict(low_structure=False, content_hash="h", text="body", page_start=1, page_end=1)
        c.execute(insert(store.doc_tree_nodes_t), [
            dict(base, id="n1", project_id="p1", doc_id="r1", parent_id=None, ordinal="0", level=1, title="A"),
            dict(base, id="n2", project_id="p2", doc_id="r2", parent_id=None, ordinal="0", level=1, title="A"),
            dict(base, id="n3", project_id="p1", doc_id="r3", parent_id=None, ordinal="0", level=1, title="Policy"),
            dict(base, id="n4", project_id="p1", doc_id="r4", parent_id=None, ordinal="0", level=1,
                 title="Flat", low_structure=True),
        ])
    return eng


def test_outline_is_scoped_to_project_and_doc_type():
    rows = store.load_outline("p1", "requirement", engine=_engine())
    assert [r["id"] for r in rows] == ["n1"]


def test_low_structure_documents_are_excluded_from_tree_leg():
    rows = store.load_outline("p1", "requirement", engine=_engine())
    assert "n4" not in [r["id"] for r in rows]


def test_foreign_node_ids_are_not_loaded():
    texts = store.load_node_texts("p1", ["n1", "n2"], engine=_engine())
    assert set(texts) == {"n1"}


def test_selected_parent_with_empty_body_resolves_to_subtree_text():
    eng = _engine()
    with eng.begin() as c:
        base = dict(low_structure=False, content_hash="h", page_start=1, page_end=2)
        c.execute(insert(store.doc_tree_nodes_t), [
            dict(base, id="p-root", project_id="p1", doc_id="r1", parent_id=None, ordinal="1", level=1,
                 title="2 Payments", text=""),
            dict(base, id="p-child", project_id="p1", doc_id="r1", parent_id="p-root", ordinal="1.0",
                 level=2, title="2.1 Limits", text="5000 GBP per day."),
        ])
    out = store.load_node_texts("p1", ["p-root"], engine=eng)
    assert "5000 GBP per day." in out["p-root"]["text"]
    assert out["p-root"]["title"] == "2 Payments"
