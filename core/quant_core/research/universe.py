"""
Active trading universe selection for Moroccan equities (MASI).

Thresholds are calibrated for Casablanca Bourse liquidity profiles:
- min_bars=252: at least one year of trading history
- min_adv_mad=1_000_000: ≥ 1M MAD average daily value traded (price × volume)
- min_price=5.0: exclude sub-5 MAD penny stocks
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass
class UniverseRow:
    symbol: str
    n_bars: int
    adv_mad: float          # average daily value traded (MAD)
    avg_price: float        # mean close over window
    last_date: str          # ISO date of last bar
    is_tradeable: bool
    exclusion_reason: Optional[str] = None


@dataclass
class ActiveUniverse:
    as_of: str
    tradeable: List[str]
    excluded: List[UniverseRow]
    rows: List[UniverseRow] = field(default_factory=list)

    @property
    def n_tradeable(self) -> int:
        return len(self.tradeable)


def compute_adv(
    prices: pd.DataFrame,
    window: int = 63,
) -> float:
    """Average daily value traded (close × volume) over the last `window` bars.

    If volume is zero or missing, falls back to NaN so the caller can apply
    its own threshold policy (e.g. volume-blind markets use bar-count only).
    """
    if prices.empty:
        return float("nan")

    recent = prices.tail(window)

    close_col = _find_col(recent, ["close", "adj_close", "Close", "AdjClose"])
    vol_col = _find_col(recent, ["volume", "Volume"])

    if close_col is None:
        return float("nan")

    close = recent[close_col].dropna()

    if vol_col is not None:
        vol = recent[vol_col].fillna(0)
        value = close * vol
        traded_days = int((vol > 0).sum())
        if traded_days == 0:
            return float("nan")
        return float(value[vol > 0].mean())
    else:
        return float("nan")


def is_tradeable(
    prices: pd.DataFrame,
    min_bars: int = 252,
    min_adv_mad: float = 0.0,
    min_price: float = 0.0,
    adv_window: int = 63,
) -> tuple[bool, Optional[str]]:
    """Return (tradeable, exclusion_reason).

    For markets where volume is not reliably reported (common for MASI
    small-caps), set min_adv_mad=0 and rely on min_bars alone.
    """
    if prices is None or prices.empty:
        return False, "no_data"

    n_bars = len(prices.dropna(how="all"))
    if n_bars < min_bars:
        return False, f"insufficient_history ({n_bars} < {min_bars})"

    close_col = _find_col(prices, ["close", "adj_close", "Close", "AdjClose"])
    if close_col is None:
        return False, "no_close_column"

    avg_price = float(prices[close_col].tail(63).mean())
    if avg_price < min_price:
        return False, f"price_too_low ({avg_price:.2f} < {min_price})"

    if min_adv_mad > 0:
        adv = compute_adv(prices, window=adv_window)
        if np.isnan(adv):
            pass  # volume not available; don't exclude
        elif adv < min_adv_mad:
            return False, f"adv_too_low ({adv:,.0f} < {min_adv_mad:,.0f})"

    return True, None


def get_active_universe(
    prices_by_symbol: Dict[str, pd.DataFrame],
    min_bars: int = 252,
    min_adv_mad: float = 0.0,
    min_price: float = 5.0,
    adv_window: int = 63,
    as_of: Optional[str] = None,
) -> ActiveUniverse:
    """Filter a dict of OHLCV DataFrames to the active tradeable universe.

    Args:
        prices_by_symbol: mapping symbol → OHLCV DataFrame (indexed by date).
        min_bars: minimum number of rows with data.
        min_adv_mad: minimum average daily value in MAD (0 = disabled).
        min_price: minimum average close price in MAD.
        adv_window: rolling window for ADV computation (bars).
        as_of: optional ISO date string for provenance; defaults to today.

    Returns:
        ActiveUniverse with tradeable list and per-symbol metadata.
    """
    import datetime

    if as_of is None:
        as_of = datetime.date.today().isoformat()

    rows: List[UniverseRow] = []

    for symbol, prices in prices_by_symbol.items():
        tradeable, reason = is_tradeable(
            prices,
            min_bars=min_bars,
            min_adv_mad=min_adv_mad,
            min_price=min_price,
            adv_window=adv_window,
        )

        close_col = _find_col(prices, ["close", "adj_close", "Close", "AdjClose"]) if prices is not None and not prices.empty else None

        n_bars = len(prices.dropna(how="all")) if prices is not None else 0
        adv = compute_adv(prices, window=adv_window) if prices is not None and not prices.empty else float("nan")
        avg_price = float(prices[close_col].tail(63).mean()) if close_col and not prices.empty else float("nan")

        last_date = ""
        if prices is not None and not prices.empty:
            try:
                last_date = str(prices.index[-1])[:10]
            except Exception:
                pass

        rows.append(UniverseRow(
            symbol=symbol,
            n_bars=n_bars,
            adv_mad=adv,
            avg_price=avg_price,
            last_date=last_date,
            is_tradeable=tradeable,
            exclusion_reason=reason,
        ))

    tradeable_symbols = [r.symbol for r in rows if r.is_tradeable]
    excluded_rows = [r for r in rows if not r.is_tradeable]

    return ActiveUniverse(
        as_of=as_of,
        tradeable=sorted(tradeable_symbols),
        excluded=excluded_rows,
        rows=rows,
    )


def _find_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None
