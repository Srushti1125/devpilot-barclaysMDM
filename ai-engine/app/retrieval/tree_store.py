"""
Read-only access to doc_tree_nodes (IMPLEMENTATION.draft.md §2.3.3).

The backend owns the table (Alembic) and writes rows at upload time. The ai-engine only reads:
the outline for tree search and node text for parent resolution. Every query is scoped by
project_id (tenant isolation, §2.3.5).

Table definitions here are read-side mirrors used for Core queries. They are not migrations.
"""
from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, Text, create_engine, select
from sqlalchemy.engine import Engine

_md = MetaData()

requirements_t = Table(
    "requirements", _md,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(36)),
    Column("doc_type", String(50)),
)

doc_tree_nodes_t = Table(
    "doc_tree_nodes", _md,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(36)),
    Column("doc_id", String(36)),
    Column("parent_id", String(36), nullable=True),
    Column("ordinal", String(64)),
    Column("level", Integer),
    Column("title", String(512)),
    Column("page_start", Integer, nullable=True),
    Column("page_end", Integer, nullable=True),
    Column("text", Text),
    Column("low_structure", Boolean),
    Column("content_hash", String(64)),
)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    from app.config import settings
    return create_engine(settings.DATABASE_URL, pool_pre_ping=True)


def load_outline(project_id: str, doc_type: str, engine: Engine | None = None) -> list[dict]:
    """
    Structured nodes for a project's documents of one doc_type. Documents flagged low_structure
    (flat pseudo-sections) are excluded entirely: the tree leg is skipped for them (§2.3.5).
    Text is not loaded here; the outline is what the selector LLM sees.
    """
    eng = engine or get_engine()
    n, r = doc_tree_nodes_t.c, requirements_t.c
    stmt = (
        select(n.id, n.doc_id, n.parent_id, n.ordinal, n.level, n.title,
               n.page_start, n.page_end, n.low_structure, n.content_hash)
        .select_from(doc_tree_nodes_t.join(requirements_t, n.doc_id == r.id))
        .where(n.project_id == project_id, r.project_id == project_id, r.doc_type == doc_type)
        .order_by(n.doc_id, n.ordinal)
    )
    with eng.connect() as conn:
        rows = [dict(row._mapping) for row in conn.execute(stmt)]

    flat_docs = {row["doc_id"] for row in rows if row["low_structure"]}
    return [row for row in rows if row["doc_id"] not in flat_docs]


def load_node_texts(project_id: str, node_ids: list[str], engine: Engine | None = None) -> dict[str, dict]:
    """
    Parent resolution (IMPLEMENTATION.draft.md §2.3.4): each requested node's text is its own body
    followed by all descendant bodies, in document order. A selected section whose body is empty
    (text lives in its subsections) therefore still yields its content.
    Ids outside the project are absent from the result.
    """
    if not node_ids:
        return {}
    eng = engine or get_engine()
    n = doc_tree_nodes_t.c
    with eng.connect() as conn:
        requested = conn.execute(
            select(n.id, n.doc_id).where(n.project_id == project_id, n.id.in_(node_ids))).all()
        if not requested:
            return {}
        doc_ids = {row.doc_id for row in requested}
        # All nodes of the involved documents, so descendants can be walked in memory.
        doc_nodes = [dict(row._mapping) for row in conn.execute(
            select(n.id, n.parent_id, n.title, n.text, n.page_start, n.page_end, n.ordinal)
            .where(n.project_id == project_id, n.doc_id.in_(doc_ids))
            .order_by(n.doc_id, n.ordinal))]

    children: dict[str, list[dict]] = {}
    for row in doc_nodes:
        if row["parent_id"]:
            children.setdefault(row["parent_id"], []).append(row)
    by_id = {row["id"]: row for row in doc_nodes}

    def subtree(node_id: str) -> str:
        parts = []
        node = by_id[node_id]
        if node["text"]:
            parts.append(node["text"])
        for child in children.get(node_id, []):
            body = subtree(child["id"])
            if body:
                parts.append(f"{child['title']}\n{body}")
        return "\n\n".join(parts)

    out = {}
    for row in requested:
        node = by_id[row.id]
        out[row.id] = {"title": node["title"], "text": subtree(row.id),
                       "page_start": node["page_start"], "page_end": node["page_end"]}
    return out
