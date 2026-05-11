"""widen signal mode and combo family columns

Revision ID: d5e6f7a8b9c1
Revises: c3d4e5f6a9b0
Create Date: 2026-05-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "d5e6f7a8b9c1"
down_revision = "c3d4e5f6a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "wfo_signal_summary",
        "variant",
        existing_type=sa.String(length=16),
        type_=sa.String(length=64),
        existing_nullable=False,
        existing_server_default=sa.text("'expanded'::character varying"),
    )
    op.alter_column(
        "wfo_global_signal",
        "variant",
        existing_type=sa.String(length=16),
        type_=sa.String(length=64),
        existing_nullable=False,
        existing_server_default=sa.text("'expanded'::character varying"),
    )
    op.alter_column(
        "signal_engine_family_result",
        "family",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.alter_column(
        "signal_engine_family_result",
        "variant",
        existing_type=sa.String(length=16),
        type_=sa.String(length=64),
        existing_nullable=False,
        existing_server_default=sa.text("'expanded'::character varying"),
    )
    op.alter_column(
        "signal_engine_global_result",
        "variant",
        existing_type=sa.String(length=16),
        type_=sa.String(length=64),
        existing_nullable=False,
        existing_server_default=sa.text("'expanded'::character varying"),
    )
    op.alter_column(
        "signal_backtest_run",
        "variant",
        existing_type=sa.String(length=16),
        type_=sa.String(length=64),
        existing_nullable=False,
        existing_server_default=sa.text("'expanded'::character varying"),
    )
    op.alter_column(
        "signal_engine_batch_job",
        "variant",
        existing_type=sa.String(length=16),
        type_=sa.String(length=64),
        existing_nullable=False,
        existing_server_default=sa.text("'expanded'::character varying"),
    )


def downgrade() -> None:
    op.alter_column(
        "signal_engine_batch_job",
        "variant",
        existing_type=sa.String(length=64),
        type_=sa.String(length=16),
        existing_nullable=False,
        existing_server_default=sa.text("'expanded'::character varying"),
    )
    op.alter_column(
        "signal_backtest_run",
        "variant",
        existing_type=sa.String(length=64),
        type_=sa.String(length=16),
        existing_nullable=False,
        existing_server_default=sa.text("'expanded'::character varying"),
    )
    op.alter_column(
        "signal_engine_global_result",
        "variant",
        existing_type=sa.String(length=64),
        type_=sa.String(length=16),
        existing_nullable=False,
        existing_server_default=sa.text("'expanded'::character varying"),
    )
    op.alter_column(
        "signal_engine_family_result",
        "variant",
        existing_type=sa.String(length=64),
        type_=sa.String(length=16),
        existing_nullable=False,
        existing_server_default=sa.text("'expanded'::character varying"),
    )
    op.alter_column(
        "signal_engine_family_result",
        "family",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.alter_column(
        "wfo_global_signal",
        "variant",
        existing_type=sa.String(length=64),
        type_=sa.String(length=16),
        existing_nullable=False,
        existing_server_default=sa.text("'expanded'::character varying"),
    )
    op.alter_column(
        "wfo_signal_summary",
        "variant",
        existing_type=sa.String(length=64),
        type_=sa.String(length=16),
        existing_nullable=False,
        existing_server_default=sa.text("'expanded'::character varying"),
    )
