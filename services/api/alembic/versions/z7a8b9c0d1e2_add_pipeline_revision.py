"""add pipeline_revision lineage table (Phase 0)

Revision ID: z7a8b9c0d1e2
Revises: y6z7a8b9c0d1
Create Date: 2026-05-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "z7a8b9c0d1e2"
down_revision = "y6z7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_revision",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column(
            "upstream_rev",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("stage", "content_hash", name="uq_pipeline_revision_stage_content"),
    )
    op.create_index(
        "ix_pipeline_revision_stage_created",
        "pipeline_revision",
        ["stage", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_revision_stage_created", table_name="pipeline_revision")
    op.drop_table("pipeline_revision")
