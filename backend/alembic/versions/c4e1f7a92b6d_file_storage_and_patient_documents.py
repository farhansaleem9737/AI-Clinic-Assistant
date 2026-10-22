"""file storage and patient documents

Revision ID: c4e1f7a92b6d
Revises: 8cba3b163f58
Create Date: 2026-10-14

Files live in Cloudflare R2; PostgreSQL keeps their metadata
(``stored_files``) and who they belong to: ``doctors.photo_file_id``,
``patients.photo_file_id`` and ``patient_documents``. No bytes and no URLs
are stored in the database.

Seeds the document permissions: patients for their own record, doctors for
patients they have an appointment with. Admins and reception get none
(clinical content, architecture §1/§5).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4e1f7a92b6d'
down_revision: Union[str, Sequence[str], None] = '8cba3b163f58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISSIONS = (
    ("document:read_own", "View documents in one's own patient record"),
    ("document:upload_own", "Add documents to one's own patient record"),
    ("document:retract_own", "Retract documents one uploaded to one's own record"),
    ("document:read_assigned", "View documents of patients one has an appointment with"),
    ("document:upload_assigned", "Add documents for patients one has an appointment with"),
    ("document:retract_assigned", "Retract documents of patients one has an appointment with"),
)

ROLE_PERMISSIONS = {
    "patient": ["document:read_own", "document:upload_own", "document:retract_own"],
    "doctor": ["document:read_assigned", "document:upload_assigned", "document:retract_assigned"],
}

file_category = sa.Enum("doctor_photo", "patient_photo", "patient_document", name="file_category")
file_status = sa.Enum("active", "pending_deletion", "deleted", name="file_status")
document_type = sa.Enum(
    "lab_report", "imaging", "prescription", "referral", "discharge_summary", "other", name="document_type"
)
document_status = sa.Enum("active", "entered_in_error", name="document_status")


def _timestamps_and_id() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "stored_files",
        sa.Column("bucket", sa.String(length=63), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("category", file_category, nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("status", file_status, nullable=False),
        *_timestamps_and_id(),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_stored_files_size_positive")),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"], ["users.id"],
            name=op.f("fk_stored_files_uploaded_by_user_id_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stored_files")),
        sa.UniqueConstraint("object_key", name=op.f("uq_stored_files_object_key")),
    )
    op.create_index(op.f("ix_stored_files_category"), "stored_files", ["category"])
    op.create_index(op.f("ix_stored_files_status"), "stored_files", ["status"])

    op.create_table(
        "patient_documents",
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("appointment_id", sa.Uuid(), nullable=True),
        sa.Column("document_type", document_type, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", document_status, nullable=False),
        sa.Column("retracted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retraction_reason", sa.String(length=500), nullable=True),
        *_timestamps_and_id(),
        sa.CheckConstraint(
            "(status = 'active') = (retracted_at IS NULL)",
            name=op.f("ck_patient_documents_retraction_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"],
            name=op.f("fk_patient_documents_patient_id_patients"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["stored_files.id"],
            name=op.f("fk_patient_documents_file_id_stored_files"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"], ["appointments.id"],
            name=op.f("fk_patient_documents_appointment_id_appointments"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"], ["users.id"],
            name=op.f("fk_patient_documents_uploaded_by_user_id_users"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retracted_by_user_id"], ["users.id"],
            name=op.f("fk_patient_documents_retracted_by_user_id_users"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patient_documents")),
        sa.UniqueConstraint("file_id", name=op.f("uq_patient_documents_file_id")),
    )
    op.create_index(op.f("ix_patient_documents_appointment_id"), "patient_documents", ["appointment_id"])
    op.create_index(
        "ix_patient_documents_patient_id_created_at", "patient_documents", ["patient_id", "created_at"]
    )

    for table in ("doctors", "patients"):
        op.add_column(table, sa.Column("photo_file_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_{table}_photo_file_id_stored_files"), table, "stored_files",
            ["photo_file_id"], ["id"], ondelete="RESTRICT",
        )
        op.create_unique_constraint(op.f(f"uq_{table}_photo_file_id"), table, ["photo_file_id"])

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
    # role_permissions rows go with them (ON DELETE CASCADE).
    op.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:codes)").bindparams(codes=codes))

    for table in ("patients", "doctors"):
        op.drop_constraint(op.f(f"uq_{table}_photo_file_id"), table, type_="unique")
        op.drop_constraint(op.f(f"fk_{table}_photo_file_id_stored_files"), table, type_="foreignkey")
        op.drop_column(table, "photo_file_id")

    op.drop_index("ix_patient_documents_patient_id_created_at", table_name="patient_documents")
    op.drop_index(op.f("ix_patient_documents_appointment_id"), table_name="patient_documents")
    op.drop_table("patient_documents")
    op.drop_index(op.f("ix_stored_files_status"), table_name="stored_files")
    op.drop_index(op.f("ix_stored_files_category"), table_name="stored_files")
    op.drop_table("stored_files")

    bind = op.get_bind()
    for enum in (document_status, document_type, file_status, file_category):
        enum.drop(bind, checkfirst=True)
