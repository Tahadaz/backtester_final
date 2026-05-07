"""signal_backtest_run: add trade detail, close/position series, diagnostics, shuffle stats

Revision ID: e3f4a5b6c7d8
Revises: d1e2f3a4b5c6
Create Date: 2026-04-21 00:00:00.000000

Adds nullable JSONB/VARCHAR columns to signal_backtest_run:
  - trades_json          : per-trade detail list
  - close_series_json    : OHLCV close aligned to dates_json
  - position_series_json : executed_position per bar
  - signal_diagnostics_json : flat-signal diagnostics from run_signal_backtest
  - warning_code         : 'flat_signal' | 'few_trades' | null
  - shuffle_stats_json   : shuffled-trade bootstrap result
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signal_backtest_run", sa.Column("trades_json", JSONB, nullable=True))
    op.add_column("signal_backtest_run", sa.Column("close_series_json", JSONB, nullable=True))
    op.add_column("signal_backtest_run", sa.Column("position_series_json", JSONB, nullable=True))
    op.add_column("signal_backtest_run", sa.Column("signal_diagnostics_json", JSONB, nullable=True))
    op.add_column("signal_backtest_run", sa.Column("warning_code", sa.String(32), nullable=True))
    op.add_column("signal_backtest_run", sa.Column("shuffle_stats_json", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("signal_backtest_run", "shuffle_stats_json")
    op.drop_column("signal_backtest_run", "warning_code")
    op.drop_column("signal_backtest_run", "signal_diagnostics_json")
    op.drop_column("signal_backtest_run", "position_series_json")
    op.drop_column("signal_backtest_run", "close_series_json")
    op.drop_column("signal_backtest_run", "trades_json")
