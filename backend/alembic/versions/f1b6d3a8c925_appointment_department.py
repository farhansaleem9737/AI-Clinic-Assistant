"""appointment department

Revision ID: f1b6d3a8c925
Revises: e4a9c2f7b310
Create Date: 2026-10-28

Records each appointment's department at booking time (D92), so moving a
doctor to another department does not rewrite their past appointments.
Additive: a nullable column, an index and a foreign key. Existing rows are
backfilled with their doctor's department as it is now, the best record
available; nothing else changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1b6d3a8c925'
down_revision: Union[str, Sequence[str], None] = 'e4a9c2f7b310'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("appointments", sa.Column("department_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_appointments_department_id"), "appointments", ["department_id"])
    op.create_foreign_key(
        op.f("fk_appointments_department_id_departments"),
        "appointments", "departments", ["department_id"], ["id"], ondelete="RESTRICT",
    )
    op.execute(
        "UPDATE appointments a SET department_id = d.department_id "
        "FROM doctors d WHERE d.id = a.doctor_id AND a.department_id IS NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("fk_appointments_department_id_departments"), "appointments", type_="foreignkey")
    op.drop_index(op.f("ix_appointments_department_id"), table_name="appointments")
    op.drop_column("appointments", "department_id")
