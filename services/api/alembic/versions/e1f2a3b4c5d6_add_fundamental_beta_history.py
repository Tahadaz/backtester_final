"""add fundamental beta history

Revision ID: e1f2a3b4c5d6
Revises: e0f1a2b3c4d5
Create Date: 2026-06-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "e1f2a3b4c5d6"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundamental_beta_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("beta", sa.Float(), nullable=False),
        sa.Column("raw_beta", sa.Float(), nullable=True),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("r2", sa.Float(), nullable=True),
        sa.Column("n_obs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("zero_week_frac", sa.Float(), nullable=True),
        sa.Column("liquidity_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("proxy", sa.String(), nullable=False, server_default="MASI"),
        sa.Column("frequency", sa.String(length=16), nullable=False, server_default="weekly"),
        sa.Column("window_years", sa.Float(), nullable=False, server_default="2"),
        sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("symbol", "as_of", "proxy", "frequency", "window_years", name="uq_fundamental_beta_history_key"),
    )
    op.create_index(
        "ix_fundamental_beta_history_symbol_asof",
        "fundamental_beta_history",
        ["symbol", "as_of"],
    )
    op.create_index(
        "ix_fundamental_beta_history_proxy_asof",
        "fundamental_beta_history",
        ["proxy", "as_of"],
    )


def downgrade() -> None:
    op.drop_index("ix_fundamental_beta_history_proxy_asof", table_name="fundamental_beta_history")
    op.drop_index("ix_fundamental_beta_history_symbol_asof", table_name="fundamental_beta_history")
    op.drop_table("fundamental_beta_history")
