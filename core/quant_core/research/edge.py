"""Edge metrics — cost-aware gross/net payload for the dashboard.

Pure functions. Imports from `score_history`, `oos_index`, `stats.hit_rate`,
and `..significance` only. No DB, no SQLAlchemy.

Contract: docs/plans/edge-deploy-plan.md §3 (methodology), §4.2.a (module
shape), Amendment E (gross/net pairs).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from ..significance import monte_carlo_label_shuffle_test, monte_carlo_luck_test
from .oos_index import OosSample
from .score_history import BUCKET_NAMES, _bucket_for, _calculate_forward_returns
from .stats.hit_rate import wilson_ci

METHODOLOGY_VERSION = "2026-05-07"
DEFAULT_COST_BPS_PER_SIDE = 33.0
MC_PVALUE_THRESHOLD = 0.01
WILSON_LB_THRESHOLD = 0.50
N_MIN = 30
N_TARGET = 60
MAX_LOOKBACK_YEARS = 3.0

Direction = Literal["long", "short", "none"]
HorizonName = Literal["weekly", "monthly", "quarterly"]
SourceName = Literal["signal_engine", "wfo"]


@dataclass(frozen=True)
class ExpectancyDecomp:
    p_win: float
    avg_win: float
    p_loss: float
    avg_loss: float
    expectancy: float


@dataclass(frozen=True)
class EdgeGates:
    mc_gross: bool
    mc_net: bool
    wilson: bool
    n: bool


@dataclass(frozen=True)
class EdgeMetrics:
    symbol: str
    horizon: HorizonName
    source: SourceName
    bucket: str
    direction: Direction
    n: int
    window_start: pd.Timestamp | None
    window_end: pd.Timestamp | None
    expected_return_gross: float | None
    expected_return_net: float | None
    hit_rate: float | None
    hit_ci_lower: float | None
    hit_ci_upper: float | None
    expectancy_gross: ExpectancyDecomp | None
    expectancy_net: ExpectancyDecomp | None
    edge_ratio_gross: float | None
    edge_ratio_net: float | None
    profit_factor_gross: float | None
    profit_factor_net: float | None
    mc_luck_pvalue_gross: float | None
    mc_luck_pvalue_net: float | None
    label_shuffle_pvalue_gross: float | None
    label_shuffle_pvalue_net: float | None
    proven_edge_gross: bool
    proven_edge_net: bool
    gates: EdgeGates
    cost_bps_per_side: float
    methodology_version: str
    fragility_label: str = "unavailable"
    fragility_fold_count: int = 0
    fragility_details: tuple[dict[str, Any], ...] = ()


# ---------------------------------------------------------------------------
# Direction & strategy-perspective return
# ---------------------------------------------------------------------------

def direction_for_bucket(bucket: str) -> Direction:
    if bucket in ("strong_buy", "buy"):
        return "long"
    if bucket in ("strong_sell", "sell"):
        return "short"
    return "none"


def strategy_return(r: float, direction: Direction, c: float, include_costs: bool) -> float:
    """Per-trade return from the strategy's perspective.

    `c` is per-side cost as a fraction (e.g. 33 bps → 0.0033). Round-trip
    cost = `2*c`. Hold/none returns 0.0 (no trade).
    """
    sign = 1.0 if direction == "long" else (-1.0 if direction == "short" else 0.0)
    if sign == 0.0:
        return 0.0
    gross = sign * float(r)
    return gross - 2.0 * float(c) if include_costs else gross


def _strategy_returns_array(
    raw: np.ndarray, direction: Direction, c: float, *, include_costs: bool,
) -> np.ndarray:
    sign = 1.0 if direction == "long" else (-1.0 if direction == "short" else 0.0)
    if sign == 0.0:
        return np.zeros_like(raw, dtype="float64")
    gross = sign * raw.astype("float64", copy=False)
    return gross - 2.0 * float(c) if include_costs else gross


# ---------------------------------------------------------------------------
# Per-metric primitives — operate on strategy-perspective returns
# ---------------------------------------------------------------------------

def compute_canonical_expectancy(strategy_returns: np.ndarray) -> ExpectancyDecomp:
    r = np.asarray(strategy_returns, dtype="float64")
    n = len(r)
    if n == 0:
        return ExpectancyDecomp(p_win=0.0, avg_win=0.0, p_loss=0.0, avg_loss=0.0, expectancy=0.0)

    wins_mask = r > 0
    losses_mask = ~wins_mask  # zero treated as loss per §3.4

    n_wins = int(wins_mask.sum())
    n_losses = int(losses_mask.sum())
    p_win = n_wins / n
    p_loss = n_losses / n
    avg_win = float(np.mean(r[wins_mask])) if n_wins else 0.0
    avg_loss = float(np.mean(r[losses_mask])) if n_losses else 0.0
    expectancy = p_win * avg_win + p_loss * avg_loss
    return ExpectancyDecomp(
        p_win=float(p_win),
        avg_win=float(avg_win),
        p_loss=float(p_loss),
        avg_loss=float(avg_loss),
        expectancy=float(expectancy),
    )


def compute_profit_factor(strategy_returns: np.ndarray) -> float | None:
    r = np.asarray(strategy_returns, dtype="float64")
    pos_sum = float(np.sum(r[r > 0]))
    neg_sum = float(-np.sum(r[r < 0]))
    if neg_sum <= 0.0:
        return None
    return pos_sum / neg_sum


def compute_edge_ratio(strategy_returns: np.ndarray) -> float | None:
    r = np.asarray(strategy_returns, dtype="float64")
    n = len(r)
    if n < 2:
        return None
    std = float(np.std(r, ddof=1))
    if std <= 0.0 or not np.isfinite(std):
        return None
    return float(np.mean(r)) / std


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _empty_metrics(
    *,
    symbol: str,
    horizon: HorizonName,
    source: SourceName,
    bucket: str,
    direction: Direction,
    n: int,
    cost_bps_per_side: float,
    window_start: pd.Timestamp | None = None,
    window_end: pd.Timestamp | None = None,
    fragility_label: str = "unavailable",
    fragility_fold_count: int = 0,
    fragility_details: tuple[dict[str, Any], ...] = (),
) -> EdgeMetrics:
    gates = EdgeGates(mc_gross=False, mc_net=False, wilson=False, n=(n >= N_MIN))
    return EdgeMetrics(
        symbol=symbol, horizon=horizon, source=source, bucket=bucket,
        direction=direction, n=n,
        window_start=window_start, window_end=window_end,
        expected_return_gross=None, expected_return_net=None,
        hit_rate=None, hit_ci_lower=None, hit_ci_upper=None,
        expectancy_gross=None, expectancy_net=None,
        edge_ratio_gross=None, edge_ratio_net=None,
        profit_factor_gross=None, profit_factor_net=None,
        mc_luck_pvalue_gross=None, mc_luck_pvalue_net=None,
        label_shuffle_pvalue_gross=None, label_shuffle_pvalue_net=None,
        proven_edge_gross=False, proven_edge_net=False,
        gates=gates, cost_bps_per_side=float(cost_bps_per_side),
        methodology_version=METHODOLOGY_VERSION,
        fragility_label=str(fragility_label or "unavailable"),
        fragility_fold_count=int(fragility_fold_count or 0),
        fragility_details=tuple(fragility_details or ()),
    )


def build_edge_payload(
    *,
    symbol: str,
    horizon: HorizonName,
    source: SourceName,
    score_series: pd.Series,
    prices: pd.Series | pd.DataFrame,
    oos_sample: OosSample,
    today_bucket: str,
    fwd_horizon_bars: int,
    cost_bps_per_side: float = DEFAULT_COST_BPS_PER_SIDE,
    n_min: int = N_MIN,
    n_target: int = N_TARGET,
    max_lookback_years: float = MAX_LOOKBACK_YEARS,
    mc_iter: int = 2000,
    mc_seed: int = 42,
    return_calc_method: str = "close_to_close",
    fragility_label: str = "unavailable",
    fragility_fold_count: int = 0,
    fragility_details: tuple[dict[str, Any], ...] = (),
) -> EdgeMetrics:
    """Compute the full Edge payload for one (symbol, horizon, source, bucket)."""
    if today_bucket not in BUCKET_NAMES:
        raise ValueError(f"unknown bucket: {today_bucket!r}")

    direction = direction_for_bucket(today_bucket)
    c = float(cost_bps_per_side) * 1e-4

    # 1. Hold short-circuit — no trade, no metrics.
    if direction == "none":
        return _empty_metrics(
            symbol=symbol, horizon=horizon, source=source, bucket=today_bucket,
            direction=direction, n=0, cost_bps_per_side=cost_bps_per_side,
            fragility_label=fragility_label,
            fragility_fold_count=fragility_fold_count,
            fragility_details=fragility_details,
        )

    # 2. Build aligned (score, fwd_return) frame, filter to OOS dates, then to
    # bars whose own bucket equals today_bucket.
    score = score_series.dropna()
    fwd = _calculate_forward_returns(prices, int(fwd_horizon_bars), method=return_calc_method)
    df = pd.concat(
        [score.rename("score"), pd.Series(fwd, name="fwd")], axis=1,
    ).dropna()

    if oos_sample.dates is not None and len(oos_sample.dates) > 0:
        df = df.loc[df.index.intersection(pd.DatetimeIndex(oos_sample.dates))]

    if df.empty:
        return _empty_metrics(
            symbol=symbol, horizon=horizon, source=source, bucket=today_bucket,
            direction=direction, n=0, cost_bps_per_side=cost_bps_per_side,
            fragility_label=fragility_label,
            fragility_fold_count=fragility_fold_count,
            fragility_details=fragility_details,
        )

    df["bucket"] = df["score"].apply(_bucket_for)
    df = df[df["bucket"] == today_bucket].sort_index()

    if max_lookback_years is not None and not df.empty:
        cutoff = df.index.max() - pd.Timedelta(days=int(365.25 * float(max_lookback_years)))
        df = df[df.index >= cutoff]

    df = df.tail(int(n_target))
    n = int(len(df))
    window_start = pd.Timestamp(df.index.min()) if n else None
    window_end = pd.Timestamp(df.index.max()) if n else None

    if n < int(n_min):
        return _empty_metrics(
            symbol=symbol, horizon=horizon, source=source, bucket=today_bucket,
            direction=direction, n=n, cost_bps_per_side=cost_bps_per_side,
            window_start=window_start, window_end=window_end,
            fragility_label=fragility_label,
            fragility_fold_count=fragility_fold_count,
            fragility_details=fragility_details,
        )

    # 3. Strategy-perspective returns.
    raw = df["fwd"].to_numpy(dtype="float64")
    r_gross = _strategy_returns_array(raw, direction, c, include_costs=False)
    r_net = _strategy_returns_array(raw, direction, c, include_costs=True)

    # 4. Cost-invariant hit rate (sign already flipped → r > 0 == "win").
    hits = int(np.sum(r_gross > 0))
    hit_rate = hits / n
    hit_ci_lower, hit_ci_upper = wilson_ci(hits, n)

    # 5. Gross & net cost-sensitive metrics.
    expectancy_gross = compute_canonical_expectancy(r_gross)
    expectancy_net = compute_canonical_expectancy(r_net)
    edge_ratio_gross = compute_edge_ratio(r_gross)
    edge_ratio_net = compute_edge_ratio(r_net)
    pf_gross = compute_profit_factor(r_gross)
    pf_net = compute_profit_factor(r_net)
    er_gross = float(np.mean(r_gross))
    er_net = float(np.mean(r_net))

    # 6. MC tests. `monte_carlo_luck_test` works on signed strategy returns.
    block_mean = max(2, int(fwd_horizon_bars)) if int(fwd_horizon_bars) > 1 else None
    mc_gross_res = monte_carlo_luck_test(
        r_gross, metric="total_return", n_iter=mc_iter, seed=mc_seed, block_mean=block_mean,
    )
    mc_net_res = monte_carlo_luck_test(
        r_net, metric="total_return", n_iter=mc_iter, seed=mc_seed, block_mean=block_mean,
    )
    mc_luck_pvalue_gross = mc_gross_res.get("pvalue")
    mc_luck_pvalue_net = mc_net_res.get("pvalue")

    # Label-shuffle: permute score-to-date mapping within OOS window;
    # observed = mean of strategy returns in the today-bucket cell.
    shuffle_input_score = score.loc[score.index.intersection(df.index)]
    # For label shuffle we need the *full* OOS-filtered score series (all
    # buckets), so the null can pull non-bucket dates. Reconstruct it.
    full_oos_idx = (
        score.index.intersection(pd.DatetimeIndex(oos_sample.dates))
        if oos_sample.dates is not None and len(oos_sample.dates) > 0
        else score.index
    )
    score_oos = score.loc[full_oos_idx]
    fwd_series = pd.Series(fwd).dropna()
    fwd_oos = fwd_series.loc[fwd_series.index.intersection(full_oos_idx)]
    # Strategy-perspective forward returns for the null distribution
    fwd_strategy_gross = pd.Series(
        _strategy_returns_array(fwd_oos.to_numpy(dtype="float64"), direction, c, include_costs=False),
        index=fwd_oos.index,
    )
    fwd_strategy_net = pd.Series(
        _strategy_returns_array(fwd_oos.to_numpy(dtype="float64"), direction, c, include_costs=True),
        index=fwd_oos.index,
    )
    ls_gross_res = monte_carlo_label_shuffle_test(
        score_oos, fwd_strategy_gross, bucket=today_bucket, n_iter=mc_iter, seed=mc_seed, block_mean=block_mean,
    )
    ls_net_res = monte_carlo_label_shuffle_test(
        score_oos, fwd_strategy_net, bucket=today_bucket, n_iter=mc_iter, seed=mc_seed, block_mean=block_mean,
    )
    label_shuffle_pvalue_gross = ls_gross_res.get("pvalue")
    label_shuffle_pvalue_net = ls_net_res.get("pvalue")

    # 7. Gates.
    gate_n = n >= int(n_min)
    gate_wilson = (hit_ci_lower is not None) and (float(hit_ci_lower) > WILSON_LB_THRESHOLD)
    # MC luck test pvalue is one-sided in the *direction of the observation*,
    # so we additionally require the observed mean to be positive — a
    # cost-shifted negative-mean distribution can yield a low pvalue too, but
    # that is evidence against (not for) a positive edge.
    gate_mc_gross = (
        mc_luck_pvalue_gross is not None
        and float(mc_luck_pvalue_gross) < MC_PVALUE_THRESHOLD
        and er_gross > 0.0
    )
    gate_mc_net = (
        mc_luck_pvalue_net is not None
        and float(mc_luck_pvalue_net) < MC_PVALUE_THRESHOLD
        and er_net > 0.0
    )
    gates = EdgeGates(
        mc_gross=bool(gate_mc_gross),
        mc_net=bool(gate_mc_net),
        wilson=bool(gate_wilson),
        n=bool(gate_n),
    )
    proven_edge_gross = bool(gate_mc_gross and gate_wilson and gate_n)
    proven_edge_net = bool(gate_mc_net and gate_wilson and gate_n)

    return EdgeMetrics(
        symbol=symbol,
        horizon=horizon,
        source=source,
        bucket=today_bucket,
        direction=direction,
        n=n,
        window_start=window_start,
        window_end=window_end,
        expected_return_gross=er_gross,
        expected_return_net=er_net,
        hit_rate=float(hit_rate),
        hit_ci_lower=float(hit_ci_lower) if hit_ci_lower is not None else None,
        hit_ci_upper=float(hit_ci_upper) if hit_ci_upper is not None else None,
        expectancy_gross=expectancy_gross,
        expectancy_net=expectancy_net,
        edge_ratio_gross=edge_ratio_gross,
        edge_ratio_net=edge_ratio_net,
        profit_factor_gross=pf_gross,
        profit_factor_net=pf_net,
        mc_luck_pvalue_gross=float(mc_luck_pvalue_gross) if mc_luck_pvalue_gross is not None else None,
        mc_luck_pvalue_net=float(mc_luck_pvalue_net) if mc_luck_pvalue_net is not None else None,
        label_shuffle_pvalue_gross=float(label_shuffle_pvalue_gross) if label_shuffle_pvalue_gross is not None else None,
        label_shuffle_pvalue_net=float(label_shuffle_pvalue_net) if label_shuffle_pvalue_net is not None else None,
        proven_edge_gross=proven_edge_gross,
        proven_edge_net=proven_edge_net,
        gates=gates,
        cost_bps_per_side=float(cost_bps_per_side),
        methodology_version=METHODOLOGY_VERSION,
        fragility_label=str(fragility_label or "unavailable"),
        fragility_fold_count=int(fragility_fold_count or 0),
        fragility_details=tuple(fragility_details or ()),
    )
