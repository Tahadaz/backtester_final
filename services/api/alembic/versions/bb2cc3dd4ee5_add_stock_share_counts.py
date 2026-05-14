"""add stock share counts

Revision ID: bb2cc3dd4ee5
Revises: aa1bb2cc3dd4
Create Date: 2026-05-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "bb2cc3dd4ee5"
down_revision = "aa1bb2cc3dd4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stock_master", sa.Column("shares_outstanding", sa.BigInteger(), nullable=True))
    op.add_column("stock_master", sa.Column("shares_source", sa.String(), nullable=True))
    op.add_column("stock_master", sa.Column("shares_as_of", sa.Date(), nullable=True))
    op.add_column("stock_master", sa.Column("shares_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_master", "shares_updated_at")
    op.drop_column("stock_master", "shares_as_of")
    op.drop_column("stock_master", "shares_source")
    op.drop_column("stock_master", "shares_outstanding")
