"""add bourse live quote history

Revision ID: f0a1b2c3d4e5
Revises: ee5ff6aa7bb8, a0b1c2d3e4f6
Create Date: 2026-05-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "f0a1b2c3d4e5"
down_revision = ("ee5ff6aa7bb8", "a0b1c2d3e4f6")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bourse_live_quote_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quote_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_price", sa.Float(), nullable=True),
        sa.Column("last_price", sa.Float(), nullable=True),
        sa.Column("high_price", sa.Float(), nullable=True),
        sa.Column("low_price", sa.Float(), nullable=True),
        sa.Column("prev_close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("source_provider", sa.String(), nullable=False, server_default="casablanca_bourse_live"),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bourse_live_quote_history_symbol_observed_at",
        "bourse_live_quote_history",
        ["symbol", "observed_at"],
    )
    op.create_index(
        "ix_bourse_live_quote_history_session_symbol",
        "bourse_live_quote_history",
        ["session_date", "symbol"],
    )
    op.create_index(
        "ix_bourse_live_quote_history_observed_at",
        "bourse_live_quote_history",
        ["observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_bourse_live_quote_history_observed_at", table_name="bourse_live_quote_history")
    op.drop_index("ix_bourse_live_quote_history_session_symbol", table_name="bourse_live_quote_history")
    op.drop_index("ix_bourse_live_quote_history_symbol_observed_at", table_name="bourse_live_quote_history")
    op.drop_table("bourse_live_quote_history")
