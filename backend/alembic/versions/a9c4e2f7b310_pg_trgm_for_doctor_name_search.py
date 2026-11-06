"""pg_trgm for typo-tolerant doctor name search (D114)

Enables the pg_trgm extension, used by doctor_service.list_doctors only when a
name search finds nothing otherwise (word_similarity on the normalized name).
Additive: no tables or data change. No trigram index yet: the fallback runs
over the few doctors left after the other filters, which a sequential scan
handles; add a GIN index on the normalized name if the directory grows to
thousands of doctors and the query plan shows it.

Revision ID: a9c4e2f7b310
Revises: a7c3e91d5b20
Create Date: 2026-11-06
"""

from alembic import op

revision = "a9c4e2f7b310"
down_revision = "a7c3e91d5b20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
