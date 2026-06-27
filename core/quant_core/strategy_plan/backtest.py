"""Direct backtest helpers for saved strategy-plan configurations."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder

from core.quant_core.plotly_compat import disable_broken_narwhals_optional_plugins
from core.quant_core.plots import (
    make_cumreturn_vs_benchmark_plot,
    make_drawdown_plot,
    make_monthly_heatmap_plot,
    make_yearly_return_bar_plot,
)

disable_broken_narwhals_optional_plugins()
from core.quant_core.data import drop_incomplete_ohlcv_rows
from core.quant_core.portfolio import CostModel
from core.quant_core.results import ResultsAnalyzer
from core.quant_core.signal_engine.ensemble import FamilyHistoryMode
from core.quant_core.strategy_plan.allocation import compute_strategy_allocation
from core.quant_core.strategy_plan.score_sources import (
    build_stock_config_from_enabled_families,
    compute_strategy_score_frame,
)


@dataclass
class _StockFill:
    timestamp: pd.Timestamp
    symbol: str
    qty: int
    side: str
    price: float
    notional: float
    cost: float
    signal_score: float
    realized_pnl: float
    latent_pnl: float
    cmp: float
    close_mark: float
    available_quantity: float
    position_value_cost: float
    reason: str
    entry_rule: str = ""
    exit_rule: str = ""
    trigger_display: str = ""
    trend_score: float = 0.0
    momentum_score: float = 0.0
    oscillation_score: float = 0.0
    volume_score: float = 0.0
    consensus_score: float = 0.0


@dataclass
class _StockSimulation:
    symbol: str
    equity: pd.Series
    positions: pd.Series
    fills: pd.DataFrame
    per_fill_ledger: list[dict[str, Any]]
    raw_scores: pd.Series
    summary_metrics: dict[str, Any]
    trade_performance: list[dict[str, Any]]
    buy_hold_cum: pd.Series
    bars_window: pd.DataFrame


class BacktestCanceled(Exception):
    """Raised when a cooperative backtest cancellation is requested."""


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


def _normalize_plotly_payload(value: Any) -> dict[str, Any]:
    # Plotly figures may still contain ndarray/timestamp objects after to_plotly_json().
    # Round-tripping through Plotly's encoder gives us a plain JSON-safe payload for FastAPI.
    return json.loads(json.dumps(value, cls=PlotlyJSONEncoder))


def _default_fallback_ladder() -> list[dict[str, Any]]:
    return [
        {"score_low": 0.0, "score_high": 29.9999, "target_exposure_pct": 0},
        {"score_low": 30.0, "score_high": 49.9999, "target_exposure_pct": 25},
        {"score_low": 50.0, "score_high": 69.9999, "target_exposure_pct": 50},
        {"score_low": 70.0, "score_high": 84.9999, "target_exposure_pct": 75},
        {"score_low": 85.0, "score_high": 100.0, "target_exposure_pct": 100},
    ]


def _coerce_exposure_levels(value: Any) -> list[int]:
    if not isinstance(value, list):
        return [0, 25, 50, 75, 100]
    out: list[int] = []
    for item in value:
        pct = _safe_int(item, -1)
        if 0 <= pct <= 100:
            out.append(pct)
    cleaned = sorted(set(out))
    if 0 not in cleaned:
        cleaned.insert(0, 0)
    return cleaned if len(cleaned) >= 2 else [0, 25, 50, 75, 100]


def _is_legacy_ladder(raw: Any) -> bool:
    return isinstance(raw, dict) and "starter_threshold" in raw and "starter_target_pct" in raw


def _default_bet_sizing_config(*, legacy_manual_ladder: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "mode": "auto_calibrated",
        "calibration_lookback_bars": 756,
        "min_observations": 200,
        "min_bucket_observations": 25,
        "primary_metric": "avg_r_multiple",
        "bucket_count": 10,
        "exposure_levels": [0, 25, 50, 75, 100],
        "sample_method": "event_deduped",
        "legacy_manual_ladder": legacy_manual_ladder,
        "last_calibration": None,
    }


def _normalize_strategy_config(raw: dict[str, Any]) -> dict[str, Any]:
    capital = raw.get("capital") if isinstance(raw.get("capital"), dict) else {}
    universe = raw.get("universe") if isinstance(raw.get("universe"), dict) else {}
    allocation = raw.get("allocation") if isinstance(raw.get("allocation"), dict) else {}
    signal = raw.get("signal") if isinstance(raw.get("signal"), dict) else {}
    logic = raw.get("logic") if isinstance(raw.get("logic"), dict) else {}
    risk = raw.get("risk") if isinstance(raw.get("risk"), dict) else {}
    bet = raw.get("bet_sizing") if isinstance(raw.get("bet_sizing"), dict) else {}
    per_stock_raw = raw.get("per_stock") if isinstance(raw.get("per_stock"), dict) else {}
    if not bet:
        bet = logic.get("bet_sizing") if isinstance(logic.get("bet_sizing"), dict) else {}
    legacy_manual_ladder = bet if _is_legacy_ladder(bet) else None

    if isinstance(raw.get("bet_sizing"), dict) and str(raw["bet_sizing"].get("mode", "")) == "auto_calibrated":
        raw_bet = raw["bet_sizing"]
        bet_sizing = {
            "mode": "auto_calibrated",
            "calibration_lookback_bars": max(_safe_int(raw_bet.get("calibration_lookback_bars"), 756), 60),
            "min_observations": max(_safe_int(raw_bet.get("min_observations"), 200), 1),
            "min_bucket_observations": max(_safe_int(raw_bet.get("min_bucket_observations"), 25), 1),
            "primary_metric": "avg_r_multiple",
            "bucket_count": max(_safe_int(raw_bet.get("bucket_count"), 10), 2),
            "exposure_levels": _coerce_exposure_levels(raw_bet.get("exposure_levels")),
            "sample_method": "event_deduped",
            "legacy_manual_ladder": raw_bet.get("legacy_manual_ladder") if isinstance(raw_bet.get("legacy_manual_ladder"), dict) else legacy_manual_ladder,
            "last_calibration": raw_bet.get("last_calibration") if isinstance(raw_bet.get("last_calibration"), dict) else None,
        }
    else:
        bet_sizing = _default_bet_sizing_config(legacy_manual_ladder=legacy_manual_ladder)

    manual_raw = allocation.get("manual_overrides_by_symbol")
    manual_overrides: dict[str, float] = {}
    if isinstance(manual_raw, dict):
        for symbol, value in manual_raw.items():
            if isinstance(value, dict):
                enabled = bool(value.get("enabled"))
                capital_mad = _safe_float(value.get("capital_mad"))
                if enabled and capital_mad > 0:
                    manual_overrides[str(symbol)] = capital_mad
            else:
                capital_mad = _safe_float(value)
                if capital_mad > 0:
                    manual_overrides[str(symbol)] = capital_mad

    per_stock: dict[str, Any] = {}
    for symbol, value in per_stock_raw.items():
        if not isinstance(value, dict):
            continue
        signal_override_raw = value.get("signal") if isinstance(value.get("signal"), dict) else {}
        signal_construction_raw = value.get("signal_construction") if isinstance(value.get("signal_construction"), dict) else {}
        risk_override_raw = value.get("risk") if isinstance(value.get("risk"), dict) else {}
        per_stock[str(symbol).strip().upper()] = {
            "signal": {
                "enabled_families": [
                    str(item).strip().lower()
                    for item in list(
                        signal_override_raw.get("enabled_families")
                        or signal.get("enabled_families")
                        or logic.get("enabled_families")
                        or ["sma", "rsi", "macd", "obv"]
                    )
                    if str(item).strip()
                ],
            },
            "signal_construction": signal_construction_raw,
            "entry_rules": list(value.get("entry_rules") or []) if isinstance(value.get("entry_rules"), list) else [],
            "exit_rules": list(value.get("exit_rules") or []) if isinstance(value.get("exit_rules"), list) else [],
            "risk": {
                "max_holding_bars": max(
                    _safe_int(risk_override_raw.get("max_holding_bars"), _safe_int(risk.get("max_holding_bars"), 30)),
                    0,
                ),
                "stop_atr_multiplier": _safe_float(
                    risk_override_raw.get("stop_atr_multiplier"),
                    _safe_float(risk.get("stop_atr_multiplier"), 1.5),
                ),
                "take_profit_rr": _safe_float(
                    risk_override_raw.get("take_profit_rr"),
                    _safe_float(risk.get("take_profit_rr"), 1.5),
                ),
                "time_stop_enabled": bool(
                    risk_override_raw.get("time_stop_enabled", risk.get("time_stop_enabled", True))
                ),
                "trailing_stop_enabled": bool(
                    risk_override_raw.get("trailing_stop_enabled", risk.get("trailing_stop_enabled", False))
                ),
            },
        }

    return {
        "capital": {
            "total_capital_mad": max(_safe_float(capital.get("total_capital_mad"), 1_000_000.0), 0.0),
        },
        "universe": {
            "basket": [str(item).strip().upper() for item in list(universe.get("basket") or []) if str(item).strip()],
        },
        "allocation": {
            "method": "hrp",
            "hrp_lookback_bars": max(_safe_int(allocation.get("hrp_lookback_bars"), 252), 20),
            "manual_overrides_by_symbol": manual_overrides,
        },
        "signal": {
            "signal_policy": "consensus",
            "enabled_families": [
                str(item).strip().lower()
                for item in list(signal.get("enabled_families") or logic.get("enabled_families") or ["sma", "rsi", "macd", "obv"])
                if str(item).strip()
            ],
        },
        "bet_sizing": bet_sizing,
        "risk": {
            "max_holding_bars": max(_safe_int(risk.get("max_holding_bars"), 30), 0),
            "stop_atr_multiplier": _safe_float(risk.get("stop_atr_multiplier"), 1.5),
            "take_profit_rr": _safe_float(risk.get("take_profit_rr"), 1.5),
            "time_stop_enabled": bool(risk.get("time_stop_enabled", True)),
            "trailing_stop_enabled": bool(risk.get("trailing_stop_enabled", False)),
        },
        "per_stock": per_stock,
    }


def _build_cost_model(raw: dict[str, Any]) -> CostModel:
    return CostModel(
        brokerage_bps=_safe_float(raw.get("brokerage_bps"), 0.2),
        comm_bourse_bps=_safe_float(raw.get("comm_bourse_bps"), 0.1),
        reg_liv_bps=_safe_float(raw.get("reg_liv_bps"), 0.0),
        slippage_bps=_safe_float(raw.get("slippage_bps"), 0.0),
        tva_rate=_safe_float(raw.get("tva_rate"), 0.1),
    )


def _signal_cost_bps(cost_model: CostModel) -> float:
    return float(
        cost_model.brokerage_bps
        + cost_model.comm_bourse_bps
        + cost_model.reg_liv_bps
        + cost_model.slippage_bps
    )


def _frame_to_metric_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    out = frame.copy().reset_index()
    cols = list(out.columns)
    if len(cols) < 2:
        return []
    out = out.rename(columns={cols[0]: "metric", cols[1]: "value"})
    return out[["metric", "value"]].to_dict("records")


def _compute_consensus_scores(
    *,
    symbol: str,
    ohlcv: pd.DataFrame,
    stock_config: dict[str, Any] | None = None,
    enabled_families: list[str],
    horizon: str,
    timeframe: str,
    signal_cost_bps: float,
    cooldown_bars: int,
    family_history_mode: FamilyHistoryMode = "static_current_reps",
) -> pd.Series:
    resolved_stock_config = (
        stock_config
        if isinstance(stock_config, dict) and stock_config
        else build_stock_config_from_enabled_families(enabled_families)
    )
    frame = compute_strategy_score_frame(
        stock_config=resolved_stock_config,
        ohlcv=ohlcv,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        signal_cost_bps=signal_cost_bps,
        cooldown_bars=cooldown_bars,
        family_history_mode=family_history_mode,
    )
    return frame["consensus_score"].reindex(ohlcv.index).fillna(0.0).astype(float)


def _compute_score_frame(
    *,
    symbol: str,
    ohlcv: pd.DataFrame,
    stock_config: dict[str, Any] | None = None,
    enabled_families: list[str],
    horizon: str,
    timeframe: str,
    signal_cost_bps: float,
    cooldown_bars: int,
    family_history_mode: FamilyHistoryMode = "static_current_reps",
) -> pd.DataFrame:
    resolved_stock_config = (
        stock_config
        if isinstance(stock_config, dict) and stock_config
        else build_stock_config_from_enabled_families(enabled_families)
    )
    return compute_strategy_score_frame(
        stock_config=resolved_stock_config,
        ohlcv=ohlcv,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        signal_cost_bps=signal_cost_bps,
        cooldown_bars=cooldown_bars,
        family_history_mode=family_history_mode,
    )


def _rule_threshold_value(value: Any, default: float = 0.0) -> float:
    if isinstance(value, dict):
        return _safe_float(value.get("value"), default)
    return _safe_float(value, default)


def _rule_param_value(value: Any, default: float = 0.0) -> float:
    if isinstance(value, dict):
        return _safe_float(value.get("value"), default)
    return _safe_float(value, default)


def _fraction_from_percent(value: Any, default: float = 0.0) -> float:
    return max(0.0, min(1.0, _safe_float(value, default) / 100.0))


def _rule_kelly_fraction(sizing: dict[str, Any]) -> float | None:
    raw = sizing.get("execution_kelly_fraction")
    value = _safe_float(raw, float("nan"))
    if not math.isfinite(value) or value <= 0.0:
        return None
    return value


def _entry_rule_fraction(rule: dict[str, Any]) -> float:
    sizing = rule.get("sizing") if isinstance(rule.get("sizing"), dict) else {}
    mode = str(sizing.get("mode") or "manual").strip().lower()
    if mode == "wfo":
        return _fraction_from_percent(_rule_param_value(sizing.get("size_pct"), sizing.get("manual_pct")), 0.0)
    if mode == "kelly_wfo":
        execution_kelly = _rule_kelly_fraction(sizing)
        if execution_kelly is None:
            return _fraction_from_percent(sizing.get("manual_pct"), 0.0)
        modifier = max(0.0, _rule_param_value(sizing.get("kelly_modifier"), 0.5))
        return max(0.0, min(1.0, execution_kelly * modifier))
    return _fraction_from_percent(sizing.get("manual_pct"), 0.0)


def _exit_rule_fraction(rule: dict[str, Any]) -> float:
    sizing = rule.get("sizing") if isinstance(rule.get("sizing"), dict) else {}
    mode = str(sizing.get("mode") or "manual").strip().lower()
    if mode == "wfo":
        return _fraction_from_percent(_rule_param_value(sizing.get("reduction_pct"), sizing.get("manual_pct")), 0.0)
    if mode == "kelly_wfo":
        execution_kelly = _rule_kelly_fraction(sizing)
        if execution_kelly is None:
            return _fraction_from_percent(sizing.get("manual_pct"), 0.0)
        modifier = max(0.0, _rule_param_value(sizing.get("kelly_modifier"), 0.5))
        return max(0.0, min(1.0, execution_kelly * modifier))
    return _fraction_from_percent(sizing.get("manual_pct"), 0.0)


_PRICE_FIELD_ALIASES = {
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume": "Volume",
}


def _is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def _normalize_bar_index(bars: pd.DataFrame | None, index: int | None) -> int | None:
    if not isinstance(bars, pd.DataFrame) or bars.empty:
        return None
    if index is None:
        return len(bars.index) - 1
    if index < 0 or index >= len(bars.index):
        return None
    return index


def _bar_column(bars: pd.DataFrame, field: Any) -> pd.Series | None:
    field_name = str(field or "Close").strip()
    normalized = _PRICE_FIELD_ALIASES.get(field_name.lower(), field_name)
    for candidate in (normalized, normalized.title(), normalized.upper(), normalized.lower()):
        if candidate in bars.columns:
            return bars[candidate].astype(float)
    return None


def _bar_value(bars: pd.DataFrame | None, index: int | None, field: Any) -> float:
    if not isinstance(bars, pd.DataFrame):
        return float("nan")
    pos = _normalize_bar_index(bars, index)
    if pos is None:
        return float("nan")
    series = _bar_column(bars, field)
    if series is None:
        return float("nan")
    return _safe_float(series.iloc[pos], float("nan"))


def _rolling_operand_value(bars: pd.DataFrame | None, index: int | None, operand: dict[str, Any]) -> float:
    if not isinstance(bars, pd.DataFrame):
        return float("nan")
    function = str(operand.get("function") or operand.get("mode") or "mean").strip().lower()
    field = operand.get("field") or "Close"
    lookback = max(_safe_int(operand.get("lookback") or operand.get("window") or operand.get("period"), 20), 1)
    offset = max(_safe_int(operand.get("offset"), 0), 0)
    pos = _normalize_bar_index(bars, index)
    if pos is None:
        return float("nan")
    pos -= offset
    if pos < 0:
        return float("nan")
    series = _bar_column(bars, field)
    if series is None:
        return float("nan")
    window = series.iloc[: pos + 1].tail(lookback).astype(float)
    if len(window) < lookback:
        return float("nan")
    if function in {"highest", "high", "max"}:
        return _safe_float(window.max(), float("nan"))
    if function in {"lowest", "low", "min"}:
        return _safe_float(window.min(), float("nan"))
    if function in {"sum", "total"}:
        return _safe_float(window.sum(), float("nan"))
    return _safe_float(window.mean(), float("nan"))


def _rsi_value(close: pd.Series, index: int, period: int) -> float:
    if index < period:
        return float("nan")
    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = gains.rolling(period, min_periods=period).mean().iloc[index]
    avg_loss = losses.rolling(period, min_periods=period).mean().iloc[index]
    if not _is_finite_number(avg_gain) or not _is_finite_number(avg_loss):
        return float("nan")
    if float(avg_loss) == 0.0:
        return 100.0 if float(avg_gain) > 0.0 else 50.0
    rs = float(avg_gain) / float(avg_loss)
    return 100.0 - (100.0 / (1.0 + rs))


def _indicator_operand_value(bars: pd.DataFrame | None, index: int | None, operand: dict[str, Any]) -> float:
    if not isinstance(bars, pd.DataFrame):
        return float("nan")
    pos = _normalize_bar_index(bars, index)
    if pos is None:
        return float("nan")
    name = str(operand.get("name") or operand.get("indicator") or "").strip().lower()
    window = max(_safe_int(operand.get("window") or operand.get("period") or operand.get("lookback"), 20), 1)
    close = _bar_column(bars, operand.get("field") or "Close")
    if close is None:
        return float("nan")

    if name in {"sma", "ma", "moving_average", "bollinger_mid"}:
        return _safe_float(close.rolling(window, min_periods=window).mean().iloc[pos], float("nan"))
    if name in {"ema", "exponential_moving_average"}:
        return _safe_float(close.ewm(span=window, adjust=False).mean().iloc[pos], float("nan"))
    if name == "rsi":
        return _rsi_value(close, pos, window)
    if name in {"bollinger_upper", "bollinger_lower"}:
        multiplier = _rule_param_value(operand.get("std") or operand.get("std_dev") or operand.get("multiplier"), 2.0)
        rolling = close.rolling(window, min_periods=window)
        middle = rolling.mean().iloc[pos]
        std = rolling.std(ddof=0).iloc[pos]
        if not _is_finite_number(middle) or not _is_finite_number(std):
            return float("nan")
        return float(middle) + (float(std) * multiplier) if name == "bollinger_upper" else float(middle) - (float(std) * multiplier)
    if name in {"volume_sma", "volume_average"}:
        volume = _bar_column(bars, "Volume")
        if volume is None:
            return float("nan")
        return _safe_float(volume.rolling(window, min_periods=window).mean().iloc[pos], float("nan"))
    if name in {"volume_sma_ratio", "relative_volume"}:
        volume = _bar_column(bars, "Volume")
        if volume is None:
            return float("nan")
        average = volume.rolling(window, min_periods=window).mean().iloc[pos]
        current = volume.iloc[pos]
        if not _is_finite_number(average) or float(average) == 0.0:
            return float("nan")
        return _safe_float(current, 0.0) / float(average)
    if name == "atr":
        return _safe_float(_compute_atr_series(bars, window=window).iloc[pos], float("nan"))
    return float("nan")


def _darvas_operand_value(bars: pd.DataFrame | None, index: int | None, operand: dict[str, Any]) -> float:
    side = str(operand.get("side") or operand.get("field") or "top").strip().lower()
    return _rolling_operand_value(
        bars,
        index,
        {
            "function": "highest" if side in {"top", "upper", "high"} else "lowest",
            "field": "High" if side in {"top", "upper", "high"} else "Low",
            "lookback": operand.get("lookback") or operand.get("window") or operand.get("period") or 20,
            "offset": operand.get("offset", 1),
        },
    )


def _operand_value(
    operand: Any,
    *,
    snapshot: dict[str, float],
    bars: pd.DataFrame | None = None,
    index: int | None = None,
    previous: bool = False,
) -> float:
    if previous:
        if index is None:
            return float("nan")
        index -= 1
    if isinstance(operand, (int, float)):
        return _safe_float(operand, float("nan"))
    if isinstance(operand, str):
        return _safe_float(snapshot.get(operand), float("nan"))
    if not isinstance(operand, dict):
        return float("nan")

    if "kind" not in operand and "value" in operand and len(operand.keys() & {"left", "right", "source", "level", "children"}) == 0:
        return _rule_param_value(operand, float("nan"))

    kind = str(operand.get("kind") or operand.get("type") or "").strip().lower()
    if kind in {"constant", "number", "param", "value"}:
        return _rule_param_value(operand.get("value"), float("nan"))
    if kind in {"score", "snapshot", "variable"}:
        key = str(operand.get("key") or operand.get("variable") or "consensus_score").strip()
        return _safe_float(snapshot.get(key), float("nan"))
    if kind == "price":
        return _bar_value(bars, index, operand.get("field") or "Close")
    if kind == "volume":
        return _bar_value(bars, index, "Volume")
    if kind == "rolling":
        return _rolling_operand_value(bars, index, operand)
    if kind == "indicator":
        return _indicator_operand_value(bars, index, operand)
    if kind == "darvas_box":
        return _darvas_operand_value(bars, index, operand)
    if "variable" in operand:
        return _safe_float(snapshot.get(str(operand.get("variable"))), float("nan"))
    return float("nan")


def _compare_values(left: float, right: float, operator: str) -> bool:
    if not _is_finite_number(left) or not _is_finite_number(right):
        return False
    if operator == ">":
        return left > right
    if operator == ">=":
        return left >= right
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right
    if operator in {"=", "=="}:
        return abs(left - right) <= 1e-12
    if operator == "!=":
        return abs(left - right) > 1e-12
    return False


def _condition_matches(
    snapshot: dict[str, float],
    condition: dict[str, Any],
    *,
    bars: pd.DataFrame | None = None,
    index: int | None = None,
) -> bool:
    condition_type = str(condition.get("type") or "threshold").strip().lower()
    if condition_type in {"cross", "crossover"}:
        left_operand = condition.get("left") if "left" in condition else condition.get("source", {"kind": "price", "field": "Close"})
        right_operand = condition.get("right") if "right" in condition else condition.get("level", {"kind": "indicator", "name": "sma", "window": 20})
        left = _operand_value(left_operand, snapshot=snapshot, bars=bars, index=index)
        right = _operand_value(right_operand, snapshot=snapshot, bars=bars, index=index)
        previous_left = _operand_value(left_operand, snapshot=snapshot, bars=bars, index=index, previous=True)
        previous_right = _operand_value(right_operand, snapshot=snapshot, bars=bars, index=index, previous=True)
        direction = str(condition.get("direction") or condition.get("operator") or "above").strip().lower()
        if direction in {"above", "crosses_above", "bullish", ">"}:
            return (
                _is_finite_number(previous_left)
                and _is_finite_number(previous_right)
                and previous_left <= previous_right
                and _compare_values(left, right, ">")
            )
        if direction in {"below", "crosses_below", "bearish", "<"}:
            return (
                _is_finite_number(previous_left)
                and _is_finite_number(previous_right)
                and previous_left >= previous_right
                and _compare_values(left, right, "<")
            )
        return False

    if condition_type in {"breakout", "breakdown"}:
        left_operand = condition.get("source") if "source" in condition else condition.get("left", {"kind": "price", "field": "Close"})
        right_operand = condition.get("level") if "level" in condition else condition.get("right")
        if right_operand is None:
            return False
        direction = str(condition.get("direction") or ("below" if condition_type == "breakdown" else "above")).strip().lower()
        operator = "<" if direction in {"below", "down", "breaks_below", "breakdown"} else ">"
        left = _operand_value(left_operand, snapshot=snapshot, bars=bars, index=index)
        right = _operand_value(right_operand, snapshot=snapshot, bars=bars, index=index)
        return _compare_values(left, right, operator)

    if condition_type == "touch":
        direction = str(condition.get("direction") or "above").strip().lower()
        field = "Low" if direction in {"below", "down", "lower"} else "High"
        left_operand = condition.get("source") if "source" in condition else condition.get("left", {"kind": "price", "field": field})
        right_operand = condition.get("level") if "level" in condition else condition.get("right")
        if right_operand is None:
            return False
        operator = "<=" if direction in {"below", "down", "lower"} else ">="
        left = _operand_value(left_operand, snapshot=snapshot, bars=bars, index=index)
        right = _operand_value(right_operand, snapshot=snapshot, bars=bars, index=index)
        return _compare_values(left, right, operator)

    variable = str(condition.get("variable") or "consensus_score")
    operator = str(condition.get("operator") or ">=")
    left_operand = condition.get("left") if "left" in condition else {"kind": "score", "key": variable}
    right_operand = condition.get("right") if "right" in condition else condition.get("threshold")
    left = _operand_value(left_operand, snapshot=snapshot, bars=bars, index=index)
    right = _operand_value(right_operand, snapshot=snapshot, bars=bars, index=index)
    if not _is_finite_number(right):
        right = _rule_threshold_value(condition.get("threshold"), 0.0)
    return _compare_values(left, right, operator)


def _expression_matches(
    snapshot: dict[str, float],
    expression: dict[str, Any],
    *,
    bars: pd.DataFrame | None = None,
    index: int | None = None,
) -> bool:
    operator = str(expression.get("operator") or expression.get("logic") or "").strip().lower()
    children = [item for item in list(expression.get("children") or []) if isinstance(item, dict)]
    if operator in {"all", "and"}:
        return bool(children) and all(_expression_matches(snapshot, child, bars=bars, index=index) for child in children)
    if operator in {"any", "or"}:
        return bool(children) and any(_expression_matches(snapshot, child, bars=bars, index=index) for child in children)
    if operator == "not":
        return bool(children) and not _expression_matches(snapshot, children[0], bars=bars, index=index)
    if children:
        return all(_expression_matches(snapshot, child, bars=bars, index=index) for child in children)
    return _condition_matches(snapshot, expression, bars=bars, index=index)


def _rule_triggered(
    snapshot: dict[str, float],
    rule: dict[str, Any],
    *,
    bars: pd.DataFrame | None = None,
    index: int | None = None,
) -> bool:
    expression = rule.get("rule_expression") or rule.get("expression")
    if isinstance(expression, dict):
        return _expression_matches(snapshot, expression, bars=bars, index=index)
    conditions = [item for item in list(rule.get("conditions") or []) if isinstance(item, dict)]
    if not conditions:
        return False
    return all(_condition_matches(snapshot, condition, bars=bars, index=index) for condition in conditions)


def rule_triggered(
    snapshot: dict[str, float],
    rule: dict[str, Any],
    *,
    bars: pd.DataFrame | None = None,
    index: int | None = None,
) -> bool:
    return _rule_triggered(snapshot, rule, bars=bars, index=index)


def _operand_label(operand: Any) -> str:
    if isinstance(operand, (int, float)):
        return f"{float(operand):g}"
    if isinstance(operand, str):
        return operand
    if not isinstance(operand, dict):
        return "value"
    if "kind" not in operand and "value" in operand:
        return f"{_rule_param_value(operand, 0.0):g}"
    kind = str(operand.get("kind") or operand.get("type") or "").strip().lower()
    if kind in {"constant", "number", "param", "value"}:
        return f"{_rule_param_value(operand.get('value'), 0.0):g}"
    if kind in {"score", "snapshot", "variable"}:
        return str(operand.get("key") or operand.get("variable") or "consensus_score")
    if kind == "price":
        return str(operand.get("field") or "Close")
    if kind == "volume":
        return "Volume"
    if kind == "rolling":
        function = str(operand.get("function") or "mean").replace("_", " ")
        field = str(operand.get("field") or "Close")
        lookback = _safe_int(operand.get("lookback") or operand.get("window") or operand.get("period"), 20)
        offset = _safe_int(operand.get("offset"), 0)
        suffix = " prior" if offset else ""
        return f"{lookback}-bar {function} {field}{suffix}"
    if kind == "indicator":
        name = str(operand.get("name") or operand.get("indicator") or "indicator").upper()
        window = operand.get("window") or operand.get("period") or operand.get("lookback")
        return f"{name}({window})" if window is not None else name
    if kind == "darvas_box":
        side = str(operand.get("side") or "top")
        lookback = _safe_int(operand.get("lookback") or operand.get("window") or operand.get("period"), 20)
        return f"Darvas {side}({lookback})"
    if "variable" in operand:
        return str(operand.get("variable"))
    return "value"


def _condition_description(condition: dict[str, Any]) -> str:
    condition_type = str(condition.get("type") or "threshold").strip().lower()
    if condition_type in {"cross", "crossover"}:
        direction = str(condition.get("direction") or condition.get("operator") or "above").replace("_", " ")
        left = condition.get("left") if "left" in condition else condition.get("source")
        right = condition.get("right") if "right" in condition else condition.get("level")
        return f"{_operand_label(left)} crosses {direction} {_operand_label(right)}"
    if condition_type in {"breakout", "breakdown"}:
        direction = str(condition.get("direction") or ("below" if condition_type == "breakdown" else "above")).replace("_", " ")
        left = condition.get("source") if "source" in condition else condition.get("left")
        right = condition.get("level") if "level" in condition else condition.get("right")
        return f"{_operand_label(left)} breaks {direction} {_operand_label(right)}"
    if condition_type == "touch":
        direction = str(condition.get("direction") or "above").replace("_", " ")
        left = condition.get("source") if "source" in condition else condition.get("left")
        right = condition.get("level") if "level" in condition else condition.get("right")
        return f"{_operand_label(left)} touches {direction} {_operand_label(right)}"
    variable = str(condition.get("variable") or "consensus_score")
    left = condition.get("left") if "left" in condition else {"kind": "score", "key": variable}
    right = condition.get("right") if "right" in condition else condition.get("threshold")
    return f"{_operand_label(left)} {condition.get('operator', '>=')} {_operand_label(right)}"


def _expression_descriptions(expression: dict[str, Any]) -> list[str]:
    operator = str(expression.get("operator") or expression.get("logic") or "").strip().lower()
    children = [item for item in list(expression.get("children") or []) if isinstance(item, dict)]
    if children:
        joiner = " OR " if operator in {"any", "or"} else " AND "
        child_text = [
            " ".join(_expression_descriptions(child)).strip()
            for child in children
        ]
        return [joiner.join(text for text in child_text if text)]
    return [_condition_description(expression)]


def describe_rule_conditions(rule: dict[str, Any]) -> list[str]:
    expression = rule.get("rule_expression") or rule.get("expression")
    if isinstance(expression, dict):
        return _expression_descriptions(expression)
    return [
        _condition_description(condition)
        for condition in [item for item in list(rule.get("conditions") or []) if isinstance(item, dict)]
    ]


def rule_condition_count(rule: dict[str, Any]) -> int:
    expression = rule.get("rule_expression") or rule.get("expression")
    if isinstance(expression, dict):
        children = [item for item in list(expression.get("children") or []) if isinstance(item, dict)]
        if children:
            return sum(rule_condition_count({"rule_expression": child}) for child in children)
        return 1
    return len([item for item in list(rule.get("conditions") or []) if isinstance(item, dict)])


def build_rule_snapshot(
    score_snapshot: dict[str, Any] | pd.Series | None,
    *,
    bars: pd.DataFrame | None = None,
    index: int | None = None,
) -> dict[str, float]:
    if isinstance(score_snapshot, pd.Series):
        snapshot = {str(key): _safe_float(value, 0.0) for key, value in score_snapshot.items()}
    elif isinstance(score_snapshot, dict):
        snapshot = {str(key): _safe_float(value, 0.0) for key, value in score_snapshot.items()}
    else:
        snapshot = {}

    if isinstance(bars, pd.DataFrame):
        pos = _normalize_bar_index(bars, index)
        if pos is not None:
            for source_field, snapshot_key in (
                ("Open", "open"),
                ("High", "high"),
                ("Low", "low"),
                ("Close", "close"),
                ("Volume", "volume"),
            ):
                value = _bar_value(bars, pos, source_field)
                if _is_finite_number(value):
                    snapshot[snapshot_key] = value
            atr_value = _safe_float(_compute_atr_series(bars).iloc[pos], float("nan"))
            if _is_finite_number(atr_value):
                snapshot["atr"] = atr_value

    snapshot.setdefault("trend_score", 0.0)
    snapshot.setdefault("momentum_score", 0.0)
    snapshot.setdefault("oscillation_score", 0.0)
    snapshot.setdefault("volume_score", 0.0)
    snapshot.setdefault("consensus_score", 0.0)
    return snapshot


def _rule_reference(rule: dict[str, Any], fallback: str) -> str:
    option = str(rule.get("config_option") or "").strip().upper()
    label = str(rule.get("label") or fallback).strip()
    if option and label:
        return f"{option} - {label}"
    if option:
        return option
    if label:
        return label
    return fallback


def _rule_trigger_display(
    *,
    side: str,
    snapshot: dict[str, float],
    risk_reason: str | None,
    rule: dict[str, Any] | None,
    close_t: float,
    stop_loss: float | None,
    take_profit: float | None,
    holding_bars: int,
    max_holding_bars: int,
) -> str:
    if risk_reason == "stop_loss":
        comparator = "<=" if str(side).upper() == "BUY" else ">="
        barrier = _safe_float(stop_loss, 0.0)
        return f"SL ({close_t:.1f} {comparator} {barrier:.1f})"
    if risk_reason == "take_profit":
        comparator = ">=" if str(side).upper() == "BUY" else "<="
        barrier = _safe_float(take_profit, 0.0)
        return f"TP ({close_t:.1f} {comparator} {barrier:.1f})"
    if risk_reason == "time_stop":
        return f"TS ({max(holding_bars, max_holding_bars)} bars)"
    if not rule:
        return ""

    option = str(rule.get("config_option") or "").strip().upper()
    letter = option or str(rule.get("label") or "").strip()
    prefix = "Entry" if str(side).upper() == "BUY" else "Exit"
    conditions = [item for item in list(rule.get("conditions") or []) if isinstance(item, dict)]
    if not conditions:
        return f"{prefix} {letter}".strip()
    variable = str(conditions[0].get("variable") or "").strip()
    value = _safe_float(snapshot.get(variable), float("nan"))
    if math.isfinite(value):
        return f"{prefix} {letter} ({value:.1f})"
    return f"{prefix} {letter}".strip()


def _entry_target_fraction(
    *,
    snapshot: dict[str, float],
    entry_rules: list[dict[str, Any]],
    previous_fraction: float,
    side_policy: str,
    max_fraction: float,
    bars: pd.DataFrame | None = None,
    index: int | None = None,
) -> tuple[float, dict[str, Any] | None]:
    if not entry_rules:
        return previous_fraction, None
    triggered: list[dict[str, Any]] = [
        rule
        for rule in entry_rules
        if _rule_triggered(snapshot, rule, bars=bars, index=index)
    ]
    if not triggered:
        return previous_fraction, None

    desired_fraction = min(
        max_fraction,
        sum(
            max(0.0, _entry_rule_fraction(rule))
            for rule in triggered
            if isinstance(rule, dict)
        ),
    )
    if desired_fraction <= 0:
        return previous_fraction, None

    direction = 1.0
    consensus_score = snapshot.get("consensus_score", 0.0)
    if side_policy == "long_short" and consensus_score < 0:
        direction = -1.0
    target = direction * max(abs(previous_fraction), desired_fraction)
    return target, triggered[-1]


def _apply_exit_rules(
    *,
    snapshot: dict[str, float],
    exit_rules: list[dict[str, Any]],
    target_fraction: float,
    bars: pd.DataFrame | None = None,
    index: int | None = None,
) -> tuple[float, dict[str, Any] | None]:
    if not exit_rules or target_fraction == 0.0:
        return target_fraction, None
    remaining = abs(target_fraction)
    direction = math.copysign(1.0, target_fraction)
    triggered_rule: dict[str, Any] | None = None
    for rule in exit_rules:
        if not isinstance(rule, dict) or not _rule_triggered(snapshot, rule, bars=bars, index=index):
            continue
        reduction = _exit_rule_fraction(rule)
        remaining *= max(0.0, 1.0 - reduction)
        triggered_rule = rule
        if remaining <= 1e-9:
            remaining = 0.0
            break
    if triggered_rule is None:
        return target_fraction, None
    return direction * remaining, triggered_rule


def _compute_atr_series(ohlcv: pd.DataFrame, window: int = 14) -> pd.Series:
    high = ohlcv["High"].astype(float)
    low = ohlcv["Low"].astype(float)
    close = ohlcv["Close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=window, min_periods=1).mean().bfill().fillna(0.0)


def _align_timestamp_to_index(ts: pd.Timestamp, index: pd.Index) -> pd.Timestamp:
    index_tz = getattr(index, "tz", None)
    if index_tz is not None:
        return ts.tz_localize(index_tz) if ts.tzinfo is None else ts.tz_convert(index_tz)
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def _weighted_isotonic_increasing(values: list[float], weights: list[float]) -> list[float]:
    if not values:
        return []
    blocks: list[dict[str, Any]] = []
    for value, weight in zip(values, weights):
        blocks.append({"sum_w": float(max(weight, 1e-9)), "sum_yw": float(value * max(weight, 1e-9)), "count": 1})
        while len(blocks) >= 2:
            last = blocks[-1]
            prev = blocks[-2]
            last_mean = last["sum_yw"] / last["sum_w"]
            prev_mean = prev["sum_yw"] / prev["sum_w"]
            if prev_mean <= last_mean + 1e-12:
                break
            merged = {
                "sum_w": prev["sum_w"] + last["sum_w"],
                "sum_yw": prev["sum_yw"] + last["sum_yw"],
                "count": prev["count"] + last["count"],
            }
            blocks = blocks[:-2]
            blocks.append(merged)

    out: list[float] = []
    for block in blocks:
        mean = block["sum_yw"] / block["sum_w"]
        out.extend([float(mean)] * int(block["count"]))
    return out


def _build_calibration_plot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    fig = go.Figure()
    if rows:
        labels = [
            f"{_safe_float(row.get('score_low')):.1f}-{_safe_float(row.get('score_high')):.1f}"
            for row in rows
        ]
        fig.add_trace(
            go.Bar(
                x=labels,
                y=[_safe_int(row.get("n_observations"), 0) for row in rows],
                name="N obs",
                marker={"color": "#94a3b8"},
                opacity=0.55,
                yaxis="y2",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=labels,
                y=[_safe_float(row.get("avg_r_multiple")) for row in rows],
                name="Avg R",
                mode="lines+markers",
                line={"color": "#2563eb", "width": 2},
            )
        )
        fig.add_trace(
            go.Scatter(
                x=labels,
                y=[_safe_float(row.get("target_exposure_pct")) / 100.0 for row in rows],
                name="Target exposure",
                mode="lines+markers",
                line={"color": "#16a34a", "width": 2, "dash": "dot"},
            )
        )
    fig.update_layout(
        title="Sizing Calibration",
        margin={"l": 40, "r": 40, "t": 50, "b": 30},
        legend={"orientation": "h"},
        yaxis={"title": "Avg R / Exposure"},
        yaxis2={"title": "N obs", "overlaying": "y", "side": "right", "showgrid": False},
        xaxis={"title": "Abs score range"},
    )
    return _normalize_plotly_payload(fig.to_plotly_json())


def _simulate_calibration_observation(
    *,
    symbol: str,
    bars: pd.DataFrame,
    atr_series: pd.Series,
    observation_index: int,
    side: int,
    risk: dict[str, Any],
    cost_model: CostModel,
) -> dict[str, Any] | None:
    if observation_index < 0 or observation_index >= len(bars.index) - 1:
        return None

    entry_idx = observation_index + 1
    entry_price = _safe_float(bars["Open"].iloc[entry_idx])
    if entry_price <= 0:
        return None

    entry_ts = pd.Timestamp(bars.index[entry_idx])
    atr_value = _safe_float(atr_series.iloc[observation_index], 0.0)
    stop_loss, take_profit = _build_barriers(
        position=side,
        avg_entry_price=entry_price,
        atr=max(atr_value, 0.0),
        risk=risk,
    )
    risk_per_share = abs(entry_price - _safe_float(stop_loss, entry_price))
    if risk_per_share <= 0:
        risk_per_share = max(entry_price * 0.0025, 1e-9)

    holding_bars = 0
    exit_reason = "window_end"
    exit_price = _safe_float(bars["Close"].iloc[-1], entry_price)
    exit_ts = pd.Timestamp(bars.index[-1])

    for idx in range(entry_idx, len(bars.index) - 1):
        close_t = _safe_float(bars["Close"].iloc[idx], entry_price)
        reason: str | None = None
        if side > 0:
            if stop_loss is not None and close_t <= stop_loss:
                reason = "stop_loss"
            elif take_profit is not None and close_t >= take_profit:
                reason = "take_profit"
        else:
            if stop_loss is not None and close_t >= stop_loss:
                reason = "stop_loss"
            elif take_profit is not None and close_t <= take_profit:
                reason = "take_profit"
        if (
            reason is None
            and bool(risk.get("time_stop_enabled", True))
            and _safe_int(risk.get("max_holding_bars"), 0) > 0
            and holding_bars >= _safe_int(risk.get("max_holding_bars"), 0)
        ):
            reason = "time_stop"
        if reason is not None:
            exit_reason = reason
            exit_ts = pd.Timestamp(bars.index[idx + 1])
            exit_price = _safe_float(bars["Open"].iloc[idx + 1], close_t)
            break
        holding_bars += 1

    entry_cost, _ = cost_model.estimate_cost(float(entry_price))
    exit_cost, _ = cost_model.estimate_cost(float(exit_price))
    gross_pnl = float(side * (exit_price - entry_price))
    net_pnl = gross_pnl - float(entry_cost) - float(exit_cost)
    net_return = net_pnl / max(entry_price, 1e-9)
    r_multiple = net_pnl / risk_per_share if risk_per_share > 0 else 0.0

    return {
        "symbol": symbol,
        "timestamp": entry_ts.isoformat(),
        "side": "long" if side > 0 else "short",
        "net_return": float(net_return),
        "r_multiple": float(r_multiple),
        "win": bool(net_pnl > 0),
        "exit_reason": exit_reason,
    }


def _derive_calibrated_bet_sizing(
    *,
    basket: list[str],
    bars_by_symbol: dict[str, pd.DataFrame],
    start_ts: pd.Timestamp,
    horizon: str,
    timeframe: str,
    enabled_families: list[str],
    side_policy: str,
    cost_model: CostModel,
    risk: dict[str, Any],
    signal_cost_bps: float,
    cooldown_bars: int,
    family_history_mode: FamilyHistoryMode,
    bet_sizing_config: dict[str, Any],
    per_stock: dict[str, Any] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    lookback_bars = max(_safe_int(bet_sizing_config.get("calibration_lookback_bars"), 756), 60)
    min_observations = max(_safe_int(bet_sizing_config.get("min_observations"), 200), 1)
    min_bucket_observations = max(_safe_int(bet_sizing_config.get("min_bucket_observations"), 25), 1)
    bucket_count = max(_safe_int(bet_sizing_config.get("bucket_count"), 10), 2)
    exposure_levels = _coerce_exposure_levels(bet_sizing_config.get("exposure_levels"))

    raw_rows: list[dict[str, Any]] = []
    window_start: str | None = None
    window_end: str | None = None

    for symbol in basket:
        if cancel_check is not None and cancel_check():
            raise BacktestCanceled("Strategy backtest canceled by user.")
        full_bars = bars_by_symbol[symbol].copy().sort_index()
        full_bars.index = pd.to_datetime(full_bars.index)
        aligned_start_ts = _align_timestamp_to_index(start_ts, full_bars.index)
        pre_bars = full_bars.loc[full_bars.index < aligned_start_ts]
        if pre_bars.empty:
            continue
        if len(pre_bars) > lookback_bars:
            pre_bars = pre_bars.iloc[-lookback_bars:]
        if len(pre_bars) < 3:
            continue

        if window_start is None or pre_bars.index.min().isoformat() < window_start:
            window_start = pre_bars.index.min().date().isoformat()
        if window_end is None or pre_bars.index.max().isoformat() > window_end:
            window_end = pre_bars.index.max().date().isoformat()

        stock_overrides = (per_stock or {}).get(symbol, {}) if isinstance((per_stock or {}).get(symbol, {}), dict) else {}
        stock_signal = stock_overrides.get("signal") if isinstance(stock_overrides.get("signal"), dict) else {}
        stock_signal_construction = stock_overrides.get("signal_construction") if isinstance(stock_overrides.get("signal_construction"), dict) else {}
        stock_risk = stock_overrides.get("risk") if isinstance(stock_overrides.get("risk"), dict) else {}
        scores = _compute_consensus_scores(
            symbol=symbol,
            ohlcv=pre_bars,
            stock_config={"signal_construction": stock_signal_construction} if stock_signal_construction else None,
            enabled_families=list(stock_signal.get("enabled_families") or enabled_families),
            horizon=horizon,
            timeframe=timeframe,
            signal_cost_bps=signal_cost_bps,
            cooldown_bars=cooldown_bars,
            family_history_mode=family_history_mode,
        ).reindex(pre_bars.index).fillna(0.0).astype(float)
        atr_series = _compute_atr_series(pre_bars)

        for i in range(len(pre_bars.index) - 1):
            score = _safe_float(scores.iloc[i], 0.0)
            if side_policy == "long_only" and score <= 0:
                continue
            if side_policy == "long_short" and abs(score) <= 0:
                continue
            side = 1 if score > 0 else -1
            observation = _simulate_calibration_observation(
                symbol=symbol,
                bars=pre_bars,
                atr_series=atr_series,
                observation_index=i,
                side=side,
                risk=stock_risk if stock_risk else risk,
                cost_model=cost_model,
            )
            if observation is None:
                continue
            observation["consensus_score"] = float(score)
            observation["abs_consensus_score"] = float(abs(score))
            raw_rows.append(observation)

    if not raw_rows:
        ladder = _default_fallback_ladder()
        return {
            "status": "fallback",
            "lookback_bars": lookback_bars,
            "window_start": None,
            "window_end": None,
            "n_observations": 0,
            "primary_metric": "avg_r_multiple",
            "bucket_rows": [],
            "ladder": ladder,
            "plot": _build_calibration_plot([]),
            "reason": "insufficient historical observations",
        }

    frame = pd.DataFrame(raw_rows).sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    q = min(bucket_count, len(frame))
    ranked = frame["abs_consensus_score"].rank(method="first")
    frame["provisional_bucket"] = pd.qcut(ranked, q=q, labels=False, duplicates="drop") + 1
    keep_mask: list[bool] = []
    last_key: tuple[str, str, int] | None = None
    for row in frame.itertuples(index=False):
        key = (str(row.symbol), str(row.side), int(row.provisional_bucket))
        keep = key != last_key
        keep_mask.append(keep)
        last_key = key
    frame = frame.loc[keep_mask].reset_index(drop=True)

    n_observations = int(len(frame))
    if n_observations < 60:
        ladder = _default_fallback_ladder()
        return {
            "status": "fallback",
            "lookback_bars": lookback_bars,
            "window_start": window_start,
            "window_end": window_end,
            "n_observations": n_observations,
            "primary_metric": "avg_r_multiple",
            "bucket_rows": [],
            "ladder": ladder,
            "plot": _build_calibration_plot([]),
            "reason": "insufficient historical observations",
        }

    q = min(bucket_count, len(frame))
    ranked = frame["abs_consensus_score"].rank(method="first")
    frame["bucket_id"] = pd.qcut(ranked, q=q, labels=False, duplicates="drop") + 1
    grouped = (
        frame.groupby("bucket_id", dropna=True)
        .agg(
            score_low=("abs_consensus_score", "min"),
            score_high=("abs_consensus_score", "max"),
            n_observations=("abs_consensus_score", "count"),
            avg_r_multiple=("r_multiple", "mean"),
            avg_net_return=("net_return", "mean"),
            win_rate=("win", "mean"),
        )
        .reset_index(drop=True)
        .sort_values("score_low")
    )
    grouped["smoothed_metric"] = _weighted_isotonic_increasing(
        grouped["avg_r_multiple"].astype(float).tolist(),
        grouped["n_observations"].astype(float).tolist(),
    )

    rows = grouped.to_dict("records")
    merged_rows: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    for row in rows:
        current = {
            "score_low": float(row["score_low"]),
            "score_high": float(row["score_high"]),
            "n_observations": int(row["n_observations"]),
            "avg_r_multiple": float(row["avg_r_multiple"]),
            "avg_net_return": float(row["avg_net_return"]),
            "win_rate": float(row["win_rate"]),
            "smoothed_metric": float(row["smoothed_metric"]),
        }
        if pending is None:
            pending = current
            continue
        if pending["n_observations"] < min_bucket_observations:
            total_n = pending["n_observations"] + current["n_observations"]
            pending = {
                "score_low": pending["score_low"],
                "score_high": current["score_high"],
                "n_observations": total_n,
                "avg_r_multiple": (
                    pending["avg_r_multiple"] * pending["n_observations"] + current["avg_r_multiple"] * current["n_observations"]
                ) / max(total_n, 1),
                "avg_net_return": (
                    pending["avg_net_return"] * pending["n_observations"] + current["avg_net_return"] * current["n_observations"]
                ) / max(total_n, 1),
                "win_rate": (
                    pending["win_rate"] * pending["n_observations"] + current["win_rate"] * current["n_observations"]
                ) / max(total_n, 1),
                "smoothed_metric": (
                    pending["smoothed_metric"] * pending["n_observations"] + current["smoothed_metric"] * current["n_observations"]
                ) / max(total_n, 1),
            }
        else:
            merged_rows.append(pending)
            pending = current
    if pending is not None:
        if merged_rows and pending["n_observations"] < min_bucket_observations:
            previous = merged_rows.pop()
            total_n = previous["n_observations"] + pending["n_observations"]
            merged_rows.append(
                {
                    "score_low": previous["score_low"],
                    "score_high": pending["score_high"],
                    "n_observations": total_n,
                    "avg_r_multiple": (
                        previous["avg_r_multiple"] * previous["n_observations"] + pending["avg_r_multiple"] * pending["n_observations"]
                    ) / max(total_n, 1),
                    "avg_net_return": (
                        previous["avg_net_return"] * previous["n_observations"] + pending["avg_net_return"] * pending["n_observations"]
                    ) / max(total_n, 1),
                    "win_rate": (
                        previous["win_rate"] * previous["n_observations"] + pending["win_rate"] * pending["n_observations"]
                    ) / max(total_n, 1),
                    "smoothed_metric": (
                        previous["smoothed_metric"] * previous["n_observations"] + pending["smoothed_metric"] * pending["n_observations"]
                    ) / max(total_n, 1),
                }
            )
        else:
            merged_rows.append(pending)

    smoothed = _weighted_isotonic_increasing(
        [float(row["smoothed_metric"]) for row in merged_rows],
        [float(row["n_observations"]) for row in merged_rows],
    )
    for row, smoothed_value in zip(merged_rows, smoothed):
        row["smoothed_metric"] = float(smoothed_value)

    positive_rows = [row for row in merged_rows if row["smoothed_metric"] > 0]
    max_levels = [level for level in exposure_levels if level > 0]
    if positive_rows and positive_rows[-1]["n_observations"] < 50 and 100 in max_levels:
        max_levels = [level for level in max_levels if level < 100]
    if not max_levels:
        max_levels = [25]
    tier_count = min(len(max_levels), len(positive_rows))
    active_levels = max_levels[:tier_count]

    for row in merged_rows:
        row["target_exposure_pct"] = 0
    if positive_rows:
        total_positive = len(positive_rows)
        for idx, row in enumerate(positive_rows):
            level_index = min((idx * max(tier_count, 1)) // max(total_positive, 1), tier_count - 1)
            row["target_exposure_pct"] = int(active_levels[level_index])

    ladder = [
        {
            "score_low": float(row["score_low"]),
            "score_high": float(row["score_high"]),
            "target_exposure_pct": int(row["target_exposure_pct"]),
        }
        for row in merged_rows
    ]
    bucket_rows = [
        {
            "score_low": float(row["score_low"]),
            "score_high": float(row["score_high"]),
            "n_observations": int(row["n_observations"]),
            "avg_r_multiple": float(row["avg_r_multiple"]),
            "avg_net_return": float(row["avg_net_return"]),
            "win_rate": float(row["win_rate"]),
            "target_exposure_pct": int(row["target_exposure_pct"]),
        }
        for row in merged_rows
    ]

    return {
        "status": "ok" if n_observations >= min_observations else "provisional",
        "lookback_bars": lookback_bars,
        "window_start": window_start,
        "window_end": window_end,
        "n_observations": n_observations,
        "primary_metric": "avg_r_multiple",
        "bucket_rows": bucket_rows,
        "ladder": ladder,
        "plot": _build_calibration_plot(bucket_rows),
        "reason": None if n_observations >= 60 else "insufficient historical observations",
    }


def _target_exposure_pct_from_ladder(
    abs_score: float,
    ladder: list[dict[str, Any]],
) -> int:
    score = max(_safe_float(abs_score), 0.0)
    if not ladder:
        return 0
    for row in ladder:
        low = _safe_float(row.get("score_low"), 0.0)
        high = _safe_float(row.get("score_high"), 100.0)
        if low <= score <= high + 1e-9:
            return max(_safe_int(row.get("target_exposure_pct"), 0), 0)
    return max(_safe_int(ladder[-1].get("target_exposure_pct"), 0), 0)


def _bucket_target_fraction(
    score: float,
    *,
    side_policy: str,
    exposure_ladder: list[dict[str, Any]],
) -> float:
    score = _safe_float(score)
    direction = 0.0
    if score > 0:
        direction = 1.0
    elif score < 0 and side_policy == "long_short":
        direction = -1.0

    abs_score = abs(score)
    if direction == 0.0:
        return 0.0

    target_pct = _target_exposure_pct_from_ladder(abs_score, exposure_ladder)
    return direction * (target_pct / 100.0)


def _build_barriers(
    *,
    position: int,
    avg_entry_price: float,
    atr: float,
    risk: dict[str, Any],
) -> tuple[float | None, float | None]:
    if position == 0 or avg_entry_price <= 0:
        return None, None
    stop_mult = max(_safe_float(risk.get("stop_atr_multiplier"), 1.5), 0.0)
    take_profit_rr = max(_safe_float(risk.get("take_profit_rr"), 1.5), 0.0)
    stop_distance = atr * stop_mult
    if position > 0:
        stop_loss = avg_entry_price - stop_distance
        take_profit = avg_entry_price + stop_distance * take_profit_rr
    else:
        stop_loss = avg_entry_price + stop_distance
        take_profit = avg_entry_price - stop_distance * take_profit_rr
    return float(stop_loss), float(take_profit)


def _volume_gate_allows(
    *,
    enabled: bool,
    kind: str,
    min_volume_abs: float,
    min_volume_ratio_adv: float,
    volume_value: float,
    adv_value: float,
) -> bool:
    if not enabled:
        return True
    if kind == "min_abs":
        return volume_value >= min_volume_abs
    if adv_value <= 0:
        return False
    return volume_value >= (min_volume_ratio_adv * adv_value)


def _trade_reason(
    *,
    risk_reason: str | None,
    rule_reason: str | None,
    target_fraction: float,
    previous_fraction: float,
) -> str:
    if risk_reason:
        return risk_reason
    if rule_reason and previous_fraction == 0.0 and target_fraction != 0.0:
        return f"entry_rule:{rule_reason}"
    if rule_reason and previous_fraction != 0.0 and abs(target_fraction) < abs(previous_fraction):
        return f"exit_rule:{rule_reason}"
    if rule_reason and abs(target_fraction) > abs(previous_fraction):
        return f"entry_rule:{rule_reason}"
    if previous_fraction == 0.0 and target_fraction != 0.0:
        return "signal_entry"
    if previous_fraction != 0.0 and target_fraction == 0.0:
        return "signal_exit"
    if (
        previous_fraction != 0.0
        and target_fraction != 0.0
        and math.copysign(1.0, target_fraction) != math.copysign(1.0, previous_fraction)
    ):
        return "reverse"
    if abs(target_fraction) > abs(previous_fraction):
        return "scale_in"
    if abs(target_fraction) < abs(previous_fraction):
        return "scale_out"
    return "rebalance"


def _make_price_trade_figure(
    *,
    bars_window: pd.DataFrame,
    ledger_rows: list[dict[str, Any]],
    symbol: str,
) -> dict[str, Any]:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=bars_window.index,
            y=bars_window["Close"],
            mode="lines",
            name="Close",
            line={"color": "#2563eb", "width": 1.8},
        )
    )

    def _marker_trace(rows: list[dict[str, Any]], side: str) -> None:
        if not rows:
            return
        color = "#16a34a" if side == "BUY" else "#dc2626"
        symbol_name = "triangle-up" if side == "BUY" else "triangle-down"
        fig.add_trace(
            go.Scatter(
                x=[row["timestamp"] for row in rows],
                y=[row["prix_execution_open_jour"] for row in rows],
                mode="markers",
                name=side,
                marker={
                    "size": 12,
                    "color": color,
                    "symbol": symbol_name,
                    "line": {"color": "#111827", "width": 1},
                },
                customdata=[
                    [
                        row.get("quantite"),
                        row.get("prix_execution_open_jour"),
                        row.get("signal_score"),
                        row.get("cost"),
                        row.get("trigger_display"),
                    ]
                    for row in rows
                ],
                hovertemplate=(
                    f"{side}<br>Date=%{{x|%Y-%m-%d}}"
                    "<br>Qty=%{customdata[0]:,.0f}"
                    "<br>Price=%{customdata[1]:,.2f}"
                    "<br>Signal=%{customdata[2]:.1f}"
                    "<br>Cost=%{customdata[3]:,.2f}"
                    "<br>Trigger=%{customdata[4]}"
                    "<extra></extra>"
                ),
            )
        )

    _marker_trace([row for row in ledger_rows if str(row.get("side", "")).upper() == "BUY"], "BUY")
    _marker_trace([row for row in ledger_rows if str(row.get("side", "")).upper() == "SELL"], "SELL")
    fig.update_layout(
        title=f"{symbol} Price + Trades",
        hovermode="x unified",
        margin={"l": 40, "r": 20, "t": 40, "b": 30},
        legend={"orientation": "h", "y": -0.15},
        xaxis={"title": "Date"},
        yaxis={"title": "Price"},
    )
    return _normalize_plotly_payload(fig.to_plotly_json())


def _simulate_stock(
    *,
    symbol: str,
    bars: pd.DataFrame,
    score_series: pd.Series,
    score_frame: pd.DataFrame | None,
    allocated_capital: float,
    side_policy: str,
    exposure_ladder: list[dict[str, Any]],
    entry_rules: list[dict[str, Any]] | None,
    exit_rules: list[dict[str, Any]] | None,
    risk: dict[str, Any],
    cost_model: CostModel,
    cooldown_bars: int,
    volume_gate: dict[str, Any],
) -> _StockSimulation:
    window = bars.copy().sort_index()
    if len(window) < 2:
        empty_index = window.index[:1]
        empty_equity = pd.Series([allocated_capital], index=empty_index, dtype="float64")
        return _StockSimulation(
            symbol=symbol,
            equity=empty_equity,
            positions=pd.Series([0], index=empty_index, dtype="float64"),
            fills=pd.DataFrame(columns=["timestamp", "symbol", "qty", "side", "price", "notional", "cost"]),
            per_fill_ledger=[],
            raw_scores=score_series.reindex(window.index).fillna(0.0),
            summary_metrics={},
            trade_performance=[],
            buy_hold_cum=pd.Series([0.0], index=empty_index, dtype="float64"),
            bars_window=window,
        )

    atr_series = _compute_atr_series(window)
    volume_series = window["Volume"].astype(float) if "Volume" in window.columns else pd.Series(0.0, index=window.index)
    adv_window = max(_safe_int(volume_gate.get("adv_window"), 20), 1)
    adv20 = volume_series.rolling(adv_window, min_periods=1).mean()
    scores = score_series.reindex(window.index).fillna(0.0).astype(float)
    snapshots = (
        score_frame.reindex(window.index).fillna(0.0).astype(float)
        if isinstance(score_frame, pd.DataFrame)
        else pd.DataFrame({"consensus_score": scores}, index=window.index)
    )
    max_fraction = min(1.0, max(_safe_float(risk.get("max_position_pct"), 100.0), 0.0) / 100.0)
    has_rule_logic = bool(entry_rules or exit_rules)

    cash = float(allocated_capital)
    position = 0
    avg_entry_price = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    holding_bars = 0
    last_exit_exec_i = -10**9
    previous_fraction = 0.0
    previous_target_shares = 0

    fills: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    equity_points: list[tuple[pd.Timestamp, float]] = [(pd.Timestamp(window.index[0]), float(allocated_capital))]
    position_points: list[tuple[pd.Timestamp, int]] = [(pd.Timestamp(window.index[0]), 0)]

    for i in range(len(window.index) - 1):
        t1 = pd.Timestamp(window.index[i + 1])
        close_t = _safe_float(window["Close"].iloc[i])
        close_t1 = _safe_float(window["Close"].iloc[i + 1])
        open_t1 = _safe_float(window["Open"].iloc[i + 1], 0.0)
        volume_t1 = _safe_float(volume_series.iloc[i + 1], 0.0)
        adv_t1 = _safe_float(adv20.iloc[i + 1], 0.0)
        atr_t = _safe_float(atr_series.iloc[i], 0.0)
        score_t = _safe_float(scores.iloc[i], 0.0)
        score_snapshot = {
            str(column): _safe_float(snapshots[column].iloc[i], 0.0)
            for column in snapshots.columns
        }
        score_snapshot["consensus_score"] = _safe_float(score_snapshot.get("consensus_score"), score_t)
        snapshot = build_rule_snapshot(score_snapshot, bars=window, index=i)

        risk_reason: str | None = None
        rule_reason: str | None = None
        entry_rule_ref: str | None = None
        exit_rule_ref: str | None = None
        entry_rule_match: dict[str, Any] | None = None
        exit_rule_match: dict[str, Any] | None = None
        if position != 0:
            if position > 0:
                if stop_loss is not None and close_t <= stop_loss:
                    risk_reason = "stop_loss"
                elif take_profit is not None and close_t >= take_profit:
                    risk_reason = "take_profit"
            else:
                if stop_loss is not None and close_t >= stop_loss:
                    risk_reason = "stop_loss"
                elif take_profit is not None and close_t <= take_profit:
                    risk_reason = "take_profit"
            if (
                risk_reason is None
                and bool(risk.get("time_stop_enabled", True))
                and _safe_int(risk.get("max_holding_bars"), 0) > 0
                and holding_bars >= _safe_int(risk.get("max_holding_bars"), 0)
            ):
                risk_reason = "time_stop"

        if has_rule_logic:
            target_fraction, entry_match = _entry_target_fraction(
                snapshot=snapshot,
                entry_rules=[rule for rule in list(entry_rules or []) if isinstance(rule, dict)],
                previous_fraction=previous_fraction,
                side_policy=side_policy,
                max_fraction=max_fraction,
                bars=window,
                index=i,
            )
            target_fraction, exit_match = _apply_exit_rules(
                snapshot=snapshot,
                exit_rules=[rule for rule in list(exit_rules or []) if isinstance(rule, dict)],
                target_fraction=target_fraction,
                bars=window,
                index=i,
            )
            entry_rule_match = entry_match
            exit_rule_match = exit_match
            entry_rule_ref = _rule_reference(entry_match, "entry_rule") if isinstance(entry_match, dict) else None
            exit_rule_ref = _rule_reference(exit_match, "exit_rule") if isinstance(exit_match, dict) else None
            rule_reason = exit_rule_ref or entry_rule_ref
        else:
            target_fraction = _bucket_target_fraction(
                score_t,
                side_policy=side_policy,
                exposure_ladder=exposure_ladder,
            )
        if risk_reason:
            target_fraction = 0.0

        target_shares = previous_target_shares
        event_triggered = bool(risk_reason) or abs(target_fraction - previous_fraction) > 1e-9
        if event_triggered and open_t1 > 0:
            equity_t = cash + (position * close_t)
            target_notional = abs(target_fraction) * max(equity_t, 0.0)
            target_shares = int(math.floor(target_notional / open_t1))
            if target_fraction < 0:
                target_shares = -target_shares

        if position == 0 and target_shares != 0 and (i + 1 - last_exit_exec_i) < cooldown_bars:
            target_shares = 0

        delta = target_shares - position
        if delta != 0 and (open_t1 <= 0.0 or close_t1 <= 0.0 or volume_t1 <= 0.0):
            delta = 0
            target_shares = position
            target_fraction = previous_fraction

        if delta != 0 and abs(target_shares) > abs(position):
            if not _volume_gate_allows(
                enabled=bool(volume_gate.get("enabled", False)),
                kind=str(volume_gate.get("kind", "min_ratio_adv")),
                min_volume_abs=_safe_float(volume_gate.get("min_volume_abs"), 0.0),
                min_volume_ratio_adv=_safe_float(volume_gate.get("min_volume_ratio_adv"), 0.0),
                volume_value=volume_t1,
                adv_value=adv_t1,
            ):
                delta = 0
                target_shares = position

        if delta > 0:
            rate = (
                (cost_model.brokerage_bps + cost_model.comm_bourse_bps + cost_model.reg_liv_bps) / 10000.0
            ) * (1.0 + cost_model.tva_rate)
            rate += cost_model.slippage_bps / 10000.0
            affordable_qty = int(math.floor(cash / (open_t1 * max(1.0 + rate, 1e-9)))) if open_t1 > 0 else 0
            if position < 0:
                # Always allow enough buying power to flatten an existing short, but
                # do not let a short-cover bypass cash checks for any extra long build.
                affordable_qty = max(affordable_qty, min(delta, abs(position)))
            delta = max(min(delta, affordable_qty), 0)
            target_shares = position + delta

        if delta != 0:
            qty_abs = abs(int(delta))
            notional = float(qty_abs * open_t1)
            cost, _ = cost_model.estimate_cost(notional)
            side = "BUY" if delta > 0 else "SELL"
            previous_position = position
            previous_cmp = avg_entry_price
            realized_pnl = 0.0

            if delta > 0:
                if position >= 0:
                    old_basis = abs(position) * avg_entry_price
                    add_basis = qty_abs * open_t1 + cost
                    new_position = position + qty_abs
                    avg_entry_price = (old_basis + add_basis) / float(new_position) if new_position != 0 else 0.0
                    position = new_position
                else:
                    close_qty = min(qty_abs, abs(position))
                    remaining_open = qty_abs - close_qty
                    buy_cost_part = cost * (close_qty / qty_abs) if qty_abs > 0 else 0.0
                    realized_pnl += close_qty * (avg_entry_price - (open_t1 + (buy_cost_part / max(close_qty, 1))))
                    position += close_qty
                    if position == 0:
                        avg_entry_price = 0.0
                    if remaining_open > 0:
                        open_cost_part = cost - buy_cost_part
                        position += remaining_open
                        avg_entry_price = ((remaining_open * open_t1) + open_cost_part) / float(remaining_open)
                cash -= (notional + cost)
            else:
                if position > 0:
                    sell_qty = min(qty_abs, position)
                    sell_cost_part = cost * (sell_qty / qty_abs) if qty_abs > 0 else 0.0
                    realized_pnl += sell_qty * ((open_t1 - (sell_cost_part / max(sell_qty, 1))) - avg_entry_price)
                    position -= sell_qty
                    if position == 0:
                        avg_entry_price = 0.0
                    remaining_open = qty_abs - sell_qty
                    if remaining_open > 0:
                        open_cost_part = cost - sell_cost_part
                        position -= remaining_open
                        avg_entry_price = ((remaining_open * open_t1) - open_cost_part) / float(remaining_open)
                else:
                    old_basis = abs(position) * avg_entry_price
                    add_basis = qty_abs * open_t1 - cost
                    new_position = position - qty_abs
                    avg_entry_price = (old_basis + add_basis) / float(abs(new_position)) if new_position != 0 else 0.0
                    position = new_position
                cash += (notional - cost)

            if previous_position == 0 and position != 0:
                holding_bars = 0
            if position == 0:
                stop_loss = None
                take_profit = None
                holding_bars = 0
                last_exit_exec_i = i + 1
            else:
                if previous_position == 0 or np.sign(previous_position) != np.sign(position) or abs(position) > abs(previous_position):
                    stop_loss, take_profit = _build_barriers(
                        position=position,
                        avg_entry_price=avg_entry_price,
                        atr=max(atr_t, 0.0),
                        risk=risk,
                    )

            latent_pnl = 0.0
            if position > 0:
                latent_pnl = float(position * (close_t1 - avg_entry_price))
            elif position < 0:
                latent_pnl = float(abs(position) * (avg_entry_price - close_t1))

            fill = _StockFill(
                timestamp=t1,
                symbol=symbol,
                qty=int(delta),
                side=side,
                price=float(open_t1),
                notional=notional,
                cost=float(cost),
                signal_score=float(score_t),
                realized_pnl=float(realized_pnl),
                latent_pnl=float(latent_pnl),
                cmp=float(avg_entry_price if position != 0 else previous_cmp),
                close_mark=float(close_t1),
                available_quantity=float(abs(position)),
                position_value_cost=float(abs(position) * avg_entry_price),
                reason=_trade_reason(
                    risk_reason=risk_reason,
                    rule_reason=rule_reason,
                    target_fraction=target_fraction,
                    previous_fraction=previous_fraction,
                ),
                entry_rule=entry_rule_ref or "",
                exit_rule=(
                    "SL" if risk_reason == "stop_loss"
                    else "TP" if risk_reason == "take_profit"
                    else "TS" if risk_reason == "time_stop"
                    else (exit_rule_ref or "")
                ),
                trigger_display=_rule_trigger_display(
                    side=side,
                    snapshot=snapshot,
                    risk_reason=risk_reason,
                    rule=entry_rule_match if side == "BUY" else exit_rule_match,
                    close_t=close_t,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    holding_bars=holding_bars,
                    max_holding_bars=_safe_int(risk.get("max_holding_bars"), 0),
                ),
                trend_score=snapshot.get("trend_score", 0.0),
                momentum_score=snapshot.get("momentum_score", 0.0),
                oscillation_score=snapshot.get("oscillation_score", 0.0),
                volume_score=snapshot.get("volume_score", 0.0),
                consensus_score=snapshot.get("consensus_score", score_t),
            )
            fills.append(
                {
                    "timestamp": fill.timestamp,
                    "symbol": fill.symbol,
                    "qty": fill.qty,
                    "side": fill.side,
                    "price": fill.price,
                    "notional": fill.notional,
                    "cost": fill.cost,
                    "signal_score": fill.signal_score,
                    "reason": fill.reason,
                    "entry_rule": fill.entry_rule,
                    "exit_rule": fill.exit_rule,
                    "trigger_display": fill.trigger_display,
                    "trend_score": fill.trend_score,
                    "momentum_score": fill.momentum_score,
                    "oscillation_score": fill.oscillation_score,
                    "volume_score": fill.volume_score,
                    "consensus_score": fill.consensus_score,
                }
            )
            ledger_rows.append(
                {
                    "timestamp": fill.timestamp.isoformat(),
                    "symbol": fill.symbol,
                    "side": fill.side,
                    "prix_execution_open_jour": round(fill.price, 4),
                    "quantite": abs(fill.qty),
                    "cmp": round(fill.cmp, 4),
                    "pnl_realise": round(fill.realized_pnl, 4),
                    "pnl_latent": round(fill.latent_pnl, 4),
                    "close_du_jour": round(fill.close_mark, 4),
                    "available_quantity": round(fill.available_quantity, 4),
                    "position_value_cost": round(fill.position_value_cost, 4),
                    "notional": round(fill.notional, 4),
                    "cost": round(fill.cost, 4),
                    "signal_score": round(fill.signal_score, 2),
                    "reason": fill.reason,
                    "entry_rule": fill.entry_rule,
                    "exit_rule": fill.exit_rule,
                    "trigger_display": fill.trigger_display,
                    "trend_score": round(fill.trend_score, 2),
                    "momentum_score": round(fill.momentum_score, 2),
                    "oscillation_score": round(fill.oscillation_score, 2),
                    "volume_score": round(fill.volume_score, 2),
                    "consensus_score": round(fill.consensus_score, 2),
                }
            )

        previous_fraction = target_fraction
        previous_target_shares = position if delta != 0 else target_shares
        equity_t1 = float(cash + (position * close_t1))
        equity_points.append((t1, equity_t1))
        position_points.append((t1, int(position)))
        if position != 0:
            holding_bars += 1

    equity_series = pd.Series(
        [value for _, value in equity_points],
        index=pd.DatetimeIndex([ts for ts, _ in equity_points]),
        dtype="float64",
    )
    position_series = pd.Series(
        [value for _, value in position_points],
        index=pd.DatetimeIndex([ts for ts, _ in position_points]),
        dtype="float64",
    )
    fills_df = pd.DataFrame(fills)
    if not fills_df.empty:
        fills_df["timestamp"] = pd.to_datetime(fills_df["timestamp"])

    analyzer = ResultsAnalyzer()
    benchmark_close = window["Close"].astype(float)
    buy_hold_cum = benchmark_close / float(benchmark_close.iloc[0]) - 1.0

    if fills_df.empty:
        trade_perf = analyzer._trade_performance_summary(pd.DataFrame())
        summary_metrics = {
            "net_pnl": float(equity_series.iloc[-1] - allocated_capital),
            "total_return": float((equity_series.iloc[-1] / allocated_capital) - 1.0) if allocated_capital > 0 else 0.0,
            "fees": 0.0,
            "n_fills": 0,
        }
    else:
        round_trip_ledger = analyzer._trade_ledger_from_fills(fills_df)
        trade_perf = analyzer._trade_performance_summary(round_trip_ledger)
        dd = analyzer._drawdown_from_equity(equity_series)
        rets = equity_series.pct_change().fillna(0.0)
        headline = analyzer._headline_metrics(rets, dd, None)
        perf_map = {str(row["metric"]): row["value"] for row in _frame_to_metric_records(trade_perf)}
        summary_metrics = {
            "net_pnl": float(equity_series.iloc[-1] - allocated_capital),
            "total_return": float(headline.get("Total return", 0.0)),
            "cagr": float(headline.get("CAGR", 0.0)),
            "sharpe": float(headline.get("Sharpe", 0.0)),
            "max_drawdown": float(headline.get("Max drawdown", 0.0)),
            "win_rate": _safe_float(perf_map.get("Win Rate"), 0.0),
            "n_trades": _safe_int(perf_map.get("Trades"), 0),
            "fees": float(fills_df["cost"].sum()),
            "n_fills": int(len(fills_df)),
        }

    return _StockSimulation(
        symbol=symbol,
        equity=equity_series,
        positions=position_series,
        fills=fills_df,
        per_fill_ledger=ledger_rows,
        raw_scores=scores,
        summary_metrics=summary_metrics,
        trade_performance=_frame_to_metric_records(trade_perf),
        buy_hold_cum=buy_hold_cum,
        bars_window=window,
    )


def run_strategy_plan_backtest(
    *,
    strategy_id: str,
    strategy_name: str,
    side_policy: str,
    horizon: str,
    timeframe: str,
    config_json: dict[str, Any],
    bars_by_symbol: dict[str, pd.DataFrame],
    start_date: str,
    end_date: str,
    cost_model_raw: dict[str, Any],
    volume_gate: dict[str, Any],
    cooldown_bars: int,
    family_history_mode: FamilyHistoryMode = "static_current_reps",
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    def _raise_if_canceled() -> None:
        if cancel_check is not None and cancel_check():
            raise BacktestCanceled("Strategy backtest canceled by user.")

    config = _normalize_strategy_config(config_json or {})
    bars_by_symbol = {
        symbol: drop_incomplete_ohlcv_rows(frame)
        for symbol, frame in (bars_by_symbol or {}).items()
    }
    basket = [
        symbol
        for symbol in config["universe"]["basket"]
        if symbol in bars_by_symbol and not bars_by_symbol[symbol].empty
    ]
    if not basket:
        raise ValueError("Selected strategy has no basket symbols with market data.")

    cost_model = _build_cost_model(cost_model_raw)
    signal_cost_bps = _signal_cost_bps(cost_model)

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    if start_ts > end_ts:
        raise ValueError("start_date must be before or equal to end_date.")

    calibration = _derive_calibrated_bet_sizing(
        basket=basket,
        bars_by_symbol=bars_by_symbol,
        start_ts=start_ts,
        horizon=horizon,
        timeframe=timeframe,
        enabled_families=config["signal"]["enabled_families"],
        side_policy=side_policy,
        cost_model=cost_model,
        risk=config["risk"],
        signal_cost_bps=signal_cost_bps,
        cooldown_bars=cooldown_bars,
        family_history_mode=family_history_mode,
        bet_sizing_config=config["bet_sizing"],
        per_stock=config.get("per_stock"),
        cancel_check=cancel_check,
    )
    exposure_ladder = list(calibration.get("ladder") or _default_fallback_ladder())

    price_history = {
        symbol: bars_by_symbol[symbol]["Close"].astype(float)
        for symbol in basket
        if "Close" in bars_by_symbol[symbol].columns
    }
    allocation = compute_strategy_allocation(
        symbols=basket,
        total_capital_mad=config["capital"]["total_capital_mad"],
        price_history=price_history,
        manual_overrides_by_symbol=config["allocation"]["manual_overrides_by_symbol"],
        lookback_bars=config["allocation"]["hrp_lookback_bars"],
    )
    allocation_rows = allocation["rows"]
    allocation_by_symbol = {row["symbol"]: float(row["capital_mad"]) for row in allocation_rows}
    weight_by_symbol = {
        row["symbol"]: (float(row["capital_mad"]) / max(config["capital"]["total_capital_mad"], 1.0))
        for row in allocation_rows
    }

    stocks: list[_StockSimulation] = []
    skipped_symbols: list[str] = []
    for symbol in basket:
        _raise_if_canceled()
        bars = bars_by_symbol[symbol].copy().sort_index()
        bars.index = pd.to_datetime(bars.index)
        aligned_start_ts = _align_timestamp_to_index(start_ts, bars.index)
        aligned_end_ts = _align_timestamp_to_index(end_ts, bars.index)
        bars = bars.loc[(bars.index >= aligned_start_ts) & (bars.index <= aligned_end_ts)]
        if len(bars) < 2:
            skipped_symbols.append(symbol)
            continue

        full_bars = bars_by_symbol[symbol].copy().sort_index()
        full_bars.index = pd.to_datetime(full_bars.index)
        full_bars = full_bars.loc[full_bars.index <= _align_timestamp_to_index(end_ts, full_bars.index)]
        stock_overrides = config.get("per_stock", {}).get(symbol, {}) if isinstance(config.get("per_stock"), dict) else {}
        stock_signal = stock_overrides.get("signal") if isinstance(stock_overrides.get("signal"), dict) else {}
        stock_signal_construction = stock_overrides.get("signal_construction") if isinstance(stock_overrides.get("signal_construction"), dict) else {}
        stock_risk = stock_overrides.get("risk") if isinstance(stock_overrides.get("risk"), dict) else {}
        score_frame = _compute_score_frame(
            symbol=symbol,
            ohlcv=full_bars,
            stock_config={"signal_construction": stock_signal_construction} if stock_signal_construction else None,
            enabled_families=list(stock_signal.get("enabled_families") or config["signal"]["enabled_families"]),
            horizon=horizon,
            timeframe=timeframe,
            signal_cost_bps=signal_cost_bps,
            cooldown_bars=cooldown_bars,
            family_history_mode=family_history_mode,
        )
        scores = score_frame["consensus_score"]

        stock_sim = _simulate_stock(
            symbol=symbol,
            bars=bars,
            score_series=scores,
            score_frame=score_frame,
            allocated_capital=allocation_by_symbol.get(symbol, 0.0),
            side_policy=side_policy,
            exposure_ladder=exposure_ladder,
            entry_rules=stock_overrides.get("entry_rules") if isinstance(stock_overrides.get("entry_rules"), list) else [],
            exit_rules=stock_overrides.get("exit_rules") if isinstance(stock_overrides.get("exit_rules"), list) else [],
            risk=stock_risk if stock_risk else config["risk"],
            cost_model=cost_model,
            cooldown_bars=max(int(cooldown_bars), 0),
            volume_gate=volume_gate,
        )
        stocks.append(stock_sim)

    if not stocks:
        raise ValueError("No selected symbols have enough bars in the requested date range.")

    analyzer = ResultsAnalyzer()
    all_index = pd.DatetimeIndex(sorted(set().union(*[sim.equity.index for sim in stocks])))

    equity_frame = pd.DataFrame(index=all_index)
    position_frame = pd.DataFrame(index=all_index)
    fill_frames: list[pd.DataFrame] = []
    benchmark_returns_frame = pd.DataFrame(index=all_index)

    for sim in stocks:
        equity_frame[sim.symbol] = sim.equity.reindex(all_index).ffill().bfill()
        position_frame[sim.symbol] = sim.positions.reindex(all_index).ffill().fillna(0.0)
        if not sim.fills.empty:
            fill_frames.append(sim.fills.copy())
        bench = sim.buy_hold_cum.reindex(all_index).ffill().fillna(0.0)
        bench_equity = 1.0 + bench
        benchmark_returns_frame[sim.symbol] = bench_equity.pct_change().fillna(0.0)

    portfolio_equity = equity_frame.sum(axis=1).astype(float)
    portfolio_returns = portfolio_equity.pct_change().fillna(0.0)
    portfolio_positions = position_frame.fillna(0.0)
    portfolio_fills = pd.concat(fill_frames, ignore_index=True) if fill_frames else pd.DataFrame(
        columns=["timestamp", "symbol", "qty", "side", "price", "notional", "cost", "signal_score"]
    )
    if not portfolio_fills.empty:
        portfolio_fills["timestamp"] = pd.to_datetime(portfolio_fills["timestamp"])
        portfolio_fills = portfolio_fills.sort_values(["timestamp", "symbol"]).reset_index(drop=True)

    trade_ledger = analyzer._trade_ledger_from_fills(portfolio_fills)
    trade_performance = analyzer._trade_performance_summary(trade_ledger)
    drawdown = analyzer._drawdown_from_equity(portfolio_equity)
    monthly = analyzer._monthly_return_matrix(portfolio_returns)
    yearly = analyzer._yearly_returns(portfolio_returns)
    headline = analyzer._headline_metrics(portfolio_returns, drawdown, None)
    perf_records = _frame_to_metric_records(trade_performance)
    perf_map = {str(row["metric"]): row["value"] for row in perf_records}

    benchmark_weights = pd.Series({symbol: weight_by_symbol.get(symbol, 0.0) for symbol in benchmark_returns_frame.columns}, dtype="float64")
    if benchmark_weights.sum() > 0:
        benchmark_weights = benchmark_weights / benchmark_weights.sum()
    benchmark_returns = benchmark_returns_frame.mul(benchmark_weights, axis=1).sum(axis=1).fillna(0.0)
    benchmark_cum = (1.0 + benchmark_returns).cumprod() - 1.0

    general_metrics = {
        "net_pnl": float(portfolio_equity.iloc[-1] - config["capital"]["total_capital_mad"]),
        "total_return": float(headline.get("Total return", 0.0)),
        "cagr": float(headline.get("CAGR", 0.0)),
        "sharpe": float(headline.get("Sharpe", 0.0)),
        "max_drawdown": float(headline.get("Max drawdown", 0.0)),
        "win_rate": _safe_float(perf_map.get("Win Rate"), 0.0),
        "number_of_trades": _safe_int(perf_map.get("Trades"), 0),
        "total_fees": float(portfolio_fills["cost"].sum()) if not portfolio_fills.empty else 0.0,
    }

    general_results = {
        "metrics": general_metrics,
        "trade_performance": perf_records,
        "calibration": calibration,
        "plots": {
            "cumreturn_vs_benchmark": _normalize_plotly_payload(
                make_cumreturn_vs_benchmark_plot(
                    (1.0 + portfolio_returns).cumprod() - 1.0,
                    benchmark_cum,
                ).to_plotly_json(),
            ),
            "drawdown": _normalize_plotly_payload(
                make_drawdown_plot(drawdown).to_plotly_json(),
            ),
            "monthly_heatmap": _normalize_plotly_payload(
                make_monthly_heatmap_plot(monthly).to_plotly_json(),
            ) if not monthly.empty else {"data": [], "layout": {}},
            "yearly_barplot": _normalize_plotly_payload(
                make_yearly_return_bar_plot(yearly).to_plotly_json(),
            ) if not yearly.empty else {"data": [], "layout": {}},
        },
    }

    stock_payloads: list[dict[str, Any]] = []
    for sim in stocks:
        allocation_row = next((row for row in allocation_rows if row["symbol"] == sim.symbol), None)
        stock_cum = sim.equity / float(sim.equity.iloc[0]) - 1.0 if len(sim.equity) > 0 and sim.equity.iloc[0] != 0 else sim.equity * 0.0
        stock_payloads.append(
            {
                "symbol": sim.symbol,
                "allocation": allocation_row or {},
                "summary_metrics": sim.summary_metrics,
                "price_chart": _make_price_trade_figure(
                    bars_window=sim.bars_window,
                    ledger_rows=sim.per_fill_ledger,
                    symbol=sim.symbol,
                ),
                "cumreturn_vs_benchmark": _normalize_plotly_payload(
                    make_cumreturn_vs_benchmark_plot(stock_cum, sim.buy_hold_cum).to_plotly_json(),
                ),
                "trade_ledger": sim.per_fill_ledger,
                "trade_performance": sim.trade_performance,
            }
        )

    return {
        "strategy": {
            "id": strategy_id,
            "name": strategy_name,
            "side_policy": side_policy,
            "horizon": horizon,
            "timeframe": timeframe,
            "basket": basket,
            "allocation_rows": allocation_rows,
            "capital_mad": config["capital"]["total_capital_mad"],
            "enabled_families": config["signal"]["enabled_families"],
            "signal": config["signal"],
            "bet_sizing": {
                **config["bet_sizing"],
                "active_ladder": exposure_ladder,
            },
            "risk": config["risk"],
        },
        "assumptions": {
            "requested_start_date": start_ts.date().isoformat(),
            "requested_end_date": end_ts.date().isoformat(),
            "resolved_start_date": portfolio_equity.index.min().date().isoformat(),
            "resolved_end_date": portfolio_equity.index.max().date().isoformat(),
            "cost_model": {
                "brokerage_bps": cost_model.brokerage_bps,
                "comm_bourse_bps": cost_model.comm_bourse_bps,
                "reg_liv_bps": cost_model.reg_liv_bps,
                "slippage_bps": cost_model.slippage_bps,
                "tva_rate": cost_model.tva_rate,
            },
            "volume_gate": {
                "enabled": bool(volume_gate.get("enabled", False)),
                "kind": str(volume_gate.get("kind", "min_ratio_adv")),
                "min_volume_abs": _safe_float(volume_gate.get("min_volume_abs"), 0.0),
                "min_volume_ratio_adv": _safe_float(volume_gate.get("min_volume_ratio_adv"), 0.0),
                "adv_window": _safe_int(volume_gate.get("adv_window"), 20),
            },
            "cooldown_bars": int(cooldown_bars),
            "family_history_mode": str(family_history_mode),
            "benchmark": "initial allocated basket buy-and-hold",
            "skipped_symbols": skipped_symbols,
            "bet_sizing_mode": str(config["bet_sizing"].get("mode", "auto_calibrated")),
            "calibration_status": str(calibration.get("status", "fallback")),
        },
        "general_results": general_results,
        "stocks": stock_payloads,
    }
