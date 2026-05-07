"""add direct factor selection metrics

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-05-07 10:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s9t0u1v2w3x4"
down_revision: Union[str, None] = "r8s9t0u1v2w3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stock_factor_relevance", sa.Column("spearman_ic", sa.Float(), nullable=True))
    op.add_column("stock_factor_relevance", sa.Column("pearson_corr", sa.Float(), nullable=True))
    op.add_column("stock_factor_relevance", sa.Column("n_obs", sa.Integer(), nullable=True))
    op.add_column("stock_factor_relevance", sa.Column("selected_reason", sa.String(length=32), nullable=True))
    op.execute("UPDATE stock_factor_relevance SET spearman_ic = ic WHERE spearman_ic IS NULL")
    op.execute("UPDATE stock_factor_relevance SET n_obs = history_n_days WHERE n_obs IS NULL")

    op.add_column("stock_factor_stage1_cache", sa.Column("spearman_ic", sa.Float(), nullable=True))
    op.add_column("stock_factor_stage1_cache", sa.Column("pearson_corr", sa.Float(), nullable=True))
    op.add_column("stock_factor_stage1_cache", sa.Column("relevance_score", sa.Float(), nullable=True))
    op.add_column("stock_factor_stage1_cache", sa.Column("n_obs", sa.Integer(), nullable=True))
    op.add_column("stock_factor_stage1_cache", sa.Column("selected_reason", sa.String(length=32), nullable=True))
    op.execute("UPDATE stock_factor_stage1_cache SET spearman_ic = ic_mean WHERE spearman_ic IS NULL")
    op.execute("UPDATE stock_factor_stage1_cache SET n_obs = history_n_days WHERE n_obs IS NULL")


def downgrade() -> None:
    op.drop_column("stock_factor_stage1_cache", "selected_reason")
    op.drop_column("stock_factor_stage1_cache", "n_obs")
    op.drop_column("stock_factor_stage1_cache", "relevance_score")
    op.drop_column("stock_factor_stage1_cache", "pearson_corr")
    op.drop_column("stock_factor_stage1_cache", "spearman_ic")

    op.drop_column("stock_factor_relevance", "selected_reason")
    op.drop_column("stock_factor_relevance", "n_obs")
    op.drop_column("stock_factor_relevance", "pearson_corr")
    op.drop_column("stock_factor_relevance", "spearman_ic")
