"""add desk portfolio state

Revision ID: c3d4e5f6a9b0
Revises: b2c3d4e5f6a8
Create Date: 2026-05-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "c3d4e5f6a9b0"
down_revision = "b2c3d4e5f6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "desk_portfolio_position",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False, server_default=sa.text("'long'")),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("average_price_mad", sa.Float(), nullable=True),
        sa.Column("opened_at", sa.Date(), nullable=True),
        sa.Column("planned_holding_bars", sa.Integer(), nullable=True),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("target_1", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "side", name="uq_desk_portfolio_position_symbol_side"),
    )
    op.create_index("ix_desk_portfolio_position_status", "desk_portfolio_position", ["status"])
    op.create_index("ix_desk_portfolio_position_symbol", "desk_portfolio_position", ["symbol"])

    op.create_table(
        "desk_portfolio_fill",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("price_mad", sa.Float(), nullable=False),
        sa.Column("fees_mad", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_desk_portfolio_fill_timestamp", "desk_portfolio_fill", ["timestamp"])
    op.create_index("ix_desk_portfolio_fill_symbol_timestamp", "desk_portfolio_fill", ["symbol", "timestamp"])


def downgrade() -> None:
    op.drop_index("ix_desk_portfolio_fill_symbol_timestamp", table_name="desk_portfolio_fill")
    op.drop_index("ix_desk_portfolio_fill_timestamp", table_name="desk_portfolio_fill")
    op.drop_table("desk_portfolio_fill")
    op.drop_index("ix_desk_portfolio_position_symbol", table_name="desk_portfolio_position")
    op.drop_index("ix_desk_portfolio_position_status", table_name="desk_portfolio_position")
    op.drop_table("desk_portfolio_position")
