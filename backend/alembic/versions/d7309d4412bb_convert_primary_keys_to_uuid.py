"""convert primary keys to uuid

Revision ID: d7309d4412bb
Revises: 828cba23d723
Create Date: 2026-09-29

Replaces the integer primary keys of users, departments, doctors and
refresh_tokens with UUIDv7 (architecture D1/D6), preserving every existing row
and every relationship.

Method, per table: add a ``new_id uuid`` column filled by ``uuidv7()``
(PostgreSQL 18), add ``new_<fk>`` columns and fill them by joining on the old
integer keys, then drop the old constraints and columns and rename the new ones
into place. Constraint names follow the naming convention, which revision
828cba23d723 guarantees on both fresh and existing databases.

Downgrade performs the reverse mapping with fresh integer keys. Integer values
are renumbered, so ids handed out earlier (URLs, logs) will not round-trip.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd7309d4412bb'
down_revision: Union[str, Sequence[str], None] = '828cba23d723'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    for table in ("users", "departments", "doctors", "refresh_tokens"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN new_id uuid NOT NULL DEFAULT uuidv7()")

    op.execute("ALTER TABLE doctors ADD COLUMN new_user_id uuid, ADD COLUMN new_department_id uuid")
    op.execute("UPDATE doctors d SET new_user_id = u.new_id FROM users u WHERE d.user_id = u.id")
    op.execute("UPDATE doctors d SET new_department_id = x.new_id FROM departments x WHERE d.department_id = x.id")
    op.execute("ALTER TABLE refresh_tokens ADD COLUMN new_user_id uuid")
    op.execute("UPDATE refresh_tokens t SET new_user_id = u.new_id FROM users u WHERE t.user_id = u.id")

    # Children first: foreign keys must go before the primary keys they reference.
    op.execute(
        "ALTER TABLE doctors "
        "DROP CONSTRAINT fk_doctors_user_id_users, "
        "DROP CONSTRAINT fk_doctors_department_id_departments, "
        "DROP CONSTRAINT uq_doctors_user_id, "
        "DROP CONSTRAINT pk_doctors"
    )
    op.execute(
        "ALTER TABLE refresh_tokens "
        "DROP CONSTRAINT fk_refresh_tokens_user_id_users, "
        "DROP CONSTRAINT pk_refresh_tokens"
    )
    op.execute("ALTER TABLE users DROP CONSTRAINT pk_users")
    op.execute("ALTER TABLE departments DROP CONSTRAINT pk_departments")

    op.execute("ALTER TABLE doctors DROP COLUMN id, DROP COLUMN user_id, DROP COLUMN department_id")
    op.execute("ALTER TABLE refresh_tokens DROP COLUMN id, DROP COLUMN user_id")
    op.execute("ALTER TABLE users DROP COLUMN id")
    op.execute("ALTER TABLE departments DROP COLUMN id")

    for table in ("users", "departments", "doctors", "refresh_tokens"):
        op.execute(f"ALTER TABLE {table} RENAME COLUMN new_id TO id")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT pk_{table} PRIMARY KEY (id)")
    op.execute("ALTER TABLE doctors RENAME COLUMN new_user_id TO user_id")
    op.execute("ALTER TABLE doctors RENAME COLUMN new_department_id TO department_id")
    op.execute("ALTER TABLE refresh_tokens RENAME COLUMN new_user_id TO user_id")

    op.execute("ALTER TABLE doctors ALTER COLUMN user_id SET NOT NULL, ALTER COLUMN department_id SET NOT NULL")
    op.execute("ALTER TABLE refresh_tokens ALTER COLUMN user_id SET NOT NULL")

    op.execute(
        "ALTER TABLE doctors "
        "ADD CONSTRAINT uq_doctors_user_id UNIQUE (user_id), "
        "ADD CONSTRAINT fk_doctors_user_id_users FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE, "
        "ADD CONSTRAINT fk_doctors_department_id_departments "
        "FOREIGN KEY (department_id) REFERENCES departments (id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE refresh_tokens ADD CONSTRAINT fk_refresh_tokens_user_id_users "
        "FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE"
    )


def downgrade() -> None:
    """Downgrade schema."""
    for table in ("users", "departments", "doctors", "refresh_tokens"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN old_id serial NOT NULL")

    op.execute("ALTER TABLE doctors ADD COLUMN old_user_id integer, ADD COLUMN old_department_id integer")
    op.execute("UPDATE doctors d SET old_user_id = u.old_id FROM users u WHERE d.user_id = u.id")
    op.execute("UPDATE doctors d SET old_department_id = x.old_id FROM departments x WHERE d.department_id = x.id")
    op.execute("ALTER TABLE refresh_tokens ADD COLUMN old_user_id integer")
    op.execute("UPDATE refresh_tokens t SET old_user_id = u.old_id FROM users u WHERE t.user_id = u.id")

    op.execute(
        "ALTER TABLE doctors "
        "DROP CONSTRAINT fk_doctors_user_id_users, "
        "DROP CONSTRAINT fk_doctors_department_id_departments, "
        "DROP CONSTRAINT uq_doctors_user_id, "
        "DROP CONSTRAINT pk_doctors"
    )
    op.execute(
        "ALTER TABLE refresh_tokens "
        "DROP CONSTRAINT fk_refresh_tokens_user_id_users, "
        "DROP CONSTRAINT pk_refresh_tokens"
    )
    op.execute("ALTER TABLE users DROP CONSTRAINT pk_users")
    op.execute("ALTER TABLE departments DROP CONSTRAINT pk_departments")

    op.execute("ALTER TABLE doctors DROP COLUMN id, DROP COLUMN user_id, DROP COLUMN department_id")
    op.execute("ALTER TABLE refresh_tokens DROP COLUMN id, DROP COLUMN user_id")
    op.execute("ALTER TABLE users DROP COLUMN id")
    op.execute("ALTER TABLE departments DROP COLUMN id")

    for table in ("users", "departments", "doctors", "refresh_tokens"):
        op.execute(f"ALTER TABLE {table} RENAME COLUMN old_id TO id")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT pk_{table} PRIMARY KEY (id)")
    op.execute("ALTER TABLE doctors RENAME COLUMN old_user_id TO user_id")
    op.execute("ALTER TABLE doctors RENAME COLUMN old_department_id TO department_id")
    op.execute("ALTER TABLE refresh_tokens RENAME COLUMN old_user_id TO user_id")

    op.execute("ALTER TABLE doctors ALTER COLUMN user_id SET NOT NULL, ALTER COLUMN department_id SET NOT NULL")
    op.execute("ALTER TABLE refresh_tokens ALTER COLUMN user_id SET NOT NULL")

    op.execute(
        "ALTER TABLE doctors "
        "ADD CONSTRAINT uq_doctors_user_id UNIQUE (user_id), "
        "ADD CONSTRAINT fk_doctors_user_id_users FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE, "
        "ADD CONSTRAINT fk_doctors_department_id_departments "
        "FOREIGN KEY (department_id) REFERENCES departments (id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE refresh_tokens ADD CONSTRAINT fk_refresh_tokens_user_id_users "
        "FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE"
    )
