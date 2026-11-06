"""medical catalog: specializations, topics and their links (D118)

Revision ID: d5e9a3c7b418
Revises: c8d1f4a7e352
Create Date: 2026-11-06

Schema only, additive, safe on a live database:
- departments.slug (nullable, unique) and departments.aliases (JSONB, default []);
- specializations, department_specializations, doctor_specializations,
  medical_topics, medical_topic_specializations.

No rows are written or changed here. The catalog itself (24 departments, their
specializations, conditions and symptoms) is loaded by the idempotent seed:
    python -m scripts.seed_catalog
which never deletes, renames or merges an existing department or doctor.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5e9a3c7b418"
down_revision: Union[str, Sequence[str], None] = "c8d1f4a7e352"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON_LIST = dict(server_default=sa.text("'[]'::jsonb"), nullable=False)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.add_column("departments", sa.Column("slug", sa.String(120), nullable=True))
    op.add_column("departments", sa.Column("aliases", postgresql.JSONB(), **_JSON_LIST))
    op.create_unique_constraint(op.f("uq_departments_slug"), "departments", ["slug"])

    op.create_table(
        "specializations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("aliases", postgresql.JSONB(), **_JSON_LIST),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_specializations")),
        sa.UniqueConstraint("name", name=op.f("uq_specializations_name")),
        sa.UniqueConstraint("slug", name=op.f("uq_specializations_slug")),
    )
    op.create_table(
        "department_specializations",
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("specialization_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], name=op.f("fk_department_specializations_department_id_departments"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["specialization_id"], ["specializations.id"], name=op.f("fk_department_specializations_specialization_id_specializations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("department_id", "specialization_id", name=op.f("pk_department_specializations")),
    )
    op.create_index("ix_department_specializations_specialization_id", "department_specializations", ["specialization_id"])
    op.create_table(
        "doctor_specializations",
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("specialization_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"], name=op.f("fk_doctor_specializations_doctor_id_doctors"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["specialization_id"], ["specializations.id"], name=op.f("fk_doctor_specializations_specialization_id_specializations"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("doctor_id", "specialization_id", name=op.f("pk_doctor_specializations")),
    )
    op.create_index("ix_doctor_specializations_specialization_id", "doctor_specializations", ["specialization_id"])
    op.create_table(
        "medical_topics",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("canonical_name", sa.String(150), nullable=False),
        sa.Column("slug", sa.String(150), nullable=False),
        sa.Column("topic_type", sa.String(20), nullable=False),
        sa.Column("aliases", postgresql.JSONB(), **_JSON_LIST),
        sa.Column("urgent", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("topic_type IN ('disease', 'condition', 'symptom')", name=op.f("ck_medical_topics_topic_type_known")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_medical_topics")),
        sa.UniqueConstraint("canonical_name", name=op.f("uq_medical_topics_canonical_name")),
        sa.UniqueConstraint("slug", name=op.f("uq_medical_topics_slug")),
    )
    op.create_table(
        "medical_topic_specializations",
        sa.Column("topic_id", sa.Uuid(), nullable=False),
        sa.Column("specialization_id", sa.Uuid(), nullable=False),
        sa.Column("relevance", sa.String(10), nullable=False),
        sa.Column("review_status", sa.String(10), server_default="curated", nullable=False),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("relevance IN ('primary', 'secondary')", name=op.f("ck_medical_topic_specializations_relevance_known")),
        sa.CheckConstraint("review_status IN ('curated', 'reviewed')", name=op.f("ck_medical_topic_specializations_review_status_known")),
        sa.ForeignKeyConstraint(["topic_id"], ["medical_topics.id"], name=op.f("fk_medical_topic_specializations_topic_id_medical_topics"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["specialization_id"], ["specializations.id"], name=op.f("fk_medical_topic_specializations_specialization_id_specializations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], name=op.f("fk_medical_topic_specializations_reviewed_by_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("topic_id", "specialization_id", name=op.f("pk_medical_topic_specializations")),
    )
    op.create_index("ix_medical_topic_specializations_specialization_id", "medical_topic_specializations", ["specialization_id"])


def downgrade() -> None:
    op.drop_index("ix_medical_topic_specializations_specialization_id", table_name="medical_topic_specializations")
    op.drop_table("medical_topic_specializations")
    op.drop_table("medical_topics")
    op.drop_index("ix_doctor_specializations_specialization_id", table_name="doctor_specializations")
    op.drop_table("doctor_specializations")
    op.drop_index("ix_department_specializations_specialization_id", table_name="department_specializations")
    op.drop_table("department_specializations")
    op.drop_table("specializations")
    op.drop_constraint(op.f("uq_departments_slug"), "departments", type_="unique")
    op.drop_column("departments", "aliases")
    op.drop_column("departments", "slug")
