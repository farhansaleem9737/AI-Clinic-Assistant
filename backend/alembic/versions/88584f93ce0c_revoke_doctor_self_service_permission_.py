"""revoke doctor self-service permission from admin

Revision ID: 88584f93ce0c
Revises: b295d309a7bd
Create Date: 2026-09-30

Revision 0c482adf0579 granted the admin role every permission that existed at
the time, including ``doctor:update_own``. That permission means "edit my own
doctor profile": an administrator has no doctor profile, and already edits any
doctor through ``doctor:update``. Holding it only made the UI offer admins a
"My Profile" page that cannot exist for them.

Later migrations already follow the rule that ``*_own`` permissions belong to
the patient and doctor roles only; this brings the first seed in line.
"""
from typing import Sequence, Union

from alembic import op


revision: str = '88584f93ce0c'
down_revision: Union[str, Sequence[str], None] = 'b295d309a7bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE role_id = (SELECT id FROM roles WHERE code = 'admin')
          AND permission_id = (SELECT id FROM permissions WHERE code = 'doctor:update_own')
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.code = 'admin' AND p.code = 'doctor:update_own'
        ON CONFLICT DO NOTHING
        """
    )
