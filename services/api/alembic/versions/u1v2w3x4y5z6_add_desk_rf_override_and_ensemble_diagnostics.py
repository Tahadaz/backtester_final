"""add desk rf override and ensemble diagnostics

Revision ID: u1v2w3x4y5z6
Revises: e5f6a7b8c9d0
Create Date: 2026-06-02
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "u1v2w3x4y5z6"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None

DESK_RF_OVERRIDE_ID = uuid.UUID("315b11ef-0aa7-48ef-8d5d-202606020031")
DESK_RF_VERSION_LABEL = "desk-rf-bam-2026-06-01"


def upgrade() -> None:
    op.add_column("fundamental_ensemble_result", sa.Column("fair_value_mean", sa.Float(), nullable=True))
    op.add_column("fundamental_ensemble_result", sa.Column("model_dispersion_cv", sa.Float(), nullable=True))
    op.add_column("fundamental_ensemble_result", sa.Column("dispersion_factor", sa.Float(), nullable=True))

    assumption_set = sa.table(
        "fundamental_assumption_set",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("scope_type", sa.String(20)),
        sa.column("scope_key", sa.String()),
        sa.column("scenario", sa.String(32)),
        sa.column("version_label", sa.String(80)),
        sa.column("assumptions_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("source", sa.String(32)),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        assumption_set,
        [
            {
                "id": DESK_RF_OVERRIDE_ID,
                "scope_type": "desk",
                "scope_key": "GLOBAL",
                "scenario": "base",
                "version_label": DESK_RF_VERSION_LABEL,
                "assumptions_json": {"risk_free_rate": 0.035, "currency": "MAD"},
                "source": "bam_curve_20260601",
                "is_active": True,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM fundamental_assumption_set "
            "WHERE scope_type = 'desk' AND scope_key = 'GLOBAL' "
            "AND scenario = 'base' AND version_label = :version_label"
        ).bindparams(version_label=DESK_RF_VERSION_LABEL)
    )
    op.drop_column("fundamental_ensemble_result", "dispersion_factor")
    op.drop_column("fundamental_ensemble_result", "model_dispersion_cv")
    op.drop_column("fundamental_ensemble_result", "fair_value_mean")
