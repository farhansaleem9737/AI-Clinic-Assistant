"""appointments.booking_mode: automatic token, custom time, or staff override (D120)

Revision ID: e3b7c1d9f240
Revises: d5e9a3c7b418
Create Date: 2026-11-06

Additive and safe on a live database: one nullable column and a check. Existing
appointments keep NULL ("booked before D120"): their mode is not guessed, and
their times and lengths are not touched.

Rollback: `alembic downgrade d5e9a3c7b418` drops the column (the mode of later
bookings is lost; the bookings themselves are not).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3b7c1d9f240"
down_revision: Union[str, Sequence[str], None] = "d5e9a3c7b418"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("appointments", sa.Column("booking_mode", sa.String(length=10), nullable=True))
    op.create_check_constraint(
        op.f("ck_appointments_booking_mode_known"), "appointments", "booking_mode IN ('auto', 'custom', 'override')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_appointments_booking_mode_known"), "appointments", type_="check")
    op.drop_column("appointments", "booking_mode")
