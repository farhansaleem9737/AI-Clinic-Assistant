"""ai assistant

Revision ID: a3c8e1f4b207
Revises: f1b6d3a8c925
Create Date: 2026-10-29

Conversations, messages and uploaded documents for the floating AI
assistant (D96). Additive only: three new tables, nothing else changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a3c8e1f4b207'
down_revision: Union[str, Sequence[str], None] = 'f1b6d3a8c925'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ai_conversations",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_ai_conversations_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_conversations")),
    )
    op.create_index("ix_ai_conversations_user_id_updated_at", "ai_conversations", ["user_id", "updated_at"])

    op.create_table(
        "ai_messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("document_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("action", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f("ck_ai_messages_role")),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["ai_conversations.id"],
            name=op.f("fk_ai_messages_conversation_id_ai_conversations"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_messages")),
    )
    op.create_index("ix_ai_messages_conversation_id_created_at", "ai_messages", ["conversation_id", "created_at"])

    op.create_table(
        "ai_documents",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.CheckConstraint("status IN ('ready', 'no_text', 'failed')", name=op.f("ck_ai_documents_status")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_ai_documents_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["ai_conversations.id"],
            name=op.f("fk_ai_documents_conversation_id_ai_conversations"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_documents")),
        sa.UniqueConstraint("object_key", name=op.f("uq_ai_documents_object_key")),
    )
    op.create_index("ix_ai_documents_user_id_created_at", "ai_documents", ["user_id", "created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_ai_documents_user_id_created_at", table_name="ai_documents")
    op.drop_table("ai_documents")
    op.drop_index("ix_ai_messages_conversation_id_created_at", table_name="ai_messages")
    op.drop_table("ai_messages")
    op.drop_index("ix_ai_conversations_user_id_updated_at", table_name="ai_conversations")
    op.drop_table("ai_conversations")
