"""add BVC source documents and period metrics

Revision ID: b0c1d2e3f4a8
Revises: a0b1c2d3e4f7
Create Date: 2026-05-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "b0c1d2e3f4a8"
down_revision = "a0b1c2d3e4f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundamental_source_document",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fundamental_import.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("company_name", sa.String(), nullable=True),
        sa.Column("document_title", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("period_type", sa.String(length=20), nullable=True),
        sa.Column("period_label", sa.String(length=20), nullable=True),
        sa.Column("period_end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("extracted_field_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "raw_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("import_id", "source_url", name="uq_fundamental_source_document_import_url"),
    )
    op.create_index(
        "ix_fundamental_source_document_import_symbol",
        "fundamental_source_document",
        ["import_id", "symbol"],
    )
    op.create_index(
        "ix_fundamental_source_document_period",
        "fundamental_source_document",
        ["period_type", "fiscal_year"],
    )

    op.create_table(
        "fundamental_period_metric",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fundamental_import.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("fundamental_source_document.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("period_type", sa.String(length=20), nullable=False, server_default="annual"),
        sa.Column("period_label", sa.String(length=20), nullable=False, server_default="FY"),
        sa.Column("period_end_date", sa.Date(), nullable=True),
        sa.Column("metric_name", sa.String(), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("raw_metric_name", sa.String(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("document_title", sa.Text(), nullable=True),
        sa.Column("is_proxy", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "import_id",
            "symbol",
            "fiscal_year",
            "period_type",
            "period_label",
            "metric_name",
            name="uq_fundamental_period_metric_key",
        ),
    )
    op.create_index(
        "ix_fundamental_period_metric_symbol_period",
        "fundamental_period_metric",
        ["symbol", "period_type", "fiscal_year"],
    )
    op.create_index(
        "ix_fundamental_period_metric_import_symbol",
        "fundamental_period_metric",
        ["import_id", "symbol"],
    )


def downgrade() -> None:
    op.drop_index("ix_fundamental_period_metric_import_symbol", table_name="fundamental_period_metric")
    op.drop_index("ix_fundamental_period_metric_symbol_period", table_name="fundamental_period_metric")
    op.drop_table("fundamental_period_metric")
    op.drop_index("ix_fundamental_source_document_period", table_name="fundamental_source_document")
    op.drop_index("ix_fundamental_source_document_import_symbol", table_name="fundamental_source_document")
    op.drop_table("fundamental_source_document")
