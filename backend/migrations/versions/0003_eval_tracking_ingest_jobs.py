"""Eval tracking columns + async ingest jobs table (IMPLEMENTATION.draft.md §6.1, §6.2).

Fresh databases created through 0001's create_all() already carry these shapes, so every
operation is guarded via the inspector (same idempotent pattern as 0002). Upgraded
databases get them added here.
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_eval_tracking_ingest_jobs"
down_revision = "0002_doc_tree_nodes"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade():
    existing = _columns("generation_history")
    if not existing:
        return  # table absent entirely: 0001 create_all() builds the current schema.

    # Batch mode: SQLite cannot ALTER ADD CONSTRAINT inline; PG emits plain DDL.
    with op.batch_alter_table("generation_history") as batch:
        if "requirement_id" not in existing:
            batch.add_column(sa.Column("requirement_id", sa.String(36),
                                       sa.ForeignKey("requirements.id", ondelete="SET NULL",
                                                   name="fk_gen_history_req"),
                                       nullable=True))
        if "eval_score" not in existing:
            batch.add_column(sa.Column("eval_score", sa.Float, nullable=True))
        if "retry_count" not in existing:
            batch.add_column(sa.Column("retry_count", sa.Integer, nullable=False,
                                       server_default="0"))
        if "model_used" not in existing:
            batch.add_column(sa.Column("model_used", sa.String(80), nullable=True))

    idx = _indexes("generation_history")
    if "ix_generation_history_requirement_id" not in idx:
        op.create_index("ix_generation_history_requirement_id", "generation_history",
                        ["requirement_id"])

    if not sa.inspect(op.get_bind()).has_table("ingest_jobs"):
        op.create_table(
            "ingest_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("requirement_id", sa.String(36),
                      sa.ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False),
            sa.Column("engine_job_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("status", sa.String(20), nullable=False, server_default="processing"),
            sa.Column("chunks_indexed", sa.Integer, nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
        )
        op.create_index("ix_ingest_jobs_requirement_id", "ingest_jobs", ["requirement_id"])


def downgrade():
    if sa.inspect(op.get_bind()).has_table("ingest_jobs"):
        op.drop_index("ix_ingest_jobs_requirement_id", table_name="ingest_jobs")
        op.drop_table("ingest_jobs")

    existing = _columns("generation_history")
    drops = [c for c in ("model_used", "retry_count", "eval_score", "requirement_id") if c in existing]
    if "ix_generation_history_requirement_id" in _indexes("generation_history"):
        op.drop_index("ix_generation_history_requirement_id", table_name="generation_history")
    if drops:
        with op.batch_alter_table("generation_history") as batch:
            for column in drops:
                batch.drop_column(column)
