"""update cost of equity floor for brief 39

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-06-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "d8e9f0a1b2c3"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE fundamental_assumption_set
            SET assumptions_json = jsonb_set(
                    coalesce(assumptions_json, '{}'::jsonb),
                    '{cost_of_equity_floor}',
                    '0.065'::jsonb,
                    true
                ),
                version_label = CASE
                    WHEN version_label = 'desk-rf-ke-floor-bam-2026-06-01'
                    THEN 'desk-rf-ke-floor-brief39-2026-06-06'
                    ELSE version_label
                END
            WHERE scope_type = 'desk'
              AND scope_key = 'GLOBAL'
              AND is_active IS TRUE
              AND assumptions_json ? 'cost_of_equity_floor'
              AND (assumptions_json->>'cost_of_equity_floor')::double precision >= 0.095
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE fundamental_assumption_set
            SET assumptions_json = jsonb_set(
                    coalesce(assumptions_json, '{}'::jsonb),
                    '{cost_of_equity_floor}',
                    '0.095'::jsonb,
                    true
                ),
                version_label = 'desk-rf-ke-floor-bam-2026-06-01'
            WHERE scope_type = 'desk'
              AND scope_key = 'GLOBAL'
              AND is_active IS TRUE
              AND version_label = 'desk-rf-ke-floor-brief39-2026-06-06'
              AND assumptions_json ? 'cost_of_equity_floor'
            """
        )
    )
