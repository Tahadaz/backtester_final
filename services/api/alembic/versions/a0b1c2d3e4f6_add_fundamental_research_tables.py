"""add fundamental research v2 tables

Revision ID: a0b1c2d3e4f6
Revises: z7a8b9c0d1e2
Create Date: 2026-05-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "a0b1c2d3e4f6"
down_revision = "z7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundamental_import",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("dataset.id"), nullable=True),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("methodology_version", sa.String(32), nullable=False, server_default="v2"),
        sa.Column("rq_job_id", sa.String(), nullable=True),
        sa.Column("company_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("symbol_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("annual_metric_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latest_snapshot_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality_issue_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_fundamental_import_status_created", "fundamental_import", ["status", "created_at"])
    op.create_index("ix_fundamental_import_rq_job_id", "fundamental_import", ["rq_job_id"])

    op.create_table(
        "fundamental_company_map",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("mapped_company_name", sa.String(), nullable=True),
        sa.Column("canonical_company_name", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("shares_outstanding", sa.Float(), nullable=True),
        sa.Column("match_type", sa.String(), nullable=True),
        sa.Column("score_note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("is_duplicate_symbol", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("import_id", "company_name", name="uq_fundamental_company_map_import_company"),
    )
    op.create_index("ix_fundamental_company_map_symbol", "fundamental_company_map", ["symbol"])

    op.create_table(
        "fundamental_annual_metric",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("statement_year", sa.Integer(), nullable=False),
        sa.Column("metric_name", sa.String(), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("raw_metric_name", sa.String(), nullable=True),
        sa.Column("source_sheet", sa.String(), nullable=True),
        sa.Column("source_field", sa.String(), nullable=True),
        sa.Column("is_proxy", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("import_id", "symbol", "statement_year", "metric_name", name="uq_fundamental_annual_metric_key"),
    )
    op.create_index("ix_fundamental_annual_metric_symbol_year", "fundamental_annual_metric", ["symbol", "statement_year"])

    op.create_table(
        "fundamental_latest_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("latest_statement_year", sa.Integer(), nullable=True),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("scores_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("diagnostics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("coverage_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("model_eligibility_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("import_id", "symbol", name="uq_fundamental_latest_snapshot_import_symbol"),
    )
    op.create_index("ix_fundamental_latest_snapshot_symbol", "fundamental_latest_snapshot", ["symbol"])

    op.create_table(
        "fundamental_quality_issue",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("metric_name", sa.String(), nullable=True),
        sa.Column("statement_year", sa.Integer(), nullable=True),
        sa.Column("context_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_fundamental_quality_issue_import_symbol", "fundamental_quality_issue", ["import_id", "symbol"])
    op.create_index("ix_fundamental_quality_issue_code", "fundamental_quality_issue", ["code"])

    op.create_table(
        "fundamental_assumption_set",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope_type", sa.String(20), nullable=False, server_default="symbol"),
        sa.Column("scope_key", sa.String(), nullable=False, server_default="GLOBAL"),
        sa.Column("scenario", sa.String(32), nullable=False, server_default="base"),
        sa.Column("version_label", sa.String(80), nullable=False, server_default="base"),
        sa.Column("assumptions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source", sa.String(32), nullable=False, server_default="seeded_default"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("scope_type", "scope_key", "scenario", "version_label", name="uq_fundamental_assumption_scope_scenario_version"),
    )
    op.create_index("ix_fundamental_assumption_scope", "fundamental_assumption_set", ["scope_type", "scope_key"])
    op.create_index("ix_fundamental_assumption_active", "fundamental_assumption_set", ["scenario", "is_active"])

    op.create_table(
        "fundamental_valuation_result",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("scenario", sa.String(32), nullable=False, server_default="base"),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("fair_value", sa.Float(), nullable=True),
        sa.Column("current_price", sa.Float(), nullable=True),
        sa.Column("upside_pct", sa.Float(), nullable=True),
        sa.Column("confidence", sa.String(20), nullable=False, server_default="unavailable"),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("family", sa.String(32), nullable=False, server_default="intrinsic"),
        sa.Column("methodology", sa.Text(), nullable=True),
        sa.Column("model_version", sa.String(32), nullable=False, server_default="v2"),
        sa.Column("is_proxy", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("data_quality_score", sa.Float(), nullable=True),
        sa.Column("inputs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("outputs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("import_id", "symbol", "scenario", "model", name="uq_fundamental_valuation_key"),
    )
    op.create_index("ix_fundamental_valuation_symbol", "fundamental_valuation_result", ["symbol"])

    op.create_table(
        "fundamental_ensemble_result",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("scenario", sa.String(32), nullable=False, server_default="base"),
        sa.Column("fair_value_low", sa.Float(), nullable=True),
        sa.Column("fair_value_base", sa.Float(), nullable=True),
        sa.Column("fair_value_high", sa.Float(), nullable=True),
        sa.Column("current_price", sa.Float(), nullable=True),
        sa.Column("upside_pct", sa.Float(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("usable_model_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("excluded_model_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_weights_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("import_id", "symbol", "scenario", name="uq_fundamental_ensemble_key"),
    )
    op.create_index("ix_fundamental_ensemble_symbol", "fundamental_ensemble_result", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_fundamental_ensemble_symbol", table_name="fundamental_ensemble_result")
    op.drop_table("fundamental_ensemble_result")
    op.drop_index("ix_fundamental_valuation_symbol", table_name="fundamental_valuation_result")
    op.drop_table("fundamental_valuation_result")
    op.drop_index("ix_fundamental_assumption_active", table_name="fundamental_assumption_set")
    op.drop_index("ix_fundamental_assumption_scope", table_name="fundamental_assumption_set")
    op.drop_table("fundamental_assumption_set")
    op.drop_index("ix_fundamental_quality_issue_code", table_name="fundamental_quality_issue")
    op.drop_index("ix_fundamental_quality_issue_import_symbol", table_name="fundamental_quality_issue")
    op.drop_table("fundamental_quality_issue")
    op.drop_index("ix_fundamental_latest_snapshot_symbol", table_name="fundamental_latest_snapshot")
    op.drop_table("fundamental_latest_snapshot")
    op.drop_index("ix_fundamental_annual_metric_symbol_year", table_name="fundamental_annual_metric")
    op.drop_table("fundamental_annual_metric")
    op.drop_index("ix_fundamental_company_map_symbol", table_name="fundamental_company_map")
    op.drop_table("fundamental_company_map")
    op.drop_index("ix_fundamental_import_rq_job_id", table_name="fundamental_import")
    op.drop_index("ix_fundamental_import_status_created", table_name="fundamental_import")
    op.drop_table("fundamental_import")
