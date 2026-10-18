"""
Seed the offline-eval corpus for the §2.3.6 ship run.

golden.jsonl questions reference eval_project_XX ids that have no indexed documents —
retrieval would return empty context under BOTH modes and the comparison would be
meaningless. This script ingests, for each eval project, one sectioned Markdown document
built from that project's golden questions, through the SAME code path as live ingestion
(one parse -> tree nodes + node-linked child chunks).

doc_tree_nodes FKs to projects/requirements, so the script seeds coherent rows for those
too (one synthetic owner user + a placeholder project + a requirements row per corpus doc).
Everything is dev/eval data on the local compose DB, marked with the eval-corpus:// source
prefix and INSERT ... ON CONFLICT DO NOTHING; embeddings are cleaned and re-indexed per
doc, so re-runs are idempotent.

Run from ai-engine/:
    PYTHONPATH=. python scripts/prepare_eval_corpus.py
"""
import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from app.config import settings
from app.evaluation.batch_harness import load_golden_rows
from app.ingestion.pipeline import chunks_from_nodes
from app.retrieval.tree_index import blocks_from_markdown, build_tree
from app.retrieval.vectorstore import index_chunks

NAMESPACE = uuid.UUID("6f1c2a5e-0d7e-4c55-9d3a-00000000dead")

ENSURE_USER = text("""
    INSERT INTO users (id, email, full_name, password_hash, role, is_active, created_at)
    VALUES (:id, :email, 'Eval Corpus Seeder', '!', 'member', true, :created_at)
    ON CONFLICT (id) DO NOTHING
""")
ENSURE_PROJECT = text("""
    INSERT INTO projects (id, name, description, owner_id, created_at)
    VALUES (:id, :name, 'offline eval corpus placeholder', :owner_id, :created_at)
    ON CONFLICT (id) DO NOTHING
""")
ENSURE_REQUIREMENT = text("""
    INSERT INTO requirements (id, project_id, uploaded_by, filename, file_path,
                              content, doc_type, chunks_indexed, created_at)
    VALUES (:id, :project_id, :uploaded_by, 'eval_corpus.md', :file_path,
            :content, 'requirement', 0, :created_at)
    ON CONFLICT (id) DO NOTHING
""")
DELETE_EVAL_EMBEDDINGS = text("""
    DELETE FROM langchain_pg_embedding
    WHERE cmetadata->>'source' = :source
""")
INSERT_NODE = text("""
    INSERT INTO doc_tree_nodes
      (id, project_id, doc_id, parent_id, ordinal, level, title,
       page_start, page_end, text, summary, low_structure, content_hash, created_at)
    VALUES
      (:id, :project_id, :doc_id, :parent_id, :ordinal, :level, :title,
       :page_start, :page_end, :text, NULL, :low_structure, :content_hash, :created_at)
    ON CONFLICT (id) DO NOTHING
""")


def eval_doc_id(project_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"eval-corpus:{project_id}"))


def corpus_markdown(project_id: str, rows: list[dict]) -> str:
    parts = [f"# {project_id} Requirements Corpus", ""]
    for i, row in enumerate(rows, start=1):
        parts.append(f"## Requirement {i}: {row['artifact_type'].replace('_', ' ')}")
        parts.append(row["question"])
        parts.append("")
    return "\n".join(parts)


def main() -> None:
    rows = load_golden_rows()
    by_project: dict[str, list[dict]] = {}
    for row in rows:
        by_project.setdefault(row["project_id"], []).append(row)

    engine = create_engine(settings.DATABASE_URL)
    now = datetime.now(timezone.utc)
    owner_id = str(uuid.uuid5(NAMESPACE, "eval-corpus-user"))

    with engine.begin() as conn:
        conn.execute(ENSURE_USER, dict(id=owner_id, email=f"eval-corpus-{owner_id[:8]}@example.com",
                                      created_at=now))

    for project_id, project_rows in sorted(by_project.items()):
        doc_id = eval_doc_id(project_id)
        md = corpus_markdown(project_id, project_rows)
        source = f"eval-corpus://{project_id}"

        blocks = blocks_from_markdown(md)
        nodes = build_tree(doc_id, blocks)
        chunks = chunks_from_nodes(nodes, project_id=project_id, doc_id=doc_id,
                                   doc_type="requirement", source=source)

        with engine.begin() as conn:  # FK parents first
            conn.execute(ENSURE_PROJECT, dict(id=project_id, name=f"Eval {project_id}",
                                              owner_id=owner_id, created_at=now))
            conn.execute(ENSURE_REQUIREMENT, dict(id=doc_id, project_id=project_id,
                                                  uploaded_by=owner_id, file_path=source,
                                                  content=md, created_at=now))
            conn.execute(DELETE_EVAL_EMBEDDINGS, dict(source=source))  # idempotent re-run

        n_chunks = index_chunks(chunks)

        content_hash = hashlib.sha256(md.encode()).hexdigest()
        params = [dict(id=node.node_id, project_id=project_id, doc_id=doc_id,
                       parent_id=node.parent_id, ordinal=node.ordinal, level=node.level,
                       title=node.title[:512], page_start=node.page_start, page_end=node.page_end,
                       text=node.text, low_structure=node.low_structure,
                       content_hash=content_hash, created_at=now)
                  for node in nodes]  # parents precede children: self-FK inserts cleanly
        with engine.begin() as conn:
            conn.execute(INSERT_NODE, params)
        print(f"seeded {project_id}: {len(nodes)} nodes, {n_chunks} chunks", flush=True)

    print("corpus ready")


if __name__ == "__main__":
    main()
