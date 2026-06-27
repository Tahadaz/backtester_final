"""Add fundamental data verification table.

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-06-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c7d8e9f0a1b2"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundamental_data_verification",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("statement_year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("failed_checks_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("offending_metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recomputed_metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("corrections_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_urls_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stockanalysis_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tieout_report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status in ('verified','data_unverified')", name="ck_fundamental_data_verification_status"),
        sa.ForeignKeyConstraint(["import_id"], ["fundamental_import.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_id", "symbol", "statement_year", name="uq_fundamental_data_verification_import_symbol_year"),
    )
    op.create_index("ix_fundamental_data_verification_status", "fundamental_data_verification", ["status"])
    op.create_index("ix_fundamental_data_verification_symbol_year", "fundamental_data_verification", ["symbol", "statement_year"])


def downgrade() -> None:
    op.drop_index("ix_fundamental_data_verification_symbol_year", table_name="fundamental_data_verification")
    op.drop_index("ix_fundamental_data_verification_status", table_name="fundamental_data_verification")
    op.drop_table("fundamental_data_verification")
