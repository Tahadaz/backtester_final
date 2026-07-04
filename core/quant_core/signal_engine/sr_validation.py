"""Evidence gates for support/resistance execution overlays.

This module is intentionally pure: no database, HTTP, or plotting concerns.
It validates whether an S/R overlay adds value to an existing baseline signal
after costs, using a chronological selection/proof split.
"""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from core.quant_core.research.edge import (
    FRESHNESS_MIN_N,
    MC_PVALUE_THRESHOLD,
    N_MIN,
    WILSON_LB_THRESHOLD,
)
from core.quant_core.research.stats.hit_rate import wilson_ci

SR_VALIDATION_VERSION = "2026-07-03-sr-overlay-validation-v1"
DEFAULT_SELECTION_FRACTION = 0.5
DEFAULT_BOOTSTRAP_ITER = 1000


def _finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if np.isfinite(out) else None


def _safe_returns(values: Sequence[Any] | np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype="float64")
    if arr.ndim != 1:
        arr = arr.reshape(-1)
    arr = np.where(np.isfinite(arr), arr, 0.0)
    return arr


def _max_drawdown_from_returns(returns: np.ndarray) -> float:
    if returns.size == 0:
        return 0.0
    equity = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / np.where(peak > 0.0, peak, 1.0)
    return float(np.nanmax(drawdown)) if drawdown.size else 0.0


def _sharpe(returns: np.ndarray) -> float:
    if returns.size < 2:
        return 0.0
    std = float(np.std(returns, ddof=1))
    if std <= 0.0 or not np.isfinite(std):
        return 0.0
    return float(np.mean(returns) / std * np.sqrt(252.0))


def _trade_close_slot(trade: dict[str, Any]) -> int | None:
    close_idx = _finite_float(trade.get("close_idx"))
    if close_idx is None:
        return None
    return max(0, int(close_idx) - 1)


