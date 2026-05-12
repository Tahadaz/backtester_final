"""WFO signal layer — per-category WFO-optimized signal.

Runs a Walk-Forward Analysis across all indicators in a category,
selects the best decorrelated ensemble, and returns a signal score
comparable to the A→G pipeline output.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from core.quant_core.horizons import DEFAULT_COST_BPS_PER_SIDE, canonical_horizon
from core.quant_core.signal_engine.candidates import generate_candidates
from core.quant_core.signal_engine.current_signal import build_current_signal
from core.quant_core.signal_engine.domain import (
    CATEGORY_FAMILIES,
    FAMILY_SIGNAL_TYPE,
    HORIZON_PARAMS,
    VALID_HORIZONS,
    VariantDef,
    signal_type_label,
    VARIANT_FAMILIES,
)
from core.quant_core.signal_engine.oos_eval import compute_signal_array
from core.quant_core.signal_engine.redundancy import _pearson_corr
from core.quant_core.wfo.config import WalkForwardConfig
from core.quant_core.wfo.engine import EngineResult, WindowScoreResult, run_wfo_engine
from core.quant_core.wfo.window import build_walk_forward_windows


STRICT_WINDOW_POLICY = "strict_fold_driven"
MANUAL_WINDOW_POLICY = "manual_override"
STRICT_RATIO_ANCHORS = (0.25, 0.30, 0.35)
DEFAULT_TOP_K_FOLDS = 6
DEFAULT_MIN_WALK_FORWARDS = 5
DEFAULT_STRICT_FALLBACK_ENABLED = True
DEFAULT_STRICT_FALLBACK_FLOOR = 3
HORIZON_TRAIN_BANDS: dict[str, tuple[int, int]] = {
    "weekly": (168, 336),
    "monthly": (378, 630),
    "quarterly": (672, 1008),
}


def _canonical_signal_horizon(horizon: str) -> str:
    return canonical_horizon(horizon, allow_legacy=True)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def compute_robustness_grade(wfe: float, robustness_ratio: float) -> str:
    """Map WFE + robustness_ratio to a letter grade.

    A: WFE >= 0.65 AND robustness >= 0.75
    B: WFE >= 0.55 AND robustness >= 0.60
    C: WFE >= 0.50 AND robustness >= 0.50
    D: WFE >= 0.40 OR  robustness >= 0.40
    F: everything else
    """
    if wfe >= 0.65 and robustness_ratio >= 0.75:
        return "A"
    if wfe >= 0.55 and robustness_ratio >= 0.60:
        return "B"
    if wfe >= 0.50 and robustness_ratio >= 0.50:
        return "C"
    if wfe >= 0.40 or robustness_ratio >= 0.40:
        return "D"
    return "F"


def compute_composite_score(
    wfe: float,
    robustness_ratio: float,
    mean_oos_sharpe: float,
    worst_fold_drawdown: float,
) -> float:
    """Composite ranking score (0-100) for cross-category comparison.

    Formula:
        0.40 × wfe_norm + 0.30 × robustness_norm + 0.20 × sharpe_norm + 0.10 × dd_norm

    Each component normalized to [0, 1]:
    - wfe_norm      = clamp(wfe, 0, 1)
    - robustness_n  = clamp(robustness_ratio, 0, 1)
    - sharpe_n      = clamp(mean_oos_sharpe / 2.0, 0, 1)   (Sharpe 2.0 = perfect)
    - dd_n          = clamp(1 - |worst_fold_drawdown|, 0, 1)
    """
    def clamp01(x: float) -> float:
        return max(0.0, min(1.0, x))

    wfe_n    = clamp01(wfe)
    rob_n    = clamp01(robustness_ratio)
    sharpe_n = clamp01(mean_oos_sharpe / 2.0)
    dd_n     = clamp01(1.0 - abs(worst_fold_drawdown))

    raw = 0.40 * wfe_n + 0.30 * rob_n + 0.20 * sharpe_n + 0.10 * dd_n
    return round(raw * 100, 2)


# ---------------------------------------------------------------------------
# Grid construction
# ---------------------------------------------------------------------------

def build_category_candidate_grid(
    category: str,
    horizon: str,
    families: list[str] | None = None,
) -> list[VariantDef]:
    """Build the full candidate pool for a category by unioning all families.

    For category="tendance", calls generate_candidates() for each of
    [sma, ema, ema_cross, ichimoku, psar] and concatenates the results.

    Parameters
    ----------
    families:
        Override the family list for this category. When None, uses the full
        CATEGORY_FAMILIES[category] list (expanded variant).

    Returns
    -------
    list[VariantDef]
        Typically 100-200 variants depending on category and horizon.
    """
    horizon = _canonical_signal_horizon(horizon)
    if category not in CATEGORY_FAMILIES:
        raise ValueError(f"Unknown category {category!r}")
    if horizon not in VALID_HORIZONS:
        raise ValueError(f"Unknown horizon {horizon!r}")

    active_families = families if families is not None else CATEGORY_FAMILIES[category]

    pool: list[VariantDef] = []
    for family in active_families:
        try:
            pool.extend(generate_candidates(family, horizon))
        except (ValueError, NotImplementedError):
            pass  # family not yet implemented
    return pool


def _variant_min_history(variant: VariantDef) -> int:
    """Estimate the minimum number of bars needed to compute this variant's signal.

    Uses the largest period-like param as a proxy for warmup bars.
    Falls back to 50 if no period param is found.
    """
    period_keys = ("window", "period", "slow", "slow_period", "tenkan", "kijun",
                   "senkou_b", "n_slow", "slow_window")
    max_period = 1
    for key in period_keys:
        val = variant.params.get(key)
        if isinstance(val, (int, float)) and val > max_period:
            max_period = int(val)
    return max(max_period + 1, 50)


# ---------------------------------------------------------------------------
# Minimal trading wrapper (PROM evaluation)
# ---------------------------------------------------------------------------

def _evaluate_variant_returns_and_pnl(
    signal_arr: np.ndarray,
    close: np.ndarray,
    cost_bps: float = DEFAULT_COST_BPS_PER_SIDE,
) -> tuple[float, np.ndarray]:
    """Calculate daily returns net of transaction costs."""
    if len(signal_arr) < 2:
        return 0.0, np.array([])
    returns = np.diff(close) / close[:-1]
    positions = signal_arr[:-1]
    trades = np.abs(np.diff(np.concatenate(([0.0], positions))))
    costs = trades * cost_bps / 10_000.0
    daily_returns = positions * returns - costs
    gross_pnl = np.sum(daily_returns)
    return float(gross_pnl), daily_returns


def _evaluate_variant_pnl(
    signal_arr: np.ndarray,
    close: np.ndarray,
    cost_bps: float = DEFAULT_COST_BPS_PER_SIDE,
) -> float:
    """Simple signal-following P&L: go long when signal > 0, flat otherwise.

    Returns total return net of transaction costs.
    """
    pnl, _ = _evaluate_variant_returns_and_pnl(signal_arr, close, cost_bps)
    return pnl


def _extract_trades(signal_arr: np.ndarray, close: np.ndarray) -> list[float]:
    """Extract per-trade returns from signal array."""
    trades: list[float] = []
    in_trade = False
    entry_price = 0.0
    direction = 0.0

    for i in range(len(signal_arr)):
        if not in_trade and signal_arr[i] != 0:
            in_trade = True
            entry_price = close[i]
            direction = signal_arr[i]
        elif in_trade and (signal_arr[i] == 0 or signal_arr[i] != direction):
            trade_return = direction * (close[i] - entry_price) / entry_price
            trades.append(trade_return)
            in_trade = False
            if signal_arr[i] != 0 and signal_arr[i] != direction:
                entry_price = close[i]
                direction = signal_arr[i]
                in_trade = True

    if in_trade and len(close) > 0:
        trades.append(direction * (close[-1] - entry_price) / entry_price)

    return trades


def _compute_prom_for_variant(
    close_is: np.ndarray,
    close_oos: np.ndarray,
    variant: VariantDef,
    full_close: np.ndarray,
    variant_idx_start_is: int,
    variant_idx_start_oos: int,
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    cost_bps: float = DEFAULT_COST_BPS_PER_SIDE,
) -> tuple[float, float, float, float]:
    """Compute (prom, is_return, oos_return, oos_sharpe) for a single variant.

    Uses compute_signal_array() on full data then slices to IS/OOS windows.
    """
    from core.quant_core.wfo.prom import compute_prom

    vol_full  = volume if volume is not None else None
    high_full = high   if high   is not None else None
    low_full  = low    if low    is not None else None

    sig_full = compute_signal_array(
        full_close, variant,
        volume=vol_full, high=high_full, low=low_full,
    )

    sig_is  = sig_full[variant_idx_start_is:variant_idx_start_is + len(close_is)]
    sig_oos = sig_full[variant_idx_start_oos:variant_idx_start_oos + len(close_oos)]

    is_return = _evaluate_variant_pnl(sig_is,  close_is,  cost_bps)
    oos_return, oos_daily_rets = _evaluate_variant_returns_and_pnl(sig_oos, close_oos, cost_bps)
    
    import math
    from core.quant_core.significance import sharpe_ratio
    oos_sharpe = float(sharpe_ratio(oos_daily_rets))
    if math.isnan(oos_sharpe):
        oos_sharpe = 0.0

    trade_list = _extract_trades(sig_is, close_is)
    if len(trade_list) >= 2:
        prom = compute_prom(trade_list, 1.0)
    else:
        prom = is_return

    return prom, is_return, oos_return, oos_sharpe


# ---------------------------------------------------------------------------
# WFO result dataclass
# ---------------------------------------------------------------------------

@dataclass
class WfoCategoryResult:
    """Result of WFO for one category × symbol × horizon."""
    category: str
    symbol: str
    horizon: str
    status: str                                  # "succeeded" | "failed" | "insufficient_data"
    score_pct: float                             # -100 to +100
    signal_label: str
    representatives: list[dict[str, Any]]
    wfe_pct: float
    robustness_ratio: float
    total_folds: int
    profitable_folds: int
    mean_oos_sharpe: float
    total_oos_pnl: float
    worst_fold_drawdown: float
    composite_score: float
    robustness_grade: str
    engine_result: EngineResult | None = None
    config_used: dict[str, Any] = field(default_factory=dict)
    window_diagnostics: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    data_as_of: str = ""
    compute_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Window-policy helpers
# ---------------------------------------------------------------------------

def _config_to_dict(config: WalkForwardConfig) -> dict[str, int]:
    return {
        "train_bars": int(config.train_bars),
        "oos_bars": int(config.oos_bars),
        "step_bars": int(config.effective_step),
    }


def _single_window_dominance(engine_result: EngineResult | None) -> float:
    if engine_result is None or not engine_result.windows:
        return 1.0
    pnl_values = [max(0.0, float(window.oos_return)) for window in engine_result.windows]
    total_positive = sum(pnl_values)
    if total_positive <= 0:
        return 1.0
    return max(pnl_values) / total_positive


def _fail_result(
    *,
    category: str,
    horizon: str,
    started_at: float,
    reason: str,
    status: str = "failed",
    config_used: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
    engine_result: EngineResult | None = None,
) -> WfoCategoryResult:
    return WfoCategoryResult(
        category=category,
        symbol="",
        horizon=horizon,
        status=status,
        score_pct=0.0,
        signal_label="Pas disponible",
        representatives=[],
        wfe_pct=0.0,
        robustness_ratio=0.0,
        total_folds=0,
        profitable_folds=0,
        mean_oos_sharpe=0.0,
        total_oos_pnl=0.0,
        worst_fold_drawdown=0.0,
        composite_score=0.0,
        robustness_grade="F",
        engine_result=engine_result,
        config_used=config_used or {},
        window_diagnostics=diagnostics or {},
        error_message=reason,
        compute_seconds=round(time.monotonic() - started_at, 2),
    )


def _slice_or_none(data: np.ndarray | None, start: int) -> np.ndarray | None:
    if data is None:
        return None
    if start <= 0:
        return data
    return data[start:]


def _apply_horizon_cap(
    *,
    horizon: str,
    close: np.ndarray,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None, np.ndarray | None, int, int]:
    horizon = _canonical_signal_horizon(horizon)
    hp = HORIZON_PARAMS[horizon]
    cap_bars = max(int(hp.get("max_years", 0) * 252), hp["train"] + hp["test"])
    if len(close) <= cap_bars:
        return close, volume, high, low, len(close), 0
    start = len(close) - cap_bars
    return (
        close[start:],
        _slice_or_none(volume, start),
        _slice_or_none(high, start),
        _slice_or_none(low, start),
        cap_bars,
        start,
    )


def _strict_window_candidates(
    *,
    horizon: str,
    data_length: int,
    max_lookback: int,
    requested_min_walk_forwards: int = DEFAULT_MIN_WALK_FORWARDS,
    strict_fallback_enabled: bool = DEFAULT_STRICT_FALLBACK_ENABLED,
    strict_fallback_floor: int = DEFAULT_STRICT_FALLBACK_FLOOR,
    top_k_folds: int = DEFAULT_TOP_K_FOLDS,
) -> tuple[list[WalkForwardConfig], dict[str, Any]]:
    horizon = _canonical_signal_horizon(horizon)
    band_min, band_max = HORIZON_TRAIN_BANDS[horizon]
    hp = HORIZON_PARAMS[horizon]
    anchor = {
        "train_bars": hp["train"],
        "oos_bars": hp["test"],
        "step_bars": hp["step"],
    }

    strict_fallback_floor = max(1, int(strict_fallback_floor))
    requested = max(int(requested_min_walk_forwards), strict_fallback_floor)
    candidate_rows: list[dict[str, Any]] = []

    for train in range(band_min, band_max + 1):
        for ratio in STRICT_RATIO_ANCHORS:
            oos = max(1, int(round(train * ratio)))
            actual_ratio = oos / train
            if actual_ratio < 0.25 or actual_ratio > 0.35:
                continue
            config = WalkForwardConfig(train_bars=train, oos_bars=oos, step_bars=oos)
            windows = build_walk_forward_windows(
                data_length=data_length,
                config=config,
                max_lookback=max_lookback,
            )
            fold_count = len(windows)
            if fold_count <= 0:
                continue
            candidate_rows.append(
                {
                    "config": config,
                    "fold_count": fold_count,
                    "ratio": round(actual_ratio, 4),
                    "anchor_distance": abs(train - anchor["train_bars"]),
                }
            )

    effective_min_walk_forwards = requested
    feasible_rows = [row for row in candidate_rows if row["fold_count"] >= effective_min_walk_forwards]
    fallback_applied = False

    if not feasible_rows and strict_fallback_enabled:
        for candidate_min in range(requested - 1, strict_fallback_floor - 1, -1):
            fallback_rows = [row for row in candidate_rows if row["fold_count"] >= candidate_min]
            if fallback_rows:
                feasible_rows = fallback_rows
                effective_min_walk_forwards = candidate_min
                fallback_applied = candidate_min != requested
                break

    if not feasible_rows:
        feasible_rows = []

    feasible_rows.sort(
        key=lambda row: (
            -row["fold_count"],
            row["anchor_distance"],
            abs(row["ratio"] - 0.30),
            row["config"].train_bars,
            row["config"].oos_bars,
        )
    )

    shortlisted_rows = feasible_rows[: max(1, int(top_k_folds))]
    diagnostics = {
        "window_policy_used": STRICT_WINDOW_POLICY,
        "horizon_name": horizon,
        "horizon_anchor": anchor,
        "train_band": {"min": band_min, "max": band_max},
        "requested_min_walk_forwards": requested,
        "effective_min_walk_forwards": effective_min_walk_forwards,
        "fallback_applied": fallback_applied,
        "top_k_folds_used": min(len(shortlisted_rows), max(1, int(top_k_folds))),
        "horizon_cap_years": hp.get("max_years"),
        "max_lookback": max_lookback,
        "candidate_configs_considered": [
            {
                **_config_to_dict(row["config"]),
                "fold_count": row["fold_count"],
                "oos_is_ratio": row["ratio"],
                "anchor_distance": row["anchor_distance"],
            }
            for row in shortlisted_rows
        ],
    }
    return [row["config"] for row in shortlisted_rows], diagnostics


def _execute_wfo_category_signal(
    *,
    category: str,
    horizon: str,
    close: np.ndarray,
    pool: list[VariantDef],
    config: WalkForwardConfig,
    max_lookback: int,
    started_at: float,
    cost_bps: float = DEFAULT_COST_BPS_PER_SIDE,
    max_reps: int = 1,
    max_corr: float = 0.85,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    config_used: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> WfoCategoryResult:
    min_bars = config.train_bars + config.oos_bars + max_lookback
    config_payload = {
        **_config_to_dict(config),
        "min_bars_needed": min_bars,
        "max_lookback": max_lookback,
    }
    if config_used:
        config_payload.update(config_used)

    if len(close) < min_bars:
        return _fail_result(
            category=category,
            horizon=horizon,
            started_at=started_at,
            reason=f"Need {min_bars} bars, have {len(close)}",
            status="insufficient_data",
            config_used=config_payload,
            diagnostics=diagnostics,
        )

    _volume = volume
    _high = high
    _low = low

    def evaluate_window(window) -> WindowScoreResult:
        raw_scores: dict[int, float] = {}
        is_returns: dict[int, float] = {}
        oos_returns: dict[int, float] = {}
        oos_sharpes: dict[int, float] = {}

        close_is = close[window.train_start:window.train_end]
        close_oos = close[window.oos_start:window.oos_end]

        for i, variant in enumerate(pool):
            try:
                prom, is_ret, oos_ret, oos_shrp = _compute_prom_for_variant(
                    close_is=close_is,
                    close_oos=close_oos,
                    variant=variant,
                    full_close=close,
                    variant_idx_start_is=window.train_start,
                    variant_idx_start_oos=window.oos_start,
                    volume=_volume,
                    high=_high,
                    low=_low,
                    cost_bps=cost_bps,
                )
            except Exception:
                prom, is_ret, oos_ret, oos_shrp = 0.0, 0.0, 0.0, 0.0
            raw_scores[i] = prom
            is_returns[i] = is_ret
            oos_returns[i] = oos_ret
            oos_sharpes[i] = oos_shrp

        return WindowScoreResult(
            raw_scores=raw_scores,
            is_returns=is_returns,
            oos_returns=oos_returns,
            oos_sharpes=oos_sharpes,
        )

    engine_result = run_wfo_engine(
        data_length=len(close),
        config=config,
        evaluate_window=evaluate_window,
        max_lookback=max_lookback,
    )

    if not engine_result.windows:
        return _fail_result(
            category=category,
            horizon=horizon,
            started_at=started_at,
            reason="No WFO windows produced",
            config_used=config_payload,
            diagnostics=diagnostics,
            engine_result=engine_result,
        )

    last_window = engine_result.windows[-1]
    smoothed = last_window.smoothed_scores
    ranked_indices = sorted(smoothed.keys(), key=lambda idx: smoothed[idx], reverse=True)

    recent_n = min(252, len(close))
    recent_close = close[-recent_n:]
    recent_vol = _volume[-recent_n:] if _volume is not None else None
    recent_high = _high[-recent_n:] if _high is not None else None
    recent_low = _low[-recent_n:] if _low is not None else None

    sig_arrays: list[np.ndarray] = []
    selected: list[tuple[int, VariantDef, float]] = []

    for idx in ranked_indices:
        if len(selected) >= max_reps:
            break
        variant = pool[idx]
        try:
            sig = compute_signal_array(
                recent_close,
                variant,
                volume=recent_vol,
                high=recent_high,
                low=recent_low,
            )
        except Exception:
            continue

        is_redundant = any(
            abs(_pearson_corr(sig, existing_sig)) > max_corr for existing_sig in sig_arrays
        )
        if not is_redundant:
            selected.append((idx, variant, smoothed[idx]))
            sig_arrays.append(sig)

    if selected:
        total_prom = sum(max(0.01, item[2]) for item in selected)
        weights = [max(0.01, item[2]) / total_prom for item in selected]
    else:
        weights = []

    current_signals = []
    for (_, variant, _), weight in zip(selected, weights):
        try:
            current_signals.append(
                build_current_signal(
                    variant,
                    close,
                    volume=_volume,
                    high=_high,
                    low=_low,
                    reliability_weight=weight,
                )
            )
        except Exception:
            pass

    if current_signals:
        total_weight = sum(signal.reliability_weight for signal in current_signals)
        score_raw = (
            sum(signal.signal * signal.reliability_weight for signal in current_signals) / total_weight
            if total_weight > 0
            else 0.0
        )
        score_pct = 100.0 * score_raw
    else:
        score_pct = 0.0

    first_family = CATEGORY_FAMILIES[category][0]
    signal_type = FAMILY_SIGNAL_TYPE.get(first_family, "trend")
    label = signal_type_label(signal_type, score_pct)

    reps_list: list[dict[str, Any]] = []
    for (_, variant, prom_val), weight, current_signal in zip(selected, weights, current_signals):
        reps_list.append(
            {
                "family": variant.family,
                "archetype": variant.archetype,
                "variant_id": variant.variant_id,
                "params": variant.params,
                "signal": current_signal.signal,
                "signal_label": current_signal.signal_label,
                "normalized_weight": round(weight, 4),
                "contribution": round(weight * current_signal.signal, 4),
                "description": variant.description,
                "current_close": current_signal.current_close,
                "indicator_value": current_signal.indicator_value,
                "explanation": current_signal.explanation,
                "wfo_prom": round(prom_val, 6),
            }
        )

    oos_returns_list = [window.oos_return for window in engine_result.windows]
    profitable_count = sum(1 for value in oos_returns_list if value > 0)
    mean_sharpe = float(np.mean(oos_returns_list)) if oos_returns_list else 0.0
    total_pnl = sum(oos_returns_list)
    worst_dd = min(oos_returns_list) if oos_returns_list else 0.0

    composite = compute_composite_score(
        engine_result.wfe,
        engine_result.robustness_ratio,
        mean_sharpe,
        worst_dd,
    )
    grade = compute_robustness_grade(engine_result.wfe, engine_result.robustness_ratio)

    return WfoCategoryResult(
        category=category,
        symbol="",
        horizon=horizon,
        status="succeeded",
        score_pct=round(score_pct, 2),
        signal_label=label,
        representatives=reps_list,
        wfe_pct=round(engine_result.wfe * 100, 2),
        robustness_ratio=round(engine_result.robustness_ratio, 4),
        total_folds=len(engine_result.windows),
        profitable_folds=profitable_count,
        mean_oos_sharpe=round(mean_sharpe, 4),
        total_oos_pnl=round(total_pnl, 4),
        worst_fold_drawdown=round(worst_dd, 4),
        composite_score=round(composite, 2),
        robustness_grade=grade,
        engine_result=engine_result,
        config_used=config_payload,
        window_diagnostics=diagnostics or {},
        data_as_of="",
        compute_seconds=round(time.monotonic() - started_at, 2),
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_wfo_category_signal(
    category: str,
    horizon: str,
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    cost_bps: float = DEFAULT_COST_BPS_PER_SIDE,
    max_reps: int = 1,
    max_corr: float = 0.85,
    train_bars: int | None = None,
    oos_bars: int | None = None,
    step_bars: int | None = None,
    window_policy: str = STRICT_WINDOW_POLICY,
    top_k_folds: int = DEFAULT_TOP_K_FOLDS,
    min_walk_forwards: int = DEFAULT_MIN_WALK_FORWARDS,
    strict_fallback_enabled: bool = DEFAULT_STRICT_FALLBACK_ENABLED,
    strict_fallback_floor: int = DEFAULT_STRICT_FALLBACK_FLOOR,
    families: list[str] | None = None,
) -> WfoCategoryResult:
    """Run Signal-page WFO for one category with auto or manual window selection."""
    t0 = time.monotonic()
    horizon = _canonical_signal_horizon(horizon)

    pool = build_category_candidate_grid(category, horizon, families=families)
    if not pool:
        return _fail_result(
            category=category,
            horizon=horizon,
            started_at=t0,
            reason="No candidates for category",
        )

    hp = HORIZON_PARAMS[horizon]
    max_lookback = max(_variant_min_history(v) for v in pool)
    manual_override = any(value is not None for value in (train_bars, oos_bars, step_bars))

    if manual_override:
        config = WalkForwardConfig(
            train_bars=train_bars if train_bars is not None else hp["train"],
            oos_bars=oos_bars if oos_bars is not None else hp["test"],
            step_bars=step_bars if step_bars is not None else hp["step"],
        )
        diagnostics = {
            "window_policy_used": MANUAL_WINDOW_POLICY,
            "horizon_name": horizon,
            "horizon_anchor": {
                "train_bars": hp["train"],
                "oos_bars": hp["test"],
                "step_bars": hp["step"],
            },
            "train_band": {
                "min": HORIZON_TRAIN_BANDS[horizon][0],
                "max": HORIZON_TRAIN_BANDS[horizon][1],
            },
            "candidate_configs_considered": [_config_to_dict(config)],
            "selected_config": _config_to_dict(config),
            "selected_config_rank": 1,
            "requested_min_walk_forwards": None,
            "effective_min_walk_forwards": None,
            "fallback_applied": False,
            "top_k_folds_used": 1,
            "horizon_cap_years": hp.get("max_years"),
            "max_lookback": max_lookback,
        }
        return _execute_wfo_category_signal(
            category=category,
            horizon=horizon,
            close=close,
            pool=pool,
            config=config,
            max_lookback=max_lookback,
            started_at=t0,
            cost_bps=cost_bps,
            max_reps=max_reps,
            max_corr=max_corr,
            volume=volume,
            high=high,
            low=low,
            config_used={"window_policy_used": MANUAL_WINDOW_POLICY},
            diagnostics=diagnostics,
        )

    working_close, working_volume, working_high, working_low, capped_bars, cap_start_offset = _apply_horizon_cap(
        horizon=horizon,
        close=close,
        volume=volume,
        high=high,
        low=low,
    )
    candidates, base_diagnostics = _strict_window_candidates(
        horizon=horizon,
        data_length=len(working_close),
        max_lookback=max_lookback,
        requested_min_walk_forwards=min_walk_forwards,
        strict_fallback_enabled=strict_fallback_enabled,
        strict_fallback_floor=strict_fallback_floor,
        top_k_folds=top_k_folds,
    )

    if not candidates:
        base_diagnostics["horizon_cap_bars_used"] = capped_bars
        base_diagnostics["horizon_cap_start_offset"] = cap_start_offset
        return _fail_result(
            category=category,
            horizon=horizon,
            started_at=t0,
            status="insufficient_data",
            reason="No feasible strict WFO window configuration",
            diagnostics=base_diagnostics,
            config_used={"window_policy_used": window_policy},
        )

    ranked_results: list[tuple[tuple[float, float, float, float, float], WfoCategoryResult]] = []
    candidate_metrics: list[dict[str, Any]] = []
    anchor_train = hp["train"]
    base_diagnostics["horizon_cap_bars_used"] = capped_bars
    base_diagnostics["horizon_cap_start_offset"] = cap_start_offset

    for candidate_config in candidates:
        config_dict = _config_to_dict(candidate_config)
        result = _execute_wfo_category_signal(
            category=category,
            horizon=horizon,
            close=working_close,
            pool=pool,
            config=candidate_config,
            max_lookback=max_lookback,
            started_at=t0,
            cost_bps=cost_bps,
            max_reps=max_reps,
            max_corr=max_corr,
            volume=working_volume,
            high=working_high,
            low=working_low,
            config_used={"window_policy_used": window_policy},
            diagnostics={**base_diagnostics, "selected_config": config_dict},
        )
        candidate_row = {**config_dict, "status": result.status}
        if result.status == "succeeded" and result.engine_result is not None:
            dominance = _single_window_dominance(result.engine_result)
            train_distance = abs(candidate_config.train_bars - anchor_train) / max(1, anchor_train)
            ranking_key = (
                -result.wfe_pct,
                -result.robustness_ratio,
                dominance,
                train_distance,
                -result.total_oos_pnl,
            )
            ranked_results.append((ranking_key, result))
            candidate_row.update(
                {
                    "wfe_pct": result.wfe_pct,
                    "robustness_ratio": result.robustness_ratio,
                    "single_window_dominance": round(dominance, 6),
                    "total_oos_pnl": result.total_oos_pnl,
                    "distance_to_anchor": round(train_distance, 6),
                    "total_folds": result.total_folds,
                }
            )
        else:
            candidate_row["error_message"] = result.error_message
        candidate_metrics.append(candidate_row)

    if not ranked_results:
        base_diagnostics["candidate_configs_considered"] = candidate_metrics
        return _fail_result(
            category=category,
            horizon=horizon,
            started_at=t0,
            reason="Strict window search produced no successful WFO runs",
            diagnostics=base_diagnostics,
            config_used={"window_policy_used": window_policy},
        )

    ranked_results.sort(key=lambda item: item[0])
    best_result = ranked_results[0][1]
    selected_config = best_result.config_used.copy()
    selected_triplet = {
        "train_bars": selected_config["train_bars"],
        "oos_bars": selected_config["oos_bars"],
        "step_bars": selected_config["step_bars"],
    }

    selected_rank = 1
    for index, row in enumerate(candidate_metrics, start=1):
        if (
            row.get("train_bars") == selected_triplet["train_bars"]
            and row.get("oos_bars") == selected_triplet["oos_bars"]
            and row.get("step_bars") == selected_triplet["step_bars"]
        ):
            selected_rank = index
            break

    best_result.config_used["window_policy_used"] = window_policy
    best_result.window_diagnostics = {
        **base_diagnostics,
        "candidate_configs_considered": candidate_metrics,
        "selected_config": selected_triplet,
        "selected_config_rank": selected_rank,
        "window_policy_used": window_policy,
    }
    return best_result

    if manual_override:
        config = WalkForwardConfig(
            train_bars=train_bars if train_bars is not None else hp["train"],
            oos_bars=oos_bars if oos_bars is not None else hp["test"],
            step_bars=step_bars if step_bars is not None else hp["step"],
        )
    else:
        config = WalkForwardConfig(
            train_bars=hp["train"],
            oos_bars=hp["test"],
            step_bars=hp["step"],
        )

    min_bars = eff_train + eff_oos + max_lookback
    if len(close) < min_bars:
        return _fail(f"Need {min_bars} bars, have {len(close)}", "insufficient_data")

    # Slice helpers — avoid redundant slicing in the closure
    _volume = volume
    _high   = high
    _low    = low

    def evaluate_window(window) -> WindowScoreResult:
        raw_scores: dict[int, float] = {}
        is_returns: dict[int, float] = {}
        oos_returns: dict[int, float] = {}

        close_is  = close[window.train_start:window.train_end]
        close_oos = close[window.oos_start:window.oos_end]

        for i, variant in enumerate(pool):
            try:
                prom, is_ret, oos_ret = _compute_prom_for_variant(
                    close_is=close_is,
                    close_oos=close_oos,
                    variant=variant,
                    full_close=close,
                    variant_idx_start_is=window.train_start,
                    variant_idx_start_oos=window.oos_start,
                    volume=_volume, high=_high, low=_low,
                    cost_bps=cost_bps,
                )
            except Exception:
                prom, is_ret, oos_ret = 0.0, 0.0, 0.0
            raw_scores[i]  = prom
            is_returns[i]  = is_ret
            oos_returns[i] = oos_ret

        return WindowScoreResult(
            raw_scores=raw_scores,
            is_returns=is_returns,
            oos_returns=oos_returns,
        )

    engine_result = run_wfo_engine(
        data_length=len(close),
        config=config,
        evaluate_window=evaluate_window,
        max_lookback=max_lookback,
    )

    if not engine_result.windows:
        return WfoCategoryResult(
            category=category, symbol="", horizon=horizon,
            status="failed", score_pct=0.0, signal_label="Pas disponible",
            representatives=[], wfe_pct=0.0, robustness_ratio=0.0,
            total_folds=0, profitable_folds=0, mean_oos_sharpe=0.0,
            total_oos_pnl=0.0, worst_fold_drawdown=0.0,
            composite_score=0.0, robustness_grade="F",
            engine_result=engine_result,
            error_message="No WFO windows produced",
            compute_seconds=round(time.monotonic() - t0, 2),
        )

    last_window = engine_result.windows[-1]
    smoothed = last_window.smoothed_scores

    # Rank all candidates by smoothed PROM in the last IS window
    ranked_indices = sorted(smoothed.keys(), key=lambda k: smoothed[k], reverse=True)

    # Select top K decorrelated representatives on recent data
    recent_n = min(252, len(close))
    recent_close  = close[-recent_n:]
    recent_vol    = _volume[-recent_n:] if _volume is not None else None
    recent_high   = _high[-recent_n:]   if _high   is not None else None
    recent_low    = _low[-recent_n:]    if _low    is not None else None

    sig_arrays: list[np.ndarray] = []
    selected: list[tuple[int, VariantDef, float]] = []

    for idx in ranked_indices:
        if len(selected) >= max_reps:
            break
        variant = pool[idx]
        try:
            sig = compute_signal_array(
                recent_close, variant,
                volume=recent_vol, high=recent_high, low=recent_low,
            )
        except Exception:
            continue

        is_redundant = any(
            abs(_pearson_corr(sig, existing_sig)) > max_corr
            for existing_sig in sig_arrays
        )
        if not is_redundant:
            selected.append((idx, variant, smoothed[idx]))
            sig_arrays.append(sig)

    # Weights proportional to smoothed PROM (floor at 0.01 to avoid zero weights)
    if selected:
        total_prom = sum(max(0.01, s[2]) for s in selected)
        weights = [max(0.01, s[2]) / total_prom for s in selected]
    else:
        weights = []

    # Build current-bar signals
    current_signals = []
    for (idx, variant, prom_val), weight in zip(selected, weights):
        try:
            cs = build_current_signal(
                variant, close,
                volume=_volume, high=_high, low=_low,
                reliability_weight=weight,
            )
            current_signals.append(cs)
        except Exception:
            pass

    # Weighted ensemble score
    if current_signals:
        total_w = sum(cs.reliability_weight for cs in current_signals)
        score_raw = (
            sum(cs.signal * cs.reliability_weight for cs in current_signals) / total_w
            if total_w > 0 else 0.0
        )
        score_pct = 100.0 * score_raw
    else:
        score_pct = 0.0

    # Signal label
    first_family = CATEGORY_FAMILIES[category][0]
    signal_type  = FAMILY_SIGNAL_TYPE.get(first_family, "trend")
    label = signal_type_label(signal_type, score_pct)

    # Build representatives list
    reps_list: list[dict[str, Any]] = []
    for (idx, variant, prom_val), weight, cs in zip(selected, weights, current_signals):
        reps_list.append({
            "family":           variant.family,
            "archetype":        variant.archetype,
            "variant_id":       variant.variant_id,
            "params":           variant.params,
            "signal":           cs.signal,
            "signal_label":     cs.signal_label,
            "normalized_weight": round(weight, 4),
            "contribution":     round(weight * cs.signal, 4),
            "description":      variant.description,
            "current_close":    cs.current_close,
            "indicator_value":  cs.indicator_value,
            "explanation":      cs.explanation,
            "wfo_prom":         round(prom_val, 6),
        })

    # Aggregate metrics
    oos_returns_list = [w.oos_return for w in engine_result.windows]
    profitable_count = sum(1 for r in oos_returns_list if r > 0)
    mean_sharpe  = float(np.mean(oos_returns_list)) if oos_returns_list else 0.0
    total_pnl    = sum(oos_returns_list)
    worst_dd     = min(oos_returns_list) if oos_returns_list else 0.0

    composite = compute_composite_score(
        engine_result.wfe, engine_result.robustness_ratio, mean_sharpe, worst_dd
    )
    grade = compute_robustness_grade(engine_result.wfe, engine_result.robustness_ratio)

    return WfoCategoryResult(
        category=category, symbol="", horizon=horizon,
        status="succeeded",
        score_pct=round(score_pct, 2),
        signal_label=label,
        representatives=reps_list,
        wfe_pct=round(engine_result.wfe * 100, 2),
        robustness_ratio=round(engine_result.robustness_ratio, 4),
        total_folds=len(engine_result.windows),
        profitable_folds=profitable_count,
        mean_oos_sharpe=round(mean_sharpe, 4),
        total_oos_pnl=round(total_pnl, 4),
        worst_fold_drawdown=round(worst_dd, 4),
        composite_score=round(composite, 2),
        robustness_grade=grade,
        engine_result=engine_result,
        data_as_of="",
        compute_seconds=round(time.monotonic() - t0, 2),
    )
