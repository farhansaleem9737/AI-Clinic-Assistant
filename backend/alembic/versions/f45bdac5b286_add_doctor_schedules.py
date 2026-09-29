"""add doctor schedules

Revision ID: f45bdac5b286
Revises: 6fa6ba9837dc
Create Date: 2026-09-29

Doctor availability (architecture §9, D9): recurring weekly templates in local
wall-clock time plus one-off exceptions over exact instants. Bookable slots
are computed from these at read time; no slot table is materialised.

Seeds the schedule permissions. ``availability:read`` is separate from
``schedule:read`` so patients can see free slots without seeing staff-only
details such as the reason a doctor is on leave.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f45bdac5b286'
down_revision: Union[str, Sequence[str], None] = '6fa6ba9837dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISSIONS = (
    ("availability:read", "See a doctor's free appointment slots"),
    ("schedule:read", "View doctors' working templates and exceptions"),
    ("schedule:manage_own", "Manage one's own schedule"),
    ("schedule:manage_any", "Manage any doctor's schedule"),
)

ROLE_PERMISSIONS = {
    "patient": ["availability:read"],
    "doctor": ["availability:read", "schedule:read", "schedule:manage_own"],
    "receptionist": ["availability:read", "schedule:read", "schedule:manage_any"],
    "admin": ["availability:read", "schedule:read", "schedule:manage_any"],
}

exception_kind = sa.Enum("leave", "holiday", "block", "extra_availability", name="schedule_exception_kind")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "schedule_templates",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("slot_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name=op.f("ck_schedule_templates_weekday_range")),
        sa.CheckConstraint("start_time < end_time", name=op.f("ck_schedule_templates_start_before_end")),
        sa.CheckConstraint("slot_minutes BETWEEN 5 AND 240", name=op.f("ck_schedule_templates_slot_minutes_range")),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from", name=op.f("ck_schedule_templates_valid_range")
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"], ["doctors.id"], name=op.f("fk_schedule_templates_doctor_id_doctors"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedule_templates")),
    )
    op.create_index("ix_schedule_templates_doctor_id_weekday", "schedule_templates", ["doctor_id", "weekday"])

    op.create_table(
        "schedule_exceptions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("kind", exception_kind, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_schedule_exceptions_ends_after_starts")),
        sa.ForeignKeyConstraint(
            ["doctor_id"], ["doctors.id"], name=op.f("fk_schedule_exceptions_doctor_id_doctors"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_schedule_exceptions_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedule_exceptions")),
    )
    op.create_index(
        "ix_schedule_exceptions_doctor_id_starts_at", "schedule_exceptions", ["doctor_id", "starts_at"]
    )

    conn = op.get_bind()
    for code, description in PERMISSIONS:
        conn.execute(
            sa.text("INSERT INTO permissions (code, description) VALUES (:code, :description)"),
            {"code": code, "description": description},
        )
    for role_code, permission_codes in ROLE_PERMISSIONS.items():
        for permission_code in permission_codes:
            conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT r.id, p.id FROM roles r, permissions p WHERE r.code = :r AND p.code = :p"
                ),
                {"r": role_code, "p": permission_code},
            )


def downgrade() -> None:
    """Downgrade schema."""
    codes = [code for code, _ in PERMISSIONS]
    op.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:codes)").bindparams(codes=codes))
    op.drop_index("ix_schedule_exceptions_doctor_id_starts_at", table_name="schedule_exceptions")
    op.drop_table("schedule_exceptions")
    exception_kind.drop(op.get_bind(), checkfirst=True)
    op.drop_index("ix_schedule_templates_doctor_id_weekday", table_name="schedule_templates")
    op.drop_table("schedule_templates")
