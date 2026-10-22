"""Persist project assistant conversation messages."""
import sqlalchemy as sa
from alembic import op

revision = "0004_chat_msgs"
down_revision = "0003_eval_tracking_ingest_jobs"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("chat_messages"):
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(10), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("chat_messages")}
    if "ix_chat_messages_project_id" not in indexes:
        op.create_index("ix_chat_messages_project_id", "chat_messages", ["project_id"])
    if "ix_chat_messages_user_id" not in indexes:
        op.create_index("ix_chat_messages_user_id", "chat_messages", ["user_id"])
    if "ix_chat_messages_created_at" not in indexes:
        op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])


def downgrade():
    if sa.inspect(op.get_bind()).has_table("chat_messages"):
        op.drop_table("chat_messages")
