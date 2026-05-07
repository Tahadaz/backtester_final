"""Signal-based backtest + Monte Carlo builders.

Consumes already-committed representative variants (from DB or in-memory cache)
to build per-bar signal series and run historical backtests.

Key contract: no A→G selection or WFO optimization happens here.
Representatives and their weights are **inputs**, taken as-is.
"""
from __future__ import annotations

import logging
import hashlib
import json
import math
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .domain import CATEGORY_FAMILIES
from .oos_eval import compute_signal_array, VariantDef

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_variant_def(rep: dict, *, fallback_family: str | None = None) -> VariantDef:
    """Reconstruct a VariantDef from a serialized representative dict."""
    family = str(rep.get("family") or fallback_family or "").strip()
    if not family:
        raise ValueError(
            f"Representative {rep.get('variant_id', '<missing>')} missing family; "
            "cannot reconstruct VariantDef safely."
        )
    return VariantDef(
        variant_id=str(rep["variant_id"]),
        family=family,
        archetype=str(rep["archetype"]),
        params=dict(rep.get("params") or {}),
    )


def _build_family_signal_series_result(
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
    representatives_json: list[dict],
    *,
    fallback_family: str | None = None,
) -> tuple[np.ndarray, int, int]:
    """Return (signal_series, successful_rep_count, failed_rep_count)."""
    if not representatives_json:
        return np.zeros(len(close), dtype=np.float64), 0, 0

    weighted_sum = np.zeros(len(close), dtype=np.float64)
    total_weight = 0.0
    success_count = 0
    failed_count = 0
    failure_samples: list[str] = []

    for rep in representatives_json:
        w = float(rep.get("normalized_weight") or rep.get("reliability_weight") or 1.0)
        if w <= 0:
            w = 1.0
        try:
            variant = _make_variant_def(rep, fallback_family=fallback_family)
            sig = compute_signal_array(close, variant, volume=volume, high=high, low=low).astype(np.float64)
        except Exception as exc:
            failed_count += 1
            if len(failure_samples) < 3:
                failure_samples.append(f"{rep.get('variant_id', '<missing>')}: {exc}")
            continue
        weighted_sum += w * sig
        total_weight += w
        success_count += 1

    if success_count == 0:
        sample_str = "; ".join(failure_samples) if failure_samples else "no representative rebuilt successfully"
        family_str = fallback_family or "<unknown-family>"
        raise ValueError(f"All representatives failed for family {family_str}: {sample_str}")

    if failed_count:
        logger.warning(
            "Signal rebuild skipped %d/%d representatives for family %s",
            failed_count,
            len(representatives_json),
            fallback_family or representatives_json[0].get("family") or "<unknown-family>",
        )

    result = weighted_sum / total_weight if total_weight > 0 else np.zeros(len(close), dtype=np.float64)
    return np.clip(result, -1.0, 1.0), success_count, failed_count


def _cagr(total_return: float, n_bars: int) -> float:
    if n_bars < 1:
        return 0.0
    years = n_bars / 252.0
    if years <= 0:
        return 0.0
    equity_final = 1.0 + total_return
    if equity_final <= 0:
        return -1.0
    return float(equity_final ** (1.0 / years) - 1.0)


def _sharpe(returns: np.ndarray) -> float:
    if len(returns) < 2:
        return 0.0
    mu = float(np.mean(returns))
    sigma = float(np.std(returns, ddof=1))
    if sigma <= 0:
        return 0.0
    return float(mu / sigma * math.sqrt(252))


