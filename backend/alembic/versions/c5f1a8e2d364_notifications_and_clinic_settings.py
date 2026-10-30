"""notifications and clinic settings

Revision ID: c5f1a8e2d364
Revises: b8e4c2a9d715
Create Date: 2026-10-27

In-app notifications for users (created by real events), and the clinic's
own details (name, contact) edited by administrators: one row, id = 1 (D86).
Seeds ``settings:manage`` for the admin role. Additive only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5f1a8e2d364'
down_revision: Union[str, Sequence[str], None] = 'b8e4c2a9d715'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSION = ("settings:manage", "Edit the clinic's details shown in the application")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notifications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("link", sa.String(length=255), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.CheckConstraint(
            "link IS NULL OR (link LIKE '/%' AND link NOT LIKE '//%')", name=op.f("ck_notifications_internal_link")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_notifications_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index("ix_notifications_user_id_created_at", "notifications", ["user_id", "created_at"])

    op.create_table(
        "clinic_settings",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("clinic_name", sa.String(length=120), nullable=True),
        sa.Column("contact_phone", sa.String(length=30), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_clinic_settings_single_row")),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"],
            name=op.f("fk_clinic_settings_updated_by_user_id_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clinic_settings")),
    )

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
    op.drop_table("clinic_settings")
    op.drop_index("ix_notifications_user_id_created_at", table_name="notifications")
    op.drop_table("notifications")
