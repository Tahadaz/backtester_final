from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import inspect
import math
from typing import Any

import numpy as np
import pandas as pd

from core.quant_core.data import drop_incomplete_ohlcv_rows
from core.quant_core.signal_engine.ensemble import (
    FamilyHistoryMode,
    compute_family_score_timeseries,
    family_signal_is_available,
    run_family_ensemble_full,
)
from core.quant_core.signal_engine.domain import ALL_FAMILIES, VariantDef
from core.quant_core.signal_engine.indicator_series import (
    compute_ad_series,
    compute_adx_series,
    compute_atr_series,
    compute_cci_series,
    compute_cmf_series,
    compute_ema_cross_series,
    compute_ema_series,
    compute_force_index_series,
    compute_ichimoku_series,
    compute_macd_series,
    compute_mfi_series,
    compute_obv_deviation,
    compute_psar_series,
    compute_roc_series,
    compute_rsi_series,
    compute_sma_series,
    compute_stochastic_series,
    compute_trix_series,
    compute_tsi_series,
    compute_uo_series,
    compute_vwap_series,
)


FAMILY_IDS = ALL_FAMILIES
BASE_SCORE_KEYS = {
    "sma": "trend_score",
    "ema": "ema_score",
    "ema_cross": "ema_cross_score",
    "ichimoku": "ichimoku_score",
    "psar": "psar_score",
    "macd": "momentum_score",
    "roc": "roc_score",
    "trix": "trix_score",
    "adx": "adx_score",
    "tsi": "tsi_score",
    "rsi": "oscillation_score",
    "stochastic": "stochastic_score",
    "cci": "cci_score",
    "mfi": "mfi_score",
    "uo": "uo_score",
    "obv": "volume_score",
    "cmf": "cmf_score",
    "ad": "ad_score",
    "vwap": "vwap_score",
    "fi": "fi_score",
}
BASE_SCORE_LABELS = {
    "sma": "Trend Score",
    "ema": "EMA Score",
    "ema_cross": "EMA Cross Score",
    "ichimoku": "Ichimoku Score",
    "psar": "PSAR Score",
    "macd": "Momentum Score",
    "roc": "ROC Score",
    "trix": "TRIX Score",
    "adx": "ADX Score",
    "tsi": "TSI Score",
    "rsi": "Oscillation Score",
    "stochastic": "Stochastic Score",
    "cci": "CCI Score",
    "mfi": "MFI Score",
    "uo": "Ultimate Oscillator Score",
    "obv": "Volume Score",
    "cmf": "CMF Score",
    "ad": "A/D Line Score",
    "vwap": "VWAP Score",
    "fi": "Force Index Score",
}
DEFAULT_SOURCE_MODE = "indicator_rows"
DEFAULT_ROW_PARAMS = {
    "sma": {"window": 21},
    "ema": {"window": 21},
    "ema_cross": {"fast": 12, "slow": 26},
    "ichimoku": {"tenkan": 9, "kijun": 26, "senkou_b": 52},
    "psar": {"af_step": 0.02, "af_max": 0.2},
    "rsi": {"period": 21},
    "macd": {"fast": 12, "slow": 26, "signal": 9},
    "roc": {"period": 60},
    "trix": {"period": 15},
    "adx": {"period": 21, "adx_threshold": 25},
    "tsi": {"long_period": 25, "short_period": 13},
    "stochastic": {"k_period": 14, "d_period": 3},
    "cci": {"period": 22},
    "mfi": {"period": 14, "oversold": 20, "overbought": 80},
    "uo": {"period_1": 7, "period_2": 14, "period_3": 28},
    "obv": {"ema_period": 21},
    "cmf": {"period": 22},
    "ad": {"ema_period": 21},
    "vwap": {"period": 22, "threshold_pct": 1},
    "fi": {"period": 21},
}
DEFAULT_FAMILY_ENSEMBLE_LOOKBACK = {
    "sma": 400,
    "ema": 400,
    "ema_cross": 400,
    "ichimoku": 400,
    "psar": 100,
    "rsi": 41,
    "macd": 70,
    "roc": 80,
    "trix": 60,
    "adx": 70,
    "tsi": 70,
    "stochastic": 40,
    "cci": 60,
    "mfi": 40,
    "uo": 50,
    "obv": 400,
    "cmf": 60,
    "ad": 400,
    "vwap": 60,
    "fi": 60,
}
INDICATOR_ARCHETYPES = {
    "sma": "price_vs_sma",
    "ema": "price_vs_ema",
    "ema_cross": "ema_cross",
    "ichimoku": "ichi_cloud",
    "psar": "psar_trend",
    "macd": "macd_cross",
    "roc": "roc_zero",
    "trix": "trix_zero",
    "adx": "adx_trend",
    "tsi": "tsi_zero",
    "rsi": "rsi_level",
    "stochastic": "stoch_level",
    "cci": "cci_level",
    "mfi": "mfi_level",
    "uo": "uo_level",
    "obv": "obv_trend",
    "cmf": "cmf_flow",
    "ad": "ad_trend",
    "vwap": "vwap_dev",
    "fi": "fi_trend",
}
LEGACY_RAW_SCORE_CONTRACT_VERSION = "legacy_raw_v1"
BOUNDED_SCORE_CONTRACT_VERSION = "bounded_100_v2"
DEFAULT_SCORE_CONTRACT_VERSION = BOUNDED_SCORE_CONTRACT_VERSION
_MAD_SCALE = 0.6745
_MAD_EPSILON = 1e-9


