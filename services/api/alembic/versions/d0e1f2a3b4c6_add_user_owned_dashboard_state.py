"""add user-owned dashboard state

Revision ID: d0e1f2a3b4c6
Revises: c0d1e2f3a4b5
Create Date: 2026-05-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d0e1f2a3b4c6"
down_revision: Union[str, None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("dashboard_custom_index", sa.Column("owner_user_id", sa.String(), nullable=True))
    op.drop_index("uq_dashboard_custom_index_name_ci", table_name="dashboard_custom_index")
    op.create_index(
        "ix_dashboard_custom_index_owner_updated_at",
        "dashboard_custom_index",
        ["owner_user_id", "updated_at"],
    )
    op.create_index(
        "uq_dashboard_custom_index_owner_name_ci",
        "dashboard_custom_index",
        ["owner_user_id", sa.text("lower(name)")],
        unique=True,
    )

    op.add_column("desk_portfolio_position", sa.Column("owner_user_id", sa.String(), nullable=True))
    op.drop_constraint(
        "uq_desk_portfolio_position_symbol_side",
        "desk_portfolio_position",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_desk_portfolio_position_owner_symbol_side",
        "desk_portfolio_position",
        ["owner_user_id", "symbol", "side"],
    )
    op.create_index(
        "ix_desk_portfolio_position_owner_status",
        "desk_portfolio_position",
        ["owner_user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_desk_portfolio_position_owner_status", table_name="desk_portfolio_position")
    op.drop_constraint(
        "uq_desk_portfolio_position_owner_symbol_side",
        "desk_portfolio_position",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_desk_portfolio_position_symbol_side",
        "desk_portfolio_position",
        ["symbol", "side"],
    )
    op.drop_column("desk_portfolio_position", "owner_user_id")

    op.drop_index("uq_dashboard_custom_index_owner_name_ci", table_name="dashboard_custom_index")
    op.drop_index("ix_dashboard_custom_index_owner_updated_at", table_name="dashboard_custom_index")
    op.create_index(
        "uq_dashboard_custom_index_name_ci",
        "dashboard_custom_index",
        [sa.text("lower(name)")],
        unique=True,
    )
    op.drop_column("dashboard_custom_index", "owner_user_id")
