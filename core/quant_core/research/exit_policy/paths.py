"""Intra-trade path reconstruction from stored WFO trades + daily OHLCV.

No-look-ahead guarantee:
  - ATR computed from bars up to and including the entry bar only.
  - S/R computed from bars up to and including the entry bar only.
  - MAE/MFE computed from bars open_date..close_date (the trade window itself).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_ATR_WINDOW = 20


@dataclass
class TradePath:
    symbol: str
    direction: float          # +1.0 long, -1.0 short
    open_date: pd.Timestamp
    close_date: pd.Timestamp
    open_price: float
    close_price: float
    pnl_return: float         # stored natural exit return (Policy A source, no look-ahead)
    bars: pd.DataFrame        # OHLC bars open_date..close_date inclusive; DatetimeIndex; Title-case cols
    atr_entry: float          # ATR(20) up to and including the entry bar
    support: float | None     # entry-time support level (for policies D/E)
    resistance: float | None  # entry-time resistance level
    mae: float                # Maximum Adverse Excursion over the trade window (fraction, signed)
    mfe: float                # Maximum Favorable Excursion over the trade window (fraction, signed)


def _compute_atr_from_history(history: pd.DataFrame) -> float:
    from core.quant_core.strategy_plan.levels import compute_atr

    if len(history) < 2:
        return 0.0
    high = history["High"].values.astype(np.float64)
    low = history["Low"].values.astype(np.float64)
    close = history["Close"].values.astype(np.float64)
    atr_abs, _ = compute_atr(high, low, close, window=_ATR_WINDOW)
    return float(atr_abs)


def _compute_sr_from_history(
    history: pd.DataFrame,
    direction: float,
) -> tuple[float | None, float | None]:
    from core.quant_core.decision.levels import compute_levels_support_resistance

    if len(history) < 10:
        return None, None
    try:
        levels = compute_levels_support_resistance(history, direction=int(direction))
        return levels.get("support"), levels.get("resistance")
    except Exception:
        logger.debug("S/R computation failed", exc_info=True)
        return None, None


def _compute_mae_mfe(bars: pd.DataFrame, direction: float, entry_price: float) -> tuple[float, float]:
    """MAE and MFE over the full bar path, in units of (price / entry_price).

    For longs:  mae = (low_min - entry) / entry  (≤ 0 when adverse)
                mfe = (high_max - entry) / entry  (≥ 0 when favorable)
    For shorts: mae = (entry - high_max) / entry  (≤ 0 when adverse)
                mfe = (entry - low_min)  / entry  (≥ 0 when favorable)
    """
    if bars.empty or entry_price == 0.0:
        return 0.0, 0.0
    low_min = float(bars["Low"].min())
    high_max = float(bars["High"].max())
    if direction >= 0:
        return (low_min - entry_price) / entry_price, (high_max - entry_price) / entry_price
    else:
        return (entry_price - high_max) / entry_price, (entry_price - low_min) / entry_price


def _normalize_ohlcv_index(ohlcv: pd.DataFrame) -> pd.DatetimeIndex:
    """Return a tz-naive, date-normalized DatetimeIndex aligned to ohlcv."""
    idx = ohlcv.index
    if not isinstance(idx, pd.DatetimeIndex):
        idx = pd.to_datetime(idx)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.normalize()


def reconstruct_trade_paths(
    trades: list[dict[str, Any]],
    ohlcv: pd.DataFrame,
    *,
    symbol: str,
    compute_sr: bool = True,
) -> list[TradePath]:
    """Build TradePath list from stored trade dicts + full-history OHLCV.

    Args:
        trades:    List of trade dicts as stored in SignalBacktestRun.trades_json.
                   Each must have: open_date, close_date, open_price, close_price,
                   pnl_return, direction.
        ohlcv:     Full OHLCV DataFrame for the symbol (DatetimeIndex, Title-case cols).
        symbol:    Symbol name (for logging).
        compute_sr: Whether to compute S/R levels (adds latency; needed for policies D/E).

    Returns:
        List of TradePath. Trades whose OHLC cannot be reconstructed are dropped.
    """
    paths: list[TradePath] = []
    dropped = 0
    dates_norm = _normalize_ohlcv_index(ohlcv)

    for trade in trades:
        try:
            direction = float(trade.get("direction", 1.0) or 1.0)
            open_ts = pd.Timestamp(str(trade["open_date"])).normalize()
            close_ts = pd.Timestamp(str(trade["close_date"])).normalize()
            open_price = float(trade["open_price"])
            close_price = float(trade["close_price"])
            pnl_return = float(trade.get("pnl_return", 0.0) or 0.0)

            if open_ts > close_ts:
                dropped += 1
                continue

            # History up to and including entry bar (for ATR + S/R — no look-ahead)
            hist_mask = dates_norm <= open_ts
            history = ohlcv.loc[hist_mask]

            # Trade window bars (for policy simulation and MAE/MFE).
            # Re-index to the tz-naive normalized dates so bar timestamps are
            # comparable with the tz-naive open/close dates inside _first_touch
            # (the raw OHLCV index may be tz-aware).
            win_mask = (dates_norm >= open_ts) & (dates_norm <= close_ts)
            bars = ohlcv.loc[win_mask].copy()
            bars.index = dates_norm[win_mask]

            if bars.empty:
                dropped += 1
                logger.debug("No bars for %s %s..%s", symbol, open_ts.date(), close_ts.date())
                continue

            atr_entry = _compute_atr_from_history(history)
            support, resistance = None, None
            if compute_sr:
                support, resistance = _compute_sr_from_history(history, direction)

            mae, mfe = _compute_mae_mfe(bars, direction, open_price)

            paths.append(TradePath(
                symbol=symbol,
                direction=direction,
                open_date=open_ts,
                close_date=close_ts,
                open_price=open_price,
                close_price=close_price,
                pnl_return=pnl_return,
                bars=bars,
                atr_entry=atr_entry,
                support=support,
                resistance=resistance,
                mae=mae,
                mfe=mfe,
            ))
        except Exception:
            dropped += 1
            logger.debug("Path reconstruction failed for trade %s in %s", trade, symbol, exc_info=True)

    if dropped:
        logger.info(
            "Dropped %d/%d trades for %s (OHLC unavailable or malformed)",
            dropped, dropped + len(paths), symbol,
        )
    return paths
