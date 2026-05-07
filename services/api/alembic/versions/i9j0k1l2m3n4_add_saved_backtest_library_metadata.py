"""add saved backtest library metadata

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m
Create Date: 2026-04-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("strategy_backtest_run", sa.Column("title", sa.String(length=200), nullable=False, server_default=""))
    op.add_column("strategy_backtest_run", sa.Column("execution_fingerprint", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("strategy_backtest_run", sa.Column("strategy_snapshot_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("strategy_backtest_run", sa.Column("data_snapshot_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("strategy_backtest_run", sa.Column("result_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_index(
        "ix_strategy_backtest_run_execution_fingerprint",
        "strategy_backtest_run",
        ["execution_fingerprint"],
        unique=False,
    )

    op.alter_column("strategy_backtest_run", "title", server_default=None)
    op.alter_column("strategy_backtest_run", "execution_fingerprint", server_default=None)
    op.alter_column("strategy_backtest_run", "strategy_snapshot_json", server_default=None)
    op.alter_column("strategy_backtest_run", "data_snapshot_json", server_default=None)
    op.alter_column("strategy_backtest_run", "result_json", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_strategy_backtest_run_execution_fingerprint", table_name="strategy_backtest_run")
    op.drop_column("strategy_backtest_run", "result_json")
    op.drop_column("strategy_backtest_run", "data_snapshot_json")
    op.drop_column("strategy_backtest_run", "strategy_snapshot_json")
    op.drop_column("strategy_backtest_run", "execution_fingerprint")
    op.drop_column("strategy_backtest_run", "title")
