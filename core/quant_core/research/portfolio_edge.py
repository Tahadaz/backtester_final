"""Portfolio-level Edge metrics for dashboard sector and index baskets."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .edge import (
    MAX_LOOKBACK_YEARS,
    N_MIN,
    N_TARGET,
    WILSON_LB_THRESHOLD,
    Direction,
    ExitCandidate,
    _calculate_exit_returns,
    _exit_candidates,
    _strategy_returns_array,
    bootstrap_mean_ci,
    compute_canonical_expectancy,
    compute_edge_ratio,
    compute_profit_factor,
)
from .score_history import _bucket_for
from .stats.hit_rate import wilson_ci

PORTFOLIO_EDGE_METHODOLOGY_VERSION = "2026-05-10-equal-active-auto-v1"


@dataclass(frozen=True)
class PortfolioEdgeMember:
    symbol: str
    bucket: str
    direction: Direction
    score_series: pd.Series
    prices: pd.Series | pd.DataFrame
    selection_oos_dates: pd.DatetimeIndex
    proof_oos_dates: pd.DatetimeIndex


def _is_actionable(bucket: str, direction: str) -> bool:
    if bucket in {"buy", "strong_buy"}:
        return direction == "long"
    if bucket in {"sell", "strong_sell"}:
        return direction == "short"
    return False


def _clean_dates(dates: pd.DatetimeIndex | None) -> pd.DatetimeIndex:
    if dates is None:
        return pd.DatetimeIndex([])
    idx = pd.DatetimeIndex(dates).dropna().sort_values().unique()
    if idx.tz is not None:
        idx = idx.tz_convert(None)
    return idx


def _member_frame(
    member: PortfolioEdgeMember,
    *,
    candidate: ExitCandidate,
    oos_dates: pd.DatetimeIndex,
    cost_bps_per_side: float,
) -> pd.DataFrame:
    if not _is_actionable(member.bucket, member.direction):
        return pd.DataFrame()

    score = member.score_series.dropna()
    if isinstance(score.index, pd.DatetimeIndex) and score.index.tz is not None:
        score = score.set_axis(score.index.tz_convert(None))

    fwd = _calculate_exit_returns(member.prices, candidate)
    df = pd.concat([score.rename("score"), pd.Series(fwd, name="fwd")], axis=1).dropna()
    if df.empty:
        return df

    if len(oos_dates) == 0:
        return pd.DataFrame()
    df = df.loc[df.index.intersection(oos_dates)]
    if df.empty:
        return df

    df["bucket"] = df["score"].apply(_bucket_for)
    df = df[df["bucket"] == member.bucket].sort_index()
    if df.empty:
        return df

    c = float(cost_bps_per_side) * 1e-4
    raw = df["fwd"].to_numpy(dtype="float64")
    df["gross"] = _strategy_returns_array(raw, member.direction, c, include_costs=False)
    df["net"] = _strategy_returns_array(raw, member.direction, c, include_costs=True)
    df["stock"] = raw
    df["symbol"] = member.symbol
    return df[["gross", "net", "stock", "symbol"]]


def _basket_frame(
    members: list[PortfolioEdgeMember],
    *,
    candidate: ExitCandidate,
    use_selection_dates: bool,
    cost_bps_per_side: float,
    max_lookback_years: float | None,
    n_target: int,
) -> pd.DataFrame:
    by_date: dict[pd.Timestamp, dict[str, list[float] | set[str]]] = {}
    for member in members:
        dates = _clean_dates(member.selection_oos_dates if use_selection_dates else member.proof_oos_dates)
        frame = _member_frame(
            member,
            candidate=candidate,
            oos_dates=dates,
            cost_bps_per_side=cost_bps_per_side,
        )
        for ts, row in frame.iterrows():
            key = pd.Timestamp(ts)
            slot = by_date.setdefault(
                key,
                {"gross": [], "net": [], "stock": [], "symbols": set()},
            )
            slot["gross"].append(float(row["gross"]))  # type: ignore[union-attr]
            slot["net"].append(float(row["net"]))  # type: ignore[union-attr]
            slot["stock"].append(float(row["stock"]))  # type: ignore[union-attr]
            slot["symbols"].add(str(row["symbol"]))  # type: ignore[union-attr]

    rows: list[dict[str, Any]] = []
    for ts in sorted(by_date):
        slot = by_date[ts]
        gross = list(slot["gross"])  # type: ignore[arg-type]
        net = list(slot["net"])  # type: ignore[arg-type]
        stock = list(slot["stock"])  # type: ignore[arg-type]
        symbols = set(slot["symbols"])  # type: ignore[arg-type]
        if not gross:
            continue
        rows.append({
            "date": ts,
            "gross": float(np.mean(gross)),
            "net": float(np.mean(net)),
            "stock": float(np.mean(stock)),
            "member_count": len(symbols),
        })

    if not rows:
        return pd.DataFrame(columns=["gross", "net", "stock", "member_count"])

    out = pd.DataFrame(rows).set_index("date").sort_index()
    if max_lookback_years is not None and not out.empty:
        cutoff = out.index.max() - pd.Timedelta(days=int(365.25 * float(max_lookback_years)))
        out = out[out.index >= cutoff]
    return out.tail(int(n_target))


def _selection_summary(df: pd.DataFrame) -> dict[str, Any]:
    n = int(len(df))
    if n <= 0:
        return {
            "n": 0,
            "window_start": None,
            "window_end": None,
            "gross": None,
            "net": None,
            "hit_rate": None,
        }
    gross = df["gross"].to_numpy(dtype="float64")
    net = df["net"].to_numpy(dtype="float64")
    return {
        "n": n,
        "window_start": pd.Timestamp(df.index.min()).date().isoformat(),
        "window_end": pd.Timestamp(df.index.max()).date().isoformat(),
        "gross": float(np.mean(gross)),
        "net": float(np.mean(net)),
        "hit_rate": float(np.mean(gross > 0.0)),
    }


def _select_candidate(
    members: list[PortfolioEdgeMember],
    *,
    candidates: tuple[ExitCandidate, ...],
    cost_bps_per_side: float,
    n_min: int,
    n_target: int,
    max_lookback_years: float | None,
) -> tuple[ExitCandidate, dict[str, Any]]:
    best: tuple[float, float, int, int, ExitCandidate, pd.DataFrame] | None = None
    fallback: tuple[int, float, float, int, ExitCandidate, pd.DataFrame] | None = None

    for candidate in candidates:
        df = _basket_frame(
            members,
            candidate=candidate,
            use_selection_dates=True,
            cost_bps_per_side=cost_bps_per_side,
            max_lookback_years=max_lookback_years,
            n_target=n_target,
        )
        n = int(len(df))
        if n <= 0:
            continue
        gross = df["gross"].to_numpy(dtype="float64")
        net = df["net"].to_numpy(dtype="float64")
        mean_net = float(np.mean(net))
        hit_rate = float(np.mean(gross > 0.0))

        fallback_key = (n, mean_net, hit_rate, -candidate.time_rank, candidate, df)
        if fallback is None or fallback_key[:4] > fallback[:4]:
            fallback = fallback_key

        if n < int(n_min):
            continue
        best_key = (mean_net, hit_rate, -candidate.time_rank, n, candidate, df)
        if best is None or best_key[:4] > best[:4]:
            best = best_key

    if best is not None:
        return best[4], _selection_summary(best[5])
    if fallback is not None:
        return fallback[4], _selection_summary(fallback[5])
    return candidates[0], _selection_summary(pd.DataFrame())


def build_portfolio_edge_payload(
    *,
    members: list[PortfolioEdgeMember],
    horizon: str,
    total_count: int,
    fwd_horizon_bars: int,
    holding_period_candidates: tuple[int, ...] | list[int] | None,
    cost_bps_per_side: float,
    n_min: int = N_MIN,
    n_target: int = N_TARGET,
    max_lookback_years: float | None = MAX_LOOKBACK_YEARS,
    return_calc_method: str = "open_to_exit_ladder",
) -> dict[str, Any]:
    """Compute equal-active, auto-signal portfolio Edge for one basket."""
    active_members = [
        member
        for member in members
        if _is_actionable(member.bucket, member.direction)
    ]
    candidates = _exit_candidates(holding_period_candidates, int(fwd_horizon_bars), return_calc_method)
    long_count = sum(1 for member in active_members if member.direction == "long")
    short_count = sum(1 for member in active_members if member.direction == "short")

    if not active_members:
        return {
            "label": "Portfolio auto",
            "triage": "missing",
            "horizon": horizon,
            "methodology_version": PORTFOLIO_EDGE_METHODOLOGY_VERSION,
            "side_policy": "long_short",
            "weighting": "equal_active",
            "active_count": 0,
            "total_count": int(total_count),
            "long_count": 0,
            "short_count": 0,
            "n": 0,
            "fwd_horizon_bars": int(fwd_horizon_bars),
            "return_calc_method": return_calc_method,
            "action_expected_return_net": None,
            "action_expected_return_net_ci_lower": None,
            "action_expected_return_net_ci_upper": None,
            "hit_rate": None,
            "hit_ci_lower": None,
            "hit_ci_upper": None,
            "proven_edge_net": False,
            "score": None,
        }

    selected, selection = _select_candidate(
        active_members,
        candidates=candidates,
        cost_bps_per_side=cost_bps_per_side,
        n_min=n_min,
        n_target=n_target,
        max_lookback_years=max_lookback_years,
    )
    proof = _basket_frame(
        active_members,
        candidate=selected,
        use_selection_dates=False,
        cost_bps_per_side=cost_bps_per_side,
        max_lookback_years=max_lookback_years,
        n_target=n_target,
    )
    n = int(len(proof))
    if n <= 0:
        return {
            "label": "Portfolio auto",
            "triage": "missing",
            "horizon": horizon,
            "methodology_version": PORTFOLIO_EDGE_METHODOLOGY_VERSION,
            "side_policy": "long_short",
            "weighting": "equal_active",
            "active_count": len(active_members),
            "total_count": int(total_count),
            "long_count": long_count,
            "short_count": short_count,
            "n": 0,
            "fwd_horizon_bars": selected.horizon_bars,
            "return_calc_method": selected.return_calc_method,
            "entry_price_kind": selected.entry_price_kind,
            "entry_lag_bars": selected.entry_lag_bars,
            "exit_price_kind": selected.exit_price_kind,
            "exit_lag_bars": selected.exit_lag_bars,
            "exit_timing_label": selected.label,
            "selection_n": selection["n"],
            "selection_action_expected_return_net": selection["net"],
            "selection_hit_rate": selection["hit_rate"],
            "action_expected_return_net": None,
            "action_expected_return_net_ci_lower": None,
            "action_expected_return_net_ci_upper": None,
            "hit_rate": None,
            "hit_ci_lower": None,
            "hit_ci_upper": None,
            "proven_edge_net": False,
            "score": None,
        }

    gross = proof["gross"].to_numpy(dtype="float64")
    net = proof["net"].to_numpy(dtype="float64")
    stock = proof["stock"].to_numpy(dtype="float64")
    member_counts = proof["member_count"].to_numpy(dtype="float64")
    hits = int(np.sum(gross > 0.0))
    hit_rate = hits / n
    hit_ci_lower, hit_ci_upper = wilson_ci(hits, n)
    er_gross = float(np.mean(gross))
    er_net = float(np.mean(net))
    er_stock = float(np.mean(stock))
    er_gross_ci_lower, er_gross_ci_upper = bootstrap_mean_ci(gross, n_iter=1000, seed=5101)
    er_net_ci_lower, er_net_ci_upper = bootstrap_mean_ci(net, n_iter=1000, seed=5102)
    er_stock_ci_lower, er_stock_ci_upper = bootstrap_mean_ci(stock, n_iter=1000, seed=5103)
    gate_n = n >= int(n_min)
    gate_wilson = hit_ci_lower is not None and float(hit_ci_lower) > WILSON_LB_THRESHOLD
    gate_bootstrap_net = er_net_ci_lower is not None and float(er_net_ci_lower) > 0.0
    proven_net = bool(gate_n and gate_wilson and gate_bootstrap_net)
    triage = "proven" if proven_net else ("insufficient" if not gate_n else "watch")
    score = er_net_ci_lower if er_net_ci_lower is not None else er_net

    return {
        "label": "Portfolio auto",
        "triage": triage,
        "horizon": horizon,
        "methodology_version": PORTFOLIO_EDGE_METHODOLOGY_VERSION,
        "side_policy": "long_short",
        "weighting": "equal_active",
        "active_count": len(active_members),
        "total_count": int(total_count),
        "long_count": long_count,
        "short_count": short_count,
        "n": n,
        "window_start": pd.Timestamp(proof.index.min()).date().isoformat(),
        "window_end": pd.Timestamp(proof.index.max()).date().isoformat(),
        "fwd_horizon_bars": selected.horizon_bars,
        "return_calc_method": selected.return_calc_method,
        "entry_price_kind": selected.entry_price_kind,
        "entry_lag_bars": selected.entry_lag_bars,
        "exit_price_kind": selected.exit_price_kind,
        "exit_lag_bars": selected.exit_lag_bars,
        "exit_timing_label": selected.label,
        "selection_n": selection["n"],
        "selection_window_start": selection["window_start"],
        "selection_window_end": selection["window_end"],
        "selection_action_expected_return_gross": selection["gross"],
        "selection_action_expected_return_net": selection["net"],
        "selection_hit_rate": selection["hit_rate"],
        "action_expected_return_gross": er_gross,
        "action_expected_return_gross_ci_lower": er_gross_ci_lower,
        "action_expected_return_gross_ci_upper": er_gross_ci_upper,
        "action_expected_return_net": er_net,
        "action_expected_return_net_ci_lower": er_net_ci_lower,
        "action_expected_return_net_ci_upper": er_net_ci_upper,
        "stock_expected_return": er_stock,
        "stock_expected_return_ci_lower": er_stock_ci_lower,
        "stock_expected_return_ci_upper": er_stock_ci_upper,
        "expected_return_net": er_net,
        "hit_rate": float(hit_rate),
        "hit_ci_lower": float(hit_ci_lower) if hit_ci_lower is not None else None,
        "hit_ci_upper": float(hit_ci_upper) if hit_ci_upper is not None else None,
        "expectancy_gross": compute_canonical_expectancy(gross).__dict__,
        "expectancy_net": compute_canonical_expectancy(net).__dict__,
        "edge_ratio_gross": compute_edge_ratio(gross),
        "edge_ratio_net": compute_edge_ratio(net),
        "profit_factor_gross": compute_profit_factor(gross),
        "profit_factor_net": compute_profit_factor(net),
        "average_member_count": float(np.mean(member_counts)) if len(member_counts) else None,
        "min_member_count": int(np.min(member_counts)) if len(member_counts) else None,
        "max_member_count": int(np.max(member_counts)) if len(member_counts) else None,
        "gates": {
            "n": bool(gate_n),
            "wilson": bool(gate_wilson),
            "bootstrap_net": bool(gate_bootstrap_net),
        },
        "proven_edge_net": proven_net,
        "score": float(score) if score is not None else None,
    }
