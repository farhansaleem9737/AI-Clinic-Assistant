"""add roles and permissions

Revision ID: 0c482adf0579
Revises: d7309d4412bb
Create Date: 2026-09-29

Replaces the single ``users.role`` enum column with RBAC tables
(architecture D3/D4): roles, permissions, role_permissions, user_roles.

Seeds the four built-in roles and the permissions the current endpoints need,
then gives every existing user the role their ``users.role`` column held
before dropping that column and the ``user_role`` enum type.

Seed data is written out literally, not imported from application code:
a migration must keep meaning the same thing after the code moves on. Later
feature migrations add their own permissions the same way.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0c482adf0579'
down_revision: Union[str, Sequence[str], None] = 'd7309d4412bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROLES = (
    ("patient", "Patient", "Books and manages their own appointments."),
    ("doctor", "Doctor", "Sees assigned patients and manages own schedule."),
    ("receptionist", "Receptionist", "Front-desk operations: patients, bookings, check-in."),
    ("admin", "Administrator", "Manages users, roles, departments and doctors."),
)

PERMISSIONS = (
    ("user:read", "List and view user accounts"),
    ("user:create", "Create staff user accounts"),
    ("user:update", "Edit user accounts"),
    ("user:deactivate", "Deactivate or reactivate user accounts"),
    ("user:assign_role", "Grant or revoke roles"),
    ("role:read", "View roles and their permissions"),
    ("department:manage", "Create, edit and deactivate departments"),
    ("doctor:read", "View full doctor profiles, including internal fields"),
    ("doctor:create", "Create doctor profiles"),
    ("doctor:update", "Edit any doctor profile"),
    ("doctor:deactivate", "Deactivate or reactivate doctors"),
    ("doctor:update_own", "Edit the permitted fields of one's own doctor profile"),
)

ROLE_PERMISSIONS = {
    "admin": [code for code, _ in PERMISSIONS],
    "receptionist": ["doctor:read"],
    "doctor": ["doctor:update_own"],
    "patient": [],
}


def _uuid_pk() -> sa.Column:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "roles",
        _uuid_pk(),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("code", name=op.f("uq_roles_code")),
    )
    op.create_table(
        "permissions",
        _uuid_pk(),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_permissions")),
        sa.UniqueConstraint("code", name=op.f("uq_permissions_code")),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name=op.f("fk_role_permissions_role_id_roles"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permissions.id"],
            name=op.f("fk_role_permissions_permission_id_permissions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name=op.f("pk_role_permissions")),
    )
    op.create_index(op.f("ix_role_permissions_permission_id"), "role_permissions", ["permission_id"])
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("granted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_roles_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name=op.f("fk_user_roles_role_id_roles"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["users.id"],
            name=op.f("fk_user_roles_granted_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name=op.f("pk_user_roles")),
    )
    op.create_index(op.f("ix_user_roles_role_id"), "user_roles", ["role_id"])

    conn = op.get_bind()
    for code, name, description in ROLES:
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

    # Every existing user keeps exactly the role they had.
    op.execute(
        "INSERT INTO user_roles (user_id, role_id, granted_at) "
        "SELECT u.id, r.id, now() FROM users u JOIN roles r ON r.code = u.role::text"
    )
    op.drop_column("users", "role")
    op.execute("DROP TYPE user_role")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("CREATE TYPE user_role AS ENUM ('patient', 'doctor', 'receptionist', 'admin')")
    op.add_column("users", sa.Column("role", sa.Enum(name="user_role", create_type=False), nullable=True))
    # A user may now hold several roles; the single column keeps the most privileged.
    op.execute(
        """
        UPDATE users u SET role = picked.code::user_role
        FROM (
            SELECT DISTINCT ON (ur.user_id) ur.user_id, r.code
            FROM user_roles ur JOIN roles r ON r.id = ur.role_id
            WHERE r.code IN ('patient', 'doctor', 'receptionist', 'admin')
            ORDER BY ur.user_id,
                     array_position(ARRAY['admin', 'receptionist', 'doctor', 'patient'], r.code)
        ) picked
        WHERE picked.user_id = u.id
        """
    )
    op.execute("UPDATE users SET role = 'patient' WHERE role IS NULL")
    op.alter_column("users", "role", nullable=False)

    op.drop_index(op.f("ix_user_roles_role_id"), table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_index(op.f("ix_role_permissions_permission_id"), table_name="role_permissions")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")
