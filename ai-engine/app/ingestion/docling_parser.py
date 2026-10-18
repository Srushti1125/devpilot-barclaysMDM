"""
Structure-aware PDF/DOCX parsing with Docling (IMPLEMENTATION.draft.md §2.2.1).

Produces the same Block list that tree_index.build_tree() consumes, so the tree and the
vector chunks are derived from one parse. Tables are emitted as Markdown text blocks so
row/column meaning survives into the retrieved context.

Imports are lazy: the rest of the ai-engine must import and run when docling is absent
(the loader falls back to unstructured).
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

from app.retrieval.tree_index import Block

logger = logging.getLogger("devpilot.docling")

SUPPORTED_DOCLING_EXTENSIONS = {"pdf", "docx"}


@lru_cache(maxsize=1)
def _converter():
    """One converter per process: model load is expensive (see §11 W-1)."""
    from docling.document_converter import DocumentConverter
    return DocumentConverter()


def _page_of(item) -> int | None:
    prov = getattr(item, "prov", None) or []
    return prov[0].page_no if prov else None


def blocks_from_docling_document(document) -> list[Block]:
    """Map a DoclingDocument to Blocks. Pure function of the document, unit-testable."""
    from docling_core.types.doc import SectionHeaderItem, TableItem

    blocks: list[Block] = []
    for item, _level in document.iterate_items():
        page = _page_of(item)
        if _label(item) == "title":  # document title; older docling-core has no TitleItem class
            text = (getattr(item, "text", "") or "").strip()
            if text:
                blocks.append(Block(text=text, page=page, heading_level=1, title=text))
        elif isinstance(item, SectionHeaderItem):
            text = (item.text or "").strip()
            if text:
                level = _header_level(text, getattr(item, "level", None))
                blocks.append(Block(text=text, page=page, heading_level=level, title=text))
        elif isinstance(item, TableItem):
            md = _table_markdown(item, document)
            if md:
                blocks.append(Block(text=md, page=page))
        else:
            text = (getattr(item, "text", "") or "").strip()
            if text:
                blocks.append(Block(text=text, page=page))
    return blocks


_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+\S")


def _header_level(text: str, docling_level) -> int:
    """
    Requirement documents number their headings ("1", "1.1", "1.1.2"). Docling's own level is
    unreliable for these (observed: every header reported level 1), so the numbering depth wins.
    Unnumbered headers use Docling's level. Result is clamped to the tree's 1..6 range.
    """
    m = _NUMBERED.match(text)
    if m:
        return min(m.group(1).count(".") + 1, 6)
    return min(max(int(docling_level or 1), 1), 6)


def _label(item) -> str:
    label = getattr(item, "label", None)
    return str(getattr(label, "value", label) or "")


def _table_markdown(item, document) -> str:
    try:
        return item.export_to_markdown(document).strip()
    except TypeError:  # older docling-core signature without the document argument
        return item.export_to_markdown().strip()


def parse_to_blocks(file_path: str) -> list[Block]:
    """Parse a PDF or DOCX file with Docling and return structure-aware Blocks."""
    ext = file_path.lower().rsplit(".", 1)[-1]
    if ext not in SUPPORTED_DOCLING_EXTENSIONS:
        raise ValueError(f"Docling parser does not handle '.{ext}'")
    result = _converter().convert(file_path)
    blocks = blocks_from_docling_document(result.document)
    if not blocks:
        raise ValueError("Docling produced no structured content")
    return blocks


def blocks_to_markdown(blocks: list[Block]) -> str:
    """Render Blocks as Markdown so the existing MarkdownHeaderTextSplitter keeps section context."""
    out: list[str] = []
    for b in blocks:
        if b.heading_level:
            out.append(f"{'#' * b.heading_level} {b.title or b.text}")
        else:
            out.append(b.text)
        out.append("")
    return "\n".join(out).strip() + "\n"
