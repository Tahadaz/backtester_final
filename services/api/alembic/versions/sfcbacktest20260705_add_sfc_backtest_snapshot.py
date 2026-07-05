"""add SFC portfolio backtest snapshot table

Revision ID: sfcbacktest20260705
Revises: sfc20260705
Create Date: 2026-07-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "sfcbacktest20260705"
down_revision = "sfc20260705"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundamental_sfc_backtest_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("params_json", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fundamental_sfc_backtest_snapshot_computed",
        "fundamental_sfc_backtest_snapshot",
        ["computed_at"],
    )
    op.create_index(
        "ix_fundamental_sfc_backtest_snapshot_config",
        "fundamental_sfc_backtest_snapshot",
        ["config_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_fundamental_sfc_backtest_snapshot_config", table_name="fundamental_sfc_backtest_snapshot")
    op.drop_index("ix_fundamental_sfc_backtest_snapshot_computed", table_name="fundamental_sfc_backtest_snapshot")
    op.drop_table("fundamental_sfc_backtest_snapshot")
