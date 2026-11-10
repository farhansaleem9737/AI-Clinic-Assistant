"""Forgot password: one-time reset links, password change time (D126)

Revision ID: b4d9e2a7c615
Revises: f1c6a2d8e573
Create Date: 2026-11-10

Additive and safe on a live database:
- new table password_reset_tokens (only SHA-256 hashes of the links);
- new nullable column users.password_changed_at. Existing rows get NULL, which
  means "no change recorded": every current session keeps working.

Rollback: `alembic downgrade f1c6a2d8e573` drops both. Outstanding reset links
stop working; nothing else is lost.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4d9e2a7c615"
down_revision: Union[str, Sequence[str], None] = "f1c6a2d8e573"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_ip", postgresql.INET(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_password_reset_tokens_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_reset_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_password_reset_tokens_token_hash")),
    )
    op.create_index(op.f("ix_password_reset_tokens_user_id"), "password_reset_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_password_reset_tokens_user_id"), table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_column("users", "password_changed_at")
