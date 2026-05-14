"""add dashboard portfolios

Revision ID: ee5ff6aa7bb8
Revises: dd4ee5ff6aa7
Create Date: 2026-05-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "ee5ff6aa7bb8"
down_revision = "dd4ee5ff6aa7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_portfolio",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("symbols", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("component_shares", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("allocation_method", sa.String(length=24), nullable=False, server_default="share_quantities"),
        sa.Column("side_policy", sa.String(length=20), nullable=False, server_default="long_only"),
        sa.Column("total_capital_mad", sa.Float(), nullable=False, server_default="1000000"),
        sa.Column("cash_buffer_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("stop_loss_pct", sa.Float(), nullable=True),
        sa.Column("take_profit_pct", sa.Float(), nullable=True),
        sa.Column("display_mode", sa.String(length=32), nullable=False, server_default="trade_opportunities"),
        sa.Column("technical_direction_mode", sa.String(length=16), nullable=False, server_default="best"),
        sa.Column("horizon", sa.String(length=20), nullable=False, server_default="monthly"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("replay_start_date", sa.Date(), nullable=True),
        sa.Column("replay_end_date", sa.Date(), nullable=True),
        sa.Column("replay_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_replay_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dashboard_portfolio_owner_updated_at", "dashboard_portfolio", ["owner_user_id", "updated_at"])
    op.create_index(
        "uq_dashboard_portfolio_owner_name_ci",
        "dashboard_portfolio",
        ["owner_user_id", sa.text("lower(name)")],
        unique=True,
    )
    op.create_index("ix_dashboard_portfolio_owner_default", "dashboard_portfolio", ["owner_user_id", "is_default"])

    op.add_column("desk_portfolio_position", sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("desk_portfolio_fill", sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=True))

    op.execute(
        """
        INSERT INTO dashboard_portfolio (
            id, owner_user_id, name, symbols, component_shares, is_default
        )
        SELECT gen_random_uuid(), owner_user_id, 'Default portfolio', '[]'::jsonb, '{}'::jsonb, true
        FROM (
            SELECT DISTINCT owner_user_id FROM desk_portfolio_position
            UNION
            SELECT DISTINCT owner_user_id FROM desk_portfolio_fill
        ) owners
        """
    )
    op.execute(
        """
        UPDATE desk_portfolio_position p
        SET portfolio_id = dp.id
        FROM dashboard_portfolio dp
        WHERE dp.is_default = true
          AND (
            p.owner_user_id = dp.owner_user_id
            OR (p.owner_user_id IS NULL AND dp.owner_user_id IS NULL)
          )
        """
    )
    op.execute(
        """
        UPDATE desk_portfolio_fill f
        SET portfolio_id = dp.id
        FROM dashboard_portfolio dp
        WHERE dp.is_default = true
          AND (
            f.owner_user_id = dp.owner_user_id
            OR (f.owner_user_id IS NULL AND dp.owner_user_id IS NULL)
          )
        """
    )

    op.drop_constraint(
        "uq_desk_portfolio_position_owner_symbol_side",
        "desk_portfolio_position",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_desk_portfolio_position_portfolio_symbol_side",
        "desk_portfolio_position",
        ["portfolio_id", "symbol", "side"],
    )
    op.create_index("ix_desk_portfolio_position_portfolio_status", "desk_portfolio_position", ["portfolio_id", "status"])
    op.create_index("ix_desk_portfolio_fill_portfolio_timestamp", "desk_portfolio_fill", ["portfolio_id", "timestamp"])


def downgrade() -> None:
    op.drop_index("ix_desk_portfolio_fill_portfolio_timestamp", table_name="desk_portfolio_fill")
    op.drop_index("ix_desk_portfolio_position_portfolio_status", table_name="desk_portfolio_position")
    op.drop_constraint(
        "uq_desk_portfolio_position_portfolio_symbol_side",
        "desk_portfolio_position",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_desk_portfolio_position_owner_symbol_side",
        "desk_portfolio_position",
        ["owner_user_id", "symbol", "side"],
    )
    op.drop_column("desk_portfolio_fill", "portfolio_id")
    op.drop_column("desk_portfolio_position", "portfolio_id")
    op.drop_index("ix_dashboard_portfolio_owner_default", table_name="dashboard_portfolio")
    op.drop_index("uq_dashboard_portfolio_owner_name_ci", table_name="dashboard_portfolio")
    op.drop_index("ix_dashboard_portfolio_owner_updated_at", table_name="dashboard_portfolio")
    op.drop_table("dashboard_portfolio")
