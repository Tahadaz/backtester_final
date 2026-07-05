"""Edge metrics — cost-aware gross/net payload for the dashboard.

Pure functions. Imports from `score_history`, `oos_index`, `stats.hit_rate`,
and `..significance` only. No DB, no SQLAlchemy.

Contract: see docs/EDGE_METHOD.md for methodology and gross/net semantics.
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

METHODOLOGY_VERSION = "2026-07-05-net-edge-score-v2"
DEFAULT_COST_BPS_PER_SIDE = 33.0
MC_PVALUE_THRESHOLD = 0.05
LABEL_SHUFFLE_PVALUE_THRESHOLD = 0.05
WILSON_LB_THRESHOLD = 0.50
N_MIN = 30
N_TARGET = 60
EDGE_MAX_OBSERVATIONS = 100
MAX_LOOKBACK_YEARS = 3.0
FRESHNESS_MIN_N = 10
_USE_HORIZON_LOOKBACK = object()

Direction = Literal["long", "short", "none"]
HorizonName = Literal["weekly", "monthly", "quarterly"]
SourceName = Literal["signal_engine", "wfo"]
PriceKind = Literal["open", "close"]


@dataclass(frozen=True)
class ExitCandidate:
    horizon_bars: int
    exit_price_kind: PriceKind
    return_calc_method: str

    @property
    def entry_price_kind(self) -> PriceKind:
        if self.return_calc_method == "close_to_close":
            return "close"
        if self.return_calc_method == "close_to_open":
            return "close"
        return "open"

    @property
    def entry_lag_bars(self) -> int:
        return 0 if self.entry_price_kind == "close" else 1

    @property
    def exit_lag_bars(self) -> int:
        return int(self.horizon_bars)

    @property
    def time_rank(self) -> int:
        intra_rank = 0 if self.exit_price_kind == "open" else 1
        return int(self.horizon_bars) * 2 + intra_rank

    @property
    def label(self) -> str:
        return f"J+{int(self.horizon_bars)} {self.exit_price_kind.capitalize()}"


@dataclass(frozen=True)
class ExpectancyDecomp:
    p_win: float
    avg_win: float
    p_loss: float
    avg_loss: float
    expectancy: float


@dataclass(frozen=True)
class EdgeRecencyPolicy:
    proof_max_lookback_years: float
    freshness_lookback_years: float
    freshness_min_n: int = FRESHNESS_MIN_N


EDGE_RECENCY_POLICIES: dict[HorizonName, EdgeRecencyPolicy] = {
    "weekly": EdgeRecencyPolicy(proof_max_lookback_years=1.0, freshness_lookback_years=0.25),
    "monthly": EdgeRecencyPolicy(proof_max_lookback_years=2.0, freshness_lookback_years=0.5),
    "quarterly": EdgeRecencyPolicy(proof_max_lookback_years=3.0, freshness_lookback_years=1.0),
}


@dataclass(frozen=True)
class EdgeGates:
    mc_gross: bool
    mc_net: bool
    label_shuffle_gross: bool
    label_shuffle_net: bool
    wilson: bool
    n: bool
    freshness_gross: bool = False
    freshness_net: bool = False


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
    fwd_horizon_bars: int | None
    return_calc_method: str
    holding_period_min_bars: int | None
    holding_period_max_bars: int | None
    holding_period_candidate_count: int
    holding_period_selection_metric: str
    side_policy: str
    action_expected_return_gross: float | None
    action_expected_return_gross_ci_lower: float | None
    action_expected_return_gross_ci_upper: float | None
    action_expected_return_net: float | None
    action_expected_return_net_ci_lower: float | None
    action_expected_return_net_ci_upper: float | None
    stock_expected_return: float | None
    stock_expected_return_ci_lower: float | None
    stock_expected_return_ci_upper: float | None
    expected_return_gross: float | None
    expected_return_gross_ci_lower: float | None
    expected_return_gross_ci_upper: float | None
    expected_return_net: float | None
    expected_return_net_ci_lower: float | None
    expected_return_net_ci_upper: float | None
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
    edge_score: float | None
    edge_score_components: dict[str, float]
    gates: EdgeGates
    cost_bps_per_side: float
    methodology_version: str
    proof_max_lookback_years: float | None = None
    freshness_lookback_years: float | None = None
    freshness_min_n: int = FRESHNESS_MIN_N
    freshness_n: int = 0
    freshness_window_start: pd.Timestamp | None = None
    freshness_window_end: pd.Timestamp | None = None
    freshness_action_expected_return_gross: float | None = None
    freshness_action_expected_return_net: float | None = None
    freshness_hit_rate: float | None = None
    freshness_status: str = "unavailable"
    fragility_label: str = "unavailable"
    fragility_fold_count: int = 0
    fragility_details: tuple[dict[str, Any], ...] = ()
    variant: str = "expanded_ta_simple"
    selection_n: int = 0
    selection_window_start: pd.Timestamp | None = None
    selection_window_end: pd.Timestamp | None = None
    selection_action_expected_return_gross: float | None = None
    selection_action_expected_return_net: float | None = None
    selection_hit_rate: float | None = None
    proof_n: int = 0
    proof_window_start: pd.Timestamp | None = None
    proof_window_end: pd.Timestamp | None = None
    proof_method: str = "same_oos_sample"
    multiple_testing_count: int = 1
    mc_luck_pvalue_gross_adj: float | None = None
    mc_luck_pvalue_net_adj: float | None = None
    label_shuffle_pvalue_gross_adj: float | None = None
    label_shuffle_pvalue_net_adj: float | None = None
    entry_price_kind: str = "open"
    entry_lag_bars: int = 1
    exit_price_kind: str = "open"
    exit_lag_bars: int | None = None
    exit_timing_label: str = ""


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


def edge_recency_policy(horizon: str) -> EdgeRecencyPolicy:
    token = str(horizon or "").strip().lower()
    return EDGE_RECENCY_POLICIES.get(token, EDGE_RECENCY_POLICIES["quarterly"])  # type: ignore[arg-type]


def _resolve_proof_max_lookback_years(
    horizon: str,
    max_lookback_years: float | None | object,
) -> float | None:
    if max_lookback_years is _USE_HORIZON_LOOKBACK:
        return edge_recency_policy(horizon).proof_max_lookback_years
    return None if max_lookback_years is None else float(max_lookback_years)


def _candidate_days(values: tuple[int, ...] | list[int] | None, fallback: int) -> tuple[int, ...]:
    cleaned = sorted({int(v) for v in (values or ()) if int(v) > 0})
    if cleaned:
        return tuple(cleaned)
    return (int(fallback),)


def _legacy_exit_price_kind(return_calc_method: str) -> PriceKind:
    if return_calc_method in {"open_to_open", "close_to_open"}:
        return "open"
    return "close"


def _exit_candidates(
    values: tuple[int, ...] | list[int] | None,
    fallback: int,
    return_calc_method: str,
) -> tuple[ExitCandidate, ...]:
    days = _candidate_days(values, fallback)
    if return_calc_method == "open_to_exit_ladder":
        out: list[ExitCandidate] = []
        for h in days:
            h = int(h)
            if h > 1:
                out.append(ExitCandidate(horizon_bars=h, exit_price_kind="open", return_calc_method=return_calc_method))
            out.append(ExitCandidate(horizon_bars=h, exit_price_kind="close", return_calc_method=return_calc_method))
        return tuple(out)
    return tuple(
        ExitCandidate(
            horizon_bars=int(h),
            exit_price_kind=_legacy_exit_price_kind(return_calc_method),
            return_calc_method=return_calc_method,
        )
        for h in days
    )


def _normalized_price_frame(prices: pd.Series | pd.DataFrame) -> pd.DataFrame:
    if isinstance(prices, pd.Series):
        s = prices.dropna()
        return pd.DataFrame({"open": s, "close": s}, index=s.index)
    p = prices.copy()
    p.columns = [str(c).lower() for c in p.columns]
    if "close" not in p.columns:
        if "adj close" in p.columns:
            p["close"] = p["adj close"]
        else:
            p["close"] = p.iloc[:, 0]
    if "open" not in p.columns:
        p["open"] = p["close"]
    return p


def _calculate_exit_returns(
    prices: pd.Series | pd.DataFrame,
    candidate: ExitCandidate,
) -> pd.Series:
    if candidate.return_calc_method != "open_to_exit_ladder":
        return _calculate_forward_returns(
            prices,
            int(candidate.horizon_bars),
            method=candidate.return_calc_method,
        )
    if isinstance(prices, pd.Series):
        # Without OHLC data there is no observable Open(T+1) entry. Keep the
        # legacy close-to-close fallback for synthetic callers and old tests.
        return _calculate_forward_returns(prices, int(candidate.horizon_bars), method="close_to_close")
    p = _normalized_price_frame(prices)
    entry = p["open"].shift(-1)
    exit_series = p[candidate.exit_price_kind].shift(-int(candidate.horizon_bars))
    return (exit_series / entry) - 1.0


def _sample_frames(
    *,
    score_series: pd.Series,
    prices: pd.Series | pd.DataFrame,
    oos_sample: OosSample,
    today_bucket: str,
    fwd_horizon_bars: int,
    return_calc_method: str,
    max_lookback_years: float | None,
    n_target: int | None,
    exit_candidate: ExitCandidate | None = None,
    lookback_anchor: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    target_n = None if n_target is None else max(0, min(int(n_target), int(EDGE_MAX_OBSERVATIONS)))
    score = score_series.dropna()
    candidate = exit_candidate or _exit_candidates(
        (int(fwd_horizon_bars),),
        int(fwd_horizon_bars),
        return_calc_method,
    )[0]
    fwd = _calculate_exit_returns(prices, candidate)
    df = pd.concat(
        [score.rename("score"), pd.Series(fwd, name="fwd")], axis=1,
    ).dropna()

    if oos_sample.dates is not None and len(oos_sample.dates) > 0:
        df = df.loc[df.index.intersection(pd.DatetimeIndex(oos_sample.dates))]

    if df.empty:
        return df, df

    df["bucket"] = df["score"].apply(_bucket_for)
    full_oos_df = df.sort_index()
    bucket_df = full_oos_df[full_oos_df["bucket"] == today_bucket].sort_index()

    if max_lookback_years is not None and not full_oos_df.empty:
        anchor = pd.Timestamp(lookback_anchor) if lookback_anchor is not None else pd.Timestamp(full_oos_df.index.max())
        cutoff = anchor - pd.Timedelta(days=int(365.25 * float(max_lookback_years)))
        bucket_df = bucket_df[bucket_df.index >= cutoff]

    if target_n is not None:
        bucket_df = bucket_df.tail(target_n)
    return full_oos_df, bucket_df


def select_optimal_holding_period(
    *,
    score_series: pd.Series,
    prices: pd.Series | pd.DataFrame,
    oos_sample: OosSample,
    today_bucket: str,
    direction: Direction,
    candidates: tuple[int, ...],
    fallback_horizon_bars: int,
    cost_bps_per_side: float,
    n_min: int = N_MIN,
    n_target: int = N_TARGET,
    max_lookback_years: float = MAX_LOOKBACK_YEARS,
    return_calc_method: str = "close_to_close",
) -> int:
    """Select the best holding period using net action mean over the candidate grid.

    The final Edge payload is still computed only for the selected day count.
    Ties prefer higher hit rate, then shorter holding period.
    """
    candidate_days = _candidate_days(list(candidates), fallback_horizon_bars)
    if direction == "none":
        return int(fallback_horizon_bars)

    c = float(cost_bps_per_side) * 1e-4
    best: tuple[float, float, int, int] | None = None
    fallback: tuple[int, float, float, int] | None = None

    for h in candidate_days:
        _full, df = _sample_frames(
            score_series=score_series,
            prices=prices,
            oos_sample=oos_sample,
            today_bucket=today_bucket,
            fwd_horizon_bars=h,
            return_calc_method=return_calc_method,
            max_lookback_years=max_lookback_years,
            n_target=n_target,
        )
        n = int(len(df))
        if n <= 0:
            continue
        raw = df["fwd"].to_numpy(dtype="float64")
        r_gross = _strategy_returns_array(raw, direction, c, include_costs=False)
        r_net = _strategy_returns_array(raw, direction, c, include_costs=True)
        mean_net = float(np.mean(r_net))
        hit_rate = float(np.mean(r_gross > 0.0))

        fallback_key = (n, mean_net, hit_rate, -int(h))
        if fallback is None or fallback_key > fallback:
            fallback = fallback_key

        if n < int(n_min):
            continue
        key = (mean_net, hit_rate, -int(h), n)
        if best is None or key > best:
            best = key

    if best is not None:
        return int(-best[2])
    if fallback is not None:
        return int(-fallback[3])
    return int(fallback_horizon_bars)


def select_optimal_exit_candidate(
    *,
    score_series: pd.Series,
    prices: pd.Series | pd.DataFrame,
    oos_sample: OosSample,
    today_bucket: str,
    direction: Direction,
    candidates: tuple[ExitCandidate, ...],
    fallback_horizon_bars: int,
    cost_bps_per_side: float,
    n_min: int = N_MIN,
    n_target: int = N_TARGET,
    max_lookback_years: float = MAX_LOOKBACK_YEARS,
) -> ExitCandidate:
    """Select the best Open(T+1) exit candidate using net action mean."""
    if not candidates:
        candidates = _exit_candidates(None, int(fallback_horizon_bars), "open_to_exit_ladder")
    if direction == "none":
        return candidates[0]

    c = float(cost_bps_per_side) * 1e-4
    best: tuple[float, float, int, int] | None = None
    best_candidate: ExitCandidate | None = None
    fallback: tuple[int, float, float, int] | None = None
    fallback_candidate: ExitCandidate | None = None

    for candidate in candidates:
        _full, df = _sample_frames(
            score_series=score_series,
            prices=prices,
            oos_sample=oos_sample,
            today_bucket=today_bucket,
            fwd_horizon_bars=candidate.horizon_bars,
            return_calc_method=candidate.return_calc_method,
            max_lookback_years=max_lookback_years,
            n_target=n_target,
            exit_candidate=candidate,
        )
        n = int(len(df))
        if n <= 0:
            continue
        raw = df["fwd"].to_numpy(dtype="float64")
        r_gross = _strategy_returns_array(raw, direction, c, include_costs=False)
        r_net = _strategy_returns_array(raw, direction, c, include_costs=True)
        mean_net = float(np.mean(r_net))
        hit_rate = float(np.mean(r_gross > 0.0))

        fallback_key = (n, mean_net, hit_rate, -candidate.time_rank)
        if fallback is None or fallback_key > fallback:
            fallback = fallback_key
            fallback_candidate = candidate

        if n < int(n_min):
            continue
        key = (mean_net, hit_rate, -candidate.time_rank, n)
        if best is None or key > best:
            best = key
            best_candidate = candidate

    if best_candidate is not None:
        return best_candidate
    if fallback_candidate is not None:
        return fallback_candidate
    return candidates[0]


def _same_dates(a: pd.DatetimeIndex | None, b: pd.DatetimeIndex | None) -> bool:
    a_idx = pd.DatetimeIndex([] if a is None else a).sort_values()
    b_idx = pd.DatetimeIndex([] if b is None else b).sort_values()
    return bool(a_idx.equals(b_idx))


def _adjust_pvalue(pvalue: float | None, multiple_testing_count: int) -> float | None:
    if pvalue is None:
        return None
    try:
        p = float(pvalue)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(p):
        return None
    return float(min(1.0, max(0.0, p) * max(1, int(multiple_testing_count))))


def _selection_summary(
    df: pd.DataFrame,
    *,
    direction: Direction,
    cost_bps_per_side: float,
) -> dict[str, Any]:
    n = int(len(df))
    if n <= 0 or direction == "none":
        return {
            "n": n,
            "window_start": None,
            "window_end": None,
            "gross": None,
            "net": None,
            "hit_rate": None,
        }
    c = float(cost_bps_per_side) * 1e-4
    raw = df["fwd"].to_numpy(dtype="float64")
    r_gross = _strategy_returns_array(raw, direction, c, include_costs=False)
    r_net = _strategy_returns_array(raw, direction, c, include_costs=True)
    return {
        "n": n,
        "window_start": pd.Timestamp(df.index.min()),
        "window_end": pd.Timestamp(df.index.max()),
        "gross": float(np.mean(r_gross)),
        "net": float(np.mean(r_net)),
        "hit_rate": float(np.mean(r_gross > 0.0)),
    }


# ---------------------------------------------------------------------------
# Per-metric primitives — operate on strategy-perspective returns
# ---------------------------------------------------------------------------

def _freshness_summary(
    df: pd.DataFrame,
    *,
    direction: Direction,
    cost_bps_per_side: float,
    min_n: int,
) -> dict[str, Any]:
    summary = _selection_summary(
        df,
        direction=direction,
        cost_bps_per_side=cost_bps_per_side,
    )
    n = int(summary["n"] or 0)
    gross = summary["gross"]
    net = summary["net"]
    hit_rate = summary["hit_rate"]
    gross_pass = bool(
        n >= int(min_n)
        and gross is not None
        and gross > 0.0
        and hit_rate is not None
        and hit_rate >= 0.50
    )
    net_pass = bool(
        n >= int(min_n)
        and net is not None
        and net > 0.0
        and hit_rate is not None
        and hit_rate >= 0.50
    )
    if direction == "none":
        status = "not_actionable"
    elif n < int(min_n):
        status = "insufficient_n"
    else:
        status = "passed" if net_pass else "failed"
    return {
        **summary,
        "status": status,
        "gross_pass": gross_pass,
        "net_pass": net_pass,
    }


def _score_clamp(value: float) -> float:
    if not np.isfinite(value):
        return 0.0
    return float(max(0.0, min(100.0, value)))


def _finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _pvalue_component_score(pvalue: float | None, threshold: float) -> float:
    p = _finite_float(pvalue)
    if p is None:
        return 0.0
    p = max(0.0, min(1.0, p))
    t = max(float(threshold), 1e-9)
    if p <= t:
        return _score_clamp(50.0 + 50.0 * ((t - p) / t))
    return _score_clamp(50.0 * (1.0 - ((p - t) / max(1.0 - t, 1e-9))))


def _centered_threshold_score(value: float | None, *, center: float, span: float) -> float:
    v = _finite_float(value)
    if v is None:
        return 0.0
    half = max(float(span) / 2.0, 1e-9)
    return _score_clamp(50.0 + 50.0 * ((v - float(center)) / half))


def _bootstrap_expectancy_component_score(
    mean_net: float | None,
    lower_net: float | None,
) -> float:
    mean = _finite_float(mean_net)
    if mean is None or mean <= 0.0:
        return 0.0
    lower = _finite_float(lower_net)
    if lower is None:
        return 50.0
    if lower >= 0.0:
        base = abs(mean) if abs(mean) > 1e-12 else max(abs(lower), 1e-12)
        return _score_clamp(75.0 + 25.0 * min(1.0, lower / base))
    return _score_clamp(60.0 * (mean / (mean + abs(lower))))


def compute_edge_score(
    *,
    bucket: str,
    direction: Direction | str,
    n: int,
    action_expected_return_net: float | None,
    action_expected_return_net_ci_lower: float | None,
    hit_ci_lower: float | None,
    mc_luck_pvalue_net_adj: float | None,
    label_shuffle_pvalue_net_adj: float | None,
    freshness_n: int,
    freshness_min_n: int,
    freshness_action_expected_return_net: float | None,
    freshness_hit_rate: float | None,
    n_target: int = N_TARGET,
) -> tuple[float | None, dict[str, float]]:
    """Return a net-only 0-100 Edge ranking score plus component scores.

    The score is intentionally separate from `proven_edge_net`: it grades how
    strongly the current action satisfies the proof dimensions without changing
    the binary proven-edge methodology.
    """
    bucket_key = str(bucket or "").strip().lower()
    direction_key = str(direction or "").strip().lower()
    actionable = (
        (bucket_key in {"buy", "strong_buy"} and direction_key == "long")
        or (bucket_key in {"sell", "strong_sell"} and direction_key == "short")
    )
    if not actionable:
        return None, {}

    sample_n = _score_clamp(100.0 * max(0, int(n or 0)) / max(1, int(n_target)))
    bootstrap_er = _bootstrap_expectancy_component_score(
        action_expected_return_net,
        action_expected_return_net_ci_lower,
    )
    wilson = _centered_threshold_score(hit_ci_lower, center=WILSON_LB_THRESHOLD, span=0.30)
    mc_luck = _pvalue_component_score(mc_luck_pvalue_net_adj, MC_PVALUE_THRESHOLD)
    label_shuffle = _pvalue_component_score(label_shuffle_pvalue_net_adj, LABEL_SHUFFLE_PVALUE_THRESHOLD)

    fresh_n = _score_clamp(
        100.0 * max(0, int(freshness_n or 0)) / max(1, int(freshness_min_n or FRESHNESS_MIN_N))
    )
    fresh_er = 100.0 if (_finite_float(freshness_action_expected_return_net) or 0.0) > 0.0 else 0.0
    fresh_hit = _centered_threshold_score(freshness_hit_rate, center=0.50, span=0.30)
    freshness = _score_clamp((fresh_n + fresh_er + fresh_hit) / 3.0)

    components = {
        "sample_n": round(sample_n, 2),
        "bootstrap_er": round(bootstrap_er, 2),
        "wilson": round(wilson, 2),
        "mc_luck": round(mc_luck, 2),
        "label_shuffle": round(label_shuffle, 2),
        "freshness": round(freshness, 2),
    }
    score = sum(components.values()) / len(components)
    mean_net = _finite_float(action_expected_return_net)
    if mean_net is None or mean_net <= 0.0:
        score = min(score, 5.0)
    return round(_score_clamp(score), 2), components


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


def bootstrap_mean_ci(
    strategy_returns: np.ndarray,
    *,
    alpha: float = 0.05,
    n_iter: int = 2000,
    seed: int = 42,
) -> tuple[float | None, float | None]:
    r = np.asarray(strategy_returns, dtype="float64")
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 2:
        return None, None
    rng = np.random.default_rng(seed)
    samples = rng.choice(r, size=(int(n_iter), n), replace=True)
    means = samples.mean(axis=1)
    return (
        float(np.quantile(means, alpha / 2.0)),
        float(np.quantile(means, 1.0 - alpha / 2.0)),
    )


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
    fwd_horizon_bars: int | None,
    return_calc_method: str,
    holding_period_candidates: tuple[ExitCandidate, ...],
    holding_period_selection_metric: str,
    window_start: pd.Timestamp | None = None,
    window_end: pd.Timestamp | None = None,
    fragility_label: str = "unavailable",
    fragility_fold_count: int = 0,
    fragility_details: tuple[dict[str, Any], ...] = (),
    variant: str = "expanded_ta_simple",
    selection_n: int = 0,
    selection_window_start: pd.Timestamp | None = None,
    selection_window_end: pd.Timestamp | None = None,
    selection_action_expected_return_gross: float | None = None,
    selection_action_expected_return_net: float | None = None,
    selection_hit_rate: float | None = None,
    proof_method: str = "same_oos_sample",
    multiple_testing_count: int = 1,
    selected_exit_candidate: ExitCandidate | None = None,
    proof_max_lookback_years: float | None = None,
    freshness_lookback_years: float | None = None,
    freshness_min_n: int = FRESHNESS_MIN_N,
    freshness_n: int = 0,
    freshness_window_start: pd.Timestamp | None = None,
    freshness_window_end: pd.Timestamp | None = None,
    freshness_action_expected_return_gross: float | None = None,
    freshness_action_expected_return_net: float | None = None,
    freshness_hit_rate: float | None = None,
    freshness_status: str = "unavailable",
) -> EdgeMetrics:
    selected = selected_exit_candidate or (
        holding_period_candidates[0] if holding_period_candidates else None
    )
    candidate_days = tuple(c.horizon_bars for c in holding_period_candidates)
    gates = EdgeGates(
        mc_gross=False,
        mc_net=False,
        label_shuffle_gross=False,
        label_shuffle_net=False,
        wilson=False,
        n=(n >= N_MIN),
        freshness_gross=False,
        freshness_net=False,
    )
    edge_score, edge_score_components = compute_edge_score(
        bucket=bucket,
        direction=direction,
        n=n,
        action_expected_return_net=None,
        action_expected_return_net_ci_lower=None,
        hit_ci_lower=None,
        mc_luck_pvalue_net_adj=None,
        label_shuffle_pvalue_net_adj=None,
        freshness_n=freshness_n,
        freshness_min_n=freshness_min_n,
        freshness_action_expected_return_net=freshness_action_expected_return_net,
        freshness_hit_rate=freshness_hit_rate,
    )
    return EdgeMetrics(
        symbol=symbol, horizon=horizon, source=source, bucket=bucket,
        direction=direction, n=n,
        window_start=window_start, window_end=window_end,
        fwd_horizon_bars=selected.horizon_bars if selected else fwd_horizon_bars,
        return_calc_method=selected.return_calc_method if selected else return_calc_method,
        holding_period_min_bars=min(candidate_days) if candidate_days else None,
        holding_period_max_bars=max(candidate_days) if candidate_days else None,
        holding_period_candidate_count=len(holding_period_candidates),
        holding_period_selection_metric=holding_period_selection_metric,
        side_policy="long_short",
        action_expected_return_gross=None,
        action_expected_return_gross_ci_lower=None,
        action_expected_return_gross_ci_upper=None,
        action_expected_return_net=None,
        action_expected_return_net_ci_lower=None,
        action_expected_return_net_ci_upper=None,
        stock_expected_return=None,
        stock_expected_return_ci_lower=None,
        stock_expected_return_ci_upper=None,
        expected_return_gross=None,
        expected_return_gross_ci_lower=None,
        expected_return_gross_ci_upper=None,
        expected_return_net=None,
        expected_return_net_ci_lower=None,
        expected_return_net_ci_upper=None,
        hit_rate=None, hit_ci_lower=None, hit_ci_upper=None,
        expectancy_gross=None, expectancy_net=None,
        edge_ratio_gross=None, edge_ratio_net=None,
        profit_factor_gross=None, profit_factor_net=None,
        mc_luck_pvalue_gross=None, mc_luck_pvalue_net=None,
        label_shuffle_pvalue_gross=None, label_shuffle_pvalue_net=None,
        proven_edge_gross=False, proven_edge_net=False,
        edge_score=edge_score,
        edge_score_components=edge_score_components,
        gates=gates, cost_bps_per_side=float(cost_bps_per_side),
        methodology_version=METHODOLOGY_VERSION,
        proof_max_lookback_years=proof_max_lookback_years,
        freshness_lookback_years=freshness_lookback_years,
        freshness_min_n=int(freshness_min_n),
        freshness_n=int(freshness_n or 0),
        freshness_window_start=freshness_window_start,
        freshness_window_end=freshness_window_end,
        freshness_action_expected_return_gross=freshness_action_expected_return_gross,
        freshness_action_expected_return_net=freshness_action_expected_return_net,
        freshness_hit_rate=freshness_hit_rate,
        freshness_status=str(freshness_status or "unavailable"),
        fragility_label=str(fragility_label or "unavailable"),
        fragility_fold_count=int(fragility_fold_count or 0),
        fragility_details=tuple(fragility_details or ()),
        variant=str(variant or "expanded_ta_simple"),
        selection_n=int(selection_n or 0),
        selection_window_start=selection_window_start,
        selection_window_end=selection_window_end,
        selection_action_expected_return_gross=selection_action_expected_return_gross,
        selection_action_expected_return_net=selection_action_expected_return_net,
        selection_hit_rate=selection_hit_rate,
        proof_n=int(n or 0),
        proof_window_start=window_start,
        proof_window_end=window_end,
        proof_method=str(proof_method or "same_oos_sample"),
        multiple_testing_count=max(1, int(multiple_testing_count or 1)),
        entry_price_kind=selected.entry_price_kind if selected else "open",
        entry_lag_bars=selected.entry_lag_bars if selected else 1,
        exit_price_kind=selected.exit_price_kind if selected else "open",
        exit_lag_bars=selected.exit_lag_bars if selected else fwd_horizon_bars,
        exit_timing_label=selected.label if selected else "",
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
    holding_period_candidates: tuple[int, ...] | list[int] | None = None,
    cost_bps_per_side: float = DEFAULT_COST_BPS_PER_SIDE,
    n_min: int = N_MIN,
    n_target: int = N_TARGET,
    max_lookback_years: float | None | object = _USE_HORIZON_LOOKBACK,
    mc_iter: int = 2000,
    mc_seed: int = 42,
    return_calc_method: str = "open_to_exit_ladder",
    fragility_label: str = "unavailable",
    fragility_fold_count: int = 0,
    fragility_details: tuple[dict[str, Any], ...] = (),
    variant: str = "expanded_ta_simple",
    selection_oos_sample: OosSample | None = None,
    multiple_testing_count: int = 1,
) -> EdgeMetrics:
    """Compute the full Edge payload for one (symbol, horizon, source, bucket)."""
    if today_bucket not in BUCKET_NAMES:
        raise ValueError(f"unknown bucket: {today_bucket!r}")

    recency_policy = edge_recency_policy(horizon)
    proof_max_lookback_years = _resolve_proof_max_lookback_years(horizon, max_lookback_years)
    freshness_lookback_years = recency_policy.freshness_lookback_years
    freshness_min_n = recency_policy.freshness_min_n
    direction = direction_for_bucket(today_bucket)
    c = float(cost_bps_per_side) * 1e-4
    candidates = _exit_candidates(holding_period_candidates, int(fwd_horizon_bars), return_calc_method)
    selection_sample = selection_oos_sample or oos_sample
    proof_method = (
        "same_oos_sample"
        if selection_oos_sample is None or _same_dates(selection_sample.dates, oos_sample.dates)
        else "strict_oos_split"
    )
    selection_metric = (
        "max_net_action_expected_return"
        if proof_method == "same_oos_sample"
        else "strict_oos_selection_max_net_action_expected_return"
    )
    if return_calc_method == "open_to_exit_ladder":
        selection_metric = f"{selection_metric}_open_entry_close_open_exit_ladder"
    multiple_testing_count = max(1, int(multiple_testing_count or 1))
    selected_exit_candidate = select_optimal_exit_candidate(
        score_series=score_series,
        prices=prices,
        oos_sample=selection_sample,
        today_bucket=today_bucket,
        direction=direction,
        candidates=candidates,
        fallback_horizon_bars=int(fwd_horizon_bars),
        cost_bps_per_side=cost_bps_per_side,
        n_min=n_min,
        n_target=n_target,
        max_lookback_years=proof_max_lookback_years,
    )
    selected_fwd_horizon_bars = int(selected_exit_candidate.horizon_bars)

    _, selection_df = _sample_frames(
        score_series=score_series,
        prices=prices,
        oos_sample=selection_sample,
        today_bucket=today_bucket,
        fwd_horizon_bars=selected_fwd_horizon_bars,
        return_calc_method=selected_exit_candidate.return_calc_method,
        max_lookback_years=proof_max_lookback_years,
        n_target=n_target,
        exit_candidate=selected_exit_candidate,
    )
    selection = _selection_summary(
        selection_df,
        direction=direction,
        cost_bps_per_side=cost_bps_per_side,
    )

    # 1. Hold short-circuit — no trade, no metrics.
    if direction == "none":
        return _empty_metrics(
            symbol=symbol, horizon=horizon, source=source, bucket=today_bucket,
            direction=direction, n=0, cost_bps_per_side=cost_bps_per_side,
            fwd_horizon_bars=selected_fwd_horizon_bars,
            return_calc_method=selected_exit_candidate.return_calc_method,
            holding_period_candidates=candidates,
            holding_period_selection_metric=selection_metric,
            fragility_label=fragility_label,
            fragility_fold_count=fragility_fold_count,
            fragility_details=fragility_details,
            variant=variant,
            selection_n=selection["n"],
            selection_window_start=selection["window_start"],
            selection_window_end=selection["window_end"],
            selection_action_expected_return_gross=selection["gross"],
            selection_action_expected_return_net=selection["net"],
            selection_hit_rate=selection["hit_rate"],
            proof_method=proof_method,
            multiple_testing_count=multiple_testing_count,
            selected_exit_candidate=selected_exit_candidate,
            proof_max_lookback_years=proof_max_lookback_years,
            freshness_lookback_years=freshness_lookback_years,
            freshness_min_n=freshness_min_n,
            freshness_status="not_actionable",
        )

    # 2. Build aligned (score, fwd_return) frame, filter to OOS dates, then to
    # bars whose own bucket equals today_bucket.
    full_oos_df, df = _sample_frames(
        score_series=score_series,
        prices=prices,
        oos_sample=oos_sample,
        today_bucket=today_bucket,
        fwd_horizon_bars=selected_fwd_horizon_bars,
        return_calc_method=selected_exit_candidate.return_calc_method,
        max_lookback_years=proof_max_lookback_years,
        n_target=n_target,
        exit_candidate=selected_exit_candidate,
    )

    if full_oos_df.empty:
        return _empty_metrics(
            symbol=symbol, horizon=horizon, source=source, bucket=today_bucket,
            direction=direction, n=0, cost_bps_per_side=cost_bps_per_side,
            fwd_horizon_bars=selected_fwd_horizon_bars,
            return_calc_method=selected_exit_candidate.return_calc_method,
            holding_period_candidates=candidates,
            holding_period_selection_metric=selection_metric,
            fragility_label=fragility_label,
            fragility_fold_count=fragility_fold_count,
            fragility_details=fragility_details,
            variant=variant,
            selection_n=selection["n"],
            selection_window_start=selection["window_start"],
            selection_window_end=selection["window_end"],
            selection_action_expected_return_gross=selection["gross"],
            selection_action_expected_return_net=selection["net"],
            selection_hit_rate=selection["hit_rate"],
            proof_method=proof_method,
            multiple_testing_count=multiple_testing_count,
            selected_exit_candidate=selected_exit_candidate,
            proof_max_lookback_years=proof_max_lookback_years,
            freshness_lookback_years=freshness_lookback_years,
            freshness_min_n=freshness_min_n,
        )
    n = int(len(df))
    window_start = pd.Timestamp(df.index.min()) if n else None
    window_end = pd.Timestamp(df.index.max()) if n else None

    if n < int(n_min):
        return _empty_metrics(
            symbol=symbol, horizon=horizon, source=source, bucket=today_bucket,
            direction=direction, n=n, cost_bps_per_side=cost_bps_per_side,
            fwd_horizon_bars=selected_fwd_horizon_bars,
            return_calc_method=selected_exit_candidate.return_calc_method,
            holding_period_candidates=candidates,
            holding_period_selection_metric=selection_metric,
            window_start=window_start, window_end=window_end,
            fragility_label=fragility_label,
            fragility_fold_count=fragility_fold_count,
            fragility_details=fragility_details,
            variant=variant,
            selection_n=selection["n"],
            selection_window_start=selection["window_start"],
            selection_window_end=selection["window_end"],
            selection_action_expected_return_gross=selection["gross"],
            selection_action_expected_return_net=selection["net"],
            selection_hit_rate=selection["hit_rate"],
            proof_method=proof_method,
            multiple_testing_count=multiple_testing_count,
            selected_exit_candidate=selected_exit_candidate,
            proof_max_lookback_years=proof_max_lookback_years,
            freshness_lookback_years=freshness_lookback_years,
            freshness_min_n=freshness_min_n,
        )

    _, freshness_df = _sample_frames(
        score_series=score_series,
        prices=prices,
        oos_sample=oos_sample,
        today_bucket=today_bucket,
        fwd_horizon_bars=selected_fwd_horizon_bars,
        return_calc_method=selected_exit_candidate.return_calc_method,
        max_lookback_years=freshness_lookback_years,
        n_target=EDGE_MAX_OBSERVATIONS,
        exit_candidate=selected_exit_candidate,
    )
    freshness = _freshness_summary(
        freshness_df,
        direction=direction,
        cost_bps_per_side=cost_bps_per_side,
        min_n=freshness_min_n,
    )

    # 3. Raw stock returns and action/strategy-perspective returns.
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
    stock_er = float(np.mean(raw))
    stock_er_ci_lower, stock_er_ci_upper = bootstrap_mean_ci(
        raw, n_iter=mc_iter, seed=mc_seed + 303
    )
    er_gross = float(np.mean(r_gross))
    er_net = float(np.mean(r_net))
    er_gross_ci_lower, er_gross_ci_upper = bootstrap_mean_ci(
        r_gross, n_iter=mc_iter, seed=mc_seed + 101
    )
    er_net_ci_lower, er_net_ci_upper = bootstrap_mean_ci(
        r_net, n_iter=mc_iter, seed=mc_seed + 202
    )

    # 6. MC tests. `monte_carlo_luck_test` works on signed strategy returns.
    block_mean = max(2, int(selected_fwd_horizon_bars)) if int(selected_fwd_horizon_bars) > 1 else None
    mc_gross_res = monte_carlo_luck_test(
        r_gross, metric="total_return", n_iter=mc_iter, seed=mc_seed, block_mean=block_mean,
    )
    mc_net_res = monte_carlo_luck_test(
        r_net, metric="total_return", n_iter=mc_iter, seed=mc_seed, block_mean=block_mean,
    )
    mc_luck_pvalue_gross = mc_gross_res.get("pvalue")
    mc_luck_pvalue_net = mc_net_res.get("pvalue")

    # Label-shuffle: use the same reported edge window, but keep all buckets
    # inside that date window so the null distribution can test whether this
    # bucket assignment carried information.
    shuffle_df = full_oos_df
    if window_start is not None and window_end is not None:
        shuffle_df = shuffle_df[(shuffle_df.index >= window_start) & (shuffle_df.index <= window_end)]
    score_oos = shuffle_df["score"]
    fwd_oos = shuffle_df["fwd"]
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
    mc_luck_pvalue_gross_adj = _adjust_pvalue(mc_luck_pvalue_gross, multiple_testing_count)
    mc_luck_pvalue_net_adj = _adjust_pvalue(mc_luck_pvalue_net, multiple_testing_count)
    label_shuffle_pvalue_gross_adj = _adjust_pvalue(label_shuffle_pvalue_gross, multiple_testing_count)
    label_shuffle_pvalue_net_adj = _adjust_pvalue(label_shuffle_pvalue_net, multiple_testing_count)

    # 7. Gates.
    gate_n = n >= int(n_min)
    gate_wilson = (hit_ci_lower is not None) and (float(hit_ci_lower) > WILSON_LB_THRESHOLD)
    gate_label_shuffle_gross = (
        label_shuffle_pvalue_gross_adj is not None
        and float(label_shuffle_pvalue_gross_adj) < LABEL_SHUFFLE_PVALUE_THRESHOLD
    )
    gate_label_shuffle_net = (
        label_shuffle_pvalue_net_adj is not None
        and float(label_shuffle_pvalue_net_adj) < LABEL_SHUFFLE_PVALUE_THRESHOLD
    )
    # MC luck test pvalue is one-sided in the *direction of the observation*,
    # so we additionally require the observed mean to be positive — a
    # cost-shifted negative-mean distribution can yield a low pvalue too, but
    # that is evidence against (not for) a positive edge.
    gate_mc_gross = (
        mc_luck_pvalue_gross_adj is not None
        and float(mc_luck_pvalue_gross_adj) < MC_PVALUE_THRESHOLD
        and er_gross > 0.0
    )
    gate_mc_net = (
        mc_luck_pvalue_net_adj is not None
        and float(mc_luck_pvalue_net_adj) < MC_PVALUE_THRESHOLD
        and er_net > 0.0
    )
    gates = EdgeGates(
        mc_gross=bool(gate_mc_gross),
        mc_net=bool(gate_mc_net),
        label_shuffle_gross=bool(gate_label_shuffle_gross),
        label_shuffle_net=bool(gate_label_shuffle_net),
        wilson=bool(gate_wilson),
        n=bool(gate_n),
        freshness_gross=bool(freshness["gross_pass"]),
        freshness_net=bool(freshness["net_pass"]),
    )
    proven_edge_gross = bool(
        gate_mc_gross
        and gate_label_shuffle_gross
        and gate_wilson
        and gate_n
        and freshness["gross_pass"]
    )
    proven_edge_net = bool(
        gate_mc_net
        and gate_label_shuffle_net
        and gate_wilson
        and gate_n
        and freshness["net_pass"]
    )
    edge_score, edge_score_components = compute_edge_score(
        bucket=today_bucket,
        direction=direction,
        n=n,
        action_expected_return_net=er_net,
        action_expected_return_net_ci_lower=er_net_ci_lower,
        hit_ci_lower=hit_ci_lower,
        mc_luck_pvalue_net_adj=mc_luck_pvalue_net_adj,
        label_shuffle_pvalue_net_adj=label_shuffle_pvalue_net_adj,
        freshness_n=int(freshness["n"] or 0),
        freshness_min_n=freshness_min_n,
        freshness_action_expected_return_net=freshness["net"],
        freshness_hit_rate=freshness["hit_rate"],
    )

    return EdgeMetrics(
        symbol=symbol,
        horizon=horizon,
        source=source,
        bucket=today_bucket,
        direction=direction,
        n=n,
        window_start=window_start,
        window_end=window_end,
        fwd_horizon_bars=selected_fwd_horizon_bars,
        return_calc_method=selected_exit_candidate.return_calc_method,
        holding_period_min_bars=min(c.horizon_bars for c in candidates) if candidates else None,
        holding_period_max_bars=max(c.horizon_bars for c in candidates) if candidates else None,
        holding_period_candidate_count=len(candidates),
        holding_period_selection_metric=selection_metric,
        side_policy="long_short",
        action_expected_return_gross=er_gross,
        action_expected_return_gross_ci_lower=er_gross_ci_lower,
        action_expected_return_gross_ci_upper=er_gross_ci_upper,
        action_expected_return_net=er_net,
        action_expected_return_net_ci_lower=er_net_ci_lower,
        action_expected_return_net_ci_upper=er_net_ci_upper,
        stock_expected_return=stock_er,
        stock_expected_return_ci_lower=stock_er_ci_lower,
        stock_expected_return_ci_upper=stock_er_ci_upper,
        expected_return_gross=er_gross,
        expected_return_gross_ci_lower=er_gross_ci_lower,
        expected_return_gross_ci_upper=er_gross_ci_upper,
        expected_return_net=er_net,
        expected_return_net_ci_lower=er_net_ci_lower,
        expected_return_net_ci_upper=er_net_ci_upper,
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
        label_shuffle_pvalue_gross=(
            float(label_shuffle_pvalue_gross) if label_shuffle_pvalue_gross is not None else None
        ),
        label_shuffle_pvalue_net=float(label_shuffle_pvalue_net) if label_shuffle_pvalue_net is not None else None,
        proven_edge_gross=proven_edge_gross,
        proven_edge_net=proven_edge_net,
        edge_score=edge_score,
        edge_score_components=edge_score_components,
        gates=gates,
        cost_bps_per_side=float(cost_bps_per_side),
        methodology_version=METHODOLOGY_VERSION,
        proof_max_lookback_years=proof_max_lookback_years,
        freshness_lookback_years=freshness_lookback_years,
        freshness_min_n=freshness_min_n,
        freshness_n=int(freshness["n"] or 0),
        freshness_window_start=freshness["window_start"],
        freshness_window_end=freshness["window_end"],
        freshness_action_expected_return_gross=freshness["gross"],
        freshness_action_expected_return_net=freshness["net"],
        freshness_hit_rate=freshness["hit_rate"],
        freshness_status=str(freshness["status"] or "unavailable"),
        fragility_label=str(fragility_label or "unavailable"),
        fragility_fold_count=int(fragility_fold_count or 0),
        fragility_details=tuple(fragility_details or ()),
        variant=str(variant or "expanded_ta_simple"),
        selection_n=int(selection["n"] or 0),
        selection_window_start=selection["window_start"],
        selection_window_end=selection["window_end"],
        selection_action_expected_return_gross=selection["gross"],
        selection_action_expected_return_net=selection["net"],
        selection_hit_rate=selection["hit_rate"],
        proof_n=n,
        proof_window_start=window_start,
        proof_window_end=window_end,
        proof_method=proof_method,
        multiple_testing_count=multiple_testing_count,
        mc_luck_pvalue_gross_adj=mc_luck_pvalue_gross_adj,
        mc_luck_pvalue_net_adj=mc_luck_pvalue_net_adj,
        label_shuffle_pvalue_gross_adj=label_shuffle_pvalue_gross_adj,
        label_shuffle_pvalue_net_adj=label_shuffle_pvalue_net_adj,
        entry_price_kind=selected_exit_candidate.entry_price_kind,
        entry_lag_bars=selected_exit_candidate.entry_lag_bars,
        exit_price_kind=selected_exit_candidate.exit_price_kind,
        exit_lag_bars=selected_exit_candidate.exit_lag_bars,
        exit_timing_label=selected_exit_candidate.label,
    )
