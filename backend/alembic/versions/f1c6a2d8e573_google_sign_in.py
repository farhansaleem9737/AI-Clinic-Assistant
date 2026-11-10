"""Google sign-in: linked identities, sign-in flows, optional password (D123)

Revision ID: f1c6a2d8e573
Revises: e3b7c1d9f240
Create Date: 2026-11-10

Additive and safe on a live database:
- new tables oauth_identities and oauth_flows;
- users.password_hash becomes nullable (a Google-only account has no password).
  Existing rows all keep their hash; nothing is rewritten.

Rollback: `alembic downgrade e3b7c1d9f240`. It refuses while any account has no
password (it would break NOT NULL); those users must set a password first.
Linked Google identities are dropped (users can link again).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1c6a2d8e573"
down_revision: Union[str, Sequence[str], None] = "e3b7c1d9f240"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_pk() -> sa.Column:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "oauth_identities",
        _uuid_pk(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_oauth_identities_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_identities")),
        sa.UniqueConstraint("provider", "subject", name=op.f("uq_oauth_identities_provider_subject")),
        sa.UniqueConstraint("user_id", "provider", name=op.f("uq_oauth_identities_one_per_provider")),
    )
    op.create_index(op.f("ix_oauth_identities_user_id"), "oauth_identities", ["user_id"])

    op.create_table(
        "oauth_flows",
        _uuid_pk(),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("purpose", sa.String(length=10), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("binder_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=True),
        sa.Column("nonce", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("remember_me", sa.Boolean(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("given_name", sa.String(length=100), nullable=True),
        sa.Column("family_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('authorize', 'handoff', 'signup')", name=op.f("ck_oauth_flows_kind_known")),
        sa.CheckConstraint("purpose IN ('login', 'register', 'link')", name=op.f("ck_oauth_flows_purpose_known")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_oauth_flows_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_flows")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_oauth_flows_token_hash")),
    )
    op.create_index(op.f("ix_oauth_flows_expires_at"), "oauth_flows", ["expires_at"])

    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    passwordless = op.get_bind().scalar(sa.text("SELECT count(*) FROM users WHERE password_hash IS NULL"))
    if passwordless:
        raise RuntimeError(
            f"{passwordless} account(s) sign in only with Google. They must set a password before this downgrade."
        )
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=False)
    op.drop_index(op.f("ix_oauth_flows_expires_at"), table_name="oauth_flows")
    op.drop_table("oauth_flows")
    op.drop_index(op.f("ix_oauth_identities_user_id"), table_name="oauth_identities")
    op.drop_table("oauth_identities")