@dataclass(frozen=True)
class ScoreSourceSpec:
    family_id: str
    score_key: str
    label: str
    source_kind: str
    params: dict[str, Any]
    row_id: str | None = None


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if np.isfinite(out) else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _param_value(value: Any, default: float | int) -> float:
    if isinstance(value, dict):
        return _safe_float(value.get("value"), float(default))
    return _safe_float(value, float(default))


def _param_mode(value: Any) -> str:
    if not _is_record(value):
        return "manual"
    mode = str(value.get("mode") or "manual").strip().lower()
    return mode if mode in {"manual", "wfo"} else "manual"


def _materialize_param_value(value: Any, *, boundary: str = "current") -> Any:
    if not _is_record(value):
        return value
    mode = _param_mode(value)
    if boundary == "start" and mode == "wfo":
        return value.get("scan_min", value.get("value"))
    if boundary == "end" and mode == "wfo":
        return value.get("scan_max", value.get("value"))
    return value.get("value")


def _wfo_param_upper_bound(value: Any, default: int) -> int:
    if not _is_record(value):
        return max(_safe_int(value, default), 1)
    if _param_mode(value) == "wfo":
        return max(_safe_int(value.get("scan_max"), _safe_int(value.get("value"), default)), 1)
    return max(_safe_int(value.get("value"), default), 1)


def _family_config(stock_config: dict[str, Any], family_id: str) -> dict[str, Any]:
    signal_construction = stock_config.get("signal_construction")
    if not _is_record(signal_construction):
        return {}
    families = signal_construction.get("families")
    if not _is_record(families):
        return {}
    family = families.get(family_id)
    return family if _is_record(family) else {}


def _default_row_params(family_id: str) -> dict[str, Any]:
    return {key: {"mode": "manual", "value": value} for key, value in DEFAULT_ROW_PARAMS[family_id].items()}


def stock_score_contract_version(stock_config: dict[str, Any]) -> str:
    value = str(stock_config.get("score_contract_version") or "").strip()
    if value == BOUNDED_SCORE_CONTRACT_VERSION:
        return BOUNDED_SCORE_CONTRACT_VERSION
    return LEGACY_RAW_SCORE_CONTRACT_VERSION


def default_family_signal_config(*, family_id: str, enabled: bool = True) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "source_mode": DEFAULT_SOURCE_MODE,
        "rows": [
            {
                "id": f"{family_id}_row_1",
                "enabled": True,
                "score_key": BASE_SCORE_KEYS[family_id],
                "label": BASE_SCORE_LABELS[family_id],
                "params": _default_row_params(family_id),
            }
        ],
    }


def build_stock_config_from_enabled_families(enabled_families: list[str] | tuple[str, ...]) -> dict[str, Any]:
    enabled = {str(item).strip().lower() for item in list(enabled_families or []) if str(item).strip()}
    if not enabled:
        enabled = {"sma"}
    families = {
        family_id: {
            "enabled": family_id in enabled,
            "source_mode": "family_ensemble",
            "rows": [],
        }
        for family_id in FAMILY_IDS
    }
    return {
        "signal_construction": {
            "families": families,
        }
    }


def family_source_mode(stock_config: dict[str, Any], family_id: str) -> str:
    family = _family_config(stock_config, family_id)
    value = str(family.get("source_mode") or DEFAULT_SOURCE_MODE).strip().lower()
    return value if value in {"family_ensemble", "indicator_rows"} else DEFAULT_SOURCE_MODE


def iter_score_sources(stock_config: dict[str, Any]) -> list[ScoreSourceSpec]:
    out: list[ScoreSourceSpec] = []
    for family_id in FAMILY_IDS:
        family = _family_config(stock_config, family_id)
        if not family or not bool(family.get("enabled")):
            continue
        source_mode = family_source_mode(stock_config, family_id)
        if source_mode == "family_ensemble":
            out.append(
                ScoreSourceSpec(
                    family_id=family_id,
                    score_key=BASE_SCORE_KEYS[family_id],
                    label=BASE_SCORE_LABELS[family_id],
                    source_kind="family_ensemble",
                    params={},
                    row_id=None,
                )
            )
            continue
        rows = [item for item in list(family.get("rows") or []) if _is_record(item) and bool(item.get("enabled", True))]
        for index, row in enumerate(rows):
            score_key = str(row.get("score_key") or "").strip().lower() or (
                BASE_SCORE_KEYS[family_id] if index == 0 else f"{BASE_SCORE_KEYS[family_id]}_{index + 1}"
            )
            label = str(row.get("label") or "").strip() or (
                BASE_SCORE_LABELS[family_id] if index == 0 else f"{BASE_SCORE_LABELS[family_id]} {index + 1}"
            )
            params = row.get("params") if _is_record(row.get("params")) else {}
            out.append(
                ScoreSourceSpec(
                    family_id=family_id,
                    score_key=score_key,
                    label=label,
                    source_kind="indicator_row",
                    params=params,
                    row_id=str(row.get("id") or f"{family_id}_row_{index + 1}"),
                )
            )
    return out


