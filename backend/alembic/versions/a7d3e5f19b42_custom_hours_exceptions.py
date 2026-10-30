"""custom hours schedule exceptions

Revision ID: a7d3e5f19b42
Revises: f6c2d8a41e90
Create Date: 2026-10-27

Adds ``custom_hours`` to ``schedule_exception_kind``: an exception that
replaces a doctor's weekly hours on one local date (D78). Additive; no rows
are changed.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a7d3e5f19b42'
down_revision: Union[str, Sequence[str], None] = 'f6c2d8a41e90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # IF NOT EXISTS: PostgreSQL cannot drop an enum value, so a downgrade
    # leaves it and a re-upgrade must not fail on it.
    op.execute("ALTER TYPE schedule_exception_kind ADD VALUE IF NOT EXISTS 'custom_hours'")


def downgrade() -> None:
    """Downgrade schema.

    The enum value stays (PostgreSQL cannot drop one). Custom-hours rows would
    mean nothing to older code, so they are removed.
    """
    op.execute("DELETE FROM schedule_exceptions WHERE kind::text = 'custom_hours'")
