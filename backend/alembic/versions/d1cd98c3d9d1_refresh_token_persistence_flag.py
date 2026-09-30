"""refresh token persistence flag

Revision ID: d1cd98c3d9d1
Revises: 88584f93ce0c
Create Date: 2026-09-30

Adds ``refresh_tokens.persistent`` for the login page's "Remember me" option.

Until now every session was long-lived. With the flag, a login without
"Remember me" gets a browser-session cookie and a short server-side lifetime,
and the flag is inherited each time the token rotates.

Existing rows were all issued as long-lived sessions, so they are marked
persistent: nobody already signed in is affected.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1cd98c3d9d1'
down_revision: Union[str, Sequence[str], None] = '88584f93ce0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("refresh_tokens", sa.Column("persistent", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.alter_column("refresh_tokens", "persistent", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("refresh_tokens", "persistent")
