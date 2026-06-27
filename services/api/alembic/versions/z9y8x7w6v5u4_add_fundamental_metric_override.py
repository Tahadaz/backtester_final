"""add fundamental metric override

Revision ID: z9y8x7w6v5u4
Revises: x4y5z6a7b8c9
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "z9y8x7w6v5u4"
down_revision = "x4y5z6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundamental_metric_override",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("statement_year", sa.Integer(), nullable=False),
        sa.Column("metric_name", sa.Text(), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index(
        "uq_fundamental_metric_override_current",
        "fundamental_metric_override",
        ["symbol", "statement_year", "metric_name"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
        sqlite_where=sa.text("is_current = 1"),
    )
    op.create_index(
        "ix_fundamental_metric_override_symbol_created",
        "fundamental_metric_override",
        ["symbol", "created_at"],
    )
    op.create_index(
        "ix_fundamental_metric_override_symbol_year",
        "fundamental_metric_override",
        ["symbol", "statement_year"],
    )


def downgrade() -> None:
    op.drop_index("ix_fundamental_metric_override_symbol_year", table_name="fundamental_metric_override")
    op.drop_index("ix_fundamental_metric_override_symbol_created", table_name="fundamental_metric_override")
    op.drop_index("uq_fundamental_metric_override_current", table_name="fundamental_metric_override")
    op.drop_table("fundamental_metric_override")
