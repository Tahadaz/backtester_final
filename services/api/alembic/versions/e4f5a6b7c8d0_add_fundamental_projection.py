"""add fundamental projection table

Revision ID: e4f5a6b7c8d0
Revises: e2f3a4b5c6d7
Create Date: 2026-06-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "e4f5a6b7c8d0"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundamental_projection",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("scenario", sa.String(length=32), nullable=False, server_default="base"),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("line_item", sa.String(length=80), nullable=False),
        sa.Column("projected_value", sa.Float(), nullable=True),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("is_override", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["import_id"], ["fundamental_import.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("import_id", "symbol", "scenario", "fiscal_year", "line_item", name="uq_fundamental_projection_line"),
    )
    op.create_index("ix_fundamental_projection_symbol_asof", "fundamental_projection", ["symbol", "as_of"])
    op.create_index("ix_fundamental_projection_symbol_scenario", "fundamental_projection", ["symbol", "scenario"])


def downgrade() -> None:
    op.drop_index("ix_fundamental_projection_symbol_scenario", table_name="fundamental_projection")
    op.drop_index("ix_fundamental_projection_symbol_asof", table_name="fundamental_projection")
    op.drop_table("fundamental_projection")
