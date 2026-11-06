"""patient personal details and address parts

Revision ID: f3d8b1a6c240
Revises: e7b2c9d41a58
Create Date: 2026-11-05

Patient profile screens (D111). Additive only, safe on a live database:
nullable columns on `patients`, with checks on their values. Existing rows
keep NULL; `address` stays the street / area.
- `blood_group` (self-reported), `marital_status`, `national_id` (sensitive:
  the API returns it masked only);
- `city`, `province`, `country` (ISO 3166-1 alpha-2).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3d8b1a6c240"
down_revision: Union[str, Sequence[str], None] = "e7b2c9d41a58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = (
    ("blood_group", 3),
    ("marital_status", 10),
    ("national_id", 30),
    ("city", 100),
    ("province", 100),
    ("country", 2),
)
CHECKS = (
    ("blood_group_known", "blood_group IS NULL OR blood_group IN ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-')"),
    ("marital_status_known", "marital_status IS NULL OR marital_status IN ('single', 'married', 'divorced', 'widowed')"),
    ("country_iso2", "country IS NULL OR country ~ '^[A-Z]{2}$'"),
)


def upgrade() -> None:
    """Upgrade schema."""
    for name, length in COLUMNS:
        op.add_column("patients", sa.Column(name, sa.String(length=length), nullable=True))
    for name, condition in CHECKS:
        op.create_check_constraint(op.f(f"ck_patients_{name}"), "patients", condition)


def downgrade() -> None:
    """Downgrade schema."""
    for name, _ in CHECKS:
        op.drop_constraint(op.f(f"ck_patients_{name}"), "patients", type_="check")
    for name, _ in reversed(COLUMNS):
        op.drop_column("patients", name)
