"""add signal best evidence snapshot

Revision ID: g8h9i0j1k2l3
Revises: f7a8b9c1d2e3
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "g8h9i0j1k2l3"
down_revision = "f7a8b9c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_best_evidence_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("horizon", sa.String(length=16), nullable=False),
        sa.Column("cooldown_bars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="wfo"),
        sa.Column("variant", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="global"),
        sa.Column("scope_key", sa.String(length=64), nullable=False, server_default="global"),
        sa.Column("side_policy", sa.String(length=16), nullable=False, server_default="long_short"),
        sa.Column("evidence_payload_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("chart_payload_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "upstream_rev",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("data_as_of", sa.Date(), nullable=True),
        sa.Column("market_data_as_of", sa.Date(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("symbol", "horizon", "cooldown_bars", name="uq_signal_best_evidence_snapshot_key"),
    )
    op.create_index(
        "ix_signal_best_evidence_snapshot_status",
        "signal_best_evidence_snapshot",
        ["status"],
    )
    op.create_index(
        "ix_signal_best_evidence_snapshot_symbol_horizon",
        "signal_best_evidence_snapshot",
        ["symbol", "horizon"],
    )


def downgrade() -> None:
    op.drop_index("ix_signal_best_evidence_snapshot_symbol_horizon", table_name="signal_best_evidence_snapshot")
    op.drop_index("ix_signal_best_evidence_snapshot_status", table_name="signal_best_evidence_snapshot")
    op.drop_table("signal_best_evidence_snapshot")
