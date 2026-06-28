"""Add fundamental_consensus_estimate table for forward-estimate consensus layer.

Isolated forward-estimate store (brief 54 §3 Phase 1).  Never commingled with
reported actuals in fundamental_annual_metric or fundamental_period_metric.

Revision ID: f8a9b0c1d2e3
Revises: 356fb5ece35b
Create Date: 2026-06-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f8a9b0c1d2e3"
down_revision = "356fb5ece35b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundamental_consensus_estimate",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("period_type", sa.String(length=20), nullable=False, server_default="annual"),
        sa.Column("metric", sa.String(length=40), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="MAD"),
        sa.Column("raw_label", sa.String(length=80), nullable=True),
        sa.Column("data_source", sa.String(length=16), nullable=False, server_default="bkgr"),
        sa.Column("is_estimate", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("analyst_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("is_estimate = true", name="ck_fundamental_consensus_estimate_is_estimate"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "symbol", "fiscal_year", "metric", "source",
            name="uq_fundamental_consensus_estimate_key",
        ),
    )
    op.create_index(
        "ix_fundamental_consensus_estimate_symbol_year",
        "fundamental_consensus_estimate", ["symbol", "fiscal_year"],
    )
    op.create_index(
        "ix_fundamental_consensus_estimate_symbol_asof",
        "fundamental_consensus_estimate", ["symbol", "as_of_date"],
    )
    op.create_index(
        "ix_fundamental_consensus_estimate_metric_source",
        "fundamental_consensus_estimate", ["metric", "source"],
    )


def downgrade() -> None:
    op.drop_index("ix_fundamental_consensus_estimate_metric_source",
                  table_name="fundamental_consensus_estimate")
    op.drop_index("ix_fundamental_consensus_estimate_symbol_asof",
                  table_name="fundamental_consensus_estimate")
    op.drop_index("ix_fundamental_consensus_estimate_symbol_year",
                  table_name="fundamental_consensus_estimate")
    op.drop_table("fundamental_consensus_estimate")
