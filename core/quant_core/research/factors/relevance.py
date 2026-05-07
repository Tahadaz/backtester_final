"""
Descriptive factor-relevance study for Phase 0.

For each (factor, stock) pair, compute:
  - Spearman rank IC between factor daily change and stock 1-day forward return
  - Newey-West t-stat on that IC series
  - Rolling IC stability (coefficient of variation)
  - p-value (two-tailed, under H0: IC=0)

Then aggregate to sector / market level and produce a `FactorRelevanceMatrix`
suitable for the /analytics/factors frontend tab.

All computation is pure numpy + pandas (no scipy).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ...research.alignment import align_factor_to_target
from ...research.stats.ic import _newey_west_var, _spearman_corr


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FactorStockPair:
    """Single (factor, stock) relevance result."""
    factor_id: str
    symbol: str
    ic: float                  # mean IC over the sample
    t_stat: float              # Newey-West t-stat
    p_value: float             # two-tailed p under H0: IC=0
    ic_cv: float               # coefficient of variation (rolling stability)
    n_obs: int
    significant: bool          # |t_stat| > 1.96


@dataclass
class FactorRelevanceMatrix:
    """Full descriptive study for one factor across all tracked stocks."""
    factor_id: str
    as_of: str
    pairs: List[FactorStockPair] = field(default_factory=list)

    @property
    def significant_pairs(self) -> List[FactorStockPair]:
        return [p for p in self.pairs if p.significant]

    def to_records(self) -> List[dict]:
        return [
            {
                "factor_id": p.factor_id,
                "symbol": p.symbol,
                "ic": round(p.ic, 6),
                "t_stat": round(p.t_stat, 4),
                "p_value": round(p.p_value, 6),
                "ic_cv": round(p.ic_cv, 4),
                "n_obs": p.n_obs,
                "significant": p.significant,
            }
            for p in self.pairs
        ]


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _two_tailed_pvalue(t: float) -> float:
    """Approximate two-tailed p-value from t-stat via normal approximation."""
    if not math.isfinite(t):
        return float("nan")
    # P(|Z| > |t|) ≈ 2 * (1 - Φ(|t|))
    abs_t = abs(t)
    # Abramowitz & Stegun rational approximation to erfc
    p = 1.0 - 0.5 * (1.0 + math.erf(abs_t / math.sqrt(2.0)))
    return min(1.0, 2.0 * p)


def compute_ic_series(
    factor: pd.Series,
    target_prices: pd.Series,
    lag_rule: str = "precede_open",
    max_staleness: int = 3,
    forward_horizon: int = 1,
    target_returns: Optional[pd.Series] = None,
) -> pd.Series:
    """Compute per-bar Spearman IC contributions (rank residuals product).

    Returns a Series of per-observation sign(signal)*sign(return) cross-products
    needed to estimate the IC mean and its standard error.  We use the rank
    correlation decomposition: IC = mean(rank(signal) * rank(return)) rescaled.

    For aggregated IC estimation we return the raw pair (rank_s, rank_r) per
    observation and compute the Pearson correlation on ranks in
    `compute_pair_relevance`.

    Args:
        target_returns: pre-computed stock return series. When provided, skips
            the internal pct_change().shift() computation — allows caller to
            supply close_to_open, open_to_close, or open_to_open returns.
    """
    # Align factor to target with no-look-ahead guarantee
    aligned = align_factor_to_target(
        target=target_prices,
        factor=factor,
        lag_rule=lag_rule,
        max_staleness=max_staleness,
    )

    # Factor daily change (return of the factor itself)
    factor_ret = aligned.pct_change(fill_method=None)

    # Stock forward returns — use pre-computed if provided
    if target_returns is not None:
        stock_ret = target_returns
    else:
        stock_ret = target_prices.pct_change(fill_method=None).shift(-forward_horizon)

    common = factor_ret.index.intersection(stock_ret.index)
    f = factor_ret.loc[common].dropna()
    s = stock_ret.loc[common].dropna()

    common2 = f.index.intersection(s.index)
    return pd.DataFrame({"factor": f.loc[common2], "stock": s.loc[common2]}).dropna()


def compute_pair_relevance(
    factor_id: str,
    symbol: str,
    factor: pd.Series,
    stock_prices: pd.Series,
    lag_rule: str = "precede_open",
    max_staleness: int = 3,
    forward_horizon: int = 1,
    nw_bandwidth: int = 5,
    cv_window: int = 63,
    min_obs: int = 30,
    target_returns: Optional[pd.Series] = None,
) -> Optional[FactorStockPair]:
    """Compute full relevance stats for one (factor, stock) pair.

    Returns None if there are fewer than `min_obs` aligned observations.

    Args:
        target_returns: pre-computed stock return series (see compute_ic_series).
    """
    df = compute_ic_series(
        factor=factor,
        target_prices=stock_prices,
        lag_rule=lag_rule,
        max_staleness=max_staleness,
        forward_horizon=forward_horizon,
        target_returns=target_returns,
    )

    if len(df) < min_obs:
        return None

    f_vals = df["factor"].values
    s_vals = df["stock"].values

    # Rank-based IC (Spearman)
    ic = _spearman_corr(pd.Series(f_vals), pd.Series(s_vals))

    if not math.isfinite(ic):
        return None

    # Build IC series for NW std error estimation
    # IC_i ≈ rank(f_i) * rank(s_i) / n  — we approximate by z-scored ranks
    n = len(f_vals)
    f_ranked = pd.Series(f_vals).rank()
    s_ranked = pd.Series(s_vals).rank()
    # Per-obs contribution: demean ranks then multiply
    f_z = (f_ranked - f_ranked.mean()) / (f_ranked.std(ddof=1) + 1e-12)
    s_z = (s_ranked - s_ranked.mean()) / (s_ranked.std(ddof=1) + 1e-12)
    ic_i = (f_z * s_z).values  # unit-variance contribution per obs

    nw_var = _newey_west_var(ic_i, bandwidth=nw_bandwidth)
    nw_se = math.sqrt(max(nw_var, 1e-12) / n)
    t_stat = ic / nw_se if nw_se > 0 else 0.0
    p_value = _two_tailed_pvalue(t_stat)

    # Rolling IC stability
    ic_series = pd.Series(ic_i)
    rolling_ic = ic_series.rolling(cv_window).mean()
    rolling_std = rolling_ic.std(ddof=1)
    rolling_mean = abs(rolling_ic.mean())
    ic_cv = float(rolling_std / rolling_mean) if rolling_mean > 1e-6 else float("nan")

    return FactorStockPair(
        factor_id=factor_id,
        symbol=symbol,
        ic=float(ic),
        t_stat=float(t_stat),
        p_value=float(p_value),
        ic_cv=float(ic_cv) if math.isfinite(ic_cv) else float("nan"),
        n_obs=n,
        significant=abs(t_stat) > 1.96,
    )


def compute_factor_relevance(
    factor_id: str,
    factor_series: pd.Series,
    stock_prices: Dict[str, pd.Series],
    lag_rule: str = "precede_open",
    max_staleness: int = 3,
    forward_horizon: int = 1,
    nw_bandwidth: int = 5,
    cv_window: int = 63,
    min_obs: int = 30,
    as_of: Optional[str] = None,
) -> FactorRelevanceMatrix:
    """Compute factor-relevance for one factor vs all stocks.

    Args:
        factor_id: canonical ID of the macro factor (e.g. "VIX").
        factor_series: daily close prices of the factor (pd.Series indexed by date).
        stock_prices: mapping symbol → daily close prices.
        lag_rule: alignment rule ("precede_open" | "previous_close" | "contemporaneous").
        max_staleness: max consecutive NaN days to forward-fill.
        forward_horizon: forward return horizon in bars (default 1 = 1-day).
        nw_bandwidth: Newey-West lag truncation.
        cv_window: rolling window for IC stability estimation.
        min_obs: skip pairs with fewer aligned observations.
        as_of: provenance date string.

    Returns:
        FactorRelevanceMatrix with one FactorStockPair per stock.
    """
    import datetime

    if as_of is None:
        as_of = datetime.date.today().isoformat()

    pairs: List[FactorStockPair] = []

    for symbol, prices in stock_prices.items():
        result = compute_pair_relevance(
            factor_id=factor_id,
            symbol=symbol,
            factor=factor_series,
            stock_prices=prices,
            lag_rule=lag_rule,
            max_staleness=max_staleness,
            forward_horizon=forward_horizon,
            nw_bandwidth=nw_bandwidth,
            cv_window=cv_window,
            min_obs=min_obs,
        )
        if result is not None:
            pairs.append(result)

    return FactorRelevanceMatrix(factor_id=factor_id, as_of=as_of, pairs=pairs)
