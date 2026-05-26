"""add fundamental assumption override

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-05-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundamental_assumption_override",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("scenario", sa.Text(), nullable=False),
        sa.Column("overrides", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint("scenario in ('bear','base','bull')", name="ck_fundamental_assumption_override_scenario"),
    )
    op.create_index(
        "uq_fundamental_assumption_override_current",
        "fundamental_assumption_override",
        ["symbol", "scenario"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )
    op.create_index(
        "ix_fundamental_assumption_override_symbol_created",
        "fundamental_assumption_override",
        ["symbol", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("fundamental_assumption_override")
