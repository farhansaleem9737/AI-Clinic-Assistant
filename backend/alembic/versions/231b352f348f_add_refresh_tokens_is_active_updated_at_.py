"""add refresh tokens, is_active, updated_at, role enum

Revision ID: 231b352f348f
Revises: 5fe0b8c8ede5
Create Date: 2026-09-04 16:26:31.086566

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '231b352f348f'
down_revision: Union[str, Sequence[str], None] = '5fe0b8c8ede5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('refresh_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=255), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_refresh_tokens_token'), 'refresh_tokens', ['token'], unique=True)

    # Add columns with a server-side default so existing rows get a value
    op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('users', sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))

    # Remove the server default afterward — app code handles defaults going forward
    op.alter_column('users', 'is_active', server_default=None)
    op.alter_column('users', 'updated_at', server_default=None)

    # Create the enum type first, then cast existing text values into it explicitly
    user_role_enum = sa.Enum('patient', 'doctor', 'receptionist', 'admin', name='user_role')
    user_role_enum.create(op.get_bind())
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::user_role")


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('users', 'role',
               existing_type=sa.Enum('patient', 'doctor', 'receptionist', 'admin', name='user_role'),
               type_=sa.VARCHAR(length=50),
               existing_nullable=False)
    op.execute("DROP TYPE user_role")

    op.drop_column('users', 'updated_at')
    op.drop_column('users', 'is_active')

    op.drop_index(op.f('ix_refresh_tokens_token'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')