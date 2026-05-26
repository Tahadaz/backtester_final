"""add stat arb pair signal tables

Revision ID: a0b1c2d3e4f7
Revises: c2d3e4f5a6b7
Create Date: 2026-05-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "a0b1c2d3e4f7"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stat_arb_pair_signal",
        sa.Column("pair_id", sa.String(32), nullable=False),
        sa.Column("symbol_y", sa.String(), nullable=False),
        sa.Column("symbol_x", sa.String(), nullable=False),
        sa.Column("horizon", sa.String(16), nullable=False),
        sa.Column("archetype", sa.String(32), nullable=False),
        sa.Column("lag_bars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("action_type", sa.String(32), nullable=False, server_default="none"),
        sa.Column("current_signal", sa.String(32), nullable=False, server_default="none"),
        sa.Column("direction", sa.String(32), nullable=False, server_default="none"),
        sa.Column("validation_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("n_obs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_folds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hedge_ratio", sa.Float(), nullable=True),
        sa.Column("intercept", sa.Float(), nullable=True),
        sa.Column("zscore", sa.Float(), nullable=True),
        sa.Column("half_life", sa.Float(), nullable=True),
        sa.Column("adf_pvalue", sa.Float(), nullable=True),
        sa.Column("raw_pvalue", sa.Float(), nullable=True),
        sa.Column("fdr_qvalue", sa.Float(), nullable=True),
        sa.Column("oos_sharpe", sa.Float(), nullable=True),
        sa.Column("oos_return", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("profitable_fold_ratio", sa.Float(), nullable=True),
        sa.Column("data_as_of", sa.Date(), nullable=True),
        sa.Column("cost_bps_per_side", sa.Float(), nullable=False, server_default="33.0"),
        sa.Column("slippage_bps_per_side", sa.Float(), nullable=False, server_default="5.0"),
        sa.Column("borrow_bps_annual", sa.Float(), nullable=False, server_default="300.0"),
        sa.Column(
            "metrics_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "chart_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "warnings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("pair_id"),
    )
    op.create_index("ix_stat_arb_pair_horizon_status", "stat_arb_pair_signal", ["horizon", "status"])
    op.create_index("ix_stat_arb_pair_symbols", "stat_arb_pair_signal", ["symbol_y", "symbol_x"])
    op.create_index("ix_stat_arb_pair_archetype", "stat_arb_pair_signal", ["archetype"])

    op.create_table(
        "stat_arb_batch_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("horizon", sa.String(16), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("rq_job_id", sa.String(), nullable=True),
        sa.Column("total_pairs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_pairs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_pairs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stat_arb_job_horizon_status", "stat_arb_batch_job", ["horizon", "status"])
    op.create_index("ix_stat_arb_job_created_at", "stat_arb_batch_job", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_stat_arb_job_created_at", table_name="stat_arb_batch_job")
    op.drop_index("ix_stat_arb_job_horizon_status", table_name="stat_arb_batch_job")
    op.drop_table("stat_arb_batch_job")
    op.drop_index("ix_stat_arb_pair_archetype", table_name="stat_arb_pair_signal")
    op.drop_index("ix_stat_arb_pair_symbols", table_name="stat_arb_pair_signal")
    op.drop_index("ix_stat_arb_pair_horizon_status", table_name="stat_arb_pair_signal")
    op.drop_table("stat_arb_pair_signal")
