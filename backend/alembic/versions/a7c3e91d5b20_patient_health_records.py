"""patient allergies, diagnoses and medications

Revision ID: a7c3e91d5b20
Revises: f3d8b1a6c240
Create Date: 2026-11-06

Medical Information tabs (D112). Additive only, safe on a live database: three
new tables and four permissions, nothing existing is changed.

- patients report their own allergies and the medicines they take;
- doctors record allergies, diagnoses and medications for patients they have
  an appointment with (same rule as documents);
- admins and reception get none (clinical content).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c3e91d5b20"
down_revision: Union[str, Sequence[str], None] = "f3d8b1a6c240"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISSIONS = (
    ("health_record:read_own", "View allergies, diagnoses and medications in one's own patient record"),
    ("health_record:report_own", "Report one's own allergies and medications"),
    ("health_record:read_assigned", "View allergies, diagnoses and medications of patients one has an appointment with"),
    ("health_record:write_assigned", "Record allergies, diagnoses and medications for patients one has an appointment with"),
)

ROLE_PERMISSIONS = {
    "patient": ["health_record:read_own", "health_record:report_own"],
    "doctor": ["health_record:read_assigned", "health_record:write_assigned"],
}

TABLES = ("patient_allergies", "patient_diagnoses", "patient_medications")


def _common(table: str) -> list:
    return [
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("recorded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f(f"fk_{table}_patient_id_patients"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_user_id"], ["users.id"],
            name=op.f(f"fk_{table}_recorded_by_user_id_users"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["removed_by_user_id"], ["users.id"],
            name=op.f(f"fk_{table}_removed_by_user_id_users"), ondelete="RESTRICT",
        ),
    ]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "patient_allergies",
        *_common("patient_allergies"),
        sa.Column("substance", sa.String(length=120), nullable=False),
        sa.Column("reaction", sa.String(length=200), nullable=True),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.CheckConstraint("source IN ('patient', 'clinician')", name=op.f("ck_patient_allergies_source_known")),
        sa.CheckConstraint(
            "severity IN ('mild', 'moderate', 'severe', 'unknown')", name=op.f("ck_patient_allergies_severity_known")
        ),
    )
    op.create_index("ix_patient_allergies_patient_id", "patient_allergies", ["patient_id"])
    op.create_index(
        "uq_patient_allergies_current_substance", "patient_allergies", ["patient_id", sa.text("lower(substance)")],
        unique=True, postgresql_where=sa.text("removed_at IS NULL"),
    )

    op.create_table(
        "patient_diagnoses",
        *_common("patient_diagnoses"),
        sa.Column("condition", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("diagnosed_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.CheckConstraint("source = 'clinician'", name=op.f("ck_patient_diagnoses_source_clinician")),
        sa.CheckConstraint("status IN ('active', 'resolved')", name=op.f("ck_patient_diagnoses_status_known")),
    )
    op.create_index("ix_patient_diagnoses_patient_id", "patient_diagnoses", ["patient_id"])

    op.create_table(
        "patient_medications",
        *_common("patient_medications"),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("dosage", sa.String(length=100), nullable=True),
        sa.Column("frequency", sa.String(length=100), nullable=True),
        sa.Column("instructions", sa.String(length=500), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.CheckConstraint("source IN ('patient', 'clinician')", name=op.f("ck_patient_medications_source_known")),
        sa.CheckConstraint("status IN ('active', 'stopped')", name=op.f("ck_patient_medications_status_known")),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name=op.f("ck_patient_medications_dates_ordered"),
        ),
    )
    op.create_index("ix_patient_medications_patient_id", "patient_medications", ["patient_id"])

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
    op.drop_index("uq_patient_allergies_current_substance", table_name="patient_allergies")
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_patient_id", table_name=table)
        op.drop_table(table)
