"""department icon and color

Revision ID: e4a9c2f7b310
Revises: d2e7b4c9a118
Create Date: 2026-10-28

Optional display metadata for departments (D89). Two nullable columns, no
backfill: NULL means the UI picks an icon from the department name.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e4a9c2f7b310'
down_revision: Union[str, Sequence[str], None] = 'd2e7b4c9a118'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("departments", sa.Column("icon", sa.String(length=30), nullable=True))
    op.add_column("departments", sa.Column("color", sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("departments", "color")
    op.drop_column("departments", "icon")
