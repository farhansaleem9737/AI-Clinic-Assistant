"""Forgot password by emailed 6-digit code instead of a link (D127)

Revision ID: c8e1f2a9d374
Revises: b4d9e2a7c615
Create Date: 2026-11-11

Additive and safe on a live database. password_reset_tokens gets:
- code_hash: HMAC-SHA256 of the emailed code (never the code itself);
- attempts: wrong guesses at that code;
- verified_at: when the right code was entered.
token_hash becomes nullable: a challenge has no reset token until its code is
verified. Existing rows keep their values.

Rollback: `alembic downgrade b4d9e2a7c615`. Rows without a token_hash (code
challenges) are deleted first, then the columns go. Outstanding codes stop
working; nothing else is lost.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8e1f2a9d374"
down_revision: Union[str, Sequence[str], None] = "b4d9e2a7c615"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("password_reset_tokens", sa.Column("code_hash", sa.CHAR(length=64), nullable=True))
    op.add_column(
        "password_reset_tokens", sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False)
    )
    op.add_column("password_reset_tokens", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("password_reset_tokens", "token_hash", existing_type=sa.CHAR(length=64), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM password_reset_tokens WHERE token_hash IS NULL")
    op.alter_column("password_reset_tokens", "token_hash", existing_type=sa.CHAR(length=64), nullable=False)
    op.drop_column("password_reset_tokens", "verified_at")
    op.drop_column("password_reset_tokens", "attempts")
    op.drop_column("password_reset_tokens", "code_hash")
