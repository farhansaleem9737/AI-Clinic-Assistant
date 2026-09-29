"""add appointments

Revision ID: b295d309a7bd
Revises: f45bdac5b286
Create Date: 2026-09-29

Appointments and their status history (architecture §8, D10, D12).

* Double-booking is prevented by the database: EXCLUDE constraints (GiST,
  needs the ``btree_gist`` extension) forbid two slot-holding appointments
  whose ``[starts_at, ends_at)`` overlap for the same doctor, or for the same
  patient. Cancelled and no-show rows release the slot.
* ``rescheduled`` is not a status: the old row is cancelled with reason
  ``rescheduled`` and the new row points back via ``rescheduled_from_id``.
* ``appointment_status_history`` is append-only: one row per transition.
* ``(booked_by_user_id, idempotency_key)`` is unique so a retried booking
  request returns the original appointment instead of creating another.

Seeds the appointment permissions.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b295d309a7bd'
down_revision: Union[str, Sequence[str], None] = 'f45bdac5b286'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISSIONS = (
    ("appointment:read_own", "View one's own appointments"),
    ("appointment:read_assigned", "View appointments with oneself as the doctor"),
    ("appointment:read_any", "View any appointment"),
    ("appointment:create_own", "Book appointments for oneself"),
    ("appointment:create", "Book appointments for any patient"),
    ("appointment:confirm_own", "Confirm one's own appointment"),
    ("appointment:cancel_own", "Cancel one's own appointment before the cutoff"),
    ("appointment:reschedule_own", "Reschedule one's own appointment before the cutoff"),
    ("appointment:cancel_assigned", "Cancel appointments with oneself as the doctor"),
    ("appointment:cancel_any", "Cancel any appointment"),
    ("appointment:manage", "Schedule, confirm, reschedule, mark no-show and annotate any appointment"),
    ("appointment:check_in", "Check patients in on arrival"),
    ("appointment:consult", "Start and complete consultations with oneself as the doctor"),
)

ROLE_PERMISSIONS = {
    "patient": [
        "appointment:read_own",
        "appointment:create_own",
        "appointment:confirm_own",
        "appointment:cancel_own",
        "appointment:reschedule_own",
    ],
    "doctor": ["appointment:read_assigned", "appointment:cancel_assigned", "appointment:consult"],
    "receptionist": [
        "appointment:read_any",
        "appointment:create",
        "appointment:cancel_any",
        "appointment:manage",
        "appointment:check_in",
    ],
    "admin": [
        "appointment:read_any",
        "appointment:create",
        "appointment:cancel_any",
        "appointment:manage",
        "appointment:check_in",
    ],
}

appointment_status = sa.Enum(
    "requested", "scheduled", "confirmed", "checked_in", "in_progress", "completed", "cancelled", "no_show",
    name="appointment_status",
)
cancellation_reason = sa.Enum(
    "patient_request", "doctor_unavailable", "clinic_decision", "rescheduled", "other",
    name="appointment_cancellation_reason",
)


def upgrade() -> None:
    """Upgrade schema."""
    # Lets GiST index plain equality on uuid next to the range overlap operator.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "appointments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", appointment_status, nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("staff_notes", sa.String(length=1000), nullable=True),
        sa.Column("booked_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("cancellation_reason", cancellation_reason, nullable=True),
        sa.Column("cancellation_note", sa.String(length=500), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("rescheduled_from_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_appointments_ends_after_starts")),
        sa.CheckConstraint(
            "(status = 'cancelled') = (cancellation_reason IS NOT NULL)",
            name=op.f("ck_appointments_cancellation_reason_iff_cancelled"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_appointments_patient_id_patients"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"], ["doctors.id"], name=op.f("fk_appointments_doctor_id_doctors"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["booked_by_user_id"],
            ["users.id"],
            name=op.f("fk_appointments_booked_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by_user_id"],
            ["users.id"],
            name=op.f("fk_appointments_cancelled_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rescheduled_from_id"],
            ["appointments.id"],
            name=op.f("fk_appointments_rescheduled_from_id_appointments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointments")),
        sa.UniqueConstraint("rescheduled_from_id", name=op.f("uq_appointments_rescheduled_from_id")),
        sa.UniqueConstraint(
            "booked_by_user_id", "idempotency_key", name="uq_appointments_booked_by_idempotency_key"
        ),
    )
    for column in ("doctor_id", "patient_id"):
        op.execute(
            f"ALTER TABLE appointments ADD CONSTRAINT ex_appointments_{column.split('_')[0]}_overlap "
            f"EXCLUDE USING gist ({column} WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&) "
            "WHERE (status NOT IN ('cancelled', 'no_show'))"
        )
    op.create_index("ix_appointments_doctor_id_starts_at", "appointments", ["doctor_id", "starts_at"])
    op.create_index("ix_appointments_patient_id_starts_at", "appointments", ["patient_id", "starts_at"])

    op.create_table(
        "appointment_status_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("appointment_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", appointment_status, nullable=True),
        sa.Column("to_status", appointment_status, nullable=False),
        sa.Column("changed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.id"],
            name=op.f("fk_appointment_status_history_appointment_id_appointments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"],
            ["users.id"],
            name=op.f("fk_appointment_status_history_changed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointment_status_history")),
    )
    op.create_index(
        op.f("ix_appointment_status_history_appointment_id"), "appointment_status_history", ["appointment_id"]
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
    op.drop_index(op.f("ix_appointment_status_history_appointment_id"), table_name="appointment_status_history")
    op.drop_table("appointment_status_history")
    op.drop_index("ix_appointments_patient_id_starts_at", table_name="appointments")
    op.drop_index("ix_appointments_doctor_id_starts_at", table_name="appointments")
    op.drop_table("appointments")
    bind = op.get_bind()
    cancellation_reason.drop(bind, checkfirst=True)
    appointment_status.drop(bind, checkfirst=True)
    # btree_gist is left installed: other objects may rely on it, and it is harmless.