def score_variable_catalog(stock_config: dict[str, Any]) -> list[dict[str, str]]:
    items = [
        {
            "value": source.score_key,
            "label": source.label,
            "family": source.family_id,
            "source_kind": source.source_kind,
        }
        for source in iter_score_sources(stock_config)
    ]
    items.append(
        {
            "value": "consensus_score",
            "label": "Consensus Score",
            "family": "aggregate",
            "source_kind": "consensus",
        }
    )
    return items


def score_variable_keys(stock_config: dict[str, Any]) -> set[str]:
    return {item["value"] for item in score_variable_catalog(stock_config)}


def source_has_wfo_params(source: ScoreSourceSpec) -> bool:
    return any(_param_mode(value) == "wfo" for value in source.params.values())


def source_wfo_param_names(source: ScoreSourceSpec) -> list[str]:
    return [name for name, value in source.params.items() if _param_mode(value) == "wfo"]


def source_params_bundle(source: ScoreSourceSpec, *, boundary: str = "current") -> dict[str, Any]:
    if boundary not in {"current", "start", "end"}:
        raise ValueError(f"Unsupported parameter boundary: {boundary}")
    return {
        name: _materialize_param_value(value, boundary=boundary)
        for name, value in source.params.items()
    }


def _param_number(params: dict[str, Any], names: str | tuple[str, ...], default: float | int) -> float:
    keys = (names,) if isinstance(names, str) else names
    for key in keys:
        if key in params:
            return _param_value(params.get(key), default)
    return float(default)


def _int_param(params: dict[str, Any], names: str | tuple[str, ...], default: int, *, minimum: int = 1) -> int:
    return max(_safe_int(_param_number(params, names, default), default), minimum)


def _float_param(params: dict[str, Any], name: str, default: float, *, minimum: float | None = None) -> float:
    value = _safe_float(_param_number(params, name, default), default)
    if minimum is not None:
        return max(value, minimum)
    return value


def source_plain_params(source: ScoreSourceSpec, *, boundary: str = "current") -> dict[str, Any]:
    defaults = DEFAULT_ROW_PARAMS.get(source.family_id, {})
    raw = source_params_bundle(source, boundary=boundary)
    out = {**defaults, **raw}
    if source.family_id == "sma" and "period" in out and "window" not in out:
        out["window"] = out["period"]
    return out


def score_source_variant(source: ScoreSourceSpec, *, params_override: dict[str, Any] | None = None) -> VariantDef:
    raw_params = params_override if isinstance(params_override, dict) else source_plain_params(source)
    params = {**DEFAULT_ROW_PARAMS.get(source.family_id, {}), **raw_params}
    if source.family_id == "sma" and "period" in params and "window" not in params:
        params["window"] = params["period"]
    return VariantDef(
        variant_id=f"strategy_{source.score_key}",
        family=source.family_id,
        archetype=INDICATOR_ARCHETYPES[source.family_id],
        params=params,
        description=source.label,
    )


def _safe_ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    values = np.full(len(numerator), np.nan, dtype="float64")
    mask = np.isfinite(numerator) & np.isfinite(denominator) & (denominator != 0.0)
    values[mask] = numerator[mask] / denominator[mask]
    return values


def _supports_keyword(func: Any, name: str) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return True
    return name in signature.parameters or any(
        param.kind == inspect.Parameter.VAR_KEYWORD
        for param in signature.parameters.values()
    )


def _wfo_param_upper_bound_any(params: dict[str, Any], names: str | tuple[str, ...], default: int) -> int:
    keys = (names,) if isinstance(names, str) else names
    for key in keys:
        if key in params:
            return _wfo_param_upper_bound(params.get(key), default)
    return _wfo_param_upper_bound(None, default)


