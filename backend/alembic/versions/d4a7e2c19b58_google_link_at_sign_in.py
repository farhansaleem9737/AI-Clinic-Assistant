"""Link Google to an existing account at sign-in, after proving ownership (D128)

Revision ID: d4a7e2c19b58
Revises: c8e1f2a9d374
Create Date: 2026-11-11

Additive and safe on a live database. oauth_flows (short-lived sign-in steps):
- kind may also be 'link': Google confirmed an address that already has an
  account, and the owner must prove they control that account first;
- attempts: wrong passwords or codes at that step;
- code_hash: HMAC-SHA256 of an emailed confirmation code (never the code);
- code_sent_at: when that code was sent (expiry and resend wait).
No user, identity, patient or appointment rows are touched.

Rollback: `alembic downgrade c8e1f2a9d374` deletes pending 'link' steps (people
mid-way start again), then restores the old constraint and drops the columns.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4a7e2c19b58"
down_revision: Union[str, Sequence[str], None] = "c8e1f2a9d374"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("oauth_flows", sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False))
    op.add_column("oauth_flows", sa.Column("code_hash", sa.CHAR(length=64), nullable=True))
    op.add_column("oauth_flows", sa.Column("code_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint(op.f("ck_oauth_flows_kind_known"), "oauth_flows", type_="check")
    op.create_check_constraint(
        op.f("ck_oauth_flows_kind_known"), "oauth_flows", "kind IN ('authorize', 'handoff', 'signup', 'link')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM oauth_flows WHERE kind = 'link'")
    op.drop_constraint(op.f("ck_oauth_flows_kind_known"), "oauth_flows", type_="check")
    op.create_check_constraint(op.f("ck_oauth_flows_kind_known"), "oauth_flows", "kind IN ('authorize', 'handoff', 'signup')")
    op.drop_column("oauth_flows", "code_sent_at")
    op.drop_column("oauth_flows", "code_hash")
    op.drop_column("oauth_flows", "attempts")
