"""expand factor selection schema to horizon-aware state

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-05-06 15:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r8s9t0u1v2w3"
down_revision: Union[str, None] = "q7r8s9t0u1v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # stock_factor_relevance
    op.add_column("stock_factor_relevance", sa.Column("horizon", sa.String(), server_default="mid", nullable=False))
    op.add_column("stock_factor_relevance", sa.Column("factor_canonical_id", sa.String(), nullable=True))
    op.add_column("stock_factor_relevance", sa.Column("rank", sa.Integer(), nullable=True))
    op.add_column("stock_factor_relevance", sa.Column("ic", sa.Float(), nullable=True))
    op.add_column("stock_factor_relevance", sa.Column("ic_t_stat", sa.Float(), nullable=True))
    op.add_column("stock_factor_relevance", sa.Column("bh_p_adj", sa.Float(), nullable=True))
    op.add_column("stock_factor_relevance", sa.Column("lasso_coef", sa.Float(), nullable=True))
    op.add_column("stock_factor_relevance", sa.Column("regime_start", sa.Date(), nullable=True))
    op.add_column("stock_factor_relevance", sa.Column("cusum_status", sa.String(), server_default="valid", nullable=False))
    op.add_column("stock_factor_relevance", sa.Column("low_confidence", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("stock_factor_relevance", sa.Column("next_forced_recal", sa.DateTime(timezone=True), nullable=True))
    op.add_column("stock_factor_relevance", sa.Column("history_n_days", sa.Integer(), nullable=True))
    op.execute("UPDATE stock_factor_relevance SET factor_canonical_id = factor_id WHERE factor_canonical_id IS NULL")
    op.execute("UPDATE stock_factor_relevance SET lasso_coef = relevance_score WHERE lasso_coef IS NULL")
    op.execute("UPDATE stock_factor_relevance SET cusum_status = CASE WHEN cusum_alarm THEN 'invalidated' ELSE 'valid' END")
    op.alter_column("stock_factor_relevance", "factor_canonical_id", nullable=False)
    op.drop_index("ix_stock_factor_relevance_is_active", table_name="stock_factor_relevance")
    op.drop_constraint("stock_factor_relevance_pkey", "stock_factor_relevance", type_="primary")
    op.create_primary_key(
        "stock_factor_relevance_pkey",
        "stock_factor_relevance",
        ["symbol", "horizon", "factor_canonical_id"],
    )
    op.create_index(
        "idx_sfr_active",
        "stock_factor_relevance",
        ["symbol", "horizon"],
        unique=False,
        postgresql_where=sa.text("cusum_status = 'valid'"),
    )
    op.alter_column("stock_factor_relevance", "horizon", server_default=None)
    op.alter_column("stock_factor_relevance", "cusum_status", server_default=None)
    op.alter_column("stock_factor_relevance", "low_confidence", server_default=None)

    # stock_factor_stage1_cache
    op.add_column("stock_factor_stage1_cache", sa.Column("horizon", sa.String(), server_default="mid", nullable=False))
    op.add_column("stock_factor_stage1_cache", sa.Column("factor_canonical_id", sa.String(), nullable=True))
    op.add_column("stock_factor_stage1_cache", sa.Column("bh_p_adj", sa.Float(), nullable=True))
    op.add_column("stock_factor_stage1_cache", sa.Column("regime_start", sa.Date(), nullable=True))
    op.add_column("stock_factor_stage1_cache", sa.Column("low_confidence", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("stock_factor_stage1_cache", sa.Column("history_n_days", sa.Integer(), nullable=True))
    op.execute("UPDATE stock_factor_stage1_cache SET factor_canonical_id = factor_id WHERE factor_canonical_id IS NULL")
    op.alter_column("stock_factor_stage1_cache", "factor_canonical_id", nullable=False)
    op.drop_index("ix_stage1_cache_symbol", table_name="stock_factor_stage1_cache")
    op.drop_constraint("stock_factor_stage1_cache_pkey", "stock_factor_stage1_cache", type_="primary")
    op.create_primary_key(
        "stock_factor_stage1_cache_pkey",
        "stock_factor_stage1_cache",
        ["symbol", "horizon", "factor_canonical_id"],
    )
    op.create_index("ix_stage1_cache_symbol_horizon", "stock_factor_stage1_cache", ["symbol", "horizon"])
    op.alter_column("stock_factor_stage1_cache", "horizon", server_default=None)
    op.alter_column("stock_factor_stage1_cache", "low_confidence", server_default=None)

    # Existing Factor x TA persisted outputs were produced with symbol-level
    # factor eligibility. They must be recomputed after horizon-aware selection.
    op.execute("DELETE FROM signal_engine_family_result WHERE variant = 'factor_x_ta'")
    op.execute("DELETE FROM signal_engine_global_result WHERE variant = 'factor_x_ta'")
    op.execute("DELETE FROM wfo_signal_summary WHERE variant = 'factor_x_ta'")
    op.execute("DELETE FROM wfo_global_signal WHERE variant = 'factor_x_ta'")


def downgrade() -> None:
    op.drop_index("ix_stage1_cache_symbol_horizon", table_name="stock_factor_stage1_cache")
    op.drop_constraint("stock_factor_stage1_cache_pkey", "stock_factor_stage1_cache", type_="primary")
    op.create_primary_key("stock_factor_stage1_cache_pkey", "stock_factor_stage1_cache", ["symbol", "factor_id"])
    op.create_index("ix_stage1_cache_symbol", "stock_factor_stage1_cache", ["symbol"])
    op.drop_column("stock_factor_stage1_cache", "history_n_days")
    op.drop_column("stock_factor_stage1_cache", "low_confidence")
    op.drop_column("stock_factor_stage1_cache", "regime_start")
    op.drop_column("stock_factor_stage1_cache", "bh_p_adj")
    op.drop_column("stock_factor_stage1_cache", "factor_canonical_id")
    op.drop_column("stock_factor_stage1_cache", "horizon")

    op.drop_index("idx_sfr_active", table_name="stock_factor_relevance")
    op.drop_constraint("stock_factor_relevance_pkey", "stock_factor_relevance", type_="primary")
    op.create_primary_key("stock_factor_relevance_pkey", "stock_factor_relevance", ["symbol", "factor_id"])
    op.create_index("ix_stock_factor_relevance_is_active", "stock_factor_relevance", ["is_active"])
    op.drop_column("stock_factor_relevance", "history_n_days")
    op.drop_column("stock_factor_relevance", "next_forced_recal")
    op.drop_column("stock_factor_relevance", "low_confidence")
    op.drop_column("stock_factor_relevance", "cusum_status")
    op.drop_column("stock_factor_relevance", "regime_start")
    op.drop_column("stock_factor_relevance", "lasso_coef")
    op.drop_column("stock_factor_relevance", "bh_p_adj")
    op.drop_column("stock_factor_relevance", "ic_t_stat")
    op.drop_column("stock_factor_relevance", "ic")
    op.drop_column("stock_factor_relevance", "rank")
    op.drop_column("stock_factor_relevance", "factor_canonical_id")
    op.drop_column("stock_factor_relevance", "horizon")
