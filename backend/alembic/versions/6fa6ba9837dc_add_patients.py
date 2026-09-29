"""add patients

Revision ID: 6fa6ba9837dc
Revises: 77777c10d186
Create Date: 2026-09-29

Creates the Patient profile (architecture §3, §10):

* ``user_id`` UNIQUE and NULLABLE — walk-in patients may have no login.
* ``mrn`` — medical record number generated from ``patient_mrn_seq``.
* demographics and contact fields only; no clinical data.

Seeds the patient permissions and grants them to the built-in roles.
Existing users with the patient role are *not* given a profile: their legal
name and date of birth are unknown, and inventing them would corrupt the
record. They complete their profile themselves (POST /patients/me).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6fa6ba9837dc'
down_revision: Union[str, Sequence[str], None] = '77777c10d186'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISSIONS = (
    ("patient:read_own", "View one's own patient profile"),
    ("patient:update_own", "Edit the contact details of one's own profile"),
    ("patient:read_assigned", "View patients one has an appointment with"),
    ("patient:read_any", "Search and view any patient"),
    ("patient:create", "Register patients and create their portal login"),
    ("patient:update", "Edit patient demographics and link accounts"),
    ("patient:deactivate", "Deactivate or reactivate patients"),
)

ROLE_PERMISSIONS = {
    "patient": ["patient:read_own", "patient:update_own"],
    "doctor": ["patient:read_assigned"],
    "receptionist": ["patient:read_any", "patient:create", "patient:update"],
    "admin": [code for code, _ in PERMISSIONS if not code.endswith("_own") and code != "patient:read_assigned"],
}

sex_at_birth = sa.Enum("female", "male", "intersex", "unknown", name="sex_at_birth")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SEQUENCE patient_mrn_seq")
    op.create_table(
        "patients",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "mrn",
            sa.String(length=20),
            server_default=sa.text("('MRN' || lpad(nextval('patient_mrn_seq')::text, 8, '0'))"),
            nullable=False,
        ),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("sex_at_birth", sex_at_birth, nullable=False),
        sa.Column("gender_identity", sa.String(length=50), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("preferred_language", sa.String(length=35), nullable=True),
        sa.Column("registered_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_patients_user_id_users"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["registered_by_user_id"],
            ["users.id"],
            name=op.f("fk_patients_registered_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patients")),
        sa.UniqueConstraint("mrn", name=op.f("uq_patients_mrn")),
        sa.UniqueConstraint("user_id", name=op.f("uq_patients_user_id")),
    )
    op.execute("ALTER SEQUENCE patient_mrn_seq OWNED BY patients.mrn")
    op.create_index(op.f("ix_patients_date_of_birth"), "patients", ["date_of_birth"])
    op.create_index(op.f("ix_patients_phone"), "patients", ["phone"])
    op.create_index("ix_patients_last_name_first_name", "patients", ["last_name", "first_name"])

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
    op.drop_index("ix_patients_last_name_first_name", table_name="patients")
    op.drop_index(op.f("ix_patients_phone"), table_name="patients")
    op.drop_index(op.f("ix_patients_date_of_birth"), table_name="patients")
    op.drop_table("patients")  # drops the owned sequence too
    sex_at_birth.drop(op.get_bind(), checkfirst=True)
