"""convert timestamp columns to timestamptz

Converts every persistent timestamp from TIMESTAMP WITHOUT TIME ZONE to
TIMESTAMP WITH TIME ZONE, to match the project policy of storing timezone-aware
UTC instants (SQLAlchemy ``DateTime(timezone=True)``).

Interpreting the existing naive values
--------------------------------------
A bare ``ALTER COLUMN ... TYPE timestamptz`` interprets existing naive values in
the *session* TimeZone. That is correct for one of these columns and wrong for
the other three, so each conversion states its intent explicitly.

* ``users.created_at``, ``refresh_tokens.created_at``, ``refresh_tokens.expires_at``
  were written by application code using ``datetime.utcnow()`` — naive values
  that already mean UTC. They convert with ``AT TIME ZONE 'UTC'``, which reads
  the naive value as UTC and preserves the instant exactly.

* ``users.updated_at`` is different. Revision 231b352f348f added it with
  ``server_default=sa.func.now()``. ``now()`` returns timestamptz, and storing it
  into a ``timestamp`` column cast it through the session TimeZone — so those
  backfilled values are naive *session-local* time, not UTC. They convert with a
  plain ``::timestamptz``, which reinterprets them in the session TimeZone and is
  the exact inverse of the cast that produced them. Reading these as UTC instead
  would shift every backfilled row by the server's UTC offset.

Both directions are lossless for the instant being represented.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fadd14706b01'
down_revision: Union[str, Sequence[str], None] = '231b352f348f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, nullable) for columns whose naive values already mean UTC.
_UTC_COLUMNS = (
    ("users", "created_at", False),
    ("refresh_tokens", "created_at", False),
    ("refresh_tokens", "expires_at", False),
)


def upgrade() -> None:
    """Upgrade schema."""
    for table, column, nullable in _UTC_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=nullable,
            # Read the naive value as UTC — preserves the instant.
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )

    op.alter_column(
        "users",
        "updated_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        # Backfilled by now() cast through the session TimeZone in 231b352f348f;
        # a plain cast reverses that. Do NOT use AT TIME ZONE 'UTC' here.
        postgresql_using="updated_at::timestamptz",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "users",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
        # Back to naive session-local time, matching what 231b352f348f produced.
        postgresql_using="updated_at::timestamp",
    )

    for table, column, nullable in reversed(_UTC_COLUMNS):
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            existing_nullable=nullable,
            # Back to a naive value that means UTC.
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )
