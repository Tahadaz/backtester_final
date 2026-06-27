"""add desk cost of equity floor

Revision ID: v2w3x4y5z6a7
Revises: u1v2w3x4y5z6
Create Date: 2026-06-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "v2w3x4y5z6a7"
down_revision = "u1v2w3x4y5z6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE fundamental_assumption_set
            SET assumptions_json = assumptions_json || '{"cost_of_equity_floor": 0.095}'::jsonb,
                version_label = 'desk-rf-ke-floor-bam-2026-06-01'
            WHERE scope_type = 'desk'
              AND scope_key = 'GLOBAL'
              AND scenario = 'base'
              AND version_label = 'desk-rf-bam-2026-06-01'
              AND is_active IS TRUE
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE fundamental_assumption_set
            SET assumptions_json = assumptions_json - 'cost_of_equity_floor',
                version_label = 'desk-rf-bam-2026-06-01'
            WHERE scope_type = 'desk'
              AND scope_key = 'GLOBAL'
              AND scenario = 'base'
              AND version_label = 'desk-rf-ke-floor-bam-2026-06-01'
              AND is_active IS TRUE
            """
        )
    )
