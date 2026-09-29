"""department status, timezone and updated_at

Revision ID: 90b5e35b13bb
Revises: a1794a7fec19
Create Date: 2026-09-29

* ``is_active`` — departments are deactivated, never deleted (architecture §20).
* ``timezone`` — IANA name; a department's recurring schedules are expanded in
  its own timezone so "09:00" stays 09:00 across DST (architecture §2, §9).
  Existing rows are backfilled with this environment's ``CLINIC_TIMEZONE``,
  the one piece of configuration that says where the clinic is.
* ``updated_at`` — backfilled from ``created_at``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.core.config import settings


revision: str = '90b5e35b13bb'
down_revision: Union[str, Sequence[str], None] = 'a1794a7fec19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("departments", sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column("departments", sa.Column("timezone", sa.String(length=64), nullable=True))
    op.add_column("departments", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        sa.text("UPDATE departments SET timezone = :tz, updated_at = created_at").bindparams(
            tz=settings.clinic_timezone
        )
    )
    op.alter_column("departments", "timezone", nullable=False)
    op.alter_column("departments", "updated_at", nullable=False)
    op.alter_column("departments", "is_active", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("departments", "updated_at")
    op.drop_column("departments", "timezone")
    op.drop_column("departments", "is_active")
