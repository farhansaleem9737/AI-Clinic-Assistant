"""patient emergency contact and preferred contact method

Revision ID: b8e4c2a9d715
Revises: a7d3e5f19b42
Create Date: 2026-10-27

Operational contact data for the patient record (D81): an emergency contact
(name, relationship, phone) and how the clinic should reach the patient.
All nullable and additive; existing rows are unchanged.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8e4c2a9d715'
down_revision: Union[str, Sequence[str], None] = 'a7d3e5f19b42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = (
    ("emergency_contact_name", 100),
    ("emergency_contact_relationship", 50),
    ("emergency_contact_phone", 30),
    ("preferred_contact_method", 10),
)


def upgrade() -> None:
    """Upgrade schema."""
    for name, length in COLUMNS:
        op.add_column("patients", sa.Column(name, sa.String(length=length), nullable=True))
    op.create_check_constraint(
        op.f("ck_patients_contact_method_known"),
        "patients",
        "preferred_contact_method IS NULL OR preferred_contact_method IN ('phone', 'sms', 'email')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_patients_contact_method_known"), "patients", type_="check")
    for name, _ in reversed(COLUMNS):
        op.drop_column("patients", name)
