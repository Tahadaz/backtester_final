"""add fundamental currency and band fields

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fundamental_valuation_result", sa.Column("currency", sa.String(length=8), nullable=True))
    op.add_column("fundamental_ensemble_result", sa.Column("currency", sa.String(length=8), nullable=True))
    op.add_column("fundamental_ensemble_result", sa.Column("model_dispersion_low", sa.Float(), nullable=True))
    op.add_column("fundamental_ensemble_result", sa.Column("model_dispersion_base", sa.Float(), nullable=True))
    op.add_column("fundamental_ensemble_result", sa.Column("model_dispersion_high", sa.Float(), nullable=True))
    op.add_column("fundamental_ensemble_result", sa.Column("monte_carlo_low", sa.Float(), nullable=True))
    op.add_column("fundamental_ensemble_result", sa.Column("monte_carlo_base", sa.Float(), nullable=True))
    op.add_column("fundamental_ensemble_result", sa.Column("monte_carlo_high", sa.Float(), nullable=True))
    op.execute(
        """
        UPDATE fundamental_assumption_set
        SET assumptions_json = jsonb_set(
            jsonb_set(
                jsonb_set(
                    jsonb_set(assumptions_json, '{wacc}', '0.0851'::jsonb, true),
                    '{default_debt_weight}', '0.30'::jsonb, true
                ),
                '{default_equity_weight}', '0.70'::jsonb, true
            ),
            '{currency}', '"MAD"'::jsonb, true
        )
        WHERE source = 'seeded_default'
           OR assumptions_json->>'wacc' = '0.105'
        """
    )


def downgrade() -> None:
    op.drop_column("fundamental_ensemble_result", "monte_carlo_high")
    op.drop_column("fundamental_ensemble_result", "monte_carlo_base")
    op.drop_column("fundamental_ensemble_result", "monte_carlo_low")
    op.drop_column("fundamental_ensemble_result", "model_dispersion_high")
    op.drop_column("fundamental_ensemble_result", "model_dispersion_base")
    op.drop_column("fundamental_ensemble_result", "model_dispersion_low")
    op.drop_column("fundamental_ensemble_result", "currency")
    op.drop_column("fundamental_valuation_result", "currency")
