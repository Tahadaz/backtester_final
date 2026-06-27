"""add period keys to fundamental projection

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "x4y5z6a7b8c9"
down_revision = "w3x4y5z6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fundamental_projection", sa.Column("periods_per_year", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("fundamental_projection", sa.Column("period_type", sa.String(length=20), nullable=False, server_default="annual"))
    op.add_column("fundamental_projection", sa.Column("period_index", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("fundamental_projection", sa.Column("period_label", sa.String(length=20), nullable=False, server_default="FY"))
    op.add_column("fundamental_projection", sa.Column("period_end_date", sa.Date(), nullable=True))
    op.drop_constraint("uq_fundamental_projection_line", "fundamental_projection", type_="unique")
    op.create_unique_constraint(
        "uq_fundamental_projection_line",
        "fundamental_projection",
        ["import_id", "symbol", "scenario", "fiscal_year", "period_type", "period_index", "line_item"],
    )
    op.create_index(
        "ix_fundamental_projection_symbol_period",
        "fundamental_projection",
        ["symbol", "scenario", "period_type", "fiscal_year", "period_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_fundamental_projection_symbol_period", table_name="fundamental_projection")
    op.drop_constraint("uq_fundamental_projection_line", "fundamental_projection", type_="unique")
    op.create_unique_constraint(
        "uq_fundamental_projection_line",
        "fundamental_projection",
        ["import_id", "symbol", "scenario", "fiscal_year", "line_item"],
    )
    op.drop_column("fundamental_projection", "period_end_date")
    op.drop_column("fundamental_projection", "period_label")
    op.drop_column("fundamental_projection", "period_index")
    op.drop_column("fundamental_projection", "period_type")
    op.drop_column("fundamental_projection", "periods_per_year")
