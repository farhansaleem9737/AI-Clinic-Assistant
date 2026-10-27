"""doctor languages

Revision ID: e3b8f1c62a47
Revises: d2a7c9e4f1b3
Create Date: 2026-10-27

Adds ``doctors.languages`` (free text such as "English, Urdu"), shown on the
public profile (architecture §7 lists languages among the public doctor
fields). Nullable and additive: existing rows keep working unchanged.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3b8f1c62a47'
down_revision: Union[str, Sequence[str], None] = 'd2a7c9e4f1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("doctors", sa.Column("languages", sa.String(length=200), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("doctors", "languages")
