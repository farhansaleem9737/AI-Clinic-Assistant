"""Receptionists assigned by individual doctors, with per-doctor permissions (D131)

Revision ID: a3f7c9e1d264
Revises: e7c3a91d5f20
Create Date: 2026-11-13

Additive and safe on a live database:
- role `doctor_receptionist` (no patient or appointment permission of its own;
  those come only from an active assignment, checked per request);
- permission `receptionist:manage_own`, granted to the `doctor` role;
- tables doctor_receptionists and receptionist_invitations.
The existing clinic-wide `receptionist` role, and every existing row, are untouched.

Rollback: `alembic downgrade e7c3a91d5f20` drops the tables, the permission and
the role. It refuses while any user still holds the role (remove it first).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3f7c9e1d264"
down_revision: Union[str, Sequence[str], None] = "e7c3a91d5f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = (
    "doctor_receptionist",
    "Doctor's receptionist",
    "Works for the doctors who invited them, with the permissions each of those doctors grants.",
)
PERMISSIONS = (("receptionist:manage_own", "Invite, scope, suspend and remove one's own receptionists"),)
ROLE_PERMISSIONS = {
    "doctor": ["receptionist:manage_own"],
    # Enough to see doctors and free times when booking for an assigned doctor.
    "doctor_receptionist": ["doctor:read", "availability:read", "schedule:read"],
}


def _uuid_pk() -> sa.Column:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "doctor_receptionists",
        _uuid_pk(),
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("receptionist_user_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("permissions", postgresql.ARRAY(sa.String(length=30)), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'suspended', 'revoked')", name=op.f("ck_doctor_receptionists_status_known")),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"], name=op.f("fk_doctor_receptionists_doctor_id_doctors"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["receptionist_user_id"], ["users.id"], name=op.f("fk_doctor_receptionists_receptionist_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"], ["users.id"], name=op.f("fk_doctor_receptionists_assigned_by_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctor_receptionists")),
        sa.UniqueConstraint("doctor_id", "receptionist_user_id", name=op.f("uq_doctor_receptionists_doctor_receptionist")),
    )
    op.create_index(op.f("ix_doctor_receptionists_doctor_id"), "doctor_receptionists", ["doctor_id"])
    op.create_index(op.f("ix_doctor_receptionists_receptionist_user_id"), "doctor_receptionists", ["receptionist_user_id"])

    op.create_table(
        "receptionist_invitations",
        _uuid_pk(),
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("permissions", postgresql.ARRAY(sa.String(length=30)), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_user_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_status", sa.String(length=20), nullable=True),
        sa.CheckConstraint(
            "NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)", name=op.f("ck_receptionist_invitations_single_outcome")
        ),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"], name=op.f("fk_receptionist_invitations_doctor_id_doctors"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"], ["users.id"], name=op.f("fk_receptionist_invitations_invited_by_user_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["accepted_user_id"], ["users.id"], name=op.f("fk_receptionist_invitations_accepted_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receptionist_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_receptionist_invitations_token_hash")),
    )
    op.create_index(op.f("ix_receptionist_invitations_doctor_id"), "receptionist_invitations", ["doctor_id"])
    op.create_index(
        "uq_receptionist_invitations_open", "receptionist_invitations", ["doctor_id", "email"], unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
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
    conn = op.get_bind()
    holders = conn.execute(
        sa.text("SELECT count(*) FROM user_roles ur JOIN roles r ON r.id = ur.role_id WHERE r.code = :code"),
        {"code": ROLE[0]},
    ).scalar()
    if holders:
        raise RuntimeError(f"{holders} user(s) still hold the {ROLE[0]} role: remove it before downgrading.")
    op.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:codes)").bindparams(codes=[c for c, _ in PERMISSIONS]))
    op.execute(sa.text("DELETE FROM roles WHERE code = :code").bindparams(code=ROLE[0]))
    op.drop_index("uq_receptionist_invitations_open", table_name="receptionist_invitations")
    op.drop_index(op.f("ix_receptionist_invitations_doctor_id"), table_name="receptionist_invitations")
    op.drop_table("receptionist_invitations")
    op.drop_index(op.f("ix_doctor_receptionists_receptionist_user_id"), table_name="doctor_receptionists")
    op.drop_index(op.f("ix_doctor_receptionists_doctor_id"), table_name="doctor_receptionists")
    op.drop_table("doctor_receptionists")
