"""apply constraint naming convention to existing databases

Revision ID: 828cba23d723
Revises: fff745854020
Create Date: 2026-09-29 16:47:10.715077

Why this exists
---------------
``Base.metadata`` now carries a naming convention (``app/db/base.py``). Alembic
applies ``target_metadata``'s convention to the operations of *every*
migration it runs, including old ones. So:

* a database built from empty today gets convention names
  (``pk_users``, ``fk_doctors_user_id_users``, ``uq_doctors_user_id`` ...);
* a database that ran those same migrations before the convention existed
  has PostgreSQL's defaults (``users_pkey``, ``doctors_user_id_fkey``,
  ``doctors_user_id_key`` ...).

The two paths must end in the same schema. This revision renames the old
default names to the convention names, and only where the old name is
present, so it is a no-op on a freshly built database.

Downgrade renames them back to the PostgreSQL defaults (again only where the
convention name is present), which is exactly the state existing databases
had at fff745854020.
"""
from typing import Sequence, Union

from alembic import op


revision: str = '828cba23d723'
down_revision: Union[str, Sequence[str], None] = 'fff745854020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, PostgreSQL default name, naming-convention name)
_RENAMES = (
    ("users", "users_pkey", "pk_users"),
    ("refresh_tokens", "refresh_tokens_pkey", "pk_refresh_tokens"),
    ("refresh_tokens", "refresh_tokens_user_id_fkey", "fk_refresh_tokens_user_id_users"),
    ("departments", "departments_pkey", "pk_departments"),
    ("doctors", "doctors_pkey", "pk_doctors"),
    ("doctors", "doctors_user_id_fkey", "fk_doctors_user_id_users"),
    ("doctors", "doctors_department_id_fkey", "fk_doctors_department_id_departments"),
    ("doctors", "doctors_user_id_key", "uq_doctors_user_id"),
)


def _rename_if_present(table: str, old: str, new: str) -> None:
    # Renaming a primary-key or unique constraint also renames its backing index.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = '{table}'::regclass AND conname = '{old}'
            ) THEN
                ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new};
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    """Upgrade schema."""
    for table, default_name, convention_name in _RENAMES:
        _rename_if_present(table, default_name, convention_name)


def downgrade() -> None:
    """Downgrade schema."""
    for table, default_name, convention_name in reversed(_RENAMES):
        _rename_if_present(table, convention_name, default_name)
