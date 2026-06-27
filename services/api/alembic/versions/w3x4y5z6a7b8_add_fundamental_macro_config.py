"""add fundamental macro config

Revision ID: w3x4y5z6a7b8
Revises: v2w3x4y5z6a7
Create Date: 2026-06-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "w3x4y5z6a7b8"
down_revision = "v2w3x4y5z6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundamental_macro_config",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("scope_key", sa.String(), nullable=False, server_default="GLOBAL"),
        sa.Column("version_label", sa.String(length=80), nullable=False, server_default="base"),
        sa.Column("risk_free_mode", sa.String(length=20), nullable=False, server_default="tenor"),
        sa.Column("treasury_tenor", sa.String(length=16), nullable=False, server_default="10Y"),
        sa.Column("treasury_curve_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("manual_risk_free_rate", sa.Float(), nullable=True),
        sa.Column("erp_mode", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("erp_index_symbol", sa.String(), nullable=False, server_default="MASI"),
        sa.Column("erp_index_asset_class", sa.String(length=20), nullable=False, server_default="index"),
        sa.Column("erp_lookback_years", sa.Float(), nullable=False, server_default="10"),
        sa.Column("erp_mean_method", sa.String(length=20), nullable=False, server_default="geometric"),
        sa.Column("manual_equity_risk_premium", sa.Float(), nullable=True),
        sa.Column("country_risk_mode", sa.String(length=20), nullable=False, server_default="auto"),
        sa.Column("morocco_country_risk_premium", sa.Float(), nullable=False, server_default="0"),
        sa.Column("manual_country_risk_premium", sa.Float(), nullable=True),
        sa.Column("computed_values_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="seeded_default"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_fundamental_macro_config_active",
        "fundamental_macro_config",
        ["scope_key", "is_active"],
    )
    macro_config = sa.table(
        "fundamental_macro_config",
        sa.column("scope_key", sa.String()),
        sa.column("version_label", sa.String(length=80)),
        sa.column("risk_free_mode", sa.String(length=20)),
        sa.column("treasury_tenor", sa.String(length=16)),
        sa.column("treasury_curve_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("erp_mode", sa.String(length=20)),
        sa.column("erp_index_symbol", sa.String()),
        sa.column("erp_index_asset_class", sa.String(length=20)),
        sa.column("erp_lookback_years", sa.Float()),
        sa.column("erp_mean_method", sa.String(length=20)),
        sa.column("manual_equity_risk_premium", sa.Float()),
        sa.column("country_risk_mode", sa.String(length=20)),
        sa.column("morocco_country_risk_premium", sa.Float()),
        sa.column("computed_values_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("source", sa.String(length=64)),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        macro_config,
        [
            {
                "scope_key": "GLOBAL",
                "version_label": "macro-seed-bam-masi-2026-06-03",
                "risk_free_mode": "tenor",
                "treasury_tenor": "10Y",
                "treasury_curve_json": {"1Y": 0.030, "5Y": 0.033, "10Y": 0.035},
                "erp_mode": "manual",
                "erp_index_symbol": "MASI",
                "erp_index_asset_class": "index",
                "erp_lookback_years": 10.0,
                "erp_mean_method": "geometric",
                "manual_equity_risk_premium": 0.060,
                "country_risk_mode": "auto",
                "morocco_country_risk_premium": 0.0,
                "computed_values_json": {
                    "risk_free_rate": 0.035,
                    "equity_risk_premium": 0.060,
                    "country_risk_premium": 0.0,
                    "crp_coupling": "MASI-derived/manual MASI baseline => CRP=0",
                },
                "source": "phase1_macro_seed",
                "is_active": True,
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_fundamental_macro_config_active", table_name="fundamental_macro_config")
    op.drop_table("fundamental_macro_config")
