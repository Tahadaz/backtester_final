"""add live quotes and fill owner

Revision ID: cc3dd4ee5ff6
Revises: bb2cc3dd4ee5
Create Date: 2026-05-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "cc3dd4ee5ff6"
down_revision = "bb2cc3dd4ee5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bourse_live_quote",
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=True),
        sa.Column("quote_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_price", sa.Float(), nullable=True),
        sa.Column("last_price", sa.Float(), nullable=True),
        sa.Column("high_price", sa.Float(), nullable=True),
        sa.Column("low_price", sa.Float(), nullable=True),
        sa.Column("prev_close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("source_provider", sa.String(), nullable=False, server_default="casablanca_bourse_live"),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column(
            "raw_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("symbol"),
    )
    op.create_index("ix_bourse_live_quote_updated_at", "bourse_live_quote", ["updated_at"])
    op.create_index("ix_bourse_live_quote_session_date", "bourse_live_quote", ["session_date"])

    op.add_column("desk_portfolio_fill", sa.Column("owner_user_id", sa.String(), nullable=True))
    op.create_index(
        "ix_desk_portfolio_fill_owner_timestamp",
        "desk_portfolio_fill",
        ["owner_user_id", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_desk_portfolio_fill_owner_timestamp", table_name="desk_portfolio_fill")
    op.drop_column("desk_portfolio_fill", "owner_user_id")
    op.drop_index("ix_bourse_live_quote_session_date", table_name="bourse_live_quote")
    op.drop_index("ix_bourse_live_quote_updated_at", table_name="bourse_live_quote")
    op.drop_table("bourse_live_quote")
