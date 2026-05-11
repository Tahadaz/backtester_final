"""expand Factor x TA factor universe to 14

Revision ID: f7a8b9c1d2e3
Revises: e6f7a8b9c1d2
Create Date: 2026-05-10
"""
from __future__ import annotations

from alembic import op


revision = "f7a8b9c1d2e3"
down_revision = "e6f7a8b9c1d2"
branch_labels = None
depends_on = None


_ALL_FACTOR_TICKERS = (
    "^VIX",
    "^GSPC",
    "^NDX",
    "^N225",
    "^FCHI",
    "^FTSE",
    "BZ=F",
    "GC=F",
    "SI=F",
    "DX-Y.NYB",
    "EURUSD=X",
    "AED=X",
    "^TNX",
    "BTC-USD",
)

_NEW_FACTOR_TICKERS = (
    "^NDX",
    "^N225",
    "^FCHI",
    "^FTSE",
    "GC=F",
    "SI=F",
    "AED=X",
    "BTC-USD",
)

_FACTOR_X_TA_VARIANTS = (
    "factor_x_ta",
    "legacy_factor_x_ta_simple",
    "expanded_factor_x_ta_simple",
    "legacy_factor_x_ta_combo",
    "expanded_factor_x_ta_combo",
)


def _sql_tuple(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    factor_values = ", ".join(f"('{ticker}')" for ticker in _ALL_FACTOR_TICKERS)
    op.execute(
        f"""
        WITH symbols AS (
            SELECT symbol AS stock_symbol
            FROM stock_master
            WHERE is_active = true
            UNION
            SELECT DISTINCT stock_symbol
            FROM stock_factor_config
        ),
        factors(factor_ticker) AS (
            VALUES {factor_values}
        )
        INSERT INTO stock_factor_config (stock_symbol, factor_ticker, enabled)
        SELECT symbols.stock_symbol, factors.factor_ticker, true
        FROM symbols
        CROSS JOIN factors
        WHERE symbols.stock_symbol IS NOT NULL
        ON CONFLICT (stock_symbol, factor_ticker) DO NOTHING
        """
    )

    variants = _sql_tuple(_FACTOR_X_TA_VARIANTS)
    op.execute(f"DELETE FROM signal_engine_family_result WHERE variant IN ({variants})")
    op.execute(f"DELETE FROM signal_engine_global_result WHERE variant IN ({variants})")
    op.execute(f"DELETE FROM wfo_signal_summary WHERE variant IN ({variants})")
    op.execute(f"DELETE FROM wfo_global_signal WHERE variant IN ({variants})")


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM stock_factor_config
        WHERE factor_ticker IN ({_sql_tuple(_NEW_FACTOR_TICKERS)})
        """
    )
