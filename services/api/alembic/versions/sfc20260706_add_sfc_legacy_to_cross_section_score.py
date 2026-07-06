"""add sfc legacy score to fundamental cross-section table

Revision ID: sfc20260706
Revises: sfc20260705
Create Date: 2026-07-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "sfc20260706"
down_revision = "sfc20260705"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fundamental_cross_section_score", sa.Column("sfc_legacy", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("fundamental_cross_section_score", "sfc_legacy")
