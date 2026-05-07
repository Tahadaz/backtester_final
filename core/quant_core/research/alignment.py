"""Calendar-aware cross-market alignment.

Critical: incorrect alignment is the #1 source of silent look-ahead in
multi-market backtests. See docs/factor-layer/04-calendar-alignment.md.

Lag rules:
- 'precede_open': factor close that PRECEDES each target session open (safest).
  VIX at 21:00 UTC → use for MASI open at 09:00 UTC next day.
- 'previous_close': use prior session's close regardless of clock time.
- 'contemporaneous': same calendar date (only safe when both close before target open).

All functions operate on date-indexed Series (no intraday timestamps).
"""
from __future__ import annotations

from typing import Literal

import pandas as pd

LagRule = Literal["precede_open", "previous_close", "contemporaneous"]


def align_factor_to_target(
    target: pd.Series,
    factor: pd.Series,
    lag_rule: LagRule = "precede_open",
    max_staleness: int = 3,
) -> pd.Series:
    """Align a factor series to the target (MASI stock) session dates.

    Args:
        target: price or return series indexed by session dates (MASI calendar).
                The index is the date on which MASI opens for trading.
        factor: macro factor series (VIX, DXY, etc.), possibly on a different calendar.
                Values are the previous session's close (already lagged by 1 bar by
                convention in yfinance daily download).
        lag_rule: how to match factor observations to target dates.
            'precede_open': factor date d maps to the first target date t such that
                target session t starts AFTER factor close on date d. For US factors
                closing at 21:00 UTC, this means MASI opens the NEXT morning (09:00 UTC).
                Implementation: factor[d] → target[d+1] if d is a factor trading day,
                or target[d] if target is open on d and factor has data.
                In practice for daily data: left-join target dates to factor data,
                then forward-fill up to max_staleness, then shift factor by +1 day
                relative to target so that factor[d] is available at target[d].
            'previous_close': factor is lagged by one calendar position unconditionally.
                factor.shift(1) aligned to target dates.
            'contemporaneous': factor date d maps to target date d directly (no lag).
                Only safe when both markets close before the other's open.

        max_staleness: maximum number of target sessions a forward-filled factor value
            may be stale before being set to NaN (default: 3 sessions).

    Returns:
        pd.Series indexed like target, containing aligned factor values.
        NaN where the factor is unavailable or stale beyond max_staleness.

    No-look-ahead guarantee:
        For 'precede_open' and 'previous_close': factor.align[t] uses only information
        available at market close of day t-1 at the latest.
        For 'contemporaneous': factor.align[t] uses same-day data — caller's responsibility
        to verify the factor closes before the target's open.
    """
    target_idx = target.index
    factor = factor.dropna()

    if lag_rule == "contemporaneous":
        aligned = factor.reindex(target_idx)
        aligned = _forward_fill_with_staleness_guard(aligned, max_staleness)
        return aligned

    elif lag_rule == "previous_close":
        # Lag factor by one position in its own calendar, then align to target
        factor_lagged = factor.shift(1)
        aligned = factor_lagged.reindex(target_idx, method="ffill", limit=max_staleness)
        return aligned

    else:  # precede_open (default, safest)
        # factor[d] is the close of the factor market on trading day d.
        # MASI opens on day d+1 at 09:00 UTC, after factor closes at 21:00 UTC on d.
        # So at MASI target date t, we want the factor close from the LAST factor
        # trading day BEFORE t.
        #
        # Implementation:
        # 1. Shift factor by 1 in its own calendar: factor_prev[d] = factor[d-1 on factor cal].
        #    This converts "factor close on d" to "value available at start of d+1".
        # 2. Reindex to target calendar with ffill (limit=max_staleness) to handle
        #    MASI sessions that fall on US holidays.
        #
        # No-look-ahead proof: after step 1, factor_prev[d] uses data from d-1.
        # After step 2, aligned[t] = factor_prev from the most recent factor date ≤ t,
        # which by step 1 is factor data from strictly before t.
        factor_prev = factor.shift(1)
        aligned = factor_prev.reindex(target_idx, method="ffill", limit=max_staleness)
        return aligned


def _forward_fill_with_staleness_guard(
    series: pd.Series,
    max_staleness: int,
) -> pd.Series:
    """Forward-fill series but set to NaN after max_staleness consecutive stale values."""
    if max_staleness <= 0:
        return series

    result = series.copy()
    stale_count = 0
    last_valid = None

    for i in range(len(result)):
        val = result.iloc[i]
        if pd.isna(val):
            if last_valid is not None and stale_count < max_staleness:
                result.iloc[i] = last_valid
                stale_count += 1
            else:
                stale_count = 0
                last_valid = None
        else:
            last_valid = val
            stale_count = 0

    return result


def align_cross_market(
    target: pd.DataFrame | pd.Series,
    factors: dict[str, pd.Series],
    lag_rules: dict[str, LagRule] | None = None,
    default_lag_rule: LagRule = "precede_open",
    max_staleness: int = 3,
) -> pd.DataFrame:
    """Align multiple factor series to a target market calendar.

    Args:
        target: target price/return series or DataFrame (MASI stock).
                Index = MASI trading dates.
        factors: dict[name -> factor_series].
        lag_rules: per-factor override of lag rule (default: default_lag_rule).
        default_lag_rule: default lag rule for all factors.
        max_staleness: maximum staleness in target sessions before NaN.

    Returns:
        pd.DataFrame with one column per factor, indexed like target.
        All columns are aligned with no look-ahead.
    """
    if isinstance(target, pd.DataFrame):
        target_series = target.iloc[:, 0]
    else:
        target_series = target

    if lag_rules is None:
        lag_rules = {}

    aligned_cols = {}
    for name, factor in factors.items():
        rule = lag_rules.get(name, default_lag_rule)
        aligned_cols[name] = align_factor_to_target(
            target_series, factor, lag_rule=rule, max_staleness=max_staleness
        )

    return pd.DataFrame(aligned_cols, index=target_series.index)
