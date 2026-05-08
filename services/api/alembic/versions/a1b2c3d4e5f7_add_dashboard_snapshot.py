"""add dashboard_snapshot table (Phase 1)

Revision ID: a1b2c3d4e5f7
Revises: z7a8b9c0d1e2
Create Date: 2026-05-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "a1b2c3d4e5f7"
down_revision = "z7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_snapshot",
        sa.Column("horizon", sa.String(16), primary_key=True),
        sa.Column("as_of_date", sa.Date(), primary_key=True),
        sa.Column(
            "payload_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "upstream_rev",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_dashboard_snapshot_horizon_computed",
        "dashboard_snapshot",
        ["horizon", "computed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_dashboard_snapshot_horizon_computed", table_name="dashboard_snapshot")
    op.drop_table("dashboard_snapshot")
