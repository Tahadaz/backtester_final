"""add factor selection tables

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-05-05 13:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "q7r8s9t0u1v2"
down_revision: Union[str, None] = "p6q7r8s9t0u1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # stock_factor_relevance
    op.create_table(
        "stock_factor_relevance",
        sa.Column("symbol", sa.String(), primary_key=True, nullable=False),
        sa.Column("factor_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_calibrated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("cusum_drift_score", sa.Float(), nullable=True),
        sa.Column("cusum_alarm", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_stock_factor_relevance_symbol", "stock_factor_relevance", ["symbol"])
    op.create_index("ix_stock_factor_relevance_is_active", "stock_factor_relevance", ["is_active"])

    # stock_factor_stage1_cache
    op.create_table(
        "stock_factor_stage1_cache",
        sa.Column("symbol", sa.String(), primary_key=True, nullable=False),
        sa.Column("factor_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("ic_mean", sa.Float(), nullable=False),
        sa.Column("ic_tstat", sa.Float(), nullable=False),
        sa.Column("passed_fdr", sa.Boolean(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_stage1_cache_symbol", "stock_factor_stage1_cache", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_stage1_cache_symbol", table_name="stock_factor_stage1_cache")
    op.drop_table("stock_factor_stage1_cache")

    op.drop_index("ix_stock_factor_relevance_is_active", table_name="stock_factor_relevance")
    op.drop_index("ix_stock_factor_relevance_symbol", table_name="stock_factor_relevance")
    op.drop_table("stock_factor_relevance")