def _row_max_lookback(family_id: str, params: dict[str, Any]) -> int:
    if family_id in {"sma", "ema"}:
        return _wfo_param_upper_bound_any(params, ("window", "period"), 21)
    if family_id == "ema_cross":
        return _wfo_param_upper_bound_any(params, "slow", 26)
    if family_id == "ichimoku":
        return _wfo_param_upper_bound_any(params, "senkou_b", 52)
    if family_id == "psar":
        return 2
    if family_id == "macd":
        slow = _wfo_param_upper_bound_any(params, "slow", 26)
        signal = _wfo_param_upper_bound_any(params, "signal", 9)
        return slow + signal
    if family_id in {"roc", "trix", "rsi", "cci", "mfi", "cmf", "vwap", "fi"}:
        return _wfo_param_upper_bound_any(params, "period", int(DEFAULT_ROW_PARAMS[family_id].get("period", 21)))
    if family_id == "adx":
        return 2 * _wfo_param_upper_bound_any(params, "period", 21)
    if family_id == "tsi":
        return _wfo_param_upper_bound_any(params, "long_period", 25) + _wfo_param_upper_bound_any(params, "short_period", 13)
    if family_id == "stochastic":
        return _wfo_param_upper_bound_any(params, "k_period", 14) + _wfo_param_upper_bound_any(params, "d_period", 3)
    if family_id == "uo":
        return _wfo_param_upper_bound_any(params, "period_3", 28)
    if family_id in {"obv", "ad"}:
        return _wfo_param_upper_bound_any(params, "ema_period", 21)
    return 1


def derive_max_lookback(
    stock_config: dict[str, Any],
    *,
    horizon: str = "medium",
    strict_indicator_rows: bool = False,
) -> int:
    max_lookback = 1
    for family_id in FAMILY_IDS:
        family = _family_config(stock_config, family_id)
        if not family or not bool(family.get("enabled")):
            continue
        source_mode = family_source_mode(stock_config, family_id)
        if source_mode == "family_ensemble":
            if strict_indicator_rows:
                raise ValueError(
                    f"Strategy WFO requires explicit indicator_rows for family '{family_id}', not family_ensemble."
                )
            max_lookback = max(max_lookback, DEFAULT_FAMILY_ENSEMBLE_LOOKBACK[family_id])
            continue
        rows = [item for item in list(family.get("rows") or []) if _is_record(item) and bool(item.get("enabled", True))]
        for row in rows:
            params = row.get("params") if _is_record(row.get("params")) else {}
            max_lookback = max(max_lookback, _row_max_lookback(family_id, params))
    return max(max_lookback, 1)


def _row_score_values(
    *,
    family_id: str,
    params: dict[str, Any],
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray,
    atr_safe: np.ndarray,
) -> np.ndarray:
    if family_id == "sma":
        period = _int_param(params, ("window", "period"), 21)
        sma = compute_sma_series(close, period)
        return _safe_ratio(close - sma, atr_safe)
    if family_id == "ema":
        period = _int_param(params, ("window", "period"), 21)
        ema_values = compute_ema_series(close, period)
        return _safe_ratio(close - ema_values, atr_safe)
    if family_id == "ema_cross":
        fast = _int_param(params, "fast", 12)
        slow = max(_int_param(params, "slow", 26), fast + 1)
        fast_ema, slow_ema = compute_ema_cross_series(close, fast, slow)
        return _safe_ratio(fast_ema - slow_ema, atr_safe)
    if family_id == "ichimoku":
        tenkan = _int_param(params, "tenkan", 9)
        kijun = max(_int_param(params, "kijun", 26), tenkan + 1)
        senkou_b = max(_int_param(params, "senkou_b", 52), kijun + 1)
        ichi = compute_ichimoku_series(high, low, close, tenkan, kijun, senkou_b)
        cloud_mid = (ichi["cloud_top"] + ichi["cloud_bottom"]) / 2.0
        return _safe_ratio(close - cloud_mid, atr_safe)
    if family_id == "psar":
        af_step = _float_param(params, "af_step", 0.02, minimum=0.001)
        af_max = max(_float_param(params, "af_max", 0.2, minimum=af_step + 0.001), af_step + 0.001)
        psar = compute_psar_series(high, low, close, af_step, af_max)
        return _safe_ratio(close - psar, atr_safe)
    if family_id == "rsi":
        period = _int_param(params, "period", 21)
        return compute_rsi_series(close, period)
    if family_id == "macd":
        fast = _int_param(params, "fast", 12)
        slow = max(_int_param(params, "slow", 26), fast + 1)
        signal = _int_param(params, "signal", 9)
        histogram, _signal_line = compute_macd_series(close, fast, slow, signal)
        return _safe_ratio(histogram, atr_safe)
    if family_id == "roc":
        return compute_roc_series(close, _int_param(params, "period", 60))
    if family_id == "trix":
        return compute_trix_series(close, _int_param(params, "period", 15))
    if family_id == "adx":
        period = _int_param(params, "period", 21)
        threshold = _float_param(params, "adx_threshold", 25.0)
        plus_di, minus_di, adx = compute_adx_series(high, low, close, period)
        values = np.full(len(close), np.nan, dtype="float64")
        mask = np.isfinite(plus_di) & np.isfinite(minus_di) & np.isfinite(adx)
        values[mask] = np.where(
            adx[mask] >= threshold,
            np.where(plus_di[mask] > minus_di[mask], adx[mask], np.where(minus_di[mask] > plus_di[mask], -adx[mask], 0.0)),
            0.0,
        )
        return values
    if family_id == "tsi":
        short_period = _int_param(params, "short_period", 13)
        long_period = max(_int_param(params, "long_period", 25), short_period + 1)
        return compute_tsi_series(close, long_period, short_period)
    if family_id == "stochastic":
        k_period = _int_param(params, "k_period", 14)
        d_period = _int_param(params, "d_period", 3)
        k_values, _d_values = compute_stochastic_series(high, low, close, k_period, d_period)
        return k_values
    if family_id == "cci":
        return compute_cci_series(high, low, close, _int_param(params, "period", 22))
    if family_id == "mfi":
        return compute_mfi_series(high, low, close, volume, _int_param(params, "period", 14))
    if family_id == "uo":
        p1 = _int_param(params, "period_1", 7)
        p2 = max(_int_param(params, "period_2", 14), p1 + 1)
        p3 = max(_int_param(params, "period_3", 28), p2 + 1)
        return compute_uo_series(high, low, close, p1, p2, p3)
    if family_id == "obv":
        ema_period = _int_param(params, "ema_period", 21)
        return compute_obv_deviation(close, volume, ema_period)
    if family_id == "cmf":
        return compute_cmf_series(high, low, close, volume, _int_param(params, "period", 22))
    if family_id == "ad":
        ema_period = _int_param(params, "ema_period", 21)
        ad_values = compute_ad_series(high, low, close, volume)
        ad_ema = compute_ema_series(ad_values, ema_period)
        return _safe_ratio(ad_values - ad_ema, np.abs(ad_ema))
    if family_id == "vwap":
        period = _int_param(params, "period", 22)
        vwap = compute_vwap_series(close, volume, period)
        return 100.0 * _safe_ratio(close - vwap, vwap)
    if family_id == "fi":
        period = _int_param(params, "period", 21)
        force = compute_force_index_series(close, volume, period)
        denom = compute_ema_series(np.abs(force), period)
        return _safe_ratio(force, denom)
    return np.full(len(close), np.nan, dtype="float64")


