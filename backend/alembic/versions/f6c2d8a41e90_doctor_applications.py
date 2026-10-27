"""doctor applications

Revision ID: f6c2d8a41e90
Revises: e3b8f1c62a47
Create Date: 2026-10-27

Self-registration as a doctor (D77). Choosing "Doctor" creates a login with
the new ``doctor_applicant`` role and a ``doctor_applications`` row; no
Doctor profile and no clinical permission exist until an administrator
approves it. Credentials go to private R2 storage (new ``file_category``
value ``doctor_credential``); ``doctor_application_documents`` links them.

Seeds ``doctor_application:manage_own`` (applicants) and
``doctor_application:review`` (admins). Additive: existing rows are untouched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6c2d8a41e90'
down_revision: Union[str, Sequence[str], None] = 'e3b8f1c62a47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROLE = ("doctor_applicant", "Doctor applicant", "Registered as a doctor; credentials not yet verified. No clinical access.")

PERMISSIONS = (
    ("doctor_application:manage_own", "View and complete one's own doctor application"),
    ("doctor_application:review", "Review, approve and reject doctor applications"),
)

ROLE_PERMISSIONS = {
    "doctor_applicant": ["doctor_application:manage_own"],
    "admin": ["doctor_application:review"],
}

application_status = sa.Enum("pending_review", "approved", "rejected", name="doctor_application_status")
credential_type = sa.Enum(
    "registration_certificate", "degree_certificate", "supporting_document", name="credential_type"
)


def _timestamps_and_id() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    """Upgrade schema."""
    # IF NOT EXISTS: PostgreSQL cannot drop an enum value, so a downgrade
    # leaves it in place and a re-upgrade must not fail on it.
    op.execute("ALTER TYPE file_category ADD VALUE IF NOT EXISTS 'doctor_credential'")

    op.create_table(
        "doctor_applications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", application_status, nullable=False),
        sa.Column("license_number", sa.String(length=50), nullable=True),
        sa.Column("registration_authority", sa.String(length=150), nullable=True),
        sa.Column("specialization", sa.String(length=150), nullable=True),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("years_of_experience", sa.Integer(), nullable=True),
        sa.Column("qualifications", sa.String(length=500), nullable=True),
        sa.Column("institution", sa.String(length=200), nullable=True),
        sa.Column("bio", sa.String(length=1000), nullable=True),
        sa.Column("consultation_fee", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("languages", sa.String(length=200), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("review_notes", sa.String(length=1000), nullable=True),
        sa.Column("doctor_id", sa.Uuid(), nullable=True),
        *_timestamps_and_id(),
        sa.CheckConstraint(
            "years_of_experience IS NULL OR years_of_experience BETWEEN 0 AND 80",
            name=op.f("ck_doctor_applications_experience_range"),
        ),
        sa.CheckConstraint(
            "consultation_fee IS NULL OR consultation_fee >= 0", name=op.f("ck_doctor_applications_fee_not_negative")
        ),
        sa.CheckConstraint(
            "(status = 'pending_review') = (reviewed_at IS NULL)",
            name=op.f("ck_doctor_applications_review_consistent"),
        ),
        sa.CheckConstraint(
            "(status = 'approved') = (doctor_id IS NOT NULL)", name=op.f("ck_doctor_applications_approval_has_profile")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_doctor_applications_user_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["department_id"], ["departments.id"],
            name=op.f("fk_doctor_applications_department_id_departments"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"], ["users.id"],
            name=op.f("fk_doctor_applications_reviewed_by_user_id_users"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"], ["doctors.id"], name=op.f("fk_doctor_applications_doctor_id_doctors"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctor_applications")),
        sa.UniqueConstraint("user_id", name=op.f("uq_doctor_applications_user_id")),
        sa.UniqueConstraint("doctor_id", name=op.f("uq_doctor_applications_doctor_id")),
    )
    op.create_index(op.f("ix_doctor_applications_status"), "doctor_applications", ["status"])
    op.create_index(op.f("ix_doctor_applications_department_id"), "doctor_applications", ["department_id"])

    op.create_table(
        "doctor_application_documents",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("document_type", credential_type, nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        *_timestamps_and_id(),
        sa.ForeignKeyConstraint(
            ["application_id"], ["doctor_applications.id"],
            name=op.f("fk_doctor_application_documents_application_id_doctor_applications"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["stored_files.id"],
            name=op.f("fk_doctor_application_documents_file_id_stored_files"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctor_application_documents")),
        sa.UniqueConstraint("file_id", name=op.f("uq_doctor_application_documents_file_id")),
    )
    op.create_index(
        op.f("ix_doctor_application_documents_application_id"), "doctor_application_documents", ["application_id"]
    )

    conn = op.get_bind()
    code, name, description = ROLE
    conn.execute(
        sa.text(
            "INSERT INTO roles (code, name, description, created_at, updated_at) "
            "VALUES (:code, :name, :description, now(), now())"
        ),
        {"code": code, "name": name, "description": description},
    )
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
    """Downgrade schema.

    Refuses (foreign keys) while any login still holds the doctor_applicant
    role: those accounts must be approved or have the role removed first.
    The ``doctor_credential`` enum value stays (PostgreSQL cannot drop it).
    """
    codes = [code for code, _ in PERMISSIONS]
    op.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:codes)").bindparams(codes=codes))
    op.execute(sa.text("DELETE FROM roles WHERE code = :code").bindparams(code=ROLE[0]))

    op.drop_index(op.f("ix_doctor_application_documents_application_id"), table_name="doctor_application_documents")
    op.drop_table("doctor_application_documents")
    op.drop_index(op.f("ix_doctor_applications_department_id"), table_name="doctor_applications")
    op.drop_index(op.f("ix_doctor_applications_status"), table_name="doctor_applications")
    op.drop_table("doctor_applications")

    bind = op.get_bind()
    for enum in (credential_type, application_status):
        enum.drop(bind, checkfirst=True)
