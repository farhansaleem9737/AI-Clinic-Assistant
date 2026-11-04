"""email outbox

Revision ID: d5a9c3e72f14
Revises: c4f8a2d61b93
Create Date: 2026-11-04

Notification emails (D109). Additive only, safe on a live database:
- `email_outbox`: emails queued with their event and sent later by the
  outbox run, with status, attempts and retry time; a unique index on
  (user_id, dedupe_key) keeps one email per event and user;
- `notification_preferences.emails` (default true): also send the enabled
  categories by email.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5a9c3e72f14"
down_revision: Union[str, Sequence[str], None] = "c4f8a2d61b93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "notification_preferences", sa.Column("emails", sa.Boolean(), server_default=sa.text("true"), nullable=False)
    )
    op.create_table(
        "email_outbox",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("to_address", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=10), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'written', 'failed', 'expired')", name=op.f("ck_email_outbox_status")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_email_outbox_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_outbox")),
    )
    op.create_index(
        "ix_email_outbox_due", "email_outbox", ["next_attempt_at"], postgresql_where=sa.text("status IN ('pending', 'sending')")
    )
    op.create_index("uq_email_outbox_user_id_dedupe_key", "email_outbox", ["user_id", "dedupe_key"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_email_outbox_user_id_dedupe_key", table_name="email_outbox")
    op.drop_index("ix_email_outbox_due", table_name="email_outbox", postgresql_where=sa.text("status IN ('pending', 'sending')"))
    op.drop_table("email_outbox")
    op.drop_column("notification_preferences", "emails")
