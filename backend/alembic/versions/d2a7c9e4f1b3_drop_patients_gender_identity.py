"""drop patients.gender_identity

Revision ID: d2a7c9e4f1b3
Revises: c4e1f7a92b6d
Create Date: 2026-10-22

The clinic no longer records gender identity. Dropping the column deletes
any values already stored, so back up the database first. Downgrade
restores the column, empty.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd2a7c9e4f1b3'
down_revision: Union[str, Sequence[str], None] = 'c4e1f7a92b6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("patients", "gender_identity")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("patients", sa.Column("gender_identity", sa.String(length=50), nullable=True))