def _normal_cdf(values: np.ndarray) -> np.ndarray:
    if len(values) == 0:
        return np.zeros(0, dtype="float64")
    vectorized_erf = np.vectorize(math.erf, otypes=[float])
    return 0.5 * (1.0 + vectorized_erf(values / math.sqrt(2.0)))


def _calibration_mask(index: pd.Index, calibration_end: pd.Timestamp | None) -> np.ndarray:
    if calibration_end is None:
        return np.ones(len(index), dtype=bool)
    timestamps = pd.to_datetime(index)
    return (timestamps <= pd.Timestamp(calibration_end)).to_numpy(dtype=bool)


def _bounded_specific_setup_values(
    raw_values: np.ndarray,
    *,
    index: pd.Index,
    score_key: str,
    family_id: str,
    row_id: str | None,
    calibration_end: pd.Timestamp | None,
) -> tuple[np.ndarray, dict[str, Any], list[str]]:
    bounded = np.zeros(len(raw_values), dtype="float64")
    finite_mask = np.isfinite(raw_values)
    reference_mask = finite_mask & _calibration_mask(index, calibration_end)
    warnings: list[str] = []
    reference_values = raw_values[reference_mask]
    calibration_end_value = (
        pd.Timestamp(index[np.flatnonzero(reference_mask)[-1]]).date().isoformat()
        if np.any(reference_mask)
        else None
    )
    calibration_start_value = (
        pd.Timestamp(index[np.flatnonzero(reference_mask)[0]]).date().isoformat()
        if np.any(reference_mask)
        else None
    )
    metadata = {
        "score_key": score_key,
        "family": family_id,
        "row_id": row_id,
        "source_kind": "indicator_row",
        "score_contract_version": BOUNDED_SCORE_CONTRACT_VERSION,
        "reference_count": int(reference_values.size),
        "calibration_start": calibration_start_value,
        "calibration_end": calibration_end_value,
        "reference_median": None,
        "reference_mad": None,
        "raw_current_value": None,
        "bounded_current_value": None,
        "warning": None,
        "applied": False,
    }
    if finite_mask.any():
        last_raw = float(raw_values[np.flatnonzero(finite_mask)[-1]])
        metadata["raw_current_value"] = last_raw
    if reference_values.size == 0:
        warning = f"{score_key}: bounded scoring fell back to 0 because no finite calibration history was available."
        warnings.append(warning)
        metadata["warning"] = warning
        return bounded, metadata, warnings

    median = float(np.median(reference_values))
    mad = float(np.median(np.abs(reference_values - median)))
    metadata["reference_median"] = median
    metadata["reference_mad"] = mad

    if not math.isfinite(mad) or mad <= _MAD_EPSILON:
        if reference_values.size > 0 and float(np.nanmax(reference_values) - np.nanmin(reference_values)) <= _MAD_EPSILON:
            warning = f"{score_key}: bounded scoring emitted 0 because the reference history is effectively constant."
        else:
            warning = f"{score_key}: bounded scoring emitted 0 because MAD was too small for stable calibration."
        warnings.append(warning)
        metadata["warning"] = warning
        if metadata["raw_current_value"] is not None:
            metadata["bounded_current_value"] = 0.0
        return bounded, metadata, warnings

    robust_z = np.zeros(len(raw_values), dtype="float64")
    robust_z[finite_mask] = _MAD_SCALE * (raw_values[finite_mask] - median) / mad
    bounded = np.clip((200.0 * _normal_cdf(robust_z)) - 100.0, -100.0, 100.0)
    metadata["applied"] = True
    if metadata["raw_current_value"] is not None:
        current_index = np.flatnonzero(finite_mask)[-1]
        metadata["bounded_current_value"] = float(bounded[current_index])
    return bounded, metadata, warnings


