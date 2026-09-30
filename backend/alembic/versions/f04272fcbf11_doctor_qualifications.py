"""doctor qualifications

Revision ID: f04272fcbf11
Revises: 1a6e1ee8ec97
Create Date: 2026-09-30

Adds ``doctors.qualifications``: the degrees and certifications shown on a
doctor's public profile (e.g. "MBBS, FCPS (Cardiology)"). Nullable: existing
profiles have none recorded and none are invented.

No new indexes. The directory filters and sorts on department (already
indexed), experience and fee; with a clinic-sized doctors table those are
cheap scans, and an index would cost more on writes than it saves on reads.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f04272fcbf11'
down_revision: Union[str, Sequence[str], None] = '1a6e1ee8ec97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("doctors", sa.Column("qualifications", sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("doctors", "qualifications")
