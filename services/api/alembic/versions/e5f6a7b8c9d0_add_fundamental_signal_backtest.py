"""add fundamental signal backtest table

Revision ID: e5f6a7b8c9d0
Revises: e4f5a6b7c8d0
Create Date: 2026-06-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "e5f6a7b8c9d0"
down_revision = "e4f5a6b7c8d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundamental_signal_backtest",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("signal", sa.String(length=32), nullable=False),
        sa.Column("universe", sa.String(length=32), nullable=False),
        sa.Column("rebalance", sa.String(length=16), nullable=False, server_default="M"),
        sa.Column("as_of", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="succeeded"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("quintile_returns_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ic_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("equity_curve_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("turnover_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("holdings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("params_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_fundamental_signal_backtest_created", "fundamental_signal_backtest", ["created_at"])
    op.create_index("ix_fundamental_signal_backtest_signal_universe", "fundamental_signal_backtest", ["signal", "universe"])


def downgrade() -> None:
    op.drop_index("ix_fundamental_signal_backtest_signal_universe", table_name="fundamental_signal_backtest")
    op.drop_index("ix_fundamental_signal_backtest_created", table_name="fundamental_signal_backtest")
    op.drop_table("fundamental_signal_backtest")
