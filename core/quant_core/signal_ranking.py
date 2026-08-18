"""Pure point-in-time decision construction for the frozen dashboard v5 method.

Callers own all I/O.  This module deliberately has no database, settings, or
clock access so live and historical ranking can consume identical inputs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import math
from typing import Any, Mapping, TypeAlias

import pandas as pd

from .historical_portfolio import (
    HistoricalOpportunity,
    SelectionObservation,
    V5_DECISION_EDGE_COST_BPS,
)
from .horizons import HORIZON_SPECS
from .research.decision_bakeoff import CATEGORY_ORDER
from .research.edge import build_edge_payload, direction_for_bucket
from .research.oos_index import OosSample, OosWindow
from .research.score_history import _bucket_for, aggregate_subset
from .signal_engine.modes import TECHNICAL_SIGNAL_MODE_NAMES


OosInput: TypeAlias = OosSample | tuple[pd.Timestamp, ...]
VALID_STATUSES = (
    "no_price_data",
    "no_score_data",
    "stale_score",
    "insufficient_history",
    "evidence_unavailable",
    "evaluated",
)


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def is_actionable_edge_bucket(bucket: Any, direction: Any) -> bool:
    bucket_key = str(bucket or "").strip().lower()
    direction_key = str(direction or "").strip().lower()
    return (bucket_key in {"buy", "strong_buy"} and direction_key == "long") or (
        bucket_key in {"sell", "strong_sell"} and direction_key == "short"
    )


def rank_and_actionability(
    edge: Mapping[str, Any],
) -> tuple[tuple[int, float, float, float] | None, list[str]]:
    """The sole v5 rankability authority; byte-equivalent to dashboard v5."""

    bucket = str(edge.get("bucket") or "").strip().lower()
    direction = str(edge.get("direction") or "none").strip().lower()
    if bucket in {"hold", "unavailable", "indisponible", ""}:
        return None, ["neutral_bucket"]
    if not is_actionable_edge_bucket(bucket, direction):
        return None, ["invalid_bucket_direction"]
    gates_raw = edge.get("gates")
    if is_dataclass(gates_raw):
        gates = asdict(gates_raw)
    else:
        gates = gates_raw if isinstance(gates_raw, Mapping) else {}
    n = _finite(edge.get("n")) or 0.0
    if n < 30 or (gates and not bool(gates.get("n", False))):
        return None, ["insufficient_dashboard_sample"]
    expected = _finite(edge.get("action_expected_return_net"))
    if expected is None:
        expected = _finite(edge.get("expected_return_net"))
    if expected is None or expected <= 0:
        return None, ["non_positive_expectancy"]
    lower = _finite(edge.get("action_expected_return_net_ci_lower"))
    if lower is None:
        lower = _finite(edge.get("expected_return_net_ci_lower"))
    penalized = lower if lower is not None else expected * 0.5
    edge_score = _finite(edge.get("edge_score"))
    rank_score = edge_score if edge_score is not None else penalized
    rank = (2 if bool(edge.get("proven_edge_net")) else 1, rank_score, penalized, expected)
    return rank, []


def best_signal_rank(edge: Mapping[str, Any]) -> tuple[int, float, float, float] | None:
    return rank_and_actionability(edge)[0]


@dataclass(frozen=True)
class AsOfInputs:
    symbol: str
    horizon: str
    variant: str
    as_of: pd.Timestamp
    category_series: Mapping[str, pd.Series]
    prices: pd.DataFrame | None
    oos: OosInput
    live_score: float | None = None
    decision_edge_cost_bps: float = V5_DECISION_EDGE_COST_BPS
    mc_iterations: int = 500
    mc_seed: int = 5107


@dataclass(frozen=True)
class AsOfDecision:
    status: str
    signal_direction: str | None
    category_scores: dict[str, float | str]
    aggregate_score: float | None
    bucket: str | None
    actionable: bool
    actionability_reasons: list[str]
    rank: tuple[int, float, float, float] | None
    evidence: dict[str, Any] | None
    selection_cutoff: str | None
    proof_cutoff: str | None
    selection_observations: tuple[SelectionObservation, ...]
    opportunity: HistoricalOpportunity | None
    computation_rejection_reasons: list[str]


def _empty(
    status: str,
    *,
    category_scores: dict[str, float | str] | None = None,
    aggregate_score: float | None = None,
    bucket: str | None = None,
    direction: str | None = None,
) -> AsOfDecision:
    return AsOfDecision(
        status=status,
        signal_direction=direction,
        category_scores=category_scores or {key: "unavailable" for key in CATEGORY_ORDER},
        aggregate_score=aggregate_score,
        bucket=bucket,
        actionable=False,
        actionability_reasons=[],
        rank=None,
        evidence=None,
        selection_cutoff=None,
        proof_cutoff=None,
        selection_observations=(),
        opportunity=None,
        computation_rejection_reasons=[status],
    )


def _normalized_series(series: pd.Series, as_of: pd.Timestamp) -> pd.Series:
    copy = pd.to_numeric(series.copy(), errors="coerce")
    copy.index = pd.DatetimeIndex(copy.index)
    if copy.index.tz is not None:
        copy.index = copy.index.tz_convert(None)
    return copy[copy.index <= as_of].dropna().sort_index()


def _historical_oos(value: OosInput, as_of: pd.Timestamp, horizon: str) -> tuple[OosSample, OosSample]:
    if isinstance(value, OosSample):
        dates = pd.DatetimeIndex(value.dates)
        windows = tuple(
            OosWindow(
                fold_id=window.fold_id,
                start=pd.Timestamp(window.start),
                end=min(pd.Timestamp(window.end), as_of - pd.Timedelta(nanoseconds=1)),
                winner_variant_id=window.winner_variant_id,
                winner_params=window.winner_params,
            )
            for window in value.windows
            if pd.Timestamp(window.start) < as_of
        )
        dates = dates[dates < as_of]
        proof = OosSample(value.source, value.horizon, windows, dates, value.score_mode)
        selection_windows = windows
    else:
        dates = pd.DatetimeIndex(value).dropna().sort_values().unique()
        dates = dates[dates < as_of]
        windows = () if len(dates) == 0 else (
            OosWindow(None, pd.Timestamp(dates[0]), pd.Timestamp(dates[-1])),
        )
        proof = OosSample("wfo", horizon, windows, dates, "fold_scoped_winner")
        selection_windows = windows
    selection_count = int(math.floor(2 * len(proof.dates) / 3))
    selection_dates = proof.dates[:selection_count]
    if len(selection_dates):
        selection_windows = (
            OosWindow(None, pd.Timestamp(selection_dates[0]), pd.Timestamp(selection_dates[-1])),
        )
    else:
        selection_windows = ()
    selection = OosSample(
        proof.source, proof.horizon, tuple(selection_windows), selection_dates, proof.score_mode,
    )
    return selection, proof


def _gates_dict(value: Any) -> dict[str, bool]:
    if is_dataclass(value):
        return {key: bool(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): bool(item) for key, item in value.items()}
    return {}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return pd.Timestamp(value).date().isoformat()


def _selection_observations(
    *,
    aggregate: pd.Series,
    prices: pd.DataFrame,
    selection_dates: pd.DatetimeIndex,
    bucket: str,
    direction: str,
    exit_lag_bars: int,
) -> tuple[SelectionObservation, ...]:
    """Reconstruct sizing returns whose exits were observable before ``as_of``."""

    open_col = next((name for name in ("Open", "open") if name in prices.columns), None)
    if open_col is None:
        return ()
    wanted = {pd.Timestamp(value).normalize() for value in selection_dates}
    observations: list[SelectionObservation] = []
    for decision_date, value in aggregate.items():
        decision = pd.Timestamp(decision_date).normalize()
        if decision not in wanted or _bucket_for(float(value)) != bucket:
            continue
        loc = int(prices.index.searchsorted(decision, side="right")) - 1
        entry_pos, exit_pos = loc + 1, loc + int(exit_lag_bars)
        if loc < 0 or entry_pos >= len(prices) or exit_pos >= len(prices):
            continue
        entry = _finite(prices.iloc[entry_pos][open_col])
        exit_price = _finite(prices.iloc[exit_pos][open_col])
        if entry is None or exit_price is None or entry <= 0:
            continue
        signed = (exit_price / entry - 1.0) * (1.0 if direction == "long" else -1.0)
        net = signed - 2.0 * V5_DECISION_EDGE_COST_BPS * 1e-4
        observations.append(SelectionObservation(_iso(prices.index[exit_pos]) or "", float(net)))
    return tuple(observations)


def build_asof_decision(inputs: AsOfInputs) -> AsOfDecision:
    """Build one mode decision using only objects known strictly before ``as_of``."""

    as_of = pd.Timestamp(inputs.as_of)
    if as_of.tzinfo is not None:
        as_of = as_of.tz_convert(None)
    as_of = as_of.normalize()
    if inputs.horizon not in HORIZON_SPECS:
        raise ValueError(f"unknown horizon: {inputs.horizon}")
    if inputs.variant not in TECHNICAL_SIGNAL_MODE_NAMES:
        raise ValueError(f"unknown technical signal mode: {inputs.variant}")
    if float(inputs.decision_edge_cost_bps) != V5_DECISION_EDGE_COST_BPS:
        raise ValueError("v5 decision evidence cost drift requires a methodology-version bump")
    if inputs.prices is None or inputs.prices.empty:
        return _empty("no_price_data")

    series_by_category = {
        key: _normalized_series(inputs.category_series[key], as_of)
        for key in CATEGORY_ORDER
        if key in inputs.category_series
    }
    scores: dict[str, float | str] = {
        key: (float(series_by_category[key].iloc[-1]) if key in series_by_category and len(series_by_category[key]) else "unavailable")
        for key in CATEGORY_ORDER
    }
    aggregate = aggregate_subset(series_by_category, CATEGORY_ORDER)
    if aggregate is None or aggregate.dropna().empty:
        return _empty("no_score_data", category_scores=scores)
    aggregate = aggregate.dropna().sort_index()
    score = _finite(inputs.live_score) if inputs.live_score is not None else _finite(aggregate.iloc[-1])
    if score is None:
        return _empty("no_score_data", category_scores=scores)
    last_score_date = pd.Timestamp(aggregate.index[-1]).normalize()
    if inputs.live_score is None and last_score_date < as_of:
        return _empty("stale_score", category_scores=scores, aggregate_score=score)
    aggregate.loc[as_of] = score
    bucket = _bucket_for(score)
    direction_raw = direction_for_bucket(bucket)
    direction = "neutral" if direction_raw == "none" else direction_raw
    selection_oos, proof_oos = _historical_oos(inputs.oos, as_of, inputs.horizon)
    if len(aggregate) < 2 or len(proof_oos.dates) < 2:
        return _empty(
            "insufficient_history", category_scores=scores, aggregate_score=score,
            bucket=bucket, direction=direction,
        )

    prices = inputs.prices.copy()
    prices.index = pd.DatetimeIndex(prices.index)
    if prices.index.tz is not None:
        prices.index = prices.index.tz_convert(None)
    # Evidence observations must have exits strictly before the decision.
    prices = prices[prices.index < as_of].sort_index()
    metrics = build_edge_payload(
        symbol=inputs.symbol.upper(),
        horizon=inputs.horizon,
        source="wfo",
        score_series=aggregate[aggregate.index < as_of],
        prices=prices,
        oos_sample=proof_oos,
        selection_oos_sample=selection_oos,
        today_bucket=bucket,
        fwd_horizon_bars=HORIZON_SPECS[inputs.horizon].reference_forward_days,
        holding_period_candidates=HORIZON_SPECS[inputs.horizon].forward_grid_days,
        cost_bps_per_side=V5_DECISION_EDGE_COST_BPS,
        n_min=30,
        n_target=60,
        max_lookback_years=None,
        mc_iter=max(100, int(inputs.mc_iterations)),
        mc_seed=int(inputs.mc_seed),
        multiple_testing_count=len(TECHNICAL_SIGNAL_MODE_NAMES),
        variant=inputs.variant,
    )
    if metrics is None:
        return _empty(
            "evidence_unavailable", category_scores=scores, aggregate_score=score,
            bucket=bucket, direction=direction,
        )
    evidence = {
        "edge_score": metrics.edge_score,
        "edge_score_components": dict(metrics.edge_score_components or {}),
        "expected_return_net": metrics.expected_return_net,
        "action_expected_return_net": metrics.action_expected_return_net,
        "ci_lower_net": metrics.expected_return_net_ci_lower,
        "action_expected_return_net_ci_lower": metrics.action_expected_return_net_ci_lower,
        "hit_ci_lower": metrics.hit_ci_lower,
        "proven_edge_net": bool(metrics.proven_edge_net),
        "gates": _gates_dict(metrics.gates),
        "mc_luck_pvalue_net_adj": metrics.mc_luck_pvalue_net_adj,
        "label_shuffle_pvalue_net_adj": metrics.label_shuffle_pvalue_net_adj,
        "freshness_status": metrics.freshness_status,
        "selection_n": int(metrics.selection_n or 0),
        "proof_n": int(metrics.proof_n or 0),
        "n": int(metrics.n or 0),
        "exit_lag_bars": metrics.exit_lag_bars,
        "entry_price_kind": metrics.entry_price_kind,
        "exit_price_kind": metrics.exit_price_kind,
        "return_calc_method": metrics.return_calc_method,
        "edge_methodology_version": metrics.methodology_version,
        "mc_iterations": max(100, int(inputs.mc_iterations)),
        "mc_seed": int(inputs.mc_seed),
        "decision_edge_cost_bps": V5_DECISION_EDGE_COST_BPS,
    }
    edge_for_rank = {**evidence, "bucket": bucket, "direction": direction_raw}
    rank, reasons = rank_and_actionability(edge_for_rank)
    actionable = rank is not None
    observations = _selection_observations(
        aggregate=aggregate[aggregate.index < as_of], prices=prices,
        selection_dates=selection_oos.dates, bucket=bucket, direction=str(direction_raw),
        exit_lag_bars=int(metrics.exit_lag_bars or HORIZON_SPECS[inputs.horizon].reference_forward_days),
    )
    opportunity = None
    if actionable:
        opportunity = HistoricalOpportunity(
            decision_date=as_of.date().isoformat(), symbol=inputs.symbol.upper(),
            horizon=inputs.horizon, variant=inputs.variant, direction=str(direction_raw),
            rank=rank or (), bucket=bucket,
            training_end=_iso(aggregate.index[-2]) if len(aggregate) > 1 else None,
            selection_sample_end=_iso(metrics.selection_window_end),
            proof_sample_end=_iso(metrics.proof_window_end),
            entry_lag_bars=int(metrics.entry_lag_bars or 1),
            exit_lag_bars=int(metrics.exit_lag_bars or HORIZON_SPECS[inputs.horizon].reference_forward_days),
            entry_price_kind=str(metrics.entry_price_kind or "open"),
            exit_price_kind=str(metrics.exit_price_kind or "open"),
            selection_observations=observations,
            provenance={**evidence, "source": "persisted_fold_scoped_wfo_oos_score_history"},
        )
    return AsOfDecision(
        status="evaluated", signal_direction=direction, category_scores=scores,
        aggregate_score=score, bucket=bucket, actionable=actionable,
        actionability_reasons=reasons, rank=rank, evidence=evidence,
        selection_cutoff=_iso(metrics.selection_window_end), proof_cutoff=_iso(metrics.proof_window_end),
        selection_observations=observations, opportunity=opportunity, computation_rejection_reasons=[],
    )
