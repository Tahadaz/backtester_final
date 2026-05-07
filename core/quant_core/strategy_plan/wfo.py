from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from itertools import product
import math
from typing import Any, Callable

import pandas as pd

from core.quant_core.data import drop_incomplete_ohlcv_rows
from core.quant_core.results import ResultsAnalyzer
from core.quant_core.strategy_plan.allocation import compute_strategy_allocation
from core.quant_core.strategy_plan.backtest import (
    _align_timestamp_to_index,
    _build_cost_model,
    _default_fallback_ladder,
    _signal_cost_bps,
    _simulate_stock,
)
from core.quant_core.strategy_plan.score_frame import compute_strategy_score_frame, derive_max_lookback
from core.quant_core.wfo.config import ParameterRange, WalkForwardConfig
from core.quant_core.wfo.date_presets import HORIZON_LOOKBACK_YEARS, TRADING_BARS_PER_YEAR
from core.quant_core.wfo.neighbor_avg import neighbor_average_1d, neighbor_average_nd
from core.quant_core.wfo.profile import evaluate_optimization_profile
from core.quant_core.wfo.prom import compute_prom
from core.quant_core.wfo.sizing import compute_kelly_fraction, compute_trade_stats
from core.quant_core.wfo.statistical import block_bootstrap_equity_paths, deflated_sharpe_ratio
from core.quant_core.wfo.wfe import ReturnWindow, compute_robustness_ratio, compute_single_window_dominance, compute_wfe
from core.quant_core.wfo.window import build_walk_forward_windows


_INTEGER_PARAM_SUFFIXES = (
    ".window",
    ".period",
    ".fast",
    ".slow",
    ".signal",
    ".ema_period",
    ".bars",
    ".cooldown_bars",
)
_WINDOW_GRID = 21
_MAX_CANDIDATE_TUPLES = 100_000
_ANALYZER = ResultsAnalyzer()
_WINDOW_POLICY_STRICT = "strict_fold_driven"
_WINDOW_POLICY_LEGACY = "legacy_ratio_scan"
_WINDOW_POLICY_FAMILY_SCORE_FIXED = "family_score_fixed"
_STRICT_RATIO_ANCHORS: tuple[float, ...] = (0.25, 0.30, 0.35)
_SHORT_OOS_CAP_MAX_EXCLUSIVE = 70
_FAMILY_SCORE_FIXED_WINDOWS: dict[str, dict[str, int]] = {
    "short": {"train_bars": 126, "oos_bars": 21, "step_bars": 21},
    "medium": {"train_bars": 252, "oos_bars": 63, "step_bars": 63},
    "long": {"train_bars": 504, "oos_bars": 126, "step_bars": 126},
}


@dataclass(frozen=True)
class _ParamDimension:
    path: str
    values: tuple[float | int, ...]
    integer_like: bool


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def _window_summaries(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "window_index": window.get("window_index"),
            "summary": dict(window.get("summary") or {}),
        }
        for window in windows
    ]


def _coerce_param_value(value: Any, *, integer_like: bool) -> float | int:
    if integer_like:
        return int(round(_safe_float(value, 0.0)))
    return float(_safe_float(value, 0.0))


