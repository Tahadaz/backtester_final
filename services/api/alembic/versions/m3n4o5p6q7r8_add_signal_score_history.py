"""add signal_score_history table

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-04-26 00:00:00.000000

Stores per-bar engine/WFO category scores so the analytics page can bucket
historical signals (Strong Sell..Strong Buy) and compute forward-return
hit rates / expected values without re-running the engine on every request.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "m3n4o5p6q7r8"
down_revision: Union[str, None] = "l2m3n4o5p6q7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signal_score_history",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),     # 'engine_legacy' | 'engine_expanded' | 'wfo'
        sa.Column("category", sa.String(32), nullable=False),   # 'tendance' | 'momentum' | 'oscillation' | 'volume'
        sa.Column("horizon", sa.String(16), nullable=False),    # 'short' | 'medium' | 'long'
        sa.Column("score_pct", sa.Float(), nullable=True),      # in [-100, +100]
        sa.PrimaryKeyConstraint("date", "symbol", "source", "category", "horizon",
                                name="pk_signal_score_history"),
    )
    op.create_index(
        "ix_ssh_symbol_source_horizon",
        "signal_score_history",
        ["symbol", "source", "horizon"],
    )
    op.create_index(
        "ix_ssh_symbol_date",
        "signal_score_history",
        ["symbol", "date"],
    )

    # Track batch jobs that populate the table (pending/running/succeeded/failed per symbol)
    op.create_table(
        "score_history_job",
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("rq_job_id", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("symbol", name="pk_score_history_job"),
    )
    op.create_index("ix_shj_status", "score_history_job", ["status"])


def downgrade() -> None:
    op.drop_index("ix_shj_status", table_name="score_history_job")
    op.drop_table("score_history_job")
    op.drop_index("ix_ssh_symbol_date", table_name="signal_score_history")
    op.drop_index("ix_ssh_symbol_source_horizon", table_name="signal_score_history")
    op.drop_table("signal_score_history")
