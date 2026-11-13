"""Receptionists who work for particular doctors (D131).

One global user account per receptionist; one row per (doctor, receptionist)
pair, each with its own status and permissions. Nothing about a doctor is put
on the user, so the same person can work for any number of doctors, and each
doctor's decisions touch only their own row.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AssignmentStatus(StrEnum):
    active = "active"
    suspended = "suspended"  # paused by the doctor; can be reactivated
    revoked = "revoked"  # removed by the doctor; only a new invitation brings it back


class DoctorReceptionist(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "doctor_receptionists"
    __table_args__ = (
        UniqueConstraint("doctor_id", "receptionist_user_id", name="uq_doctor_receptionists_doctor_receptionist"),
        CheckConstraint("status IN ('active', 'suspended', 'revoked')", name="status_known"),
    )

    doctor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("doctors.id", ondelete="CASCADE"), index=True)
    receptionist_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(10), default=AssignmentStatus.active)
    # AssignmentPermission values, validated and normalized by the service.
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String(30)), default=list)


class ReceptionistInvitation(UUIDPrimaryKeyMixin, Base):
    """A doctor's invitation to work for them. Only the SHA-256 of the token is
    stored (the token exists only in the email). Single use; status is derived
    from accepted_at / revoked_at / expires_at, never stored twice (as D87)."""

    __tablename__ = "receptionist_invitations"
    __table_args__ = (
        CheckConstraint("NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)", name="single_outcome"),
        # At most one open invitation per doctor and address.
        Index(
            "uq_receptionist_invitations_open", "doctor_id", "email", unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    doctor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("doctors.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String(30)), default=list)
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_status: Mapped[str | None] = mapped_column(String(20))
