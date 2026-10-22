"""
In-house document tree index (PageIndex-style pattern, no PageIndex dependency).

Input is an ordered list of Blocks produced by a structure-aware parser (Markdown/DOCX here;
Docling in a later step). Output is a list of TreeNode rows matching the `doc_tree_nodes`
table in IMPLEMENTATION.draft.md §2.3.3 (adjacency list via parent_id).

Design rules:
- node_id is deterministic (uuid5 over doc_id + path), so re-indexing the same content
  produces the same ids and vector metadata can reference them.
- Each node's `text` is only the body directly under its heading. `subtree_text()` returns
  the parent-level text used for context.
- Documents with no usable headings are split into pseudo-sections and flagged
  low_structure=True so the router can skip the tree leg for them.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

DEFAULT_PSEUDO_SECTION_CHARS = 3000
# Fixed namespace so node_ids are stable across processes and re-indexing runs.
_NAMESPACE = uuid.UUID("6f1c2a5e-0d7e-4c55-9d3a-000000000001")


@dataclass
class Block:
    text: str
    page: int | None = None
    heading_level: int | None = None  # None = body text; 1..6 = heading
    title: str | None = None


@dataclass
class TreeNode:
    node_id: str
    parent_id: str | None
    level: int
    title: str
    ordinal: str  # e.g. "0", "0.1", "0.1.2" - position in the tree
    page_start: int | None
    page_end: int | None
    text: str
    low_structure: bool = False
    children: list["TreeNode"] = field(default_factory=list, repr=False)


def _node_id(doc_id: str, ordinal: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{doc_id}:{ordinal}"))


def _min_max(values):
    vals = [v for v in values if v is not None]
    return (min(vals), max(vals)) if vals else (None, None)


def build_tree(doc_id: str, blocks: list[Block],
               pseudo_section_chars: int = DEFAULT_PSEUDO_SECTION_CHARS) -> list[TreeNode]:
    """Build the tree. Returns a flat list (document order); parent links are set via parent_id."""
    if not any(b.heading_level for b in blocks):
        return _pseudo_sections(doc_id, blocks, pseudo_section_chars)

    nodes: list[TreeNode] = []
    stack: list[TreeNode] = []  # open ancestors, strictly increasing level
    counters: dict[str, int] = {}  # ordinal prefix -> next child index
    body_parts: dict[str, list[str]] = {}
    body_pages: dict[str, list[int | None]] = {}

    def new_node(level: int, title: str, page: int | None, parent: TreeNode | None) -> TreeNode:
        prefix = parent.ordinal if parent else ""
        idx = counters.get(prefix, 0)
        counters[prefix] = idx + 1
        ordinal = f"{prefix}.{idx}" if prefix else str(idx)
        node = TreeNode(
            node_id=_node_id(doc_id, ordinal),
            parent_id=parent.node_id if parent else None,
            level=level, title=title.strip(), ordinal=ordinal,
            page_start=page, page_end=page, text="",
        )
        if parent:
            parent.children.append(node)
        nodes.append(node)
        body_parts[ordinal] = []
        body_pages[ordinal] = []
        return node

    # Text before the first heading becomes a root "(preamble)" node, created first so it
    # keeps ordinal "0" and document order. Content is never dropped.
    first_heading = next(i for i, b in enumerate(blocks) if b.heading_level)
    if first_heading > 0:
        preamble_blocks = blocks[:first_heading]
        preamble = new_node(0, "(preamble)", None, None)
        body_parts[preamble.ordinal] = [b.text for b in preamble_blocks]
        body_pages[preamble.ordinal] = [b.page for b in preamble_blocks]

    for block in blocks[first_heading:]:
        if block.heading_level:
            while stack and stack[-1].level >= block.heading_level:
                stack.pop()
            parent = stack[-1] if stack else None
            node = new_node(block.heading_level, block.title or block.text, block.page, parent)
            stack.append(node)
        else:
            body_parts[stack[-1].ordinal].append(block.text)
            body_pages[stack[-1].ordinal].append(block.page)

    # Finalise text and page ranges. Page range of a node covers its own body and all descendants.
    for node in nodes:
        node.text = "\n".join(t for t in body_parts[node.ordinal] if t).strip()
    for node in reversed(nodes):  # children are after parents in document order
        pages = body_pages[node.ordinal] + [node.page_start]
        for child in node.children:
            pages += [child.page_start, child.page_end]
        lo, hi = _min_max(pages)
        node.page_start, node.page_end = lo, hi
    return nodes


def _pseudo_sections(doc_id: str, blocks: list[Block], max_chars: int) -> list[TreeNode]:
    """Flat documents: group consecutive text into fixed-size sections, flagged low_structure."""
    groups: list[tuple[str, list[int | None]]] = []
    buf, pages, size = [], [], 0
    for b in blocks:
        if not b.text.strip():
            continue
        if size and size + len(b.text) > max_chars:
            groups.append(("\n".join(buf), pages))
            buf, pages, size = [], [], 0
        buf.append(b.text)
        pages.append(b.page)
        size += len(b.text)
    if buf:
        groups.append(("\n".join(buf), pages))

    nodes = []
    for i, (text, pg) in enumerate(groups):
        lo, hi = _min_max(pg)
        ordinal = str(i)
        nodes.append(TreeNode(
            node_id=_node_id(doc_id, ordinal), parent_id=None, level=1,
            title=f"Section {i + 1}", ordinal=ordinal,
            page_start=lo, page_end=hi, text=text, low_structure=True,
        ))
    return nodes


def subtree_text(node: TreeNode) -> str:
    """Node body plus all descendant bodies, in order. Used when a parent is returned as context."""
    parts = [node.text] if node.text else []
    for child in node.children:
        sub = subtree_text(child)
        if sub:
            parts.append(f"{child.title}\n{sub}")
    return "\n\n".join(parts)


# ---------- parsers that produce Blocks ----------

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def blocks_from_markdown(text: str) -> list[Block]:
    blocks: list[Block] = []
    for line in text.splitlines():
        m = _MD_HEADING.match(line)
        if m:
            blocks.append(Block(text=m.group(2), heading_level=len(m.group(1)), title=m.group(2)))
        elif line.strip():
            blocks.append(Block(text=line.strip()))
    return blocks


def blocks_from_docx(path: str) -> list[Block]:
    """Heading level from paragraph style 'Heading N'. DOCX has no page numbers here (page=None)."""
    from docx import Document as DocxDocument

    blocks: list[Block] = []
    for para in DocxDocument(path).paragraphs:
        txt = para.text.strip()
        if not txt:
            continue
        style = (para.style.name or "") if para.style is not None else ""
        m = re.match(r"Heading (\d)", style)
        if m:
            blocks.append(Block(text=txt, heading_level=int(m.group(1)), title=txt))
        else:
            blocks.append(Block(text=txt))
    return blocks