def _empirical_quantile_map(raw_values: np.ndarray, bounded_values: np.ndarray, value: float) -> float:
    finite_raw = raw_values[np.isfinite(raw_values)]
    finite_bounded = bounded_values[np.isfinite(bounded_values)]
    if finite_raw.size == 0 or finite_bounded.size == 0:
        return value
    finite_raw = np.sort(finite_raw)
    finite_bounded = np.sort(finite_bounded)
    if finite_raw.size == 1:
        return float(finite_bounded[0])
    rank = float(np.searchsorted(finite_raw, value, side="right")) / float(finite_raw.size)
    target = min(max(rank, 0.0), 1.0)
    return float(np.quantile(finite_bounded, target))


def _map_threshold_value_direct(meta: dict[str, Any], value: float) -> float:
    median = _safe_float(meta.get("reference_median"), float("nan"))
    mad = _safe_float(meta.get("reference_mad"), float("nan"))
    if not math.isfinite(median) or not math.isfinite(mad) or mad <= _MAD_EPSILON:
        return 0.0
    robust_z = _MAD_SCALE * (float(value) - median) / mad
    mapped = (200.0 * (0.5 * (1.0 + math.erf(robust_z / math.sqrt(2.0))))) - 100.0
    return float(max(-100.0, min(100.0, mapped)))


def _map_threshold_space(
    scan_min: float,
    scan_max: float,
    scan_step: float,
    *,
    mapper: Any,
) -> tuple[float, float, float]:
    if scan_step <= 0 or scan_max < scan_min:
        mapped = float(mapper(scan_min))
        return mapped, mapped, 1.0
    count = max(int(round((scan_max - scan_min) / scan_step)), 0) + 1
    raw_values = np.array([scan_min + (scan_step * idx) for idx in range(count)], dtype="float64")
    mapped_values = np.array([float(mapper(item)) for item in raw_values], dtype="float64")
    if mapped_values.size <= 1:
        value = float(mapped_values[0]) if mapped_values.size == 1 else float(mapper(scan_min))
        return value, value, 1.0
    start = float(mapped_values[0])
    end = float(mapped_values[-1])
    step = (end - start) / float(mapped_values.size - 1)
    if not math.isfinite(step) or abs(step) <= _MAD_EPSILON:
        step = 1.0
    return start, end, float(step)


def _migrate_threshold_param(raw: Any, *, mapper: Any) -> Any:
    if not _is_record(raw):
        return raw
    updated = deepcopy(raw)
    updated["value"] = float(mapper(_safe_float(updated.get("value"), 0.0)))
    if str(updated.get("mode") or "manual").strip().lower() == "wfo":
        top_min, top_max, top_step = _map_threshold_space(
            _safe_float(updated.get("scan_min"), _safe_float(updated.get("value"), 0.0)),
            _safe_float(updated.get("scan_max"), _safe_float(updated.get("value"), 0.0)),
            _safe_float(updated.get("scan_step"), 0.0),
            mapper=mapper,
        )
        updated["scan_min"] = top_min
        updated["scan_max"] = top_max
        updated["scan_step"] = top_step
        spaces = updated.get("search_spaces_by_horizon")
        if _is_record(spaces):
            next_spaces: dict[str, Any] = {}
            for horizon_key, space in spaces.items():
                if not _is_record(space):
                    continue
                mapped_min, mapped_max, mapped_step = _map_threshold_space(
                    _safe_float(space.get("scan_min"), _safe_float(updated.get("value"), 0.0)),
                    _safe_float(space.get("scan_max"), _safe_float(updated.get("value"), 0.0)),
                    _safe_float(space.get("scan_step"), top_step),
                    mapper=mapper,
                )
                next_spaces[str(horizon_key)] = {
                    "scan_min": mapped_min,
                    "scan_max": mapped_max,
                    "scan_step": mapped_step,
                }
            updated["search_spaces_by_horizon"] = next_spaces
    return updated


