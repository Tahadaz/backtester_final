"""add dashboard custom index component shares

Revision ID: aa1bb2cc3dd4
Revises: d0e1f2a3b4c6
Create Date: 2026-05-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "aa1bb2cc3dd4"
down_revision = "d0e1f2a3b4c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dashboard_custom_index",
        sa.Column(
            "component_shares",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("dashboard_custom_index", "component_shares")
