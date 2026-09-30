"""lowercase login emails

Revision ID: 1a6e1ee8ec97
Revises: d1cd98c3d9d1
Create Date: 2026-09-30

Login emails were compared exactly as typed, so ``John@Example.com`` and
``john@example.com`` could be registered as two accounts, and a user who typed
a different capitalisation at sign-in was rejected.

The API now lowercases login emails on the way in (``schemas.common.LoginEmail``).
This brings existing rows in line so those users can still sign in.

If two existing accounts differ only by letter case, the unique index on
``users.email`` makes this migration fail loudly rather than silently merging
or dropping an account; resolve the duplicate by hand and re-run.

Downgrade is a no-op: the original capitalisation is not recorded, and
lowercase addresses remain valid under the old behaviour.
"""
from typing import Sequence, Union

from alembic import op


revision: str = '1a6e1ee8ec97'
down_revision: Union[str, Sequence[str], None] = 'd1cd98c3d9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("UPDATE users SET email = lower(email) WHERE email <> lower(email)")


def downgrade() -> None:
    """Downgrade schema."""
