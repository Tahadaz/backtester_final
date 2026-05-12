"""add signal backtest cooldown dimension

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c1d2e3
Create Date: 2026-05-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "f7a8b9c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "signal_backtest_run",
        sa.Column("cooldown_bars", sa.Integer(), nullable=False, server_default="0"),
    )
    op.drop_constraint("uq_sbr_natural_key", "signal_backtest_run", type_="unique")
    op.create_unique_constraint(
        "uq_sbr_natural_key",
        "signal_backtest_run",
        [
            "symbol",
            "horizon",
            "source",
            "scope",
            "scope_key",
            "variant",
            "window_start",
            "window_end",
            "cooldown_bars",
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM signal_backtest_run WHERE cooldown_bars <> 0")
    op.drop_constraint("uq_sbr_natural_key", "signal_backtest_run", type_="unique")
    op.create_unique_constraint(
        "uq_sbr_natural_key",
        "signal_backtest_run",
        [
            "symbol",
            "horizon",
            "source",
            "scope",
            "scope_key",
            "variant",
            "window_start",
            "window_end",
        ],
    )
    op.drop_column("signal_backtest_run", "cooldown_bars")
