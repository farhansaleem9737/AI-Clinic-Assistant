"""Keep each document's extraction, so it is parsed once (D130)

Revision ID: e7c3a91d5f20
Revises: d4a7e2c19b58
Create Date: 2026-11-13

Additive and safe on a live database: one new, empty table. Nothing existing
is changed. `document_extractions` holds the server's reading of a stored
file (status and findings as JSON), one row per file and extractor version;
rows go with their file (ON DELETE CASCADE).

Rollback: `alembic downgrade d4a7e2c19b58` drops the table. Nothing is lost:
documents are simply read again when next asked about.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7c3a91d5f20"
down_revision: Union[str, Sequence[str], None] = "d4a7e2c19b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_extractions",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id"], ["stored_files.id"], name=op.f("fk_document_extractions_file_id_stored_files"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_extractions")),
        sa.UniqueConstraint("file_id", "version", name=op.f("uq_document_extractions_file_id")),
    )


def downgrade() -> None:
    op.drop_table("document_extractions")
