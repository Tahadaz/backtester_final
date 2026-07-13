"""add historical portfolio backtest run

Revision ID: 9d2f6c8e3a01
Revises: 8c1e5b7d2f90
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "9d2f6c8e3a01"
down_revision: Union[str, Sequence[str], None] = "8c1e5b7d2f90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "historical_portfolio_backtest_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("rq_job_id", sa.String(), nullable=True),
        sa.Column("methodology_version", sa.String(length=80), nullable=False),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("diagnostics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("opportunities_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trades_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("equity_curves_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("benchmark_curves_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("statistics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("validation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot_audit_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('queued','running','succeeded','failed')", name="ck_historical_portfolio_backtest_run_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_historical_portfolio_backtest_run_status", "historical_portfolio_backtest_run", ["status"])
    op.create_index("ix_historical_portfolio_backtest_run_created", "historical_portfolio_backtest_run", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_historical_portfolio_backtest_run_created", table_name="historical_portfolio_backtest_run")
    op.drop_index("ix_historical_portfolio_backtest_run_status", table_name="historical_portfolio_backtest_run")
    op.drop_table("historical_portfolio_backtest_run")
