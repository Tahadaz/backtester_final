"""Shared exit-barrier simulation for the WFO exit-treatment comparison.

A trade's *entry* is fixed by the signal (signal turns nonzero). The *exit* is
decided by the active policy:
  - "none"     : exit when the signal flips/zeros (today's behaviour).
  - "atr"      : volatility-scaled stop/take-profit at entry ± k*ATR.
  - "mae_mfe"  : same brackets, but k_sl/k_tp calibrated in-sample from the
                 MAE/MFE distribution of the natural (signal-exit) trades.

Conservative daily first-touch: gap beyond a barrier fills at the bar open;
if both barriers fall inside one bar's range, the stop fills first (pessimistic).
Barriers are scanned from the bar AFTER entry (no entry-bar look-ahead).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class TradeResult:
    entry_idx: int
    exit_idx: int
    direction: float
    gross_return: float
    reason: str          # "signal" | "stop" | "take_profit"
    mae: float           # signed adverse excursion fraction (<=0)
    mfe: float           # signed favourable excursion fraction (>=0)


def wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, window: int = 14) -> np.ndarray:
    """Wilder ATR series aligned to `close` (initial values back-filled)."""
    n = len(close)
    if n == 0:
        return np.zeros(0)
    high = np.asarray(high, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    close = np.asarray(close, dtype=np.float64)
    prev_close = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum.reduce([
        high - low,
        np.abs(high - prev_close),
        np.abs(low - prev_close),
    ])
    atr = np.empty(n, dtype=np.float64)
    if n <= window:
        atr[:] = np.cumsum(tr) / (np.arange(n) + 1.0)
        return atr
    seed = float(np.mean(tr[:window]))
    atr[:window] = seed
    a = seed
    for i in range(window, n):
        a = (a * (window - 1) + tr[i]) / window
        atr[i] = a
    return atr


def segment_trades(signal: np.ndarray) -> list[tuple[int, float, int]]:
    """Yield (entry_idx, direction, natural_end_idx) per trade from a signal array.

    Mirrors wfo_signal._extract_trades: a trade runs from the bar the signal
    becomes nonzero until the bar it flips or zeros (natural exit at that bar's
    close); a flip immediately opens the next trade. Final open trade closes on
    the last bar.
    """
    out: list[tuple[int, float, int]] = []
    n = len(signal)
    in_trade = False
    entry_idx = 0
    direction = 0.0
    for i in range(n):
        s = signal[i]
        if not in_trade and s != 0:
            in_trade = True
            entry_idx = i
            direction = float(np.sign(s))
        elif in_trade and (s == 0 or np.sign(s) != direction):
            out.append((entry_idx, direction, i))
            in_trade = False
            if s != 0 and np.sign(s) != direction:
                in_trade = True
                entry_idx = i
                direction = float(np.sign(s))
    if in_trade and n > 0:
        out.append((entry_idx, direction, n - 1))
    return out


def _excursions(open_: np.ndarray, high: np.ndarray, low: np.ndarray,
                entry_price: float, direction: float, a: int, b: int) -> tuple[float, float]:
    """MAE/MFE over bars (a, b] relative to entry_price (post-entry path)."""
    if entry_price == 0 or b <= a:
        return 0.0, 0.0
    seg_hi = float(np.max(high[a + 1:b + 1]))
    seg_lo = float(np.min(low[a + 1:b + 1]))
    if direction > 0:
        return (seg_lo - entry_price) / entry_price, (seg_hi - entry_price) / entry_price
    return (entry_price - seg_hi) / entry_price, (entry_price - seg_lo) / entry_price


def simulate_exit(
    open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray, atr: np.ndarray,
    *, entry_idx: int, direction: float, natural_end_idx: int,
    policy: str, k_sl: float, k_tp: float,
) -> TradeResult:
    """Resolve one trade's exit under `policy`. Entry fills at close[entry_idx]."""
    entry_price = float(close[entry_idx])
    mae, mfe = _excursions(open_, high, low, entry_price, direction, entry_idx, natural_end_idx)

    def natural() -> TradeResult:
        ret = direction * (float(close[natural_end_idx]) - entry_price) / entry_price if entry_price else 0.0
        return TradeResult(entry_idx, natural_end_idx, direction, ret, "signal", mae, mfe)

    if policy == "none" or entry_price <= 0:
        return natural()
    a = float(atr[entry_idx])
    if a <= 0:
        return natural()

    stop = entry_price - direction * k_sl * a
    tp = entry_price + direction * k_tp * a

    for t in range(entry_idx + 1, natural_end_idx + 1):
        o, hi, lo = float(open_[t]), float(high[t]), float(low[t])
        if direction > 0:
            if o <= stop:
                fill = o
            elif o >= tp:
                fill = o
            elif lo <= stop and hi >= tp:
                fill = stop
            elif lo <= stop:
                fill = stop
            elif hi >= tp:
                fill = tp
            else:
                continue
            reason = "stop" if fill <= entry_price else "take_profit"
        else:
            if o >= stop:
                fill = o
            elif o <= tp:
                fill = o
            elif hi >= stop and lo <= tp:
                fill = stop
            elif hi >= stop:
                fill = stop
            elif lo <= tp:
                fill = tp
            else:
                continue
            reason = "stop" if fill >= entry_price else "take_profit"
        ret = direction * (fill - entry_price) / entry_price
        m_mae, m_mfe = _excursions(open_, high, low, entry_price, direction, entry_idx, t)
        return TradeResult(entry_idx, t, direction, ret, reason, m_mae, m_mfe)

    return natural()


def calibrate_k_mae_mfe(
    natural_trades: list[TradeResult], atr_frac_at_entry: list[float],
    *, k_sl_pct: float = 90.0, k_tp_pct: float = 50.0,
    default_k_sl: float = 1.5, default_k_tp: float = 1.5, min_trades: int = 20,
) -> tuple[float, float]:
    """Derive (k_sl, k_tp) in ATR units from in-sample natural-trade excursions.

    MAE/MFE are price fractions; `atr_frac_at_entry[i]` must be the entry ATR
    expressed as a fraction of entry price (atr/entry_price), so the ratio is in
    ATR units. k_sl = high pct of winning trades' |MAE|/ATR (stop just past where
    winners normally recover); k_tp = median of all trades' MFE/ATR.
    """
    sl_units: list[float] = []
    tp_units: list[float] = []
    for tr, a in zip(natural_trades, atr_frac_at_entry):
        if a <= 0:
            continue
        if tr.mfe > 0:
            tp_units.append(tr.mfe / a)
        if tr.gross_return > 0 and tr.mae < 0:
            sl_units.append(abs(tr.mae) / a)
    if len(sl_units) < min_trades or len(tp_units) < min_trades:
        return default_k_sl, default_k_tp
    k_sl = float(np.clip(np.percentile(sl_units, k_sl_pct), 0.5, 5.0))
    k_tp = float(np.clip(np.percentile(tp_units, k_tp_pct), 0.5, 5.0))
    return k_sl, k_tp
