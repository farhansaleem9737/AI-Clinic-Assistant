"""ai usage and results

Revision ID: b7d2e9f4a613
Revises: a3c8e1f4b207
Create Date: 2026-10-29

Gemini assistant (D100). Additive only: a new `ai_usage` table (one row per
message that reached the AI provider: tokens and counts, never content) and
a nullable `results` column on `ai_messages` for result cards.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b7d2e9f4a613'
down_revision: Union[str, Sequence[str], None] = 'a3c8e1f4b207'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("ai_messages", sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.create_table(
        "ai_usage",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("model_requests", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.CheckConstraint("status IN ('ok', 'failed')", name=op.f("ck_ai_usage_status")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_ai_usage_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_usage")),
    )
    op.create_index("ix_ai_usage_user_id_created_at", "ai_usage", ["user_id", "created_at"])
    op.create_index("ix_ai_usage_created_at", "ai_usage", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_ai_usage_created_at", table_name="ai_usage")
    op.drop_index("ix_ai_usage_user_id_created_at", table_name="ai_usage")
    op.drop_table("ai_usage")
    op.drop_column("ai_messages", "results")