def migrate_stock_score_contract(
    *,
    stock_config: dict[str, Any],
    ohlcv: pd.DataFrame,
    symbol: str | None = None,
    horizon: str = "medium",
    timeframe: str = "1D",
    signal_cost_bps: float = 10.0,
    cooldown_bars: int = 0,
    calibration_end: pd.Timestamp | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    migrated = deepcopy(stock_config or {})
    initial_version = stock_score_contract_version(migrated)
    if ohlcv is None or ohlcv.empty:
        migrated["score_contract_version"] = (
            BOUNDED_SCORE_CONTRACT_VERSION if initial_version == BOUNDED_SCORE_CONTRACT_VERSION else initial_version
        )
        return migrated, {"warnings": [], "converted_variables": []}

    legacy_frame = compute_strategy_score_frame(
        stock_config=migrated,
        ohlcv=ohlcv,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        signal_cost_bps=signal_cost_bps,
        cooldown_bars=cooldown_bars,
        calibration_end=calibration_end,
        specific_setup_mode="raw",
    )
    bounded_frame = compute_strategy_score_frame(
        stock_config=migrated,
        ohlcv=ohlcv,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        signal_cost_bps=signal_cost_bps,
        cooldown_bars=cooldown_bars,
        calibration_end=calibration_end,
        specific_setup_mode="bounded",
    )
    source_meta = dict(bounded_frame.attrs.get("score_source_meta") or {})
    warnings = list(bounded_frame.attrs.get("score_warnings") or [])
    converted_variables: set[str] = set()

    if initial_version != LEGACY_RAW_SCORE_CONTRACT_VERSION:
        migrated["score_contract_version"] = BOUNDED_SCORE_CONTRACT_VERSION
        return migrated, {"warnings": warnings, "converted_variables": []}

    def needs_quantile_mapping(variable: str) -> bool:
        if variable not in legacy_frame.columns or variable not in bounded_frame.columns:
            return False
        left = pd.to_numeric(legacy_frame[variable], errors="coerce").to_numpy(dtype="float64")
        right = pd.to_numeric(bounded_frame[variable], errors="coerce").to_numpy(dtype="float64")
        mask = np.isfinite(left) & np.isfinite(right)
        if not np.any(mask):
            return False
        return bool(np.nanmax(np.abs(left[mask] - right[mask])) > 1e-6)

    def mapper_for_variable(variable: str) -> Any | None:
        meta = source_meta.get(variable) if isinstance(source_meta.get(variable), dict) else None
        if meta and str(meta.get("source_kind") or "") == "indicator_row":
            return lambda value: _map_threshold_value_direct(meta, float(value))
        if variable in {"consensus_score"} and needs_quantile_mapping(variable):
            legacy_values = pd.to_numeric(legacy_frame[variable], errors="coerce").to_numpy(dtype="float64")
            bounded_values = pd.to_numeric(bounded_frame[variable], errors="coerce").to_numpy(dtype="float64")
            return lambda value: _empirical_quantile_map(legacy_values, bounded_values, float(value))
        return None

    for section_name in ("entry_rules", "exit_rules"):
        rules = list(migrated.get(section_name) or [])
        for rule in rules:
            if not _is_record(rule):
                continue
            for condition in list(rule.get("conditions") or []):
                if not _is_record(condition):
                    continue
                variable = str(condition.get("variable") or "").strip().lower()
                mapper = mapper_for_variable(variable)
                if mapper is None:
                    continue
                condition["threshold"] = _migrate_threshold_param(condition.get("threshold"), mapper=mapper)
                converted_variables.add(variable)
        migrated[section_name] = rules

    migrated["score_contract_version"] = BOUNDED_SCORE_CONTRACT_VERSION
    return migrated, {
        "warnings": list(dict.fromkeys(warnings)),
        "converted_variables": sorted(converted_variables),
        "source_meta": source_meta,
    }


def compute_strategy_score_frame(
    *,
    stock_config: dict[str, Any],
    ohlcv: pd.DataFrame,
    symbol: str | None = None,
    horizon: str = "medium",
    timeframe: str = "1D",
    signal_cost_bps: float = 10.0,
    cooldown_bars: int = 0,
    family_history_mode: FamilyHistoryMode = "static_current_reps",
    calibration_end: pd.Timestamp | None = None,
    specific_setup_mode: str = "bounded",
) -> pd.DataFrame:
    ohlcv = drop_incomplete_ohlcv_rows(ohlcv)
    if ohlcv.empty:
        return pd.DataFrame(index=ohlcv.index)

    close = ohlcv["Close"].astype(float).to_numpy(dtype="float64")
    high = ohlcv["High"].astype(float).to_numpy(dtype="float64")
    low = ohlcv["Low"].astype(float).to_numpy(dtype="float64")
    volume = (
        ohlcv["Volume"].astype(float).to_numpy(dtype="float64")
        if "Volume" in ohlcv.columns
        else np.full(len(ohlcv), np.nan, dtype="float64")
    )
    atr = compute_atr_series(high, low, close, window=14)
    atr_safe = np.where(np.isfinite(atr) & (atr != 0.0), atr, np.nan)

    frame = pd.DataFrame(index=ohlcv.index)
    active_columns: list[str] = []
    source_meta: dict[str, Any] = {}
    warnings: list[str] = []

    for source in iter_score_sources(stock_config):
        values: np.ndarray
        if source.source_kind == "family_ensemble":
            if symbol is None:
                raise ValueError("symbol is required to compute family_ensemble score sources")
            volume_input = volume if source.family_id != "obv" else (volume if np.isfinite(volume).any() else None)
            if source.family_id == "obv" and volume_input is None:
                continue
            ensemble_kwargs: dict[str, Any] = {
                "volume": volume_input,
                "symbol": symbol,
                "horizon": horizon,
                "timeframe": timeframe,
                "cost_bps": signal_cost_bps,
                "cooldown_bars": cooldown_bars,
            }
            if _supports_keyword(run_family_ensemble_full, "high"):
                ensemble_kwargs["high"] = high
            if _supports_keyword(run_family_ensemble_full, "low"):
                ensemble_kwargs["low"] = low
            detail = run_family_ensemble_full(source.family_id, close, **ensemble_kwargs)
            signal = getattr(detail, "signal", None)
            if signal is not None and not family_signal_is_available(signal):
                warnings.append(
                    f"{source.score_key}: no representative variants available for {source.family_id}."
                )
                continue
            score_kwargs: dict[str, Any] = {
                "volume": volume_input,
                "cooldown_bars": cooldown_bars,
                "family_history_mode": family_history_mode,
                "symbol": symbol,
                "horizon": horizon,
                "timeframe": timeframe,
                "signal_cost_bps": signal_cost_bps,
            }
            if _supports_keyword(compute_family_score_timeseries, "high"):
                score_kwargs["high"] = high
            if _supports_keyword(compute_family_score_timeseries, "low"):
                score_kwargs["low"] = low
            values = compute_family_score_timeseries(detail, close, **score_kwargs)
            source_meta[source.score_key] = {
                "score_key": source.score_key,
                "family": source.family_id,
                "row_id": source.row_id,
                "source_kind": "family_ensemble",
                "score_contract_version": BOUNDED_SCORE_CONTRACT_VERSION,
                "reference_count": 0,
                "calibration_start": None,
                "calibration_end": None,
                "reference_median": None,
                "reference_mad": None,
                "raw_current_value": float(values[-1]) if len(values) else None,
                "bounded_current_value": float(values[-1]) if len(values) else None,
                "warning": None,
                "applied": False,
            }
        else:
            raw_values = _row_score_values(
                family_id=source.family_id,
                params=source_plain_params(source),
                close=close,
                high=high,
                low=low,
                volume=volume,
                atr_safe=atr_safe,
            )
            if specific_setup_mode == "raw":
                values = raw_values
                source_meta[source.score_key] = {
                    "score_key": source.score_key,
                    "family": source.family_id,
                    "row_id": source.row_id,
                    "source_kind": "indicator_row",
                    "score_contract_version": LEGACY_RAW_SCORE_CONTRACT_VERSION,
                    "reference_count": 0,
                    "calibration_start": None,
                    "calibration_end": None,
                    "reference_median": None,
                    "reference_mad": None,
                    "raw_current_value": float(raw_values[np.flatnonzero(np.isfinite(raw_values))[-1]]) if np.isfinite(raw_values).any() else None,
                    "bounded_current_value": None,
                    "warning": None,
                    "applied": False,
                }
            else:
                values, metadata, source_warnings = _bounded_specific_setup_values(
                    raw_values,
                    index=ohlcv.index,
                    score_key=source.score_key,
                    family_id=source.family_id,
                    row_id=source.row_id,
                    calibration_end=calibration_end,
                )
                source_meta[source.score_key] = metadata
                warnings.extend(source_warnings)

        frame[source.score_key] = (
            pd.Series(values, index=ohlcv.index, dtype="float64")
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
        )
        active_columns.append(source.score_key)

    if active_columns:
        frame["consensus_score"] = frame[active_columns].mean(axis=1).fillna(0.0)
    else:
        frame["consensus_score"] = 0.0
    frame = frame.astype("float64")
    consensus_series = frame["consensus_score"].astype("float64")
    source_meta["consensus_score"] = {
        "score_key": "consensus_score",
        "family": "aggregate",
        "row_id": None,
        "source_kind": "consensus",
        "score_contract_version": (
            LEGACY_RAW_SCORE_CONTRACT_VERSION if specific_setup_mode == "raw" else BOUNDED_SCORE_CONTRACT_VERSION
        ),
        "reference_count": 0,
        "calibration_start": None,
        "calibration_end": None,
        "reference_median": None,
        "reference_mad": None,
        "raw_current_value": float(consensus_series.iloc[-1]) if len(consensus_series) else None,
        "bounded_current_value": float(consensus_series.iloc[-1]) if len(consensus_series) else None,
        "warning": None,
        "applied": False,
    }
    frame.attrs["score_source_meta"] = source_meta
    frame.attrs["score_warnings"] = list(dict.fromkeys(warnings))
    frame.attrs["specific_setup_mode"] = specific_setup_mode
    frame.attrs["family_history_mode"] = family_history_mode
    return frame
