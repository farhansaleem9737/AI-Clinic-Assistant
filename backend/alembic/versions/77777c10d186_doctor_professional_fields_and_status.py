"""doctor professional fields and status

Revision ID: 77777c10d186
Revises: 90b5e35b13bb
Create Date: 2026-09-29

Completes the Doctor profile (architecture D19):

* professional fields: ``title``, ``license_number`` (unique), ``phone``,
  ``room_number``. Nullable: existing profiles have no values and none are
  invented; admins fill them in.
* ``is_active`` — doctors are deactivated, never deleted (architecture §20).
* ``user_id`` foreign key changes from ON DELETE CASCADE to RESTRICT: deleting
  a login must never silently delete a clinician's profile (§3 cascade policy).
* index on ``department_id`` for the directory's department filter.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '77777c10d186'
down_revision: Union[str, Sequence[str], None] = '90b5e35b13bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("doctors", sa.Column("title", sa.String(length=20), nullable=True))
    op.add_column("doctors", sa.Column("license_number", sa.String(length=50), nullable=True))
    op.add_column("doctors", sa.Column("phone", sa.String(length=30), nullable=True))
    op.add_column("doctors", sa.Column("room_number", sa.String(length=20), nullable=True))
    op.add_column("doctors", sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.alter_column("doctors", "is_active", server_default=None)
    op.create_unique_constraint(op.f("uq_doctors_license_number"), "doctors", ["license_number"])
    op.create_index(op.f("ix_doctors_department_id"), "doctors", ["department_id"])

    op.drop_constraint("fk_doctors_user_id_users", "doctors", type_="foreignkey")
    op.create_foreign_key(
        op.f("fk_doctors_user_id_users"), "doctors", "users", ["user_id"], ["id"], ondelete="RESTRICT"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_doctors_user_id_users", "doctors", type_="foreignkey")
    op.create_foreign_key(
        op.f("fk_doctors_user_id_users"), "doctors", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.drop_index(op.f("ix_doctors_department_id"), table_name="doctors")
    op.drop_constraint(op.f("uq_doctors_license_number"), "doctors", type_="unique")
    op.drop_column("doctors", "is_active")
    op.drop_column("doctors", "room_number")
    op.drop_column("doctors", "phone")
    op.drop_column("doctors", "license_number")
    op.drop_column("doctors", "title")
