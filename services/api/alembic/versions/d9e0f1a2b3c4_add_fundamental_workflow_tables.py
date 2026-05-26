"""add fundamental workflow tables

Revision ID: d9e0f1a2b3c4
Revises: b0c1d2e3f4a8
Create Date: 2026-05-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "d9e0f1a2b3c4"
down_revision = "b0c1d2e3f4a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fundamental_ensemble_result",
        sa.Column("sensitivity_grids_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "fundamental_integrity_report",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("statement_year", sa.Integer(), nullable=False),
        sa.Column("overall_status", sa.String(length=20), nullable=False),
        sa.Column("confidence_haircut", sa.Float(), nullable=False),
        sa.Column("checks_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("projected_statements_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("projection_checks_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("overall_status in ('pass','derived','warn','fail','unavailable')", name="ck_fundamental_integrity_status"),
        sa.UniqueConstraint("symbol", "statement_year", "import_id", name="uq_fundamental_integrity_symbol_year_import"),
    )
    op.create_index("ix_fundamental_integrity_symbol_year", "fundamental_integrity_report", ["symbol", "statement_year"])

    op.create_table(
        "fundamental_thesis",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("conviction", sa.String(length=20), nullable=False),
        sa.Column("core_thesis", sa.Text(), nullable=False),
        sa.Column("bullish_drivers_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("bearish_drivers_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("target_price", sa.Float(), nullable=True),
        sa.Column("target_horizon_months", sa.Integer(), nullable=True),
        sa.Column("stop_price", sa.Float(), nullable=True),
        sa.Column("invalidation_conditions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("linked_catalyst_ids_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint("direction in ('long','short','pair_long','pair_short','avoid')", name="ck_fundamental_thesis_direction"),
        sa.CheckConstraint("conviction in ('high','medium','low')", name="ck_fundamental_thesis_conviction"),
    )
    op.create_index("ix_fundamental_thesis_symbol_created", "fundamental_thesis", ["symbol", "created_at"])
    op.create_index(
        "uq_fundamental_thesis_current_symbol",
        "fundamental_thesis",
        ["symbol"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )

    op.create_table(
        "fundamental_catalyst",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_date_confidence", sa.String(length=20), nullable=False),
        sa.Column("impact_tier", sa.String(length=20), nullable=False),
        sa.Column("expected_direction", sa.String(length=20), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("superseded_by_id", sa.BigInteger(), sa.ForeignKey("fundamental_catalyst.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("event_type in ('earnings','dividend','ex_dividend','agm','guidance','regulatory','product','m_and_a','split','other')", name="ck_fundamental_catalyst_event_type"),
        sa.CheckConstraint("event_date_confidence in ('confirmed','estimated','rumour')", name="ck_fundamental_catalyst_date_confidence"),
        sa.CheckConstraint("impact_tier in ('high','moderate','routine')", name="ck_fundamental_catalyst_impact_tier"),
        sa.CheckConstraint("(expected_direction is null) or expected_direction in ('positive','negative','neutral')", name="ck_fundamental_catalyst_expected_direction"),
    )
    op.create_index("ix_fundamental_catalyst_symbol_date", "fundamental_catalyst", ["symbol", "event_date"])
    op.create_index("ix_fundamental_catalyst_active_date", "fundamental_catalyst", ["is_active", "event_date"])
    op.create_index("ix_fundamental_catalyst_symbol_active_date", "fundamental_catalyst", ["symbol", "is_active", "event_date"])

    op.create_table(
        "fundamental_pillar_score_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("value_score", sa.Float(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("growth_score", sa.Float(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("cash_flow_score", sa.Float(), nullable=True),
        sa.Column("health_score", sa.Float(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("pillar_coverage_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("symbol", "import_id", name="uq_fundamental_pillar_history_symbol_import"),
    )
    op.create_index("ix_fundamental_pillar_history_symbol_asof", "fundamental_pillar_score_history", ["symbol", "as_of"])


def downgrade() -> None:
    op.drop_index("ix_fundamental_pillar_history_symbol_asof", table_name="fundamental_pillar_score_history")
    op.drop_table("fundamental_pillar_score_history")
    op.drop_index("ix_fundamental_catalyst_symbol_active_date", table_name="fundamental_catalyst")
    op.drop_index("ix_fundamental_catalyst_active_date", table_name="fundamental_catalyst")
    op.drop_index("ix_fundamental_catalyst_symbol_date", table_name="fundamental_catalyst")
    op.drop_table("fundamental_catalyst")
    op.drop_index("uq_fundamental_thesis_current_symbol", table_name="fundamental_thesis")
    op.drop_index("ix_fundamental_thesis_symbol_created", table_name="fundamental_thesis")
    op.drop_table("fundamental_thesis")
    op.drop_index("ix_fundamental_integrity_symbol_year", table_name="fundamental_integrity_report")
    op.drop_table("fundamental_integrity_report")
    op.drop_column("fundamental_ensemble_result", "sensitivity_grids_json")
