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

from .domain import CATEGORY_FAMILIES, FactorConditionMeta
from .oos_eval import compute_signal_array, VariantDef
from .ta_combo import is_combo_variant, variant_from_component

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
    condition = None
    cond_payload = rep.get("factor_condition")
    if isinstance(cond_payload, dict):
        condition = FactorConditionMeta(
            condition_id=str(cond_payload["condition_id"]),
            factor_ticker=str(cond_payload["factor_ticker"]),
            form=str(cond_payload["form"]),
            lookback=int(cond_payload["lookback"]),
            threshold=float(cond_payload["threshold"]),
            direction=str(cond_payload["direction"]),
        )

    return VariantDef(
        variant_id=str(rep["variant_id"]),
        family=family,
        archetype=str(rep["archetype"]),
        params=dict(rep.get("params") or {}),
        factor_condition=condition,
    )


def _combo_requires_precomputed(variant: VariantDef) -> bool:
    if not is_combo_variant(variant):
        return False
    for payload in variant.params.get("components", []):
        if not isinstance(payload, dict):
            continue
        try:
            component = variant_from_component(payload)
        except Exception:
            continue
        if component.factor_condition is not None or component.family.endswith("@fx"):
            return True
    return False


def _build_family_signal_series_result(
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
    representatives_json: list[dict],
    *,
    fallback_family: str | None = None,
    precomputed_signals: dict[str, np.ndarray] | None = None,
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
            if (
                variant.factor_condition is not None
                or variant.family.endswith("@fx")
                or _combo_requires_precomputed(variant)
            ):
                if not precomputed_signals or variant.variant_id not in precomputed_signals:
                    raise ValueError(
                        f"missing precomputed Factor x TA signal for {variant.variant_id}"
                    )
                sig = np.asarray(precomputed_signals[variant.variant_id], dtype=np.float64)
                if len(sig) != len(close):
                    raise ValueError(
                        f"precomputed signal length {len(sig)} != close length {len(close)}"
                    )
            else:
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
    precomputed_signals: dict[str, np.ndarray] | None = None,
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
        precomputed_signals=precomputed_signals,
    )
    return result


def build_category_signal_series_engine(
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
    family_results: dict[str, dict],
    category: str,
    *,
    precomputed_signals: dict[str, np.ndarray] | None = None,
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

    family_keys: list[str] = []
    for family in families_in_category:
        for candidate_key in (family, f"{family}@fx"):
            if candidate_key in family_results and candidate_key not in family_keys:
                family_keys.append(candidate_key)
    for family_key, row in family_results.items():
        if row.get("category") == category and family_key not in family_keys:
            family_keys.append(family_key)

    family_sigs: list[tuple[float, np.ndarray]] = []
    for family_key in family_keys:
        fr = family_results.get(family_key)
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
            fallback_family=family_key,
            precomputed_signals=precomputed_signals,
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
    *,
    precomputed_signals: dict[str, np.ndarray] | None = None,
) -> np.ndarray:
    """Build signal series from WFO-selected representatives for one category.

    representatives_json comes from wfo_signal_summary.representatives_json.
    Same weight scheme as build_family_signal_series (normalized_weight).
    """
    return build_family_signal_series(
        close,
        volume,
        high,
        low,
        representatives_json,
        precomputed_signals=precomputed_signals,
    )


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

def _position_side(value: float) -> int:
    if value > 0.0:
        return 1
    if value < 0.0:
        return -1
    return 0


def apply_trade_cooldown_to_position_series(
    position_series: np.ndarray,
    cooldown_bars: int,
) -> tuple[np.ndarray, dict[str, int]]:
    """Gate a desired position series with a post-exit trade cooldown.

    The cooldown is execution-level: once an existing position is closed, or an
    opposite-side target appears, the strategy must stay flat for the next N
    bars before opening a new position. Same-side exposure changes are allowed.
    """
    desired = np.asarray(position_series, dtype=np.float64)
    cooldown = max(0, int(cooldown_bars or 0))
    diagnostics = {
        "cooldown_bars": cooldown,
        "cooldown_events": 0,
        "cooldown_blocked_bars": 0,
    }
    if cooldown <= 0 or len(desired) == 0:
        return desired.copy(), diagnostics

    executed = np.zeros(len(desired), dtype=np.float64)
    cooldown_left = 0

    for i, raw_desired in enumerate(desired):
        target = float(np.clip(raw_desired, -1.0, 1.0))
        target_side = _position_side(target)
        prev = float(executed[i - 1]) if i > 0 else 0.0
        prev_side = _position_side(prev)
        started_cooldown = False

        if prev_side != 0:
            if target_side == 0:
                executed[i] = 0.0
                cooldown_left = cooldown
                diagnostics["cooldown_events"] += 1
                started_cooldown = True
            elif target_side == prev_side:
                executed[i] = target
            else:
                executed[i] = 0.0
                cooldown_left = cooldown
                diagnostics["cooldown_events"] += 1
                diagnostics["cooldown_blocked_bars"] += 1
                started_cooldown = True
        elif target_side != 0 and cooldown_left > 0:
            executed[i] = 0.0
            diagnostics["cooldown_blocked_bars"] += 1
        else:
            executed[i] = target

        if not started_cooldown and cooldown_left > 0 and _position_side(float(executed[i])) == 0:
            cooldown_left -= 1

    return executed, diagnostics


def run_signal_backtest(
    signal_series: np.ndarray,
    close: np.ndarray,
    dates: list[str],
    *,
    cost_bps: float = 5.0,
    slippage_bps: float = 5.0,
    side_policy: str = "long_only",
    cooldown_bars: int = 0,
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
        "cooldown_bars": max(0, int(cooldown_bars or 0)),
        "cooldown_events": 0,
        "cooldown_blocked_bars": 0,
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
    desired_position = np.zeros(T, dtype=np.float64)
    if T > 1:
        desired_position[1:] = target_position[:-1]
    executed_position, cooldown_diag = apply_trade_cooldown_to_position_series(
        desired_position,
        cooldown_bars,
    )

    diagnostics = {
        "flat_executed": bool(np.all(executed_position == 0.0)),
        "target_nonzero_bars": int(np.sum(target_position != 0.0)),
        "target_mean": float(np.mean(target_position)),
        "target_min": float(np.min(target_position)),
        "target_max": float(np.max(target_position)),
        **cooldown_diag,
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
    cooldown_bars: int | None = None,
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
            "cooldown_bars": max(0, int(cooldown_bars or 0)),
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
