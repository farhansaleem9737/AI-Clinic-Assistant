"""admin invitations and audit log

Revision ID: d2e7b4c9a118
Revises: c5f1a8e2d364
Create Date: 2026-10-28

Administrator invitations (token stored only as a SHA-256 hash, single use,
expiring) and an append-only audit log for sensitive actions (D87). Seeds
``admin_invitation:manage`` for the admin role. Additive only: no existing
table or row is changed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd2e7b4c9a118'
down_revision: Union[str, Sequence[str], None] = 'c5f1a8e2d364'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSION = ("admin_invitation:manage", "Invite administrators and manage pending invitations")


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], ["users.id"], name=op.f(f"fk_{table}_{column}_users"), ondelete="SET NULL")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "admin_invitations",
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("role_code", sa.String(length=50), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_user_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("delivery_status", sa.String(length=20), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.CheckConstraint("role_code = 'admin'", name=op.f("ck_admin_invitations_admin_role_only")),
        sa.CheckConstraint(
            "NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)", name=op.f("ck_admin_invitations_single_outcome")
        ),
        _user_fk("admin_invitations", "invited_by_user_id"),
        _user_fk("admin_invitations", "accepted_user_id"),
        _user_fk("admin_invitations", "revoked_by_user_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_admin_invitations_token_hash")),
    )
    op.create_index("ix_admin_invitations_email", "admin_invitations", ["email"])

    op.create_table(
        "audit_logs",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        _user_fk("audit_logs", "actor_user_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_target", "audit_logs", ["target_type", "target_id"])

    conn = op.get_bind()
    conn.execute(
        sa.text("INSERT INTO permissions (code, description) VALUES (:code, :description)"),
        {"code": PERMISSION[0], "description": PERMISSION[1]},
    )
    conn.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r, permissions p WHERE r.code = 'admin' AND p.code = :p"
        ),
        {"p": PERMISSION[0]},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(sa.text("DELETE FROM permissions WHERE code = :code").bindparams(code=PERMISSION[0]))
    op.drop_index("ix_audit_logs_target", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_admin_invitations_email", table_name="admin_invitations")
    op.drop_table("admin_invitations")
