"""Exit-policy simulators: A (baseline) through E (hybrid ATR+S/R).

Conservative daily first-touch rule (all policies B-E):
  - Gap-through: open beyond barrier → fill at open.
  - Both barriers in range (low ≤ S and high ≥ T): stop first (pessimistic).
  - Single touch: fill at the barrier level.
  - Vertical barrier (bar.date ≥ natural exit): fill at bar.close.
  - No barrier hit throughout path → natural (signal) exit.

No-look-ahead: barriers are computed solely from entry_price and atr_entry,
both of which were fixed at the time the trade opened.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from .paths import TradePath

PolicyName = Literal["A", "B", "C", "D", "E"]

# Default k-grid for B / E variants (k_sl, k_tp ∈ this set)
K_GRID: list[float] = [1.0, 1.5, 2.0, 2.5, 3.0]
DEFAULT_K_SL: float = 1.5
DEFAULT_K_TP: float = 1.5


@dataclass
class ExitResult:
    exit_price: float
    exit_date: pd.Timestamp
    exit_reason: str        # "signal_exit" | "stop_loss" | "take_profit" | "time_exit"
    effective_return: float
    mae: float              # inherited from TradePath (path property, not policy-specific)
    mfe: float


def _pct_return(entry: float, exit_price: float, direction: float) -> float:
    """Signed % return in the direction of the trade."""
    if entry == 0.0:
        return 0.0
    return direction * (exit_price - entry) / abs(entry)


def _first_touch(
    bars: pd.DataFrame,
    *,
    direction: float,
    stop: float | None,
    take_profit: float | None,
    natural_exit_date: pd.Timestamp,
    natural_exit_price: float,
) -> tuple[float, pd.Timestamp, str]:
    """Walk bars in date order; return (fill_price, fill_date, exit_reason).

    Conservative rules (long; mirrored for short):
      1. Gap-through stop: open ≤ S → fill at open, stop_loss
      2. Gap-through TP:   open ≥ T → fill at open, take_profit
      3. Both in range (low ≤ S AND high ≥ T): fill at S, stop_loss  (stop first)
      4. Only stop touched (low ≤ S): fill at S, stop_loss
      5. Only TP touched  (high ≥ T): fill at T, take_profit
      6. Vertical barrier (bar.date ≥ natural_exit_date): fill at bar.close, time_exit
    After all bars without a hit → natural_exit_price / natural_exit_date, signal_exit
    """
    nat_date_norm = natural_exit_date.normalize()

    for bar_ts, row in bars.iterrows():
        bar_date = pd.Timestamp(bar_ts).normalize()
        o = float(row["Open"])
        h = float(row["High"])
        l = float(row["Low"])
        c = float(row["Close"])

        if stop is not None and take_profit is not None:
            if direction > 0:
                if o <= stop:
                    return o, bar_date, "stop_loss"
                if o >= take_profit:
                    return o, bar_date, "take_profit"
                if l <= stop and h >= take_profit:
                    return stop, bar_date, "stop_loss"
                if l <= stop:
                    return stop, bar_date, "stop_loss"
                if h >= take_profit:
                    return take_profit, bar_date, "take_profit"
            else:
                if o >= stop:
                    return o, bar_date, "stop_loss"
                if o <= take_profit:
                    return o, bar_date, "take_profit"
                if h >= stop and l <= take_profit:
                    return stop, bar_date, "stop_loss"
                if h >= stop:
                    return stop, bar_date, "stop_loss"
                if l <= take_profit:
                    return take_profit, bar_date, "take_profit"
        elif stop is not None:
            if direction > 0:
                if o <= stop:
                    return o, bar_date, "stop_loss"
                if l <= stop:
                    return stop, bar_date, "stop_loss"
            else:
                if o >= stop:
                    return o, bar_date, "stop_loss"
                if h >= stop:
                    return stop, bar_date, "stop_loss"
        elif take_profit is not None:
            if direction > 0:
                if o >= take_profit:
                    return o, bar_date, "take_profit"
                if h >= take_profit:
                    return take_profit, bar_date, "take_profit"
            else:
                if o <= take_profit:
                    return o, bar_date, "take_profit"
                if l <= take_profit:
                    return take_profit, bar_date, "take_profit"

        if bar_date >= nat_date_norm:
            return c, bar_date, "time_exit"

    return natural_exit_price, natural_exit_date, "signal_exit"


def _natural(path: TradePath) -> ExitResult:
    """Natural exit (fallback when barriers are degenerate)."""
    return ExitResult(
        exit_price=path.close_price,
        exit_date=path.close_date,
        exit_reason="signal_exit",
        effective_return=path.pnl_return,
        mae=path.mae,
        mfe=path.mfe,
    )


# ── Policy A: baseline ────────────────────────────────────────────────────────

def simulate_A(path: TradePath) -> ExitResult:
    """Baseline: natural signal exit, stored pnl_return unchanged. Null to beat."""
    return _natural(path)


# ── Policy B: ATR triple-barrier (static k) ───────────────────────────────────

def simulate_B(path: TradePath, *, k_sl: float = DEFAULT_K_SL, k_tp: float = DEFAULT_K_TP) -> ExitResult:
    """ATR triple-barrier with static k multiples; vertical = natural exit."""
    atr = path.atr_entry
    if atr <= 0.0 or path.open_price <= 0.0:
        return _natural(path)

    if path.direction > 0:
        stop = path.open_price - k_sl * atr
        tp = path.open_price + k_tp * atr
    else:
        stop = path.open_price + k_sl * atr
        tp = path.open_price - k_tp * atr

    ep, ed, er = _first_touch(
        path.bars,
        direction=path.direction,
        stop=stop,
        take_profit=tp,
        natural_exit_date=path.close_date,
        natural_exit_price=path.close_price,
    )
    return ExitResult(
        exit_price=ep,
        exit_date=ed,
        exit_reason=er,
        effective_return=_pct_return(path.open_price, ep, path.direction),
        mae=path.mae,
        mfe=path.mfe,
    )


# ── Policy C: calibrated triple-barrier (walk-forward k values) ───────────────

def simulate_C(path: TradePath, *, k_sl: float, k_tp: float) -> ExitResult:
    """Calibrated triple-barrier. k_sl/k_tp come from walk-forward calibration."""
    return simulate_B(path, k_sl=k_sl, k_tp=k_tp)


# ── Policy D: S/R-based barriers ──────────────────────────────────────────────

def simulate_D(path: TradePath) -> ExitResult:
    """S/R barriers: long → stop@support, TP@resistance; short reversed."""
    if path.support is None or path.resistance is None:
        return _natural(path)

    if path.direction > 0:
        stop, tp = path.support, path.resistance
        if stop >= path.open_price or tp <= path.open_price:
            return _natural(path)
    else:
        stop, tp = path.resistance, path.support
        if stop <= path.open_price or tp >= path.open_price:
            return _natural(path)

    ep, ed, er = _first_touch(
        path.bars,
        direction=path.direction,
        stop=stop,
        take_profit=tp,
        natural_exit_date=path.close_date,
        natural_exit_price=path.close_price,
    )
    return ExitResult(
        exit_price=ep,
        exit_date=ed,
        exit_reason=er,
        effective_return=_pct_return(path.open_price, ep, path.direction),
        mae=path.mae,
        mfe=path.mfe,
    )


# ── Policy E: hybrid ATR base + S/R overlay ───────────────────────────────────

def simulate_E(
    path: TradePath,
    *,
    k_sl: float = DEFAULT_K_SL,
    k_tp: float = DEFAULT_K_TP,
    min_rr_atr_mult: float = 0.5,
) -> ExitResult:
    """Hybrid: start from B; snap TP down to resistance / stop up to support.

    Snapping only tightens the bracket (not widens it) and only when the
    resulting distance respects the min_rr_atr_mult floor.
    """
    atr = path.atr_entry
    if atr <= 0.0 or path.open_price <= 0.0:
        return _natural(path)

    if path.direction > 0:
        stop = path.open_price - k_sl * atr
        tp = path.open_price + k_tp * atr
        floor = min_rr_atr_mult * atr
        if path.support is not None:
            cand = path.support
            if stop < cand < path.open_price and (path.open_price - cand) >= floor:
                stop = cand
        if path.resistance is not None:
            cand = path.resistance
            if path.open_price < cand < tp and (cand - path.open_price) >= floor:
                tp = cand
    else:
        stop = path.open_price + k_sl * atr
        tp = path.open_price - k_tp * atr
        floor = min_rr_atr_mult * atr
        if path.resistance is not None:
            cand = path.resistance
            if path.open_price < cand < stop and (cand - path.open_price) >= floor:
                stop = cand
        if path.support is not None:
            cand = path.support
            if tp < cand < path.open_price and (path.open_price - cand) >= floor:
                tp = cand

    ep, ed, er = _first_touch(
        path.bars,
        direction=path.direction,
        stop=stop,
        take_profit=tp,
        natural_exit_date=path.close_date,
        natural_exit_price=path.close_price,
    )
    return ExitResult(
        exit_price=ep,
        exit_date=ed,
        exit_reason=er,
        effective_return=_pct_return(path.open_price, ep, path.direction),
        mae=path.mae,
        mfe=path.mfe,
    )
