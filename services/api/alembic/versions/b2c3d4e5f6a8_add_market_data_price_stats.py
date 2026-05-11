"""add market data price stats

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-05-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "b2c3d4e5f6a8"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("market_data_store", sa.Column("close_last", sa.Float(), nullable=True))
    op.add_column("market_data_store", sa.Column("prev_close", sa.Float(), nullable=True))
    op.add_column("market_data_store", sa.Column("adv_20d", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("market_data_store", "adv_20d")
    op.drop_column("market_data_store", "prev_close")
    op.drop_column("market_data_store", "close_last")
