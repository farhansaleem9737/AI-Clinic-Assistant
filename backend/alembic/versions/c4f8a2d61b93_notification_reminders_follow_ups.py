"""notification reminders, preferences and follow-ups

Revision ID: c4f8a2d61b93
Revises: b7d2e9f4a613
Create Date: 2026-11-04

Notification system (D108). Additive only, safe on a live database:
- `notifications.dedupe_key` (nullable) with a unique index on
  (user_id, dedupe_key): a scheduled reminder exists at most once per user,
  however often the reminder run repeats. Existing rows keep NULL, which the
  unique index does not compare.
- a partial index for unread notifications (the bell's count);
- `notification_preferences`: optional categories a user switched off (no
  row = all on);
- `follow_ups`: a follow-up visit recorded as due by a date (no clinical text).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4f8a2d61b93"
down_revision: Union[str, Sequence[str], None] = "b7d2e9f4a613"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("notifications", sa.Column("dedupe_key", sa.String(length=120), nullable=True))
    op.create_index(
        "uq_notifications_user_id_dedupe_key", "notifications", ["user_id", "dedupe_key"], unique=True
    )
    op.create_index(
        "ix_notifications_unread", "notifications", ["user_id"], postgresql_where=sa.text("read_at IS NULL")
    )

    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("appointment_updates", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("reminders", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("follow_ups", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_notification_preferences_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_notification_preferences")),
    )

    op.create_table(
        "follow_ups",
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("doctor_id", sa.Uuid(), nullable=True),
        sa.Column("appointment_id", sa.Uuid(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_follow_ups_patient_id_patients"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"], ["doctors.id"], name=op.f("fk_follow_ups_doctor_id_doctors"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"], ["appointments.id"], name=op.f("fk_follow_ups_appointment_id_appointments"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], name=op.f("fk_follow_ups_created_by_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_follow_ups")),
    )
    op.create_index("ix_follow_ups_patient_id", "follow_ups", ["patient_id"])
    op.create_index(
        "ix_follow_ups_open_due_date", "follow_ups", ["due_date"], postgresql_where=sa.text("dismissed_at IS NULL")
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_follow_ups_open_due_date", table_name="follow_ups", postgresql_where=sa.text("dismissed_at IS NULL"))
    op.drop_index("ix_follow_ups_patient_id", table_name="follow_ups")
    op.drop_table("follow_ups")
    op.drop_table("notification_preferences")
    op.drop_index("ix_notifications_unread", table_name="notifications", postgresql_where=sa.text("read_at IS NULL"))
    op.drop_index("uq_notifications_user_id_dedupe_key", table_name="notifications")
    op.drop_column("notifications", "dedupe_key")