def _max_drawdown(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    safe_peak = np.where(peak <= 0, 1.0, peak)
    dd = 1.0 - equity / safe_peak
    return float(np.max(dd))


# ---------------------------------------------------------------------------
# Signal series builders
# ---------------------------------------------------------------------------

def build_family_signal_series(
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
    representatives_json: list[dict],
    *,
    fallback_family: str | None = None,
) -> np.ndarray:
    """Build a bar-by-bar signal series from committed representative variants.

    Calls compute_signal_array for each rep and weight-averages using
    normalized_weight (or reliability_weight as fallback).
    Returns a float64 array of length T clipped to [-1, 1].
    """
    result, _success_count, _failed_count = _build_family_signal_series_result(
        close,
        volume,
        high,
        low,
        representatives_json,
        fallback_family=fallback_family,
    )
    return result


def build_category_signal_series_engine(
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
    family_results: dict[str, dict],
    category: str,
) -> np.ndarray:
    """Aggregate family-level signals into one per-category series (A→G engine path).

    family_results keys are family names (e.g. "sma", "macd"); values are dicts with:
      representatives_json, family_score_pct, viable_count, tested_count,
      representative_count, is_provisional.

    Weight rule:
      w_f = (viable_count / max(tested_count, 1)) * representative_count
      Provisional families are excluded (w_f = 0).
      Falls back to equal weights when all weights are zero.
    """
    families_in_category = CATEGORY_FAMILIES.get(category, [])
    if not families_in_category:
        return np.zeros(len(close), dtype=np.float64)

    family_sigs: list[tuple[float, np.ndarray]] = []
    for family in families_in_category:
        fr = family_results.get(family)
        if not fr or fr.get("status") != "succeeded":
            continue
        if fr.get("is_provisional"):
            continue
        reps = fr.get("representatives_json") or []
        if not reps:
            continue

        viable = float(fr.get("viable_count") or 0)
        tested = float(max(fr.get("tested_count") or 1, 1))
        rep_count = float(fr.get("representative_count") or len(reps))
        w = (viable / tested) * rep_count

        sig, success_count, _failed_count = _build_family_signal_series_result(
            close,
            volume,
            high,
            low,
            reps,
            fallback_family=family,
        )
        if success_count == 0:
            continue
        family_sigs.append((w, sig))

    if not family_sigs:
        return np.zeros(len(close), dtype=np.float64)

    total_w = sum(w for w, _ in family_sigs)
    if total_w <= 0:
        # Fallback: equal weights
        total_w = float(len(family_sigs))
        family_sigs = [(1.0, sig) for _, sig in family_sigs]

    weighted = sum(w * sig for w, sig in family_sigs)
    return np.clip(weighted / total_w, -1.0, 1.0)


def build_category_signal_series_wfo(
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
    representatives_json: list[dict],
) -> np.ndarray:
    """Build signal series from WFO-selected representatives for one category.

    representatives_json comes from wfo_signal_summary.representatives_json.
    Same weight scheme as build_family_signal_series (normalized_weight).
    """
    return build_family_signal_series(close, volume, high, low, representatives_json)


def build_global_signal_series(
    category_series: dict[str, np.ndarray],
    weights: dict[str, float],
) -> np.ndarray:
    """Combine per-category series into a global signal using provided weights.

    weights: {category: float} — typically from WfoGlobalSignal.weights (sum≈1)
    or engine-path category weights derived from category scores.
    Missing categories are skipped; weights are renormalized.
    """
    total_w = 0.0
    weighted_sum: np.ndarray | None = None

    for cat, series in category_series.items():
        w = float(weights.get(cat) or 0.0)
        if w <= 0:
            continue
        if weighted_sum is None:
            weighted_sum = w * series.astype(np.float64)
        else:
            weighted_sum = weighted_sum + w * series.astype(np.float64)
        total_w += w

    if weighted_sum is None or total_w <= 0:
        T = next(iter(category_series.values()), np.zeros(1)).shape[0]
        return np.zeros(T, dtype=np.float64)

    return np.clip(weighted_sum / total_w, -1.0, 1.0)


def build_combination_signal_series(
    category_series: dict[str, np.ndarray],
    subset: list[str],
    weights: dict[str, float],
) -> np.ndarray:
    """Build a signal series for a subset of categories with renormalized weights."""
    sub_weights = {cat: weights.get(cat, 1.0) for cat in subset if cat in category_series}
    return build_global_signal_series(
        {cat: category_series[cat] for cat in sub_weights},
        sub_weights,
    )


# ---------------------------------------------------------------------------
# Backtest kernel
# ---------------------------------------------------------------------------

def run_signal_backtest(
    signal_series: np.ndarray,
    close: np.ndarray,
    dates: list[str],
    *,
    cost_bps: float = 5.0,
    slippage_bps: float = 5.0,
    side_policy: str = "long_only",
) -> dict[str, Any]:
    """Run a signal-based backtest on a price series.

    Convention:
    - Signal at bar t → position entered at the close of bar t+1
      (i.e. strategy returns at bar t+1 = position[t] × return[t→t+1])
    - cost+slippage applied on position changes (|pos[t] - pos[t-1]| > 0)
    - long_only: negative signals are mapped to 0

    Returns a dict with equity curve, per-bar returns, trade events, and metrics.
    """
    sig = np.asarray(signal_series, dtype=np.float64)
    cl = np.asarray(close, dtype=np.float64)
    T = len(cl)

    _empty_diag = {
        "flat_executed": True,
        "target_nonzero_bars": 0,
        "target_mean": 0.0,
        "target_min": 0.0,
        "target_max": 0.0,
    }
    if T < 2 or len(sig) < T:
        return {
            "equity": [1.0],
            "returns": [],
            "dates": dates[:1] if dates else [],
            "trades": [],
            "close_series": cl.tolist(),
            "position_series": [0.0],
            "diagnostics": _empty_diag,
            "metrics": {
                "total_return": 0.0, "cagr": 0.0, "sharpe": 0.0,
                "max_drawdown": 0.0, "win_rate": 0.0, "n_trades": 0,
            },
        }

    friction = (cost_bps + slippage_bps) / 10_000.0

    # Convert signal → position (shift by 1 bar)
    target_position = sig[:T].copy()
    if side_policy == "long_only":
        target_position = np.clip(target_position, 0.0, 1.0)
    else:
        target_position = np.clip(target_position, -1.0, 1.0)
    executed_position = np.zeros(T, dtype=np.float64)
    if T > 1:
        executed_position[1:] = target_position[:-1]

    diagnostics = {
        "flat_executed": bool(np.all(executed_position == 0.0)),
        "target_nonzero_bars": int(np.sum(target_position != 0.0)),
        "target_mean": float(np.mean(target_position)),
        "target_min": float(np.min(target_position)),
        "target_max": float(np.max(target_position)),
    }

    # Per-bar close-to-close returns
    raw_returns = np.diff(cl) / np.where(cl[:-1] == 0, 1.0, cl[:-1])  # length T-1

    # Position at bar t applies to return from bar t to t+1
    # Shift position backward by 1 so pos[0] applies to return[0]
    interval_position = executed_position[:-1]  # length T-1

    # Trade costs on position changes
    pos_change = np.abs(np.diff(np.concatenate(([0.0], executed_position))))
    costs = pos_change[:-1] * friction

    strategy_returns = interval_position * raw_returns - costs
    equity = np.concatenate(([1.0], np.cumprod(1.0 + strategy_returns)))

    # Build trade list
    trades: list[dict] = []
    in_trade = False
    trade_open_idx = 0
    trade_open_price = 0.0
    prev_pos = 0.0

    for i, pos in enumerate(executed_position):
        if not in_trade and pos != 0:
            in_trade = True
            trade_open_idx = i
            trade_open_price = cl[i]
            prev_pos = pos
        elif in_trade and (pos == 0 or pos != prev_pos):
            # Close trade at bar i
            close_price = cl[i]
            pnl = (close_price - trade_open_price) / trade_open_price * prev_pos - friction * 2
            trades.append({
                "open_idx": int(trade_open_idx),
                "close_idx": int(i),
                "open_date": dates[trade_open_idx] if trade_open_idx < len(dates) else "",
                "close_date": dates[i] if i < len(dates) else "",
                "open_price": float(trade_open_price),
                "close_price": float(close_price),
                "bars_held": int(i - trade_open_idx),
                "pnl_return": float(pnl),
                "direction": float(prev_pos),
            })
            if pos != 0:
                in_trade = True
                trade_open_idx = i
                trade_open_price = cl[i]
                prev_pos = pos
            else:
                in_trade = False

    if in_trade:
        i_last = T - 1
        close_price = cl[i_last]
        pnl = (close_price - trade_open_price) / trade_open_price * prev_pos - friction
        trades.append({
            "open_idx": int(trade_open_idx),
            "close_idx": int(i_last),
            "open_date": dates[trade_open_idx] if trade_open_idx < len(dates) else "",
            "close_date": dates[i_last] if i_last < len(dates) else "",
            "open_price": float(trade_open_price),
            "close_price": float(close_price),
            "bars_held": int(i_last - trade_open_idx),
            "pnl_return": float(pnl),
            "direction": float(prev_pos),
        })

    total_return = float(equity[-1] - 1.0)
    win_rate = float(np.mean([t["pnl_return"] > 0 for t in trades])) if trades else 0.0

    return {
        "equity": equity.tolist(),
        "returns": strategy_returns.tolist(),
        "dates": list(dates[:T]),
        "trades": trades,
        "close_series": cl.tolist(),
        "position_series": executed_position.tolist(),
        "diagnostics": diagnostics,
        "metrics": {
            "total_return": total_return,
            "cagr": _cagr(total_return, T - 1),
            "sharpe": _sharpe(strategy_returns),
            "max_drawdown": _max_drawdown(equity),
            "win_rate": win_rate,
            "n_trades": len(trades),
        },
    }


# ---------------------------------------------------------------------------
# Input hash (staleness detection)
# ---------------------------------------------------------------------------

def compute_input_hash(
    representatives_json: list[dict],
    data_as_of: date | str,
    cost_bps: float,
    slippage_bps: float,
    side_policy: str,
    *,
    mc_method: str | None = None,
    n_paths: int | None = None,
    block_mean: int | None = None,
    seed: int | None = None,
    logic_version: str | None = None,
) -> str:
    """SHA-256 of the inputs that determine backtest output.

    When data_as_of or representatives change, the hash changes and the
    stored result should be recomputed.
    """
    payload = json.dumps(
        {
            "reps": representatives_json,
            "data_as_of": str(data_as_of),
            "cost_bps": round(cost_bps, 4),
            "slippage_bps": round(slippage_bps, 4),
            "side_policy": side_policy,
            "mc_method": mc_method,
            "n_paths": n_paths,
            "block_mean": block_mean,
            "seed": seed,
            "logic_version": logic_version,
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Combinations helper
# ---------------------------------------------------------------------------

def all_category_subsets(categories: list[str]) -> list[list[str]]:
    """Return all size-2 and size-3 subsets of the given categories."""
    from itertools import combinations
    subsets: list[list[str]] = []
    for r in (2, 3):
        subsets.extend([list(c) for c in combinations(categories, r)])
    return subsets