def _window_trades(
    trades: Sequence[dict[str, Any]],
    start: int,
    end: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trade in trades:
        slot = _trade_close_slot(trade)
        if slot is not None and start <= slot < end:
            rows.append(dict(trade))
    return rows


def _metrics(
    returns: np.ndarray,
    trades: Sequence[dict[str, Any]],
    *,
    start: int,
    end: int,
) -> dict[str, Any]:
    window_returns = returns[start:end]
    window_trades = _window_trades(trades, start, end)
    trade_returns = [
        float(value)
        for trade in window_trades
        if (value := _finite_float(trade.get("pnl_return"))) is not None
    ]
    wins = sum(1 for value in trade_returns if value > 0.0)
    n_trades = len(trade_returns)
    hit_rate = float(wins / n_trades) if n_trades else 0.0
    hit_ci_lower, hit_ci_upper = wilson_ci(wins, n_trades) if n_trades else (0.0, 1.0)
    total_return = float(np.prod(1.0 + window_returns) - 1.0) if window_returns.size else 0.0
    years = max(int(window_returns.size), 1) / 252.0
    cagr = float((1.0 + total_return) ** (1.0 / years) - 1.0) if total_return > -1.0 else -1.0
    return {
        "start_idx": int(start),
        "end_idx": int(end),
        "n_bars": int(window_returns.size),
        "n_trades": int(n_trades),
        "total_return": total_return,
        "cagr": cagr,
        "mean_return": float(np.mean(window_returns)) if window_returns.size else 0.0,
        "sharpe": _sharpe(window_returns),
        "max_drawdown": _max_drawdown_from_returns(window_returns),
        "win_rate": hit_rate,
        "hit_ci_lower": float(hit_ci_lower),
        "hit_ci_upper": float(hit_ci_upper),
    }


def _uplift(baseline: dict[str, Any], overlay: dict[str, Any]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for key in ("total_return", "cagr", "mean_return", "sharpe", "win_rate"):
        base = _finite_float(baseline.get(key))
        over = _finite_float(overlay.get(key))
        out[key] = (over - base) if base is not None and over is not None else None
    base_dd = _finite_float(baseline.get("max_drawdown"))
    over_dd = _finite_float(overlay.get("max_drawdown"))
    out["max_drawdown"] = (base_dd - over_dd) if base_dd is not None and over_dd is not None else None
    return out


def _mean_uplift_pvalue(
    baseline_returns: np.ndarray,
    overlay_returns: np.ndarray,
    *,
    seed: int,
    n_iter: int,
) -> float | None:
    n = min(len(baseline_returns), len(overlay_returns))
    if n < 2:
        return None
    diff = overlay_returns[:n] - baseline_returns[:n]
    observed = float(np.mean(diff))
    if not np.isfinite(observed) or observed <= 0.0:
        return 1.0
    centered = diff - observed
    rng = np.random.default_rng(int(seed))
    count = 0
    samples = max(100, int(n_iter))
    for _ in range(samples):
        draw = rng.choice(centered, size=n, replace=True)
        if float(np.mean(draw)) >= observed:
            count += 1
    return float((count + 1) / (samples + 1))


def baseline_returns_from_position(
    close: Sequence[Any] | np.ndarray,
    position: Sequence[Any] | np.ndarray,
    *,
    cost_bps: float,
    slippage_bps: float = 0.0,
) -> np.ndarray:
    """Return per-bar baseline returns for an executed position series."""
    close_arr = _safe_returns(close)
    pos = _safe_returns(position)
    n = min(len(close_arr), len(pos))
    if n < 2:
        return np.zeros(0, dtype="float64")
    close_arr = close_arr[:n]
    pos = pos[:n]
    out = np.zeros(n - 1, dtype="float64")
    friction = (float(cost_bps) + float(slippage_bps)) / 10_000.0
    prev_pos = 0.0
    for idx in range(n - 1):
        c0 = float(close_arr[idx])
        c1 = float(close_arr[idx + 1])
        ret = (c1 / c0 - 1.0) if c0 > 0.0 else 0.0
        current_pos = float(pos[idx])
        transition_cost = abs(current_pos - prev_pos) * friction
        out[idx] = current_pos * ret - transition_cost
        prev_pos = current_pos
    if n >= 2:
        out[-1] -= abs(float(pos[n - 1]) - prev_pos) * friction
    return out


def validate_sr_overlay_candidate(
    *,
    baseline_returns: Sequence[Any] | np.ndarray,
    overlay_returns: Sequence[Any] | np.ndarray,
    overlay_trades: Sequence[dict[str, Any]],
    selection_fraction: float = DEFAULT_SELECTION_FRACTION,
    min_trades: int = N_MIN,
    freshness_min_trades: int = FRESHNESS_MIN_N,
    pvalue_threshold: float = MC_PVALUE_THRESHOLD,
    wilson_threshold: float = WILSON_LB_THRESHOLD,
    bootstrap_iter: int = DEFAULT_BOOTSTRAP_ITER,
    seed: int = 42,
) -> dict[str, Any]:
    """Validate one S/R overlay candidate against a baseline return stream."""
    baseline = _safe_returns(baseline_returns)
    overlay = _safe_returns(overlay_returns)
    n = min(len(baseline), len(overlay))
    if n < 2:
        return {
            "version": SR_VALIDATION_VERSION,
            "decision": "unavailable",
            "status": "unavailable",
            "reason": "insufficient_returns",
            "reason_codes": ["insufficient_returns"],
            "gates": {},
            "selection": {},
            "proof": {},
            "freshness": {},
        }
    baseline = baseline[:n]
    overlay = overlay[:n]
    split = min(n - 1, max(1, int(round(n * float(selection_fraction)))))
    selection_baseline = _metrics(baseline, [], start=0, end=split)
    selection_overlay = _metrics(overlay, overlay_trades, start=0, end=split)
    proof_baseline = _metrics(baseline, [], start=split, end=n)
    proof_overlay = _metrics(overlay, overlay_trades, start=split, end=n)
    selection_uplift = _uplift(selection_baseline, selection_overlay)
    proof_uplift = _uplift(proof_baseline, proof_overlay)

    proof_overlay_returns = overlay[split:n]
    proof_baseline_returns = baseline[split:n]
    pvalue = _mean_uplift_pvalue(
        proof_baseline_returns,
        proof_overlay_returns,
        seed=seed,
        n_iter=bootstrap_iter,
    )

    proof_trades = _window_trades(overlay_trades, split, n)
    fresh_trades = proof_trades[-max(1, int(freshness_min_trades)) :]
    fresh_returns = [
        float(value)
        for trade in fresh_trades
        if (value := _finite_float(trade.get("pnl_return"))) is not None
    ]
    freshness = {
        "n_trades": len(fresh_returns),
        "mean_trade_return": float(np.mean(fresh_returns)) if fresh_returns else None,
        "status": "ready" if len(fresh_returns) >= int(freshness_min_trades) else "insufficient_n",
    }

    gates = {
        "selection_positive": bool((selection_uplift.get("total_return") or 0.0) > 0.0),
        "proof_net_uplift": bool((proof_uplift.get("total_return") or 0.0) > 0.0),
        "drawdown_not_worse": bool((proof_uplift.get("max_drawdown") or 0.0) >= 0.0),
        "n": bool(int(proof_overlay["n_trades"]) >= int(min_trades)),
        "wilson": bool(float(proof_overlay["hit_ci_lower"]) > float(wilson_threshold)),
        "pvalue": bool(pvalue is not None and float(pvalue) < float(pvalue_threshold)),
        "freshness": bool(
            freshness["status"] == "ready"
            and freshness["mean_trade_return"] is not None
            and float(freshness["mean_trade_return"]) > 0.0
        ),
    }
    reason_codes = [name for name, passed in gates.items() if not passed]
    actionable = not reason_codes
    status = "actionable" if actionable else "research_only"
    return {
        "version": SR_VALIDATION_VERSION,
        "decision": status,
        "status": status,
        "reason": "validated" if actionable else "failed_gates",
        "reason_codes": reason_codes,
        "split_index": int(split),
        "gates": gates,
        "selection": {
            "baseline": selection_baseline,
            "overlay": selection_overlay,
            "uplift": selection_uplift,
        },
        "proof": {
            "baseline": proof_baseline,
            "overlay": proof_overlay,
            "uplift": proof_uplift,
            "mean_uplift_pvalue": pvalue,
        },
        "freshness": freshness,
    }