def _parse_param_path(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    text = str(path)
    current: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == ".":
            if current:
                tokens.append("".join(current))
                current = []
            index += 1
            continue
        if char == "[":
            if current:
                tokens.append("".join(current))
                current = []
            closing = text.find("]", index + 1)
            if closing < 0:
                raise ValueError(f"Malformed param path: {path}")
            raw_index = text[index + 1 : closing].strip()
            if not raw_index.isdigit():
                raise ValueError(f"Malformed list index in param path: {path}")
            tokens.append(int(raw_index))
            index = closing + 1
            continue
        current.append(char)
        index += 1
    if current:
        tokens.append("".join(current))
    return tokens


def _resolve_path(root: Any, path: str) -> Any:
    current = root
    for token in _parse_param_path(path):
        current = current[token]
    return current


def _set_param_value(root: Any, path: str, value: float | int) -> None:
    target = _resolve_path(root, path)
    if not isinstance(target, dict):
        raise ValueError(f"Target path is not a WFO param record: {path}")
    target["value"] = value


def _collect_wfo_dimensions(value: Any, path: str, out: list[_ParamDimension]) -> None:
    if isinstance(value, dict):
        mode = str(value.get("mode") or "").strip().lower()
        if mode == "wfo" and "value" in value:
            integer_like = any(str(path).endswith(suffix) for suffix in _INTEGER_PARAM_SUFFIXES)
            values = ParameterRange(
                min_value=_safe_float(value.get("scan_min"), _safe_float(value.get("value"), 0.0)),
                max_value=_safe_float(value.get("scan_max"), _safe_float(value.get("value"), 0.0)),
                step=_safe_float(value.get("scan_step"), 0.0),
            ).values()
            casted = tuple(_coerce_param_value(item, integer_like=integer_like) for item in values)
            out.append(_ParamDimension(path=path, values=casted, integer_like=integer_like))
            return
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            _collect_wfo_dimensions(child, child_path, out)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _collect_wfo_dimensions(child, f"{path}[{index}]", out)


def _candidate_dimensions(stock_config: dict[str, Any]) -> list[_ParamDimension]:
    out: list[_ParamDimension] = []
    for section in ("signal_construction", "entry_rules", "exit_rules", "risk"):
        if section in stock_config:
            _collect_wfo_dimensions(stock_config.get(section), section, out)
    return out


def _candidate_count(dimensions: list[_ParamDimension]) -> int:
    count = 1
    for dimension in dimensions:
        count *= max(len(dimension.values), 1)
    return count


def _iter_candidate_value_maps(dimensions: list[_ParamDimension]) -> list[dict[str, float | int]]:
    if not dimensions:
        return [{}]
    keys = [dimension.path for dimension in dimensions]
    combinations = product(*[dimension.values for dimension in dimensions])
    return [dict(zip(keys, values)) for values in combinations]


def _sample_dimension_values(values: tuple[float | int, ...], target_count: int) -> tuple[float | int, ...]:
    if target_count >= len(values):
        return values
    if target_count <= 1:
        return (values[len(values) // 2],)
    step = (len(values) - 1) / float(target_count - 1)
    indices = [int(round(step * index)) for index in range(target_count)]
    return tuple(values[index] for index in indices)


def _apply_candidate_guardrail(
    dimensions: list[_ParamDimension],
    *,
    max_candidate_tuples: int,
) -> tuple[list[_ParamDimension], dict[str, Any]]:
    if max_candidate_tuples < 1:
        raise ValueError("WFO candidate guardrail must be at least 1.")
    raw_candidate_count = _candidate_count(dimensions)
    raw_lengths = [max(len(dimension.values), 1) for dimension in dimensions]
    target_lengths = list(raw_lengths)
    effective_candidate_count = raw_candidate_count

    while effective_candidate_count > max_candidate_tuples and any(length > 1 for length in target_lengths):
        largest_index = max(range(len(target_lengths)), key=lambda index: target_lengths[index])
        current_len = target_lengths[largest_index]
        if current_len <= 1:
            break
        required_factor = effective_candidate_count / float(max_candidate_tuples)
        target_len = max(1, int(math.floor(current_len / required_factor)))
        if target_len >= current_len:
            target_len = current_len - 1
        effective_candidate_count = (effective_candidate_count // current_len) * target_len
        target_lengths[largest_index] = target_len

    if effective_candidate_count > max_candidate_tuples:
        raise ValueError(
            "WFO candidate guardrail pruning failed to reach the tuple budget "
            f"(raw={raw_candidate_count}, effective={effective_candidate_count}, max={max_candidate_tuples})."
        )

    for index in sorted(range(len(target_lengths)), key=lambda item: raw_lengths[item] - target_lengths[item], reverse=True):
        current_len = target_lengths[index]
        raw_len = raw_lengths[index]
        while current_len < raw_len:
            next_count = (effective_candidate_count // current_len) * (current_len + 1)
            if next_count > max_candidate_tuples:
                break
            current_len += 1
            effective_candidate_count = next_count
        target_lengths[index] = current_len

    reduced_dimensions: list[dict[str, Any]] = []
    capped_dimensions: list[_ParamDimension] = []
    for dimension, target_len in zip(dimensions, target_lengths):
        raw_len = len(dimension.values)
        if target_len >= raw_len:
            capped_dimensions.append(dimension)
            continue
        sampled_values = _sample_dimension_values(dimension.values, target_len)
        capped_dimensions.append(
            _ParamDimension(path=dimension.path, values=sampled_values, integer_like=dimension.integer_like)
        )
        reduced_dimensions.append(
            {
                "path": dimension.path,
                "raw_values": raw_len,
                "effective_values": len(sampled_values),
            }
        )

    effective_candidate_count = _candidate_count(capped_dimensions)
    applied = effective_candidate_count < raw_candidate_count
    warning = None
    if applied:
        warning = (
            f"WFO candidate grid was downsampled from {raw_candidate_count} to {effective_candidate_count} tuples "
            f"to respect the {max_candidate_tuples} tuple guardrail."
        )
    return capped_dimensions, {
        "applied": applied,
        "max_candidate_tuples": max_candidate_tuples,
        "raw_candidate_count": raw_candidate_count,
        "effective_candidate_count": effective_candidate_count,
        "reduced_dimensions": reduced_dimensions,
        "warning": warning,
    }


def _macd_params(stock_config: dict[str, Any]) -> tuple[int, int]:
    families = (((stock_config.get("signal_construction") or {}).get("families") or {}) if _is_record(stock_config.get("signal_construction")) else {})
    macd = families.get("macd") if isinstance(families, dict) else {}
    params = (macd.get("params") if isinstance(macd, dict) else None) or {}
    if not params and isinstance(macd, dict):
        rows = macd.get("rows")
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            params = rows[0].get("params") or {}
    fast_raw = (params.get("fast") or {}).get("value") if isinstance(params.get("fast"), dict) else params.get("fast")
    slow_raw = (params.get("slow") or {}).get("value") if isinstance(params.get("slow"), dict) else params.get("slow")
    return _safe_int(fast_raw, 12), _safe_int(slow_raw, 26)


def _risk_dict(stock_config: dict[str, Any], *, cooldown_override: int) -> dict[str, Any]:
    risk = stock_config.get("risk") if _is_record(stock_config.get("risk")) else {}
    stop_loss = risk.get("stop_loss") if _is_record(risk.get("stop_loss")) else {}
    take_profit = risk.get("take_profit") if _is_record(risk.get("take_profit")) else {}
    time_stop = risk.get("time_stop") if _is_record(risk.get("time_stop")) else {}
    atr_multiplier_raw = (stop_loss.get("atr_multiplier") or {}).get("value") if _is_record(stop_loss.get("atr_multiplier")) else stop_loss.get("atr_multiplier")
    rr_ratio_raw = (take_profit.get("rr_ratio") or {}).get("value") if _is_record(take_profit.get("rr_ratio")) else take_profit.get("rr_ratio")
    bars_raw = (time_stop.get("bars") or {}).get("value") if _is_record(time_stop.get("bars")) else time_stop.get("bars")
    cooldown_raw = (risk.get("cooldown_bars") or {}).get("value") if _is_record(risk.get("cooldown_bars")) else risk.get("cooldown_bars")
    return {
        "max_holding_bars": max(_safe_int(bars_raw, 30), 0),
        "stop_atr_multiplier": max(_safe_float(atr_multiplier_raw, 1.5), 0.0),
        "take_profit_rr": max(_safe_float(rr_ratio_raw, 1.5), 0.0),
        "time_stop_enabled": bool(time_stop.get("enabled", True)),
        "trailing_stop_enabled": bool(risk.get("trailing_stop_enabled", False)),
        "max_position_pct": max(_safe_float(risk.get("max_position_pct"), 20.0), 0.0),
        "cooldown_bars": max(_safe_int(cooldown_raw, cooldown_override), 0),
    }


def _valid_candidate(stock_config: dict[str, Any]) -> tuple[bool, str | None]:
    max_lookback = derive_max_lookback(stock_config, strict_indicator_rows=False)
    if max_lookback <= 0:
        return False, "Non-positive lookback"
    fast, slow = _macd_params(stock_config)
    if fast >= slow:
        return False, "macd.fast must stay below macd.slow"
    risk = _risk_dict(stock_config, cooldown_override=0)
    if risk["stop_atr_multiplier"] <= 0:
        return False, "stop_loss.atr_multiplier must be positive"
    if risk["take_profit_rr"] <= 0:
        return False, "take_profit.rr_ratio must be positive"
    if risk["max_holding_bars"] < 0:
        return False, "time_stop.bars must be non-negative"
    if risk["cooldown_bars"] < 0:
        return False, "cooldown_bars must be non-negative"
    return True, None


def _is_full_family_score_mode(stock_config: dict[str, Any]) -> bool:
    signal_construction = stock_config.get("signal_construction")
    if not _is_record(signal_construction):
        return False
    families = signal_construction.get("families")
    if not _is_record(families):
        return False

    active_modes: list[str] = []
    for family in families.values():
        if not _is_record(family) or not bool(family.get("enabled")):
            continue
        source_mode = str(family.get("source_mode") or "indicator_rows").strip().lower()
        if source_mode == "family_ensemble":
            active_modes.append("family_ensemble")
            continue
        rows = [item for item in list(family.get("rows") or []) if _is_record(item) and bool(item.get("enabled", True))]
        if rows:
            active_modes.append("indicator_rows")
    return bool(active_modes) and all(mode == "family_ensemble" for mode in active_modes)


def _family_score_fixed_window_for_horizon(horizon: str) -> dict[str, int]:
    horizon_key = str(horizon or "medium").strip().lower()
    return dict(_FAMILY_SCORE_FIXED_WINDOWS.get(horizon_key, _FAMILY_SCORE_FIXED_WINDOWS["medium"]))


def _curve_records(series: pd.Series) -> list[dict[str, Any]]:
    if series is None or series.empty:
        return []
    series = series.astype(float)
    return [{"date": pd.Timestamp(index).date().isoformat(), "value": float(value)} for index, value in series.items()]


def _normalized_curve_records(series: pd.Series) -> list[dict[str, Any]]:
    if series is None or series.empty:
        return []
    base = float(series.iloc[0]) if float(series.iloc[0]) != 0 else 1.0
    normalized = (series.astype(float) / base).replace([float("inf"), float("-inf")], 0.0).fillna(0.0)
    return _curve_records(normalized)


def _metric_summary(simulation: Any, *, trade_count: int) -> dict[str, Any]:
    metrics = dict(simulation.summary_metrics or {})
    metrics["number_of_trades"] = int(trade_count)
    return metrics


def _trade_ledger(simulation: Any) -> pd.DataFrame:
    if simulation.fills is None or simulation.fills.empty:
        return pd.DataFrame()
    fills = simulation.fills.copy()
    fills["timestamp"] = pd.to_datetime(fills["timestamp"])
    return _ANALYZER._trade_ledger_from_fills(fills)


def _simulation_returns(simulation: Any) -> list[float]:
    if simulation.equity is None or simulation.equity.empty or len(simulation.equity.index) < 2:
        return []
    return [float(value) for value in simulation.equity.astype(float).pct_change().dropna().tolist()]


def _slice_bars(frame: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    return frame.iloc[start:end].copy()


def _apply_candidate(stock_config: dict[str, Any], values: dict[str, float | int]) -> dict[str, Any]:
    candidate = deepcopy(stock_config)
    for path, value in values.items():
        _set_param_value(candidate, path, value)
    return candidate


def _stock_uses_kelly_rule_sizing(stock_config: dict[str, Any]) -> bool:
    for section in ("entry_rules", "exit_rules"):
        for rule in list(stock_config.get(section) or []):
            if not isinstance(rule, dict):
                continue
            sizing = rule.get("sizing") if isinstance(rule.get("sizing"), dict) else {}
            if str(sizing.get("mode") or "").strip().lower() == "kelly_wfo":
                return True
    return False


def _kelly_is_safe(kelly: Any) -> bool:
    return (
        _safe_float(getattr(kelly, "fraction", 0.0), 0.0) > 0.0
        and _safe_int(getattr(kelly, "n_trades", 0), 0) >= 30
        and getattr(kelly, "reason", None) is None
    )


def _apply_execution_kelly(
    stock_config: dict[str, Any],
    *,
    kelly: Any,
    context_label: str,
) -> tuple[dict[str, Any], list[str]]:
    resolved = deepcopy(stock_config)
    warnings: list[str] = []
    execution_fraction = _safe_float(getattr(kelly, "fraction", 0.0), 0.0) if _kelly_is_safe(kelly) else None
    fallback_reason = getattr(kelly, "warning", None) or getattr(kelly, "reason", None) or "Kelly unavailable"
    for section in ("entry_rules", "exit_rules"):
        for index, rule in enumerate(list(resolved.get(section) or [])):
            if not isinstance(rule, dict):
                continue
            sizing = rule.get("sizing") if isinstance(rule.get("sizing"), dict) else {}
            if str(sizing.get("mode") or "").strip().lower() != "kelly_wfo":
                continue
            sizing["execution_kelly_fraction"] = execution_fraction
            rule["sizing"] = sizing
            if execution_fraction is None:
                rule_name = str(rule.get("label") or rule.get("id") or f"{section}[{index}]").strip()
                warnings.append(
                    f"{context_label}: {section}[{index}] '{rule_name}' fell back to manual_pct because Kelly was unavailable ({fallback_reason})."
                )
    return resolved, warnings


def _simulate_candidate(
    *,
    symbol: str,
    stock_config: dict[str, Any],
    full_bars: pd.DataFrame,
    run_bars: pd.DataFrame,
    allocated_capital: float,
    side_policy: str,
    cost_model: Any,
    volume_gate: dict[str, Any],
    cooldown_bars: int,
    horizon: str,
    timeframe: str,
    signal_cost_bps: float,
) -> Any:
    score_frame = compute_strategy_score_frame(
        stock_config=stock_config,
        ohlcv=full_bars,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        signal_cost_bps=signal_cost_bps,
        cooldown_bars=cooldown_bars,
    )
    risk = _risk_dict(stock_config, cooldown_override=cooldown_bars)
    return _simulate_stock(
        symbol=symbol,
        bars=run_bars,
        score_series=score_frame["consensus_score"],
        score_frame=score_frame,
        allocated_capital=float(allocated_capital),
        side_policy=side_policy,
        exposure_ladder=_default_fallback_ladder(),
        entry_rules=list(stock_config.get("entry_rules") or []),
        exit_rules=list(stock_config.get("exit_rules") or []),
        risk=risk,
        cost_model=cost_model,
        cooldown_bars=max(int(risk.get("cooldown_bars", cooldown_bars)), 0),
        volume_gate=volume_gate,
    )


def _simulate_candidate_with_execution_kelly(
    *,
    symbol: str,
    stock_config: dict[str, Any],
    full_bars: pd.DataFrame,
    run_bars: pd.DataFrame,
    allocated_capital: float,
    side_policy: str,
    cost_model: Any,
    volume_gate: dict[str, Any],
    cooldown_bars: int,
    horizon: str,
    timeframe: str,
    signal_cost_bps: float,
    context_label: str,
) -> tuple[Any, dict[str, Any], Any | None, list[str]]:
    base_sim = _simulate_candidate(
        symbol=symbol,
        stock_config=stock_config,
        full_bars=full_bars,
        run_bars=run_bars,
        allocated_capital=allocated_capital,
        side_policy=side_policy,
        cost_model=cost_model,
        volume_gate=volume_gate,
        cooldown_bars=cooldown_bars,
        horizon=horizon,
        timeframe=timeframe,
        signal_cost_bps=signal_cost_bps,
    )
    if not _stock_uses_kelly_rule_sizing(stock_config):
        return base_sim, deepcopy(stock_config), None, []

    base_ledger = _trade_ledger(base_sim)
    kelly = compute_kelly_fraction(compute_trade_stats(base_ledger.to_dict("records")))
    resolved_config, warnings = _apply_execution_kelly(
        stock_config,
        kelly=kelly,
        context_label=context_label,
    )
    if not _kelly_is_safe(kelly):
        return base_sim, resolved_config, kelly, warnings

    resolved_sim = _simulate_candidate(
        symbol=symbol,
        stock_config=resolved_config,
        full_bars=full_bars,
        run_bars=run_bars,
        allocated_capital=allocated_capital,
        side_policy=side_policy,
        cost_model=cost_model,
        volume_gate=volume_gate,
        cooldown_bars=cooldown_bars,
        horizon=horizon,
        timeframe=timeframe,
        signal_cost_bps=signal_cost_bps,
    )
    return resolved_sim, resolved_config, kelly, warnings


def _window_configs(
    *,
    data_length: int,
    max_lookback: int,
    ratios: list[float],
    min_walk_forwards: int,
) -> list[WalkForwardConfig]:
    min_train = max(max_lookback * 10, _WINDOW_GRID)
    start_train = ((min_train + (_WINDOW_GRID - 1)) // _WINDOW_GRID) * _WINDOW_GRID
    configs: list[WalkForwardConfig] = []
    seen: set[tuple[int, int]] = set()
    for train_bars in range(start_train, max(data_length, start_train) + 1, _WINDOW_GRID):
        for ratio in ratios:
            oos_bars = max(1, int(round(train_bars * float(ratio))))
            key = (train_bars, oos_bars)
            if key in seen:
                continue
            config = WalkForwardConfig(
                train_bars=train_bars,
                oos_bars=oos_bars,
                step_bars=oos_bars,
                min_walk_forwards=min_walk_forwards,
            )
            windows = build_walk_forward_windows(data_length, config, max_lookback=max_lookback)
            if len(windows) >= min_walk_forwards:
                configs.append(config)
                seen.add(key)
    return sorted(configs, key=lambda item: (item.train_bars, item.oos_bars))


def _strict_fold_driven_configs(
    *,
    data_length: int,
    max_lookback: int,
    requested_min_walk_forwards: int,
    top_k_folds: int,
    fallback_enabled: bool,
    fallback_floor: int,
) -> tuple[list[WalkForwardConfig], dict[str, Any]]:
    requested = max(requested_min_walk_forwards, 1)
    floor = max(1, min(fallback_floor, requested))
    top_k = max(top_k_folds, 1)
    min_train = max(max_lookback * 10, 1)

    max_feasible_folds = 0
    for ratio in _STRICT_RATIO_ANCHORS:
        oos_bars = max(1, int(round(min_train * ratio)))
        config = WalkForwardConfig(
            train_bars=min_train,
            oos_bars=oos_bars,
            step_bars=oos_bars,
            min_walk_forwards=1,
        )
        fold_count = len(build_walk_forward_windows(data_length, config, max_lookback=max_lookback))
        max_feasible_folds = max(max_feasible_folds, fold_count)

    candidates_by_floor: list[int] = [requested]
    if fallback_enabled and requested > floor:
        candidates_by_floor.extend(range(requested - 1, floor - 1, -1))

    for effective_min in candidates_by_floor:
        if max_feasible_folds < effective_min:
            continue
        candidates: dict[tuple[int, int], tuple[WalkForwardConfig, int]] = {}
        for fold_target in range(max_feasible_folds, effective_min - 1, -1):
            for ratio in _STRICT_RATIO_ANCHORS:
                denominator = 1.0 + (ratio * fold_target)
                if denominator <= 0:
                    continue
                train_bars = int(math.floor((data_length - max_lookback) / denominator))
                if train_bars < min_train:
                    continue
                oos_bars = max(1, int(round(train_bars * ratio)))
                ratio_realized = float(oos_bars) / float(max(train_bars, 1))
                if ratio_realized < 0.25 or ratio_realized > 0.35:
                    continue
                config = WalkForwardConfig(
                    train_bars=train_bars,
                    oos_bars=oos_bars,
                    step_bars=oos_bars,
                    min_walk_forwards=effective_min,
                )
                fold_count = len(build_walk_forward_windows(data_length, config, max_lookback=max_lookback))
                if fold_count < effective_min:
                    continue
                key = (train_bars, oos_bars)
                previous = candidates.get(key)
                if previous is None or fold_count > previous[1]:
                    candidates[key] = (config, fold_count)

        ranked = sorted(
            candidates.values(),
            key=lambda item: (
                -item[1],
                _safe_int(item[0].oos_bars, 0),
                _safe_int(item[0].train_bars, 0),
            ),
        )
        selected = [item[0] for item in ranked[:top_k]]
        if selected:
            fallback_applied = effective_min != requested
            return selected, {
                "requested_min_walk_forwards": requested,
                "effective_min_walk_forwards": effective_min,
                "fallback_applied": fallback_applied,
                "fallback_floor": floor,
                "top_k_folds_used": top_k,
                "max_feasible_folds_before_fallback": max_feasible_folds,
                "status": "strict_fallback" if fallback_applied else "strict",
            }

    return [], {
        "requested_min_walk_forwards": requested,
        "effective_min_walk_forwards": floor if fallback_enabled else requested,
        "fallback_applied": bool(fallback_enabled and requested > floor),
        "fallback_floor": floor,
        "top_k_folds_used": top_k,
        "max_feasible_folds_before_fallback": max_feasible_folds,
        "status": "infeasible",
    }


def _apply_short_horizon_oos_cap(
    *,
    horizon: str,
    configs: list[WalkForwardConfig],
    max_exclusive: int = _SHORT_OOS_CAP_MAX_EXCLUSIVE,
) -> tuple[list[WalkForwardConfig], dict[str, Any], str | None]:
    diagnostics = {
        "short_oos_cap_max_exclusive": int(max_exclusive),
        "short_oos_cap_applied": False,
        "short_oos_cap_fallback_used": False,
        "short_oos_cap_filtered_count": 0,
    }
    horizon_key = str(horizon or "medium").strip().lower()
    if horizon_key != "short" or not configs:
        return configs, diagnostics, None

    capped_configs = [config for config in configs if _safe_int(config.oos_bars, 0) < int(max_exclusive)]
    if capped_configs:
        diagnostics["short_oos_cap_applied"] = True
        diagnostics["short_oos_cap_filtered_count"] = max(len(configs) - len(capped_configs), 0)
        return capped_configs, diagnostics, None

    diagnostics["short_oos_cap_fallback_used"] = True
    warning = (
        f"Short-horizon OOS cap (<{int(max_exclusive)} bars) was not feasible; "
        "falling back to uncapped WFO window configs."
    )
    return configs, diagnostics, warning


def _config_sort_key(result: dict[str, Any]) -> tuple[float, float, float, int]:
    return (
        -_safe_float(result.get("wfe"), 0.0),
        -_safe_float(result.get("robustness_ratio"), 0.0),
        _safe_float(result.get("single_window_dominance"), 1.0),
        _safe_int(result.get("oos_bars"), 0),
    )


def _test_bars(
    *,
    bars: pd.DataFrame,
    explicit_test_start: str | None,
    explicit_test_end: str | None,
    last_oos_end: int,
) -> pd.DataFrame:
    if explicit_test_start and explicit_test_end:
        start_ts = _align_timestamp_to_index(pd.Timestamp(explicit_test_start), bars.index)
        end_ts = _align_timestamp_to_index(pd.Timestamp(explicit_test_end), bars.index)
        return bars.loc[(bars.index >= start_ts) & (bars.index <= end_ts)].copy()
    return bars.iloc[last_oos_end:].copy()


def _bootstrap_payload(
    *,
    returns: list[float],
    dates: list[str],
    n_simulations: int,
    block_length: int | None,
) -> dict[str, Any]:
    if len(returns) < 30:
        return {
            "enabled": False,
            "warning": "Monte Carlo robustness skipped because the held-out test has fewer than 30 daily observations.",
            "method": "circular_block_bootstrap",
            "n_paths": n_simulations,
            "block_length": None,
        }
    result = block_bootstrap_equity_paths(
        returns,
        n_simulations=n_simulations,
        block_length=block_length,
        sample_curves=120,
    )
    warning = None
    if len(returns) < 126:
        warning = "Held-out test is shorter than 126 trading days. Monte Carlo is shown with a low-statistical-power warning."
    band_payload: dict[str, list[dict[str, Any]]] = {}
    for pct, values in result.percentile_bands.items():
        band_payload[str(pct)] = [
            {"date": dates[index], "value": float(value)}
            for index, value in enumerate(values)
            if index < len(dates)
        ]
    sampled_curves = []
    for curve in result.sampled_curves:
        sampled_curves.append(
            [
                {"date": dates[index], "value": float(value)}
                for index, value in enumerate(curve)
                if index < len(dates)
            ]
        )
    actual_curve = [
        {"date": dates[index], "value": float(value)}
        for index, value in enumerate(result.actual_curve)
        if index < len(dates)
    ]
    return {
        "enabled": True,
        "warning": warning,
        "method": "circular_block_bootstrap",
        "n_paths": result.n_simulations,
        "block_length": result.block_length,
        "actual_curve": actual_curve,
        "sampled_curves": sampled_curves,
        "percentile_bands": band_payload,
        "terminal_return_summary": result.terminal_return_summary,
        "max_drawdown_summary": result.max_drawdown_summary,
        "realized_path_percentile_rank": result.percentile_rank,
    }


def run_stock_walk_forward(
    *,
    symbol: str,
    strategy_id: str,
    strategy_name: str,
    side_policy: str,
    horizon: str,
    timeframe: str,
    stock_config: dict[str, Any],
    bars: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
    allocated_capital: float,
    cost_model_raw: dict[str, Any],
    volume_gate: dict[str, Any],
    cooldown_bars: int,
    wfo_config: dict[str, Any] | None = None,
    progress_callback: Callable[..., None] | None = None,
) -> dict[str, Any]:
    config = dict(wfo_config or {})
    window_policy = str(config.get("window_policy") or _WINDOW_POLICY_STRICT).strip().lower()
    if window_policy not in {_WINDOW_POLICY_STRICT, _WINDOW_POLICY_LEGACY}:
        window_policy = _WINDOW_POLICY_STRICT
    ratios = [float(item) for item in list(config.get("is_oos_ratios") or [0.25, 0.30, 0.35])]
    ratios = sorted({round(item, 4) for item in ratios if 0.0 < float(item) < 1.0})
    full_family_score_mode = _is_full_family_score_mode(stock_config)
    if not full_family_score_mode and window_policy == _WINDOW_POLICY_LEGACY and not ratios:
        raise ValueError("WFO requires at least one valid IS/OOS ratio inside (0, 1).")
    min_walk_forwards = max(_safe_int(config.get("min_walk_forwards"), 5), 1)
    top_k_folds = max(_safe_int(config.get("top_k_folds"), 12), 1)
    strict_fallback_enabled = bool(config.get("strict_fallback_enabled", True))
    strict_fallback_floor = max(_safe_int(config.get("strict_fallback_floor"), 1), 1)
    strict_fallback_floor = min(strict_fallback_floor, min_walk_forwards)
    n_monte_carlo_paths = max(_safe_int(config.get("n_monte_carlo_paths"), 1000), 100)
    monte_carlo_block_length = config.get("monte_carlo_block_length")
    explicit_test_start = str(config.get("test_period_start") or "").strip() or None
    explicit_test_end = str(config.get("test_period_end") or "").strip() or None
    if explicit_test_start is None or explicit_test_end is None:
        raise ValueError("WFO requires both test_period_start and test_period_end for the final held-out test.")

    bars = drop_incomplete_ohlcv_rows(bars).sort_index()
    bars.index = pd.to_datetime(bars.index)
    if len(bars.index) < 3:
        raise ValueError(f"Insufficient bars for {symbol}.")

    test_start_ts = _align_timestamp_to_index(pd.Timestamp(explicit_test_start), bars.index)
    test_end_ts = _align_timestamp_to_index(pd.Timestamp(explicit_test_end), bars.index)
    if test_start_ts > test_end_ts:
        raise ValueError("test_period_start must be on or before test_period_end.")

    wfo_bars_all = bars.loc[bars.index < test_start_ts].copy()
    wfo_bars = wfo_bars_all.copy()
    horizon_key = str(horizon or "medium").strip().lower()
    horizon_cap_years = HORIZON_LOOKBACK_YEARS.get(horizon_key, 10)
    max_wfo_bars = horizon_cap_years * TRADING_BARS_PER_YEAR
    horizon_cap_applied = len(wfo_bars.index) > max_wfo_bars
    if horizon_cap_applied:
        wfo_bars = wfo_bars.iloc[-max_wfo_bars:]
    if len(wfo_bars.index) < 3:
        raise ValueError(f"No WFO bars available for {symbol} before the test period.")

    dimensions = _candidate_dimensions(stock_config)
    dimensions, candidate_guardrail = _apply_candidate_guardrail(
        dimensions,
        max_candidate_tuples=_MAX_CANDIDATE_TUPLES,
    )
    raw_candidate_count = _safe_int(candidate_guardrail.get("raw_candidate_count"), 1)
    candidate_count = _safe_int(candidate_guardrail.get("effective_candidate_count"), raw_candidate_count)
    candidate_guardrail_warning = str(candidate_guardrail.get("warning") or "").strip() or None
    if candidate_count > _MAX_CANDIDATE_TUPLES:
        raise ValueError(
            f"{symbol} exceeds the WFO search guardrail with {candidate_count} candidate tuples "
            f"(raw {raw_candidate_count}, max {_MAX_CANDIDATE_TUPLES})."
        )
    candidate_maps = _iter_candidate_value_maps(dimensions)

    max_lookback = derive_max_lookback(stock_config, horizon=horizon, strict_indicator_rows=False)
    window_policy_used = _WINDOW_POLICY_FAMILY_SCORE_FIXED if full_family_score_mode else window_policy
    policy_diagnostics: dict[str, Any] = {
        "window_policy_used": window_policy_used,
        "requested_min_walk_forwards": min_walk_forwards,
        "effective_min_walk_forwards": min_walk_forwards,
        "fallback_applied": False,
        "fallback_floor": None,
        "top_k_folds_used": None,
        "ignored_inputs": [],
        "feasibility": {
            "horizon_cap_years": horizon_cap_years,
            "horizon_cap_applied": horizon_cap_applied,
            "pretest_bars_before_cap": len(wfo_bars_all.index),
            "pretest_bars_after_cap": len(wfo_bars.index),
            "T_pretest_bars": len(wfo_bars.index),
            "L_max_lookback": max_lookback,
            "max_feasible_folds_before_fallback": None,
            "status": window_policy_used,
        },
    }
    if full_family_score_mode:
        fixed_window = _family_score_fixed_window_for_horizon(horizon_key)
        fixed_config = WalkForwardConfig(
            train_bars=_safe_int(fixed_window.get("train_bars"), 252),
            oos_bars=_safe_int(fixed_window.get("oos_bars"), 63),
            step_bars=_safe_int(fixed_window.get("step_bars"), 63),
            min_walk_forwards=min_walk_forwards,
        )
        fixed_fold_count = len(build_walk_forward_windows(len(wfo_bars.index), fixed_config, max_lookback=max_lookback))
        policy_diagnostics.update(
            {
                "top_k_folds_used": None,
                "ignored_inputs": [
                    "window_policy",
                    "is_oos_ratios",
                    "top_k_folds",
                    "strict_fallback_enabled",
                    "strict_fallback_floor",
                ],
                "family_score_fixed": {
                    "horizon": horizon_key,
                    "train_bars": fixed_config.train_bars,
                    "oos_bars": fixed_config.oos_bars,
                    "step_bars": fixed_config.step_bars,
                    "requested_window_policy": window_policy,
                    "requested_is_oos_ratios": list(ratios),
                },
            }
        )
        policy_diagnostics["feasibility"]["max_feasible_folds_before_fallback"] = fixed_fold_count
        policy_diagnostics["feasibility"]["status"] = _WINDOW_POLICY_FAMILY_SCORE_FIXED
        if fixed_fold_count < min_walk_forwards:
            raise ValueError(
                f"{symbol} has no feasible fixed-window family-score WFO configuration "
                f"(horizon={horizon_key}, train_bars={fixed_config.train_bars}, "
                f"oos_bars={fixed_config.oos_bars}, step_bars={fixed_config.step_bars}, "
                f"max_lookback={max_lookback}, pretest_bars={len(wfo_bars.index)}, "
                f"requested_min_walk_forwards={min_walk_forwards}, "
                f"max_feasible_folds={fixed_fold_count})."
            )
        configs = [fixed_config]
    elif window_policy == _WINDOW_POLICY_STRICT:
        configs, strict_meta = _strict_fold_driven_configs(
            data_length=len(wfo_bars.index),
            max_lookback=max_lookback,
            requested_min_walk_forwards=min_walk_forwards,
            top_k_folds=top_k_folds,
            fallback_enabled=strict_fallback_enabled,
            fallback_floor=strict_fallback_floor,
        )
        policy_diagnostics.update(
            {
                "requested_min_walk_forwards": _safe_int(strict_meta.get("requested_min_walk_forwards"), min_walk_forwards),
                "effective_min_walk_forwards": _safe_int(strict_meta.get("effective_min_walk_forwards"), min_walk_forwards),
                "fallback_applied": bool(strict_meta.get("fallback_applied", False)),
                "fallback_floor": _safe_int(strict_meta.get("fallback_floor"), strict_fallback_floor),
                "top_k_folds_used": top_k_folds,
                "ignored_inputs": ["is_oos_ratios"],
            }
        )
        policy_diagnostics["feasibility"]["max_feasible_folds_before_fallback"] = _safe_int(
            strict_meta.get("max_feasible_folds_before_fallback"),
            0,
        )
        policy_diagnostics["feasibility"]["status"] = str(strict_meta.get("status") or "strict")
        if not configs:
            raise ValueError(
                f"{symbol} has no strict fold-driven WFO configuration "
                f"(max_lookback={max_lookback}, pretest_bars={len(wfo_bars.index)}, "
                f"requested_min_walk_forwards={min_walk_forwards}, "
                f"effective_min_walk_forwards={policy_diagnostics['effective_min_walk_forwards']}, "
                f"max_feasible_folds={policy_diagnostics['feasibility']['max_feasible_folds_before_fallback']})."
            )
    else:
        configs = _window_configs(
            data_length=len(wfo_bars.index),
            max_lookback=max_lookback,
            ratios=ratios,
            min_walk_forwards=min_walk_forwards,
        )
        if not configs:
            min_train_bars = max(max_lookback * 10, _WINDOW_GRID)
            min_ratio = min(ratios)
            min_oos_bars = max(1, int(round(min_train_bars * float(min_ratio))))
            required_pretest_bars = max_lookback + min_train_bars + (min_walk_forwards * min_oos_bars)
            raise ValueError(
                f"{symbol} does not have enough bars for any feasible WFO configuration "
                f"(max_lookback={max_lookback}, pretest_bars={len(wfo_bars.index)}, "
                f"min_train_bars={min_train_bars}, min_walk_forwards={min_walk_forwards}, "
                f"approx_required_pretest_bars={required_pretest_bars})."
            )

    configs, short_oos_cap_diagnostics, short_oos_cap_warning = _apply_short_horizon_oos_cap(
        horizon=horizon,
        configs=configs,
        max_exclusive=_SHORT_OOS_CAP_MAX_EXCLUSIVE,
    )
    diagnostic_warnings: list[str] = []
    if candidate_guardrail_warning:
        diagnostic_warnings.append(candidate_guardrail_warning)
    if short_oos_cap_warning:
        diagnostic_warnings.append(short_oos_cap_warning)

    effective_min_walk_forwards = _safe_int(policy_diagnostics.get("effective_min_walk_forwards"), min_walk_forwards)

    cost_model = _build_cost_model(cost_model_raw)
    signal_cost_bps = _signal_cost_bps(cost_model)
    config_results: list[dict[str, Any]] = []
    total_windows = sum(
        len(build_walk_forward_windows(len(wfo_bars.index), candidate, max_lookback=max_lookback))
        for candidate in configs
    )
    completed_windows = 0
    execution_warnings: list[str] = []

    for config_index, config_item in enumerate(configs):
        windows = build_walk_forward_windows(len(wfo_bars.index), config_item, max_lookback=max_lookback)
        return_windows: list[ReturnWindow] = []
        winning_windows: list[dict[str, Any]] = []
        oos_trade_rows: list[dict[str, Any]] = []
        oos_returns: list[float] = []
        oos_daily_returns: list[float] = []
        all_profile_pass = True
        last_winner_values: dict[str, float | int] = {}
        config_execution_warnings: list[str] = []

        for window_index, window in enumerate(windows):
            if progress_callback is not None:
                progress_callback(
                    phase="wfo_window",
                    symbol=symbol,
                    config_index=config_index + 1,
                    config_total=len(configs),
                    window_index=window_index + 1,
                    window_total=len(windows),
                    completed=completed_windows,
                    total=total_windows,
                    message=f"Evaluating WFO config {config_index + 1}/{len(configs)} window {window_index + 1}/{len(windows)} for {symbol}",
                )

            raw_proms: dict[Any, float] = {}
            valid_candidates: dict[Any, dict[str, float | int]] = {}
            train_bars = _slice_bars(wfo_bars, window.train_start, window.train_end)
            oos_bars = _slice_bars(wfo_bars, window.oos_start, window.oos_end)

            for candidate_map in candidate_maps:
                candidate_key = tuple(candidate_map.get(dimension.path) for dimension in dimensions)
                candidate_config = _apply_candidate(stock_config, candidate_map)
                is_valid, _reason = _valid_candidate(candidate_config)
                if not is_valid:
                    continue
                is_sim, _resolved_candidate_config, _is_kelly, candidate_warnings = _simulate_candidate_with_execution_kelly(
                    symbol=symbol,
                    stock_config=candidate_config,
                    full_bars=wfo_bars,
                    run_bars=train_bars,
                    allocated_capital=allocated_capital,
                    side_policy=side_policy,
                    cost_model=cost_model,
                    volume_gate=volume_gate,
                    cooldown_bars=cooldown_bars,
                    horizon=horizon,
                    timeframe=timeframe,
                    signal_cost_bps=signal_cost_bps,
                    context_label=f"{symbol} window {window.index} IS",
                )
                config_execution_warnings.extend(candidate_warnings)
                is_ledger = _trade_ledger(is_sim)
                raw_proms[candidate_key] = compute_prom(is_ledger.to_dict("records"), max(float(allocated_capital), 1.0))
                valid_candidates[candidate_key] = candidate_map

            if not raw_proms:
                all_profile_pass = False
                completed_windows += 1
                winning_windows.append(
                    {
                        "window_index": window.index,
                        "summary": {"window_index": window.index, "status": "no_valid_candidates"},
                        "detail": {"window_index": window.index, "status": "no_valid_candidates"},
                    }
                )
                continue

            if len(dimensions) <= 1:
                collapsed_scores = {
                    (key[0] if isinstance(key, tuple) and key else key): value
                    for key, value in raw_proms.items()
                }
                smoothed_base = neighbor_average_1d(collapsed_scores)
                smoothed_proms = {
                    key: float(smoothed_base[key[0] if isinstance(key, tuple) and key else key])
                    for key in raw_proms
                }
            else:
                smoothed_proms = {key: float(value) for key, value in neighbor_average_nd(raw_proms).items()}

            winner_key = max(smoothed_proms, key=smoothed_proms.get)
            profile = evaluate_optimization_profile(
                raw_proms,
                smoothed_proms,
                winner_key,
                neighbor_values=list(smoothed_proms.values()),
            )
            all_profile_pass = all_profile_pass and bool(profile.passes)
            winner_values = valid_candidates[winner_key]
            last_winner_values = dict(winner_values)
            winner_config = _apply_candidate(stock_config, winner_values)

            is_sim, resolved_winner_config, is_kelly, winner_is_warnings = _simulate_candidate_with_execution_kelly(
                symbol=symbol,
                stock_config=winner_config,
                full_bars=wfo_bars,
                run_bars=train_bars,
                allocated_capital=allocated_capital,
                side_policy=side_policy,
                cost_model=cost_model,
                volume_gate=volume_gate,
                cooldown_bars=cooldown_bars,
                horizon=horizon,
                timeframe=timeframe,
                signal_cost_bps=signal_cost_bps,
                context_label=f"{symbol} window {window.index} IS",
            )
            config_execution_warnings.extend(winner_is_warnings)
            oos_sim = _simulate_candidate(
                symbol=symbol,
                stock_config=resolved_winner_config,
                full_bars=wfo_bars,
                run_bars=oos_bars,
                allocated_capital=allocated_capital,
                side_policy=side_policy,
                cost_model=cost_model,
                volume_gate=volume_gate,
                cooldown_bars=cooldown_bars,
                horizon=horizon,
                timeframe=timeframe,
                signal_cost_bps=signal_cost_bps,
            )
            is_ledger = _trade_ledger(is_sim)
            oos_ledger = _trade_ledger(oos_sim)
            is_return = _safe_float((is_sim.summary_metrics or {}).get("total_return"), 0.0)
            oos_return = _safe_float((oos_sim.summary_metrics or {}).get("total_return"), 0.0)
            return_windows.append(
                ReturnWindow(
                    is_return=is_return,
                    oos_return=oos_return,
                    is_bars=max(len(train_bars.index), 1),
                    oos_bars=max(len(oos_bars.index), 1),
                )
            )
            oos_returns.append(oos_return)
            oos_daily_returns.extend(_simulation_returns(oos_sim))
            if not oos_ledger.empty:
                oos_trade_rows.extend(oos_ledger.to_dict("records"))

            train_start_date = pd.Timestamp(train_bars.index[0]).date().isoformat() if not train_bars.empty else None
            train_end_date = pd.Timestamp(train_bars.index[-1]).date().isoformat() if not train_bars.empty else None
            oos_start_date = pd.Timestamp(oos_bars.index[0]).date().isoformat() if not oos_bars.empty else None
            oos_end_date = pd.Timestamp(oos_bars.index[-1]).date().isoformat() if not oos_bars.empty else None
            winning_windows.append(
                {
                    "window_index": window.index,
                    "summary": {
                        "window_index": window.index,
                        "train_start": train_start_date,
                        "train_end": train_end_date,
                        "oos_start": oos_start_date,
                        "oos_end": oos_end_date,
                        "winner_params": winner_values,
                        "is_total_return": is_return,
                        "oos_total_return": oos_return,
                        "profile_passes": profile.passes,
                        "execution_kelly_fraction": getattr(is_kelly, "fraction", None) if is_kelly is not None else None,
                    },
                    "detail": {
                        "window_index": window.index,
                        "train_range": {"start": train_start_date, "end": train_end_date, "bars": len(train_bars.index)},
                        "oos_range": {"start": oos_start_date, "end": oos_end_date, "bars": len(oos_bars.index)},
                        "winner_params": winner_values,
                        "winner_prom": smoothed_proms[winner_key],
                        "profile": {
                            "passes": profile.passes,
                            "reason": profile.reason,
                            "detail": profile.detail,
                            "pct_profitable": profile.pct_profitable,
                            "winner_smoothed_prom": profile.winner_smoothed_prom,
                            "neighborhood_cv": profile.neighborhood_cv,
                            "warnings": list(profile.warnings),
                        },
                        "raw_proms": [
                            {"params": valid_candidates[key], "prom": float(value), "smoothed_prom": float(smoothed_proms.get(key, value))}
                            for key, value in raw_proms.items()
                        ],
                        "is_metrics": _metric_summary(is_sim, trade_count=len(is_ledger.index)),
                        "oos_metrics": _metric_summary(oos_sim, trade_count=len(oos_ledger.index)),
                        "oos_ledger": oos_ledger.to_dict("records"),
                        "execution_kelly": (
                            {
                                "fraction": getattr(is_kelly, "fraction", 0.0),
                                "half_kelly": getattr(is_kelly, "half_kelly", 0.0),
                                "win_rate": getattr(is_kelly, "win_rate", 0.0),
                                "wl_ratio": getattr(is_kelly, "wl_ratio", 0.0),
                                "n_trades": getattr(is_kelly, "n_trades", 0),
                                "reason": getattr(is_kelly, "reason", None),
                                "warning": getattr(is_kelly, "warning", None),
                            }
                            if is_kelly is not None
                            else None
                        ),
                        "execution_warnings": list(winner_is_warnings),
                    },
                }
            )
            completed_windows += 1

        wfe = compute_wfe(return_windows) if return_windows else 0.0
        robustness_ratio = compute_robustness_ratio(oos_returns)
        single_window_dominance = compute_single_window_dominance(oos_returns)
        config_results.append(
            {
                "train_bars": config_item.train_bars,
                "oos_bars": config_item.oos_bars,
                "window_count": len(windows),
                "wfe": wfe,
                "robustness_ratio": robustness_ratio,
                "single_window_dominance": single_window_dominance,
                "profitable_oos_ratio": robustness_ratio,
                "profile_passes": all_profile_pass,
                "viable": bool(wfe >= 0.50 and all_profile_pass),
                "windows": winning_windows,
                "last_winner_values": last_winner_values,
                "oos_trade_rows": oos_trade_rows,
                "oos_daily_returns": oos_daily_returns,
                "execution_warnings": list(dict.fromkeys(config_execution_warnings)),
            }
        )

    configs_tested = [
        {
            "train_bars": item["train_bars"],
            "oos_bars": item["oos_bars"],
            "window_count": item["window_count"],
            "wfe": item["wfe"],
            "robustness_ratio": item["robustness_ratio"],
            "single_window_dominance": item["single_window_dominance"],
            "profitable_oos_ratio": item["profitable_oos_ratio"],
            "profile_passes": item["profile_passes"],
            "viable": item["viable"],
        }
        for item in config_results
    ]
    viable_configs = [item for item in config_results if item["viable"]]
    if not viable_configs:
        best_config = sorted(config_results, key=_config_sort_key)[0]
        best_window_summaries = _window_summaries(best_config["windows"])
        rejection_reasons: list[str] = []
        if best_config["wfe"] < 0.50:
            rejection_reasons.append(
                f"WFE = {best_config['wfe']:.1%} < 50% threshold"
                " (Pardo Ch.11: OOS returns too low relative to IS)"
            )
        if not best_config["profile_passes"]:
            failed_profile_windows = [
                w for w in best_config["windows"]
                if not (w.get("summary") or {}).get("profile_passes", True)
            ]
            rejection_reasons.append(
                f"{len(failed_profile_windows)}/{best_config['window_count']} windows"
                " failed optimization profile check"
                " (Pardo Ch.10: <20% profitable or winner is isolated spike)"
            )
        if best_config["robustness_ratio"] < 0.50:
            n_profitable = int(
                best_config["robustness_ratio"] * best_config["window_count"]
            )
            rejection_reasons.append(
                f"Robustness = {best_config['robustness_ratio']:.1%}"
                f" ({n_profitable}/{best_config['window_count']} OOS windows profitable,"
                " need majority per Pardo Ch.11 p.289)"
            )
        return {
            "symbol": symbol,
            "status": "not_viable",
            "summary": {
                "symbol": symbol,
                "status": "not_viable",
                "candidate_count": candidate_count,
                "candidate_count_raw": raw_candidate_count,
                "max_lookback": max_lookback,
                "configs_tested": len(configs_tested),
                "best_wfe": best_config["wfe"],
                "best_robustness_ratio": best_config["robustness_ratio"],
                "rejection_reasons": rejection_reasons,
            },
            "result": {
                "symbol": symbol,
                "status": "not_viable",
                "candidate_count": candidate_count,
                "candidate_count_raw": raw_candidate_count,
                "max_lookback": max_lookback,
                "available_wfo_bars": len(wfo_bars.index),
                "winning_config": {
                    "train_bars": best_config["train_bars"],
                    "oos_bars": best_config["oos_bars"],
                    "window_count": best_config["window_count"],
                    "wfe": best_config["wfe"],
                    "robustness_ratio": best_config["robustness_ratio"],
                    "single_window_dominance": best_config["single_window_dominance"],
                    "profitable_oos_ratio": best_config["profitable_oos_ratio"],
                    "profile_passes": best_config["profile_passes"],
                    "viable": False,
                },
                "windows": best_window_summaries,
                "final_params": dict(best_config.get("last_winner_values") or {}),
                "rejection_reasons": rejection_reasons,
                "statistical_validation": {},
                "sizing": {},
                "test_period": None,
                "robustness": {},
                "all_configs_tested": configs_tested,
                "diagnostics": {
                    "signal_cost_bps": signal_cost_bps,
                    "candidate_guardrail": dict(candidate_guardrail),
                    "ratios": ratios,
                    "ratio_anchors": list(_STRICT_RATIO_ANCHORS) if window_policy_used == _WINDOW_POLICY_STRICT else ratios,
                    "min_walk_forwards": effective_min_walk_forwards,
                    "requested_min_walk_forwards": min_walk_forwards,
                    "window_policy": window_policy_used,
                    "pretest_bars": len(wfo_bars.index),
                    "test_period_start": explicit_test_start,
                    "test_period_end": explicit_test_end,
                    "short_oos_cap_max_exclusive": short_oos_cap_diagnostics["short_oos_cap_max_exclusive"],
                    "short_oos_cap_applied": bool(short_oos_cap_diagnostics["short_oos_cap_applied"]),
                    "short_oos_cap_fallback_used": bool(short_oos_cap_diagnostics["short_oos_cap_fallback_used"]),
                    "short_oos_cap_filtered_count": _safe_int(short_oos_cap_diagnostics["short_oos_cap_filtered_count"], 0),
                    "policy": policy_diagnostics,
                    "warnings": list(dict.fromkeys(diagnostic_warnings)),
                },
            },
            "windows": best_config["windows"],
        }

    winning_config = sorted(viable_configs, key=_config_sort_key)[0]
    final_params = dict(winning_config["last_winner_values"])
    final_stock_config = _apply_candidate(stock_config, final_params)
    execution_warnings.extend(list(winning_config.get("execution_warnings") or []))
    actual_windows = build_walk_forward_windows(
        len(wfo_bars.index),
        WalkForwardConfig(
            train_bars=_safe_int(winning_config["train_bars"], 0),
            oos_bars=_safe_int(winning_config["oos_bars"], 0),
            step_bars=_safe_int(winning_config["oos_bars"], 0),
            min_walk_forwards=effective_min_walk_forwards,
        ),
        max_lookback=max_lookback,
    )
    last_oos_end = actual_windows[-1].oos_end if actual_windows else 0
    test_bars = _test_bars(
        bars=bars,
        explicit_test_start=explicit_test_start,
        explicit_test_end=explicit_test_end,
        last_oos_end=last_oos_end,
    )

    final_test_result: dict[str, Any] | None = None
    robustness: dict[str, Any] = {}
    warnings: list[str] = []
    final_test_config = deepcopy(final_stock_config)
    if _stock_uses_kelly_rule_sizing(final_stock_config):
        pretest_kelly = compute_kelly_fraction(compute_trade_stats(winning_config["oos_trade_rows"]))
        final_test_config, final_test_warnings = _apply_execution_kelly(
            final_stock_config,
            kelly=pretest_kelly,
            context_label=f"{symbol} held-out test",
        )
        execution_warnings.extend(final_test_warnings)
    if len(test_bars.index) >= 2:
        final_sim = _simulate_candidate(
            symbol=symbol,
            stock_config=final_test_config,
            full_bars=bars,
            run_bars=test_bars,
            allocated_capital=allocated_capital,
            side_policy=side_policy,
            cost_model=cost_model,
            volume_gate=volume_gate,
            cooldown_bars=cooldown_bars,
            horizon=horizon,
            timeframe=timeframe,
            signal_cost_bps=signal_cost_bps,
        )
        final_ledger = _trade_ledger(final_sim)
        final_metrics = _metric_summary(final_sim, trade_count=len(final_ledger.index))
        final_test_result = {
            "start_date": pd.Timestamp(test_bars.index[0]).date().isoformat(),
            "end_date": pd.Timestamp(test_bars.index[-1]).date().isoformat(),
            "n_bars": len(test_bars.index),
            "warning": None if len(test_bars.index) >= 126 else (
                f"Test period is only {len(test_bars.index)} bars. Results are shown with reduced statistical power."
            ),
            "metrics": final_metrics,
            "equity_curve": _curve_records(final_sim.equity),
            "normalized_equity_curve": _normalized_curve_records(final_sim.equity),
            "ledger": final_ledger.to_dict("records"),
        }
        if final_test_result["warning"]:
            warnings.append(str(final_test_result["warning"]))
        final_returns = _simulation_returns(final_sim)
        final_dates = [row["date"] for row in list(final_test_result.get("normalized_equity_curve") or [])]
        robustness = _bootstrap_payload(
            returns=final_returns,
            dates=final_dates,
            n_simulations=n_monte_carlo_paths,
            block_length=_safe_int(monte_carlo_block_length, 0) or None,
        )
        if robustness.get("warning"):
            warnings.append(str(robustness.get("warning")))
    else:
        warnings.append("No held-out test period remains after the winning WFO configuration.")

    oos_trade_stats = compute_trade_stats(winning_config["oos_trade_rows"])
    kelly = compute_kelly_fraction(oos_trade_stats)
    dsr = deflated_sharpe_ratio(
        list(winning_config["oos_daily_returns"]),
        n_variants_tested=max(candidate_count, 1),
    )
    winning_window_summaries = _window_summaries(winning_config["windows"])

    stock_result = {
        "symbol": symbol,
        "status": "succeeded" if final_test_result is not None else "not_viable",
        "candidate_count": candidate_count,
        "candidate_count_raw": raw_candidate_count,
        "max_lookback": max_lookback,
        "available_wfo_bars": len(wfo_bars.index),
        "winning_config": {
            "train_bars": winning_config["train_bars"],
            "oos_bars": winning_config["oos_bars"],
            "window_count": winning_config["window_count"],
            "wfe": winning_config["wfe"],
            "robustness_ratio": winning_config["robustness_ratio"],
            "single_window_dominance": winning_config["single_window_dominance"],
            "profitable_oos_ratio": winning_config["profitable_oos_ratio"],
        },
        "windows": winning_window_summaries,
        "final_params": final_params,
        "statistical_validation": {
            "wfe": winning_config["wfe"],
            "robustness_ratio": winning_config["robustness_ratio"],
            "single_window_dominance": winning_config["single_window_dominance"],
            "deflated_sharpe_ratio": {
                "observed_sharpe": dsr.observed_sharpe,
                "benchmark_sharpe": dsr.benchmark_sharpe,
                "dsr_statistic": dsr.dsr_statistic,
                "p_value": dsr.p_value,
                "skewness": dsr.skewness,
                "kurtosis": dsr.kurtosis,
                "n_trades": dsr.n_trades,
                "n_variants": dsr.n_variants,
                "significant": dsr.significant,
            },
        },
        "sizing": {
            "kelly_fraction": kelly.fraction,
            "half_kelly": kelly.half_kelly,
            "win_rate": kelly.win_rate,
            "wl_ratio": kelly.wl_ratio,
            "n_trades": kelly.n_trades,
            "reason": kelly.reason,
            "warning": kelly.warning,
            "execution_warnings": list(dict.fromkeys(execution_warnings)),
        },
        "test_period": final_test_result,
        "robustness": robustness,
        "all_configs_tested": configs_tested,
        "diagnostics": {
            "signal_cost_bps": signal_cost_bps,
            "candidate_guardrail": dict(candidate_guardrail),
            "ratios": ratios,
            "ratio_anchors": list(_STRICT_RATIO_ANCHORS) if window_policy_used == _WINDOW_POLICY_STRICT else ratios,
            "min_walk_forwards": effective_min_walk_forwards,
            "requested_min_walk_forwards": min_walk_forwards,
            "window_policy": window_policy_used,
            "pretest_bars": len(wfo_bars.index),
            "test_period_start": explicit_test_start,
            "test_period_end": explicit_test_end,
            "short_oos_cap_max_exclusive": short_oos_cap_diagnostics["short_oos_cap_max_exclusive"],
            "short_oos_cap_applied": bool(short_oos_cap_diagnostics["short_oos_cap_applied"]),
            "short_oos_cap_fallback_used": bool(short_oos_cap_diagnostics["short_oos_cap_fallback_used"]),
            "short_oos_cap_filtered_count": _safe_int(short_oos_cap_diagnostics["short_oos_cap_filtered_count"], 0),
            "policy": policy_diagnostics,
            "warnings": list(dict.fromkeys([*diagnostic_warnings, *warnings, *execution_warnings])),
        },
    }
    summary = {
        "symbol": symbol,
        "status": stock_result["status"],
        "candidate_count": candidate_count,
        "candidate_count_raw": raw_candidate_count,
        "wfe": winning_config["wfe"],
        "robustness_ratio": winning_config["robustness_ratio"],
        "single_window_dominance": winning_config["single_window_dominance"],
        "final_test_return": ((final_test_result or {}).get("metrics") or {}).get("total_return"),
        "final_test_trades": ((final_test_result or {}).get("metrics") or {}).get("number_of_trades"),
        "warnings": list(dict.fromkeys([*diagnostic_warnings, *warnings, *execution_warnings])),
    }
    return {"symbol": symbol, "status": stock_result["status"], "summary": summary, "result": stock_result, "windows": winning_config["windows"]}


def compute_strategy_allocation_map(
    *,
    basket: list[str],
    bars_by_symbol: dict[str, pd.DataFrame],
    total_capital_mad: float,
    manual_overrides_by_symbol: dict[str, Any],
    lookback_bars: int,
) -> dict[str, float]:
    price_history = {
        symbol: bars_by_symbol[symbol]["Close"].astype(float)
        for symbol in basket
        if symbol in bars_by_symbol and "Close" in bars_by_symbol[symbol].columns
    }
    allocation = compute_strategy_allocation(
        symbols=basket,
        total_capital_mad=total_capital_mad,
        price_history=price_history,
        manual_overrides_by_symbol=manual_overrides_by_symbol,
        lookback_bars=lookback_bars,
    )
    return {row["symbol"]: float(row["capital_mad"]) for row in allocation["rows"]}


def aggregate_portfolio_test_results(
    stock_results: list[dict[str, Any]],
    *,
    n_monte_carlo_paths: int = 1000,
    monte_carlo_block_length: int | None = None,
) -> dict[str, Any]:
    successful = [item for item in stock_results if ((item.get("result") or {}).get("test_period") is not None)]
    if not successful:
        return {"status": "failed", "test_period": None, "robustness": {}}

    equity_frame = pd.DataFrame()
    for item in successful:
        symbol = str(item.get("symbol") or "")
        equity_rows = list((((item.get("result") or {}).get("test_period") or {}).get("equity_curve") or []))
        if not equity_rows:
            continue
        series = pd.Series(
            [float(row.get("value") or 0.0) for row in equity_rows],
            index=pd.to_datetime([row.get("date") for row in equity_rows]),
            dtype="float64",
        )
        equity_frame[symbol] = series

    if equity_frame.empty:
        return {"status": "failed", "test_period": None, "robustness": {}}

    equity_frame = equity_frame.sort_index().ffill().bfill()
    portfolio_equity = equity_frame.sum(axis=1).astype(float)
    returns = [float(value) for value in portfolio_equity.pct_change().dropna().tolist()]
    dates = [pd.Timestamp(index).date().isoformat() for index in portfolio_equity.index]
    drawdown = ((portfolio_equity / portfolio_equity.cummax()) - 1.0).min() if not portfolio_equity.empty else 0.0
    robustness = _bootstrap_payload(
        returns=returns,
        dates=dates,
        n_simulations=n_monte_carlo_paths,
        block_length=monte_carlo_block_length,
    )
    return {
        "status": "succeeded",
        "test_period": {
            "start_date": dates[0] if dates else None,
            "end_date": dates[-1] if dates else None,
            "n_bars": len(portfolio_equity.index),
            "metrics": {
                "net_pnl": float(portfolio_equity.iloc[-1] - portfolio_equity.iloc[0]),
                "total_return": float((portfolio_equity.iloc[-1] / portfolio_equity.iloc[0]) - 1.0)
                if float(portfolio_equity.iloc[0]) != 0
                else 0.0,
                "max_drawdown": float(drawdown),
                "number_of_stocks": len(successful),
            },
            "equity_curve": _curve_records(portfolio_equity),
            "normalized_equity_curve": _normalized_curve_records(portfolio_equity),
        },
        "robustness": robustness,
    }
