"""Add doc_tree_nodes (document tree index, IMPLEMENTATION.draft.md §2.3.3).

0001 calls Base.metadata.create_all(), which already creates every table in the current
metadata. On a fresh database that includes doc_tree_nodes, so this migration checks for
the table first to stay idempotent.
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_doc_tree_nodes"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

TABLE = "doc_tree_nodes"


def _has_table() -> bool:
    return sa.inspect(op.get_bind()).has_table(TABLE)


def upgrade():
    if _has_table():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("doc_id", sa.String(36), sa.ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.String(36), sa.ForeignKey(f"{TABLE}.id", ondelete="CASCADE"), nullable=True),
        sa.Column("ordinal", sa.String(64), nullable=False),
        sa.Column("level", sa.Integer, nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("page_start", sa.Integer, nullable=True),
        sa.Column("page_end", sa.Integer, nullable=True),
        sa.Column("text", sa.Text, nullable=False, server_default=""),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("low_structure", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_doc_tree_nodes_project_id", TABLE, ["project_id"])
    op.create_index("ix_doc_tree_nodes_doc_id", TABLE, ["doc_id"])
    op.create_index("ix_doc_tree_nodes_parent_id", TABLE, ["parent_id"])


def downgrade():
    if _has_table():
        op.drop_table(TABLE)
