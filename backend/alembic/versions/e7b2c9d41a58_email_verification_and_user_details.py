"""email verification codes and user personal details

Revision ID: e7b2c9d41a58
Revises: d5a9c3e72f14
Create Date: 2026-11-05

Additive only, safe on a live database:
- `email_verification_codes`: one live, hashed, expiring code per address,
  required by self-registration;
- `users.date_of_birth`, `users.gender` (nullable): personal details of doctors
  and staff. Existing accounts keep NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7b2c9d41a58"
down_revision: Union[str, Sequence[str], None] = "d5a9c3e72f14"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "email_verification_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_verification_codes")),
        sa.UniqueConstraint("email", name=op.f("uq_email_verification_codes_email")),
    )
    op.add_column("users", sa.Column("date_of_birth", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("gender", sa.String(length=10), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "gender")
    op.drop_column("users", "date_of_birth")
    op.drop_table("email_verification_codes")
