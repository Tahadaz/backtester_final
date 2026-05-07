"""add strategy_backtest_run tables

Revision ID: h8i9j0k1l2m
Revises: g7h8i9j0k1l2
Create Date: 2026-04-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision = "h8i9j0k1l2m"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_backtest_run",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("strategy_id", UUID(as_uuid=True), sa.ForeignKey("saved_strategy.id"), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False, server_default="direct"),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("horizon", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("request_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("summary_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("progress_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_text", sa.Text, nullable=True),
        sa.Column("rq_job_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_strategy_backtest_run_status", "strategy_backtest_run", ["status"])
    op.create_index("ix_strategy_backtest_run_created_at", "strategy_backtest_run", ["created_at"])
    op.create_index("ix_strategy_backtest_run_strategy_id", "strategy_backtest_run", ["strategy_id"])

    op.create_table(
        "strategy_backtest_stock",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("strategy_backtest_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("summary_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "symbol", name="uq_strategy_backtest_stock_run_symbol"),
    )
    op.create_index("ix_strategy_backtest_stock_run", "strategy_backtest_stock", ["run_id"])

    op.create_table(
        "strategy_backtest_window",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("strategy_backtest_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("window_index", sa.Integer(), nullable=False),
        sa.Column("summary_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("detail_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "symbol", "window_index", name="uq_strategy_backtest_window_run_symbol_index"),
    )
    op.create_index("ix_strategy_backtest_window_run", "strategy_backtest_window", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_strategy_backtest_window_run", table_name="strategy_backtest_window")
    op.drop_table("strategy_backtest_window")

    op.drop_index("ix_strategy_backtest_stock_run", table_name="strategy_backtest_stock")
    op.drop_table("strategy_backtest_stock")

    op.drop_index("ix_strategy_backtest_run_strategy_id", table_name="strategy_backtest_run")
    op.drop_index("ix_strategy_backtest_run_created_at", table_name="strategy_backtest_run")
    op.drop_index("ix_strategy_backtest_run_status", table_name="strategy_backtest_run")
    op.drop_table("strategy_backtest_run")
