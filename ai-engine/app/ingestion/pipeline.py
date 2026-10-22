"""
Ingestion pipeline (IMPLEMENTATION.draft.md §2.3.1 invariant 1, §2.3.4 parent-child).

One parse produces both indexes:
  - tree nodes (returned to the backend, which persists them to doc_tree_nodes)
  - child chunks in PGVector, one or more per tree node, each carrying node_id

Because every chunk is derived from exactly one node, "every vector hit maps to exactly one
tree node" holds by construction.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.ingestion.loaders import load_requirement_doc
from app.ingestion.splitters import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    _looks_like_markdown,
)
from app.retrieval.tree_index import Block, TreeNode, blocks_from_markdown, build_tree

PREAMBLE_TITLE = "(preamble)"


@dataclass
class PreparedDocument:
    doc_id: str
    content_hash: str
    tree_nodes: list[TreeNode]
    chunks: list[Document]


def _blocks_from_docs(docs: list[Document]) -> list[Block]:
    """Prefer structured blocks from the parser; otherwise infer structure from text."""
    for d in docs:
        blocks = d.metadata.pop("_blocks", None)
        if blocks:
            return blocks
    text = "\n\n".join(d.page_content for d in docs)
    if _looks_like_markdown(text):
        return blocks_from_markdown(text)
    return [Block(text=p.strip()) for p in text.split("\n\n") if p.strip()]


def chunks_from_nodes(
    nodes: list[TreeNode],
    *,
    project_id: str,
    doc_id: str,
    doc_type: str,
    source: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    out: list[Document] = []
    for node in nodes:
        body = node.text.strip()
        if not body:
            continue
        # Prefix the heading so the embedding carries section context. Skipped for the preamble
        # and for pseudo-sections, whose generated titles carry no meaning.
        prefix = "" if (node.title == PREAMBLE_TITLE or node.low_structure) else f"{node.title}\n"
        for piece in splitter.split_text(body):
            metadata = {
                "project_id": project_id,
                "doc_id": doc_id,
                "doc_type": doc_type,
                "source": source,
                "node_id": node.node_id,
                "title": node.title,
                "chunk_index": len(out),
            }
            if node.page_start is not None:
                metadata["page_start"] = node.page_start
            if node.page_end is not None:
                metadata["page_end"] = node.page_end
            out.append(Document(page_content=f"{prefix}{piece}", metadata=metadata))
    return out


def prepare_document(
    file_path: str,
    project_id: str,
    doc_type: str = "requirement",
    doc_id: str | None = None,
) -> PreparedDocument:
    doc_id = doc_id or str(uuid.uuid4())
    docs = load_requirement_doc(file_path, project_id, doc_type)
    blocks = _blocks_from_docs(docs)
    if not any(b.text.strip() for b in blocks):
        raise ValueError("Extraction produced no text")

    nodes = build_tree(doc_id, blocks)  # parents precede children in this list
    chunks = chunks_from_nodes(
        nodes, project_id=project_id, doc_id=doc_id, doc_type=doc_type, source=file_path,
    )
    content_hash = hashlib.sha256("\n".join(b.text for b in blocks).encode("utf-8")).hexdigest()
    return PreparedDocument(doc_id=doc_id, content_hash=content_hash,
                            tree_nodes=nodes, chunks=chunks)


def node_to_dict(node: TreeNode) -> dict:
    return {
        "node_id": node.node_id,
        "parent_id": node.parent_id,
        "ordinal": node.ordinal,
        "level": node.level,
        "title": node.title,
        "page_start": node.page_start,
        "page_end": node.page_end,
        "text": node.text,
        "low_structure": node.low_structure,
    }
