"""add fundamental cross-section score table

Revision ID: sfc20260705
Revises: f8a9b0c1d2e3
Create Date: 2026-07-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "sfc20260705"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundamental_cross_section_score",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("sfc", sa.Float(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("tercile", sa.String(length=16), nullable=False),
        sa.Column("pillar_val", sa.Float(), nullable=True),
        sa.Column("pillar_qual", sa.Float(), nullable=True),
        sa.Column("pillar_fmom", sa.Float(), nullable=True),
        sa.Column("pillar_pmom", sa.Float(), nullable=True),
        sa.Column("coverage_ratio", sa.Float(), nullable=False, server_default="0"),
        sa.Column("attribution_json", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("methodology_version", sa.String(length=64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "symbol",
            "as_of_date",
            "methodology_version",
            "config_hash",
            name="uq_fundamental_cross_section_score_key",
        ),
    )
    op.create_index(
        "ix_fundamental_cross_section_score_asof_rank",
        "fundamental_cross_section_score",
        ["as_of_date", "rank"],
    )
    op.create_index(
        "ix_fundamental_cross_section_score_symbol_asof",
        "fundamental_cross_section_score",
        ["symbol", "as_of_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_fundamental_cross_section_score_symbol_asof", table_name="fundamental_cross_section_score")
    op.drop_index("ix_fundamental_cross_section_score_asof_rank", table_name="fundamental_cross_section_score")
    op.drop_table("fundamental_cross_section_score")
