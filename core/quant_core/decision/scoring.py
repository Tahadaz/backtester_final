from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import hashlib
import math

import numpy as np
import pandas as pd

from .levels import compute_levels_support_resistance
from .regime import classify_regime
from .risk import compute_rr_and_invalidation


def _clamp_0_100(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except Exception:
        return default
    if not math.isfinite(out):
        return default
    return out


def _fmt_num(value: Any, digits: int = 4) -> str:
    out = _safe_float(value)
    if out is None:
        return "n/a"
    return f"{out:.{digits}f}"


def _fmt_pct(value: Any, digits: int = 2) -> str:
    out = _safe_float(value)
    if out is None:
        return "n/a"
    return f"{out * 100.0:.{digits}f}%"


def _weighted_total(layers: dict[str, dict[str, Any]]) -> float:
    total_weight = 0.0
    weighted = 0.0
    for payload in layers.values():
        score = _safe_float(payload.get("score"), 0.0) or 0.0
        weight = _safe_float(payload.get("weight"), 0.0) or 0.0
        weighted += score * weight
        total_weight += weight
    if total_weight <= 0:
        return 0.0
    return _clamp_0_100(weighted / total_weight)


def _normalize_direction(signal_value: float | int | None) -> int:
    v = _safe_float(signal_value, 0.0) or 0.0
    if v > 0:
        return 1
    if v < 0:
        return -1
    return 0


def _safe_last(series: pd.Series | None) -> float | None:
    if series is None or len(series) == 0:
        return None
    return _safe_float(series.iloc[-1])


def _regime_bucket(label: str | None, bias: int) -> str:
    raw = str(label or "").strip().lower()
    if "bull" in raw or bias > 0:
        return "bullish"
    if "bear" in raw or bias < 0:
        return "bearish"
    return "neutral"


def _confirmation_policy(*, direction: int, regime_label: str | None, regime_bias: int, strategy_kind: str) -> dict[str, Any]:
    base_required = 2 if strategy_kind in {"macd", "ma_cross", "ichimoku", "stoch_vwap"} else 1
    if direction == 0:
        return {
            "check_set": "neutral_none",
            "required": 0,
            "base_required": base_required,
            "counter_regime": False,
            "score_penalty": 0.0,
            "regime_bucket": _regime_bucket(regime_label, regime_bias),
            "reason": "neutral direction -> no directional confirmation",
        }

    bucket = _regime_bucket(regime_label, regime_bias)
    # Explicit (direction, regime) map keeps behavior interpretable and testable.
    policy_map: dict[tuple[int, str], dict[str, Any]] = {
        (1, "bullish"): {"check_set": "long", "required_boost": 0, "score_penalty": 0.0, "counter_regime": False},
        (1, "bearish"): {"check_set": "long", "required_boost": 1, "score_penalty": 12.0, "counter_regime": True},
        (1, "neutral"): {"check_set": "long", "required_boost": 0, "score_penalty": 0.0, "counter_regime": False},
        (-1, "bearish"): {"check_set": "short", "required_boost": 0, "score_penalty": 0.0, "counter_regime": False},
        (-1, "bullish"): {"check_set": "short", "required_boost": 1, "score_penalty": 12.0, "counter_regime": True},
        (-1, "neutral"): {"check_set": "short", "required_boost": 0, "score_penalty": 0.0, "counter_regime": False},
    }
    mapped = dict(policy_map.get((direction, bucket)) or policy_map[(direction, "neutral")])
    required = max(1, base_required + int(mapped.get("required_boost", 0)))
    mapped["required"] = required
    mapped["base_required"] = base_required
    mapped["regime_bucket"] = bucket
    mapped["reason"] = "counter-regime confirmation requires stronger evidence." if mapped["counter_regime"] else "standard directional confirmation rules."
    return mapped


def _compute_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)
    avg_gain = gains.rolling(window, min_periods=window).mean()
    avg_loss = losses.rolling(window, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def _compute_macd_hist(close: pd.Series) -> pd.Series:
    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    line = ema_fast - ema_slow
    signal = line.ewm(span=9, adjust=False).mean()
    return line - signal


def _flatten_numeric_params(raw: Any) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        return {}

    out: dict[str, float] = {}

    def _visit(prefix: str, value: Any) -> None:
        if isinstance(value, Mapping):
            for k, v in value.items():
                key = f"{prefix}.{k}" if prefix else str(k)
                _visit(key, v)
            return
        fv = _safe_float(value)
        if fv is not None:
            out[prefix] = fv

    for key, value in raw.items():
        if str(key).startswith("_"):
            continue
        _visit(str(key), value)
    return out


def _extract_perf_value(row: Mapping[str, Any]) -> float | None:
    for key in ("objective_value", "cagr", "pnl", "sharpe", "stat.cagr", "stat.pnl"):
        value = _safe_float(row.get(key))
        if value is not None:
            return value
    return None


def _bootstrap_max_drawdown_quantile(
    returns: Sequence[float],
    *,
    n_paths: int,
    seed: int,
    q: float = 0.95,
) -> float | None:
    clean = [float(x) for x in returns if _safe_float(x) is not None]
    if len(clean) < 8 or n_paths <= 0:
        return None

    rng = np.random.default_rng(seed)
    arr = np.asarray(clean, dtype=float)
    n = len(arr)
    dds: list[float] = []
    for _ in range(int(n_paths)):
        sampled = rng.choice(arr, size=n, replace=True)
        equity = np.cumprod(1.0 + sampled)
        peak = np.maximum.accumulate(equity)
        dd = (equity / np.where(peak == 0, 1.0, peak)) - 1.0
        dds.append(float(np.nanmin(dd)))
    if not dds:
        return None
    return float(np.quantile(dds, q))


def compute_opportunity_score(
    *,
    bars: pd.DataFrame,
    strategy_direction: float | int | None,
    strategy_kind: str,
    levels_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Tactical quality score of today's setup.
    """
    close = pd.to_numeric(bars.get("Close"), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    volume = pd.to_numeric(bars.get("Volume"), errors="coerce").replace([np.inf, -np.inf], np.nan)
    if close.empty:
        empty_layers = {
            k: {"score": 50.0, "weight": 0.2, "inputs": {}, "thresholds": {}, "explain": "Missing price data."}
            for k in ("regime", "direction", "confirmation", "timing", "risk")
        }
        return {"total": 50.0, "layers": empty_layers, "trigger_snapshot": {}}

    direction = _normalize_direction(strategy_direction)
    regime = classify_regime(bars)
    levels = dict(levels_payload or compute_levels_support_resistance(bars, direction=direction))
    rr_payload = compute_rr_and_invalidation(
        direction=direction,
        entry=_safe_float(levels.get("entry")),
        stop=_safe_float(levels.get("stop")),
        target=_safe_float(levels.get("target")),
    )

    regime_inputs = dict(regime.get("inputs") or {})
    regime_inputs.setdefault("label", str(regime.get("label") or "unknown"))
    regime_inputs.setdefault("bias", int(regime.get("bias") or 0))
    regime_base_explain = str(regime.get("explain") or "").strip()
    regime_explain = (
        f"Regime={regime_inputs.get('label')} (bias={regime_inputs.get('bias')}). "
        f"price={_fmt_num(regime_inputs.get('price'))}, "
        f"sma200={_fmt_num(regime_inputs.get('sma200'))}, "
        f"sma200_slope_20={_fmt_pct(regime_inputs.get('sma200_slope_pct_20'))}, "
        f"adx={_fmt_num(regime_inputs.get('adx'), 2)}."
    )
    if regime_base_explain:
        regime_explain = f"{regime_explain} {regime_base_explain}"
    regime_layer = {
        "score": _clamp_0_100(_safe_float(regime.get("score"), 50.0) or 50.0),
        "weight": 0.2,
        "inputs": regime_inputs,
        "thresholds": dict(regime.get("thresholds") or {}),
        "explain": regime_explain,
    }

    regime_bias = int(regime.get("bias") or 0)
    if direction == 0:
        direction_score = 45.0
        direction_explain = "Neutral signal; no directional edge."
    elif regime_bias == 0:
        direction_score = 60.0
        direction_explain = "Directional signal in neutral regime."
    elif direction == regime_bias:
        direction_score = 88.0
        direction_explain = "Signal aligns with structural regime."
    else:
        direction_score = 25.0
        direction_explain = "Signal conflicts with regime direction."
    direction_explain = f"{direction_explain} (strategy_direction={direction}, regime_bias={regime_bias})."
    direction_layer = {
        "score": direction_score,
        "weight": 0.2,
        "inputs": {"strategy_direction": direction, "regime_bias": regime_bias, "strategy_kind": strategy_kind},
        "thresholds": {"aligned": 1, "neutral_bias": 0, "conflict": -1},
        "explain": direction_explain,
    }

    sma20 = close.rolling(20, min_periods=20).mean()
    sma50 = close.rolling(50, min_periods=50).mean()
    sma100 = close.rolling(100, min_periods=100).mean()
    rsi14 = _compute_rsi(close, window=14)
    macd_hist = _compute_macd_hist(close)
    close_now = _safe_float(close.iloc[-1])
    sma20_now = _safe_last(sma20)
    sma50_now = _safe_last(sma50)
    sma100_now = _safe_last(sma100)
    rsi14_now = _safe_last(rsi14)
    macd_hist_now = _safe_last(macd_hist)

    if close_now is None:
        empty_layers = {
            k: {"score": 50.0, "weight": 0.2, "inputs": {}, "thresholds": {}, "explain": "Missing finite close data."}
            for k in ("regime", "direction", "confirmation", "timing", "risk")
        }
        return {"total": 50.0, "layers": empty_layers, "trigger_snapshot": {}}

    vol_ratio = None
    if volume is not None and len(volume) > 0:
        vol_avg20 = volume.rolling(20, min_periods=5).mean()
        vol_now = _safe_last(volume)
        vol_avg_now = _safe_last(vol_avg20)
        if vol_now is not None and vol_avg_now not in (None, 0.0):
            vol_ratio = _safe_float(vol_now / vol_avg_now)

    checks_long: dict[str, bool | None] = {
        "price_vs_sma50": (close_now >= sma50_now) if sma50_now is not None else None,
        "rsi_above_50": (rsi14_now >= 50.0) if rsi14_now is not None else None,
        "macd_hist_positive": (macd_hist_now >= 0.0) if macd_hist_now is not None else None,
        "volume_above_avg20": (vol_ratio >= 1.0) if vol_ratio is not None else None,
    }
    checks_short: dict[str, bool | None] = {
        "price_vs_sma50": (close_now <= sma50_now) if sma50_now is not None else None,
        "rsi_below_50": (rsi14_now <= 50.0) if rsi14_now is not None else None,
        "macd_hist_negative": (macd_hist_now <= 0.0) if macd_hist_now is not None else None,
        "volume_above_avg20": (vol_ratio >= 1.0) if vol_ratio is not None else None,
    }

    regime_label = str(regime_inputs.get("label") or regime.get("label") or "unknown")
    policy = _confirmation_policy(
        direction=direction,
        regime_label=regime_label,
        regime_bias=regime_bias,
        strategy_kind=str(strategy_kind).strip().lower(),
    )
    applied_checks_raw: dict[str, bool | None]
    if direction == 0:
        applied_checks_raw = {}
    elif policy.get("check_set") == "short":
        applied_checks_raw = checks_short
    else:
        applied_checks_raw = checks_long

    total_checks = len(applied_checks_raw)
    available_checks = {name: ok for name, ok in applied_checks_raw.items() if ok is not None}
    missing_checks = [name for name, ok in applied_checks_raw.items() if ok is None]
    passed_checks = [name for name, ok in available_checks.items() if bool(ok)]
    failed_checks = [name for name, ok in available_checks.items() if not bool(ok)]
    met = int(len(passed_checks))
    available_total = len(available_checks)
    required = int(min(total_checks, policy.get("required", 0)))

    if direction == 0:
        confirmation_score = 50.0
        confirmation_explain = "neutral direction -> no directional confirmation"
    else:
        if available_total <= 0:
            confirmation_score = 35.0
        else:
            confirmation_score = 30.0 + (70.0 * (met / max(available_total, 1)))
        if met < required:
            confirmation_score -= 20.0
        if missing_checks:
            confirmation_score -= min(15.0, 4.0 * len(missing_checks))
        confirmation_score -= float(policy.get("score_penalty", 0.0))
        confirmation_score = _clamp_0_100(confirmation_score)
        confirmation_explain = (
            f"{met}/{max(available_total, 1)} finite confirmations satisfied "
            f"(required={required}, total={total_checks}). "
            f"Applied={policy.get('check_set')} under regime={policy.get('regime_bucket')} "
            f"(counter_regime={bool(policy.get('counter_regime'))}). "
            f"Passed: {', '.join(passed_checks) if passed_checks else 'none'}. "
            f"Failed: {', '.join(failed_checks) if failed_checks else 'none'}. "
            f"Missing: {', '.join(missing_checks) if missing_checks else 'none'}. "
            f"{str(policy.get('reason') or '').strip()}"
        )
    confirmation_layer = {
        "score": confirmation_score,
        "weight": 0.2,
        "inputs": {
            "checks": applied_checks_raw,
            "applied_check_set": policy.get("check_set"),
            "applied_checks": list(applied_checks_raw.keys()),
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "missing_checks": missing_checks,
            "met": met,
            "available": available_total,
            "total": total_checks,
            "required": required,
            "policy": {
                "regime_bucket": policy.get("regime_bucket"),
                "counter_regime": bool(policy.get("counter_regime")),
                "base_required": int(policy.get("base_required", 0) or 0),
                "score_penalty": float(policy.get("score_penalty", 0.0) or 0.0),
                "reason": policy.get("reason"),
            },
        },
        "thresholds": {"min_required": required, "high_quality_ratio": 0.75, "volume_ratio_min": 1.0},
        "explain": confirmation_explain,
    }

    dist_sma100 = None
    support_dist = None
    resistance_dist = None
    if sma100_now not in (None, 0.0):
        dist_sma100 = abs(close_now - sma100_now) / abs(sma100_now)
    if dist_sma100 is None:
        timing_score = 55.0
    elif dist_sma100 <= 0.02:
        timing_score = 90.0
    elif dist_sma100 <= 0.05:
        timing_score = 65.0
    else:
        timing_score = 30.0
    support = _safe_float(levels.get("support"))
    resistance = _safe_float(levels.get("resistance"))
    if direction > 0 and support not in (None, 0.0):
        support_dist = max(0.0, (close_now - support) / close_now)
        timing_score += 8.0 if support_dist <= 0.02 else -5.0
    elif direction < 0 and resistance not in (None, 0.0):
        resistance_dist = max(0.0, (resistance - close_now) / close_now)
        timing_score += 8.0 if resistance_dist <= 0.02 else -5.0
    timing_score = _clamp_0_100(timing_score)
    timing_parts = [f"distance_to_sma100={_fmt_pct(dist_sma100)}"]
    if direction > 0:
        timing_parts.append(f"distance_to_support={_fmt_pct(support_dist)}")
    elif direction < 0:
        timing_parts.append(f"distance_to_resistance={_fmt_pct(resistance_dist)}")
    timing_explain = (
        f"{' | '.join(timing_parts)}. "
        "Timing favors non-extended entries and proximity to structural levels."
    )
    timing_layer = {
        "score": timing_score,
        "weight": 0.2,
        "inputs": {
            "close": close_now,
            "sma20": sma20_now,
            "sma50": sma50_now,
            "sma100": sma100_now,
            "rsi14": rsi14_now,
            "macd_hist": macd_hist_now,
            "vol_ratio": vol_ratio,
            "distance_to_sma100_pct": dist_sma100,
            "distance_to_support_pct": support_dist,
            "distance_to_resistance_pct": resistance_dist,
            "support": support,
            "resistance": resistance,
        },
        "thresholds": {"high": 0.02, "medium": 0.05},
        "explain": timing_explain,
    }

    rr_inputs = dict(rr_payload.get("inputs") or {})
    rr_base_explain = str(rr_payload.get("explain") or "").strip()
    risk_explain = (
        f"RR={_fmt_num(rr_payload.get('rr'), 2)} with "
        f"entry={_fmt_num(rr_inputs.get('entry'))}, "
        f"stop={_fmt_num(rr_inputs.get('stop'))}, "
        f"target={_fmt_num(rr_inputs.get('target'))}, "
        f"direction={int(_safe_float(rr_inputs.get('direction'), 0.0) or 0.0)}."
    )
    if rr_base_explain:
        risk_explain = f"{risk_explain} {rr_base_explain}"
    risk_layer = {
        "score": _clamp_0_100(_safe_float(rr_payload.get("score"), 20.0) or 20.0),
        "weight": 0.2,
        "inputs": {
            **rr_inputs,
            "levels_valid": bool(rr_payload.get("levels_valid", True)),
            "invalid_reason": rr_payload.get("invalid_reason"),
        },
        "thresholds": dict(rr_payload.get("thresholds") or {}),
        "explain": risk_explain,
    }

    trigger_snapshot = {
        "close": close_now,
        "sma20": sma20_now,
        "sma50": sma50_now,
        "sma100": sma100_now,
        "rsi14": rsi14_now,
        "macd_hist": macd_hist_now,
        "vol_ratio": vol_ratio,
        "distance_to_sma100": dist_sma100,
        "distance_to_support": support_dist,
        "distance_to_resistance": resistance_dist,
        "support": support,
        "resistance": resistance,
    }

    layers = {
        "regime": regime_layer,
        "direction": direction_layer,
        "confirmation": confirmation_layer,
        "timing": timing_layer,
        "risk": risk_layer,
    }
    return {"total": _weighted_total(layers), "layers": layers, "trigger_snapshot": trigger_snapshot}


def compute_confidence_score(
    *,
    row: Mapping[str, Any],
    same_strategy_rows: Sequence[Mapping[str, Any]],
    walk_forward_rows: Sequence[Mapping[str, Any]] | None = None,
    walk_forward_summary: Mapping[str, Any] | None = None,
    trade_ledger: Sequence[Mapping[str, Any]] | None = None,
    returns: Sequence[float] | None = None,
    mc_paths: int = 200,
    random_seed: int = 42,
) -> dict[str, Any]:
    """
    Structural robustness score.
    """
    wf_rows = list(walk_forward_rows or [])
    wf_summary = dict(walk_forward_summary or {}) if isinstance(walk_forward_summary, Mapping) else {}
    row_cagr = _safe_float(row.get("cagr"), 0.0) or 0.0
    row_sharpe = _safe_float(row.get("sharpe"), 0.0) or 0.0

    oos_values: list[float] = []
    oos_cagr: list[float] = []
    for wf in wf_rows:
        if str(wf.get("strategy_kind") or "").strip().lower() != str(row.get("strategy_kind") or "").strip().lower():
            continue
        v = _safe_float(wf.get("objective_value"))
        if v is not None:
            oos_values.append(v)
        c = _safe_float(wf.get("stat.cagr"))
        if c is not None:
            oos_cagr.append(c)

    if oos_values or oos_cagr:
        median_oos = float(np.median(oos_values)) if oos_values else 0.0
        median_oos_cagr = float(np.median(oos_cagr)) if oos_cagr else row_cagr
        positive_ratio = (
            float(np.mean([x > 0 for x in (oos_cagr or oos_values)]))
            if (oos_cagr or oos_values)
            else 0.5
        )
        oos_score = _clamp_0_100(45.0 + positive_ratio * 35.0 + np.clip(median_oos_cagr * 150.0, -20.0, 20.0))
        oos_inputs = {
            "median_oos_objective": median_oos,
            "median_oos_cagr": median_oos_cagr,
            "positive_ratio": positive_ratio,
            "n_folds": len(oos_values or oos_cagr),
        }
    elif wf_summary:
        summary_objective = _safe_float(
            wf_summary.get("objective_median"),
            _safe_float(wf_summary.get("objective_mean")),
        )
        summary_cagr = _safe_float(wf_summary.get("cagr"), row_cagr)
        summary_folds = int(_safe_float(wf_summary.get("n_folds"), 0.0) or 0.0)
        positive_ratio = _safe_float(wf_summary.get("positive_ratio"))
        if positive_ratio is None:
            ref = summary_cagr if summary_cagr is not None else summary_objective
            if ref is None:
                positive_ratio = 0.5
            elif ref > 0:
                positive_ratio = 1.0
            elif ref < 0:
                positive_ratio = 0.0
            else:
                positive_ratio = 0.5
        positive_ratio = float(np.clip(float(positive_ratio), 0.0, 1.0))
        median_oos = float(summary_objective if summary_objective is not None else 0.0)
        median_oos_cagr = float(summary_cagr if summary_cagr is not None else row_cagr)
        oos_score = _clamp_0_100(45.0 + positive_ratio * 35.0 + np.clip(median_oos_cagr * 150.0, -20.0, 20.0))
        oos_inputs = {
            "source": "walk_forward_summary",
            "median_oos_objective": median_oos,
            "median_oos_cagr": median_oos_cagr,
            "positive_ratio": positive_ratio,
            "n_folds": summary_folds,
        }
    else:
        oos_score = _clamp_0_100(50.0 + np.clip(row_cagr * 120.0, -25.0, 25.0) + np.clip(row_sharpe * 8.0, -15.0, 15.0))
        oos_inputs = {"fallback_cagr": row_cagr, "fallback_sharpe": row_sharpe}

    oos_layer = {
        "score": oos_score,
        "weight": 0.2,
        "inputs": oos_inputs,
        "thresholds": {"high_positive_ratio": 0.7, "target_cagr": 0.1},
        "explain": "Out-of-sample performance combines profitability consistency and OOS CAGR quality.",
    }

    gaps: list[float] = []
    for wf in wf_rows:
        if str(wf.get("strategy_kind") or "").strip().lower() != str(row.get("strategy_kind") or "").strip().lower():
            continue
        tr = _safe_float(wf.get("train_objective_value"))
        te = _safe_float(wf.get("objective_value"))
        if tr is None or te is None:
            continue
        base = abs(tr) if abs(tr) > 1e-9 else 1.0
        gaps.append(abs(tr - te) / base)

    n_gap_samples = len(gaps)
    if gaps:
        med_gap = float(np.median(gaps))
        if med_gap <= 0.10:
            stability_score = 90.0
        elif med_gap <= 0.25:
            stability_score = 70.0
        elif med_gap <= 0.50:
            stability_score = 45.0
        else:
            stability_score = 25.0
    elif _safe_float(wf_summary.get("is_oos_gap_median")) is not None:
        med_gap = float(_safe_float(wf_summary.get("is_oos_gap_median"), 0.0) or 0.0)
        n_gap_samples = int(_safe_float(wf_summary.get("n_folds"), 0.0) or 0.0)
        if med_gap <= 0.10:
            stability_score = 90.0
        elif med_gap <= 0.25:
            stability_score = 70.0
        elif med_gap <= 0.50:
            stability_score = 45.0
        else:
            stability_score = 25.0
    else:
        med_gap = None
        stability_score = 55.0
    stability_layer = {
        "score": stability_score,
        "weight": 0.2,
        "inputs": {"median_is_oos_gap_ratio": med_gap, "n_samples": n_gap_samples},
        "thresholds": {"excellent": 0.1, "good": 0.25, "weak": 0.5},
        "explain": "Large train/test degradation is penalized to reduce overfit confidence.",
    }

    row_params = _flatten_numeric_params(row.get("best_params_json"))
    perf_pairs: list[tuple[float, Mapping[str, Any]]] = []
    for cand in same_strategy_rows:
        perf = _extract_perf_value(cand)
        if perf is None:
            continue
        perf_pairs.append((perf, cand))

    neighbors: list[float] = []
    for perf, cand in perf_pairs:
        cand_params = _flatten_numeric_params(cand.get("best_params_json"))
        if not row_params or not cand_params:
            continue
        common_keys = [k for k in row_params.keys() if k in cand_params]
        if not common_keys:
            continue
        within = True
        for key in common_keys:
            base = abs(row_params[key]) if abs(row_params[key]) > 1e-9 else 1.0
            if abs(cand_params[key] - row_params[key]) / base > 0.10:
                within = False
                break
        if within:
            neighbors.append(float(perf))

    if len(neighbors) >= 4:
        mean_perf = float(np.mean(neighbors))
        std_perf = float(np.std(neighbors))
        denom = abs(mean_perf) if abs(mean_perf) > 1e-9 else 1.0
        cv = std_perf / denom
        if cv <= 0.10:
            robustness_score = 90.0
        elif cv <= 0.20:
            robustness_score = 72.0
        elif cv <= 0.35:
            robustness_score = 52.0
        else:
            robustness_score = 30.0
    else:
        cv = None
        robustness_score = 55.0
    robustness_layer = {
        "score": robustness_score,
        "weight": 0.2,
        "inputs": {"neighbors": len(neighbors), "coefficient_of_variation": cv},
        "thresholds": {"neighbor_tolerance_pct": 0.10, "stable_cv": 0.2},
        "explain": "Parameter robustness rewards smooth local performance around chosen parameters.",
    }

    max_dd = abs(_safe_float(row.get("max_drawdown"), 0.0) or 0.0)
    if max_dd <= 0.10:
        dd_score = 90.0
    elif max_dd <= 0.20:
        dd_score = 75.0
    elif max_dd <= 0.30:
        dd_score = 55.0
    elif max_dd <= 0.40:
        dd_score = 35.0
    else:
        dd_score = 20.0

    mc_returns = list(returns or [])
    if not mc_returns and trade_ledger:
        mc_returns = [
            float(r)
            for r in (
                _safe_float(item.get("return_pct"))
                for item in trade_ledger
                if isinstance(item, Mapping)
            )
            if r is not None
        ]
    q95 = _bootstrap_max_drawdown_quantile(
        mc_returns,
        n_paths=int(max(0, mc_paths)),
        seed=int(random_seed),
    )
    if q95 is not None:
        q95_abs = abs(q95)
        if q95_abs <= 0.20:
            mc_score = 85.0
        elif q95_abs <= 0.30:
            mc_score = 65.0
        elif q95_abs <= 0.40:
            mc_score = 45.0
        else:
            mc_score = 25.0
        dd_tail_score = _clamp_0_100(0.6 * dd_score + 0.4 * mc_score)
    else:
        dd_tail_score = dd_score
    dd_tail_layer = {
        "score": dd_tail_score,
        "weight": 0.2,
        "inputs": {"max_drawdown_abs": max_dd, "mc_max_dd_q95": q95, "mc_paths": int(mc_paths)},
        "thresholds": {"maxdd_good": 0.2, "maxdd_weak": 0.35},
        "explain": "Drawdown and bootstrap tail-risk estimate structural downside sensitivity.",
    }

    net_total = None
    gross_total = None
    if trade_ledger:
        net_vals = []
        gross_vals = []
        for item in trade_ledger:
            if not isinstance(item, Mapping):
                continue
            nv = _safe_float(item.get("net_pnl"))
            gv = _safe_float(item.get("gross_pnl"))
            if nv is not None:
                net_vals.append(nv)
            if gv is not None:
                gross_vals.append(gv)
        if net_vals:
            net_total = float(np.sum(net_vals))
        if gross_vals:
            gross_total = float(np.sum(gross_vals))

    if gross_total not in (None, 0.0) and net_total is not None:
        drag = max(0.0, 1.0 - (net_total / gross_total))
        stressed = net_total - abs(net_total) * 0.25 - abs(gross_total) * 0.10 * drag
        collapse = stressed / (abs(net_total) + 1e-9)
        cost_score = _clamp_0_100(90.0 - drag * 120.0 + np.clip(collapse, -1.0, 1.0) * 10.0)
        cost_inputs = {"net_total": net_total, "gross_total": gross_total, "drag": drag, "stressed_ratio": collapse}
    else:
        n_fills = abs(_safe_float(row.get("n_fills"), 0.0) or 0.0)
        efficiency = _safe_float(row.get("efficiency"), 0.0) or 0.0
        churn_penalty = min(35.0, n_fills / 30.0)
        cost_score = _clamp_0_100(65.0 + np.clip(efficiency * 20.0, -20.0, 20.0) - churn_penalty)
        cost_inputs = {"n_fills": n_fills, "efficiency": efficiency}
    cost_layer = {
        "score": cost_score,
        "weight": 0.2,
        "inputs": cost_inputs,
        "thresholds": {"stress_net_cut": 0.25, "stress_cost_multiplier": 1.10},
        "explain": "Cost sensitivity penalizes setups whose edge collapses under stressed frictions.",
    }

    layers = {
        "oos_performance": oos_layer,
        "is_oos_stability": stability_layer,
        "parameter_robustness": robustness_layer,
        "drawdown_tail_risk": dd_tail_layer,
        "cost_sensitivity": cost_layer,
    }
    return {"total": _weighted_total(layers), "layers": layers}


def deterministic_seed_from_key(key: str) -> int:
    digest = hashlib.sha256(str(key).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)
