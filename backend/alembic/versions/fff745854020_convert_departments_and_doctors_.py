"""convert departments and doctors timestamps to timestamptz

Revision ID: fff745854020
Revises: ca3b9a4cdbf9
Create Date: 2026-09-15

ca3b9a4cdbf9 created ``departments`` and ``doctors`` with naive TIMESTAMP
columns, because the models declared ``DateTime`` rather than
``DateTime(timezone=True)``. That is the same inconsistency fadd14706b01 fixed
for ``users`` and ``refresh_tokens``, and it would have produced the identical
failure as soon as any code compared these values against an aware datetime.

This revision brings the three remaining columns in line with the project
policy: aware UTC in Python, TIMESTAMPTZ in PostgreSQL.

Both tables were empty when this was written, so no existing values had to be
reinterpreted. ``AT TIME ZONE 'UTC'`` is used anyway: it is the correct reading
for any row an environment may already hold, since the only writer was a model
default of ``datetime.utcnow()`` -- a naive value that means UTC.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fff745854020'
down_revision: Union[str, Sequence[str], None] = 'ca3b9a4cdbf9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column) -- all non-nullable, all naive values meaning UTC.
_COLUMNS = (
    ("departments", "created_at"),
    ("doctors", "created_at"),
    ("doctors", "updated_at"),
)


def upgrade() -> None:
    """Upgrade schema."""
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=False,
            # Read the naive value as UTC -- preserves the instant.
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table, column in reversed(_COLUMNS):
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            existing_nullable=False,
            # Back to a naive value that means UTC.
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )
