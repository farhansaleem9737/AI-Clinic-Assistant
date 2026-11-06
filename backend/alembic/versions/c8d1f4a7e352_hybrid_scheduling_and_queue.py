"""hybrid scheduling and queue (D117)

Revision ID: c8d1f4a7e352
Revises: a9c4e2f7b310
Create Date: 2026-11-06

Additive and backward-compatible:
- `doctor_scheduling_policies`: one optional row per doctor (mode, consultation
  length, buffer, walk-ins, grace, overbooking). No rows are created here: a
  doctor without one keeps today's behaviour (slot length from the weekly
  templates), so existing availability is unchanged until a doctor saves a policy.
- `appointments.capacity_lane` (default 0) and `override_reason`. The doctor
  overlap EXCLUDE constraint is rebuilt with the lane: every existing row is in
  lane 0, so for them it means exactly what it meant before.
- `queue_token_counters`, `queue_entries`: the day's queue with stable tokens.
- Permission `appointment:override` for receptionists and administrators.

No existing appointment's start or end time is changed.

Rollback: `alembic downgrade a9c4e2f7b310`. It refuses while any appointment
uses a capacity lane above 0 (those double bookings would violate the restored
constraint): cancel or move them first. Queue data and policies are dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c8d1f4a7e352"
down_revision: Union[str, Sequence[str], None] = "a9c4e2f7b310"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSIONS = {"appointment:override": "Book outside the normal rules (custom time or duration, authorized double booking)"}
ROLE_PERMISSIONS = {"receptionist": ["appointment:override"], "admin": ["appointment:override"]}

_SLOT_HELD = "status NOT IN ('cancelled', 'no_show')"

mode = postgresql.ENUM("scheduled", "fifo", "hybrid", name="scheduling_mode", create_type=False)
kind = postgresql.ENUM("scheduled", "walk_in", name="queue_kind", create_type=False)
state = postgresql.ENUM(
    "registered", "waiting", "called", "in_consultation", "completed", "absent", "no_show", "cancelled",
    name="queue_state", create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    for enum in (mode, kind, state):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "doctor_scheduling_policies",
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("mode", mode, nullable=False, server_default="hybrid"),
        sa.Column("consultation_minutes", sa.SmallInteger(), nullable=False, server_default="15"),
        sa.Column("buffer_minutes", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("accept_walk_ins", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("walk_in_capacity", sa.SmallInteger(), nullable=True),
        sa.Column("late_grace_minutes", sa.SmallInteger(), nullable=False, server_default="10"),
        sa.Column("max_overbook", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("allow_receptionist_overrides", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("consultation_minutes BETWEEN 5 AND 240", name=op.f("ck_doctor_scheduling_policies_consultation_minutes_range")),
        sa.CheckConstraint("buffer_minutes BETWEEN 0 AND 120", name=op.f("ck_doctor_scheduling_policies_buffer_minutes_range")),
        sa.CheckConstraint("late_grace_minutes BETWEEN 0 AND 120", name=op.f("ck_doctor_scheduling_policies_late_grace_minutes_range")),
        sa.CheckConstraint("max_overbook BETWEEN 0 AND 5", name=op.f("ck_doctor_scheduling_policies_max_overbook_range")),
        sa.CheckConstraint(
            "walk_in_capacity IS NULL OR walk_in_capacity BETWEEN 1 AND 500",
            name=op.f("ck_doctor_scheduling_policies_walk_in_capacity_range"),
        ),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"], name=op.f("fk_doctor_scheduling_policies_doctor_id_doctors"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], name=op.f("fk_doctor_scheduling_policies_updated_by_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("doctor_id", name=op.f("pk_doctor_scheduling_policies")),
    )

    op.add_column("appointments", sa.Column("capacity_lane", sa.SmallInteger(), nullable=False, server_default="0"))
    op.add_column("appointments", sa.Column("override_reason", sa.String(length=500), nullable=True))
    op.create_check_constraint(op.f("ck_appointments_capacity_lane_range"), "appointments", "capacity_lane BETWEEN 0 AND 5")
    op.create_check_constraint(
        op.f("ck_appointments_capacity_exception_has_reason"), "appointments", "capacity_lane = 0 OR override_reason IS NOT NULL"
    )
    # Same constraint, now per capacity lane (every existing row is lane 0).
    op.execute("ALTER TABLE appointments DROP CONSTRAINT ex_appointments_doctor_overlap")
    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT ex_appointments_doctor_overlap "
        "EXCLUDE USING gist (doctor_id WITH =, capacity_lane WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&) "
        f"WHERE ({_SLOT_HELD})"
    )

    op.create_table(
        "queue_token_counters",
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("last_token", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"], name=op.f("fk_queue_token_counters_doctor_id_doctors"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("doctor_id", "session_date", name=op.f("pk_queue_token_counters")),
    )
    op.create_table(
        "queue_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("token_number", sa.Integer(), nullable=False),
        sa.Column("kind", kind, nullable=False),
        sa.Column("state", state, nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("appointment_id", sa.Uuid(), nullable=True),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deferred_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prioritized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"], name=op.f("fk_queue_entries_doctor_id_doctors"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], name=op.f("fk_queue_entries_patient_id_patients"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["appointment_id"], ["appointments.id"], name=op.f("fk_queue_entries_appointment_id_appointments"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], name=op.f("fk_queue_entries_created_by_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_queue_entries")),
        sa.UniqueConstraint("appointment_id", name=op.f("uq_queue_entries_appointment_id")),
        sa.UniqueConstraint("doctor_id", "session_date", "token_number", name="uq_queue_entries_doctor_date_token"),
    )
    op.create_index("ix_queue_entries_doctor_id_session_date", "queue_entries", ["doctor_id", "session_date"])
    op.create_index("ix_queue_entries_patient_id", "queue_entries", ["patient_id"])
    op.create_index("uq_queue_entries_one_called", "queue_entries", ["doctor_id"], unique=True, postgresql_where=sa.text("state = 'called'"))
    op.create_index(
        "uq_queue_entries_one_consultation", "queue_entries", ["doctor_id"], unique=True,
        postgresql_where=sa.text("state = 'in_consultation'"),
    )
    op.create_index(
        "uq_queue_entries_open_walk_in", "queue_entries", ["doctor_id", "session_date", "patient_id"], unique=True,
        postgresql_where=sa.text("kind = 'walk_in' AND state IN ('registered', 'waiting', 'called', 'in_consultation', 'absent')"),
    )

    conn = op.get_bind()
    for code, description in PERMISSIONS.items():
        conn.execute(sa.text("INSERT INTO permissions (code, description) VALUES (:code, :description)"), {"code": code, "description": description})
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
    conn = op.get_bind()
    lanes = conn.execute(sa.text(f"SELECT count(*) FROM appointments WHERE capacity_lane > 0 AND {_SLOT_HELD}")).scalar()
    if lanes:
        raise RuntimeError(
            f"{lanes} active double-booked appointment(s) use a capacity lane: cancel or move them before downgrading."
        )
    op.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:codes)").bindparams(codes=list(PERMISSIONS)))
    op.drop_table("queue_entries")
    op.drop_table("queue_token_counters")
    op.execute("ALTER TABLE appointments DROP CONSTRAINT ex_appointments_doctor_overlap")
    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT ex_appointments_doctor_overlap "
        "EXCLUDE USING gist (doctor_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&) "
        f"WHERE ({_SLOT_HELD})"
    )
    op.drop_constraint(op.f("ck_appointments_capacity_exception_has_reason"), "appointments", type_="check")
    op.drop_constraint(op.f("ck_appointments_capacity_lane_range"), "appointments", type_="check")
    op.drop_column("appointments", "override_reason")
    op.drop_column("appointments", "capacity_lane")
    op.drop_table("doctor_scheduling_policies")
    for enum in (state, kind, mode):
        enum.drop(op.get_bind(), checkfirst=True)
