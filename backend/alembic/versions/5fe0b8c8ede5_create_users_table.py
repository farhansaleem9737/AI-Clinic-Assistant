"""create users table

Revision ID: 5fe0b8c8ede5
Revises:
Create Date: 2026-09-01 16:31:22.072288

This revision was originally generated empty (``pass``), because ``alembic
revision --autogenerate`` was run before the model was imported into
``alembic/env.py``. The ``users`` table therefore existed in the development
database without Alembic ever having created it, and a fresh database could not
be bootstrapped: ``alembic upgrade head`` failed in 231b352f348f at
``op.add_column('users', ...)`` because the table did not exist.

The body below creates ``users`` in the shape it had *at this point in history* --
deliberately not its current shape:

* ``role`` is VARCHAR(50); 231b352f348f converts it to the ``user_role`` enum.
* ``created_at`` is naive TIMESTAMP; fadd14706b01 converts it to TIMESTAMPTZ.
* ``is_active`` and ``updated_at`` are absent; 231b352f348f adds them.

Each migration must describe the schema as of its own revision, or replaying the
chain from base produces a different database than upgrading an existing one.

Databases already stamped at or past this revision never execute this code --
Alembic skips applied revisions -- so this repair is a no-op for them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5fe0b8c8ede5'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
