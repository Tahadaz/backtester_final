"""add fundamental data source columns

Revision ID: b1c2d3e4f5a6
Revises: f0a1b2c3d4e5
Create Date: 2026-05-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "b1c2d3e4f5a6"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fundamental_import",
        sa.Column("data_source", sa.String(length=16), nullable=False, server_default="workbook"),
    )
    op.add_column(
        "fundamental_import",
        sa.Column("source_universe", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "fundamental_latest_snapshot",
        sa.Column("data_source", sa.String(length=16), nullable=False, server_default="workbook"),
    )


def downgrade() -> None:
    op.drop_column("fundamental_latest_snapshot", "data_source")
    op.drop_column("fundamental_import", "source_universe")
    op.drop_column("fundamental_import", "data_source")
