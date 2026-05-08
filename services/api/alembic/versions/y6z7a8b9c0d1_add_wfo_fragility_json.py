"""add wfo fragility json

Revision ID: y6z7a8b9c0d1
Revises: t0u1v2w3x4y5
Create Date: 2026-05-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "y6z7a8b9c0d1"
down_revision = "t0u1v2w3x4y5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wfo_signal_summary",
        sa.Column("fragility_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wfo_signal_summary", "fragility_json")
