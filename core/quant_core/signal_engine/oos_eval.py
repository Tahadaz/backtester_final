"""Layer B - Out-of-sample evaluation with walk-forward windows."""

from __future__ import annotations

import math
from typing import Callable

import numpy as np

from core.quant_core.horizons import DEFAULT_COST_BPS_PER_SIDE
from core.quant_core.optimize import ema
from core.quant_core.significance import sharpe_ratio

from .domain import HORIZON_PARAMS, VALID_HORIZONS, MethodologyWindow, OOSWindowResult, VariantDef
from .indicator_series import (
    compute_ad_series,
    compute_adx_series,
    compute_cci_series,
    compute_cmf_series,
    compute_ema_cross_series,
    compute_ema_series,
    compute_force_index_series,
    compute_ichimoku_series,
    compute_macd_pack_series,
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

SignalDispatcher = Callable[..., np.ndarray]

_SIGNAL_DISPATCHERS: dict[tuple[str, str], SignalDispatcher] = {}


def register_signal(family: str, archetype: str):
    """Decorator: register a signal function for (family, archetype)."""

    def _wrap(fn: SignalDispatcher):
        _SIGNAL_DISPATCHERS[(family, archetype)] = fn
        return fn

    return _wrap


def _require_high_low(high: np.ndarray | None, low: np.ndarray | None, family: str) -> tuple[np.ndarray, np.ndarray]:
    if high is None or low is None:
        raise ValueError(f"Family {family!r} requires high/low arrays")
    return np.asarray(high, dtype=np.float64), np.asarray(low, dtype=np.float64)


def compute_signal_array(
    close: np.ndarray,
    variant: VariantDef,
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
) -> np.ndarray:
    """Compute the signal array for *variant* on *close*."""
    close_arr = np.asarray(close, dtype=np.float64)
    # Factor-conditioned variants have family="{ta_family}@fx"; strip suffix for dispatch.
    base_family = variant.family.split("@")[0] if "@" in variant.family else variant.family
    key = (base_family, variant.archetype)
    fn = _SIGNAL_DISPATCHERS.get(key)
    if fn is None:
        raise ValueError(f"No signal dispatcher for {key!r}")

    vol = np.asarray(volume, dtype=np.float64) if volume is not None else np.zeros(len(close_arr), dtype=np.float64)
    vol = np.where(np.isnan(vol), 0.0, vol)
    raw = fn(close_arr, variant.params, vol, high=high, low=low)
    if len(raw) != len(close_arr):
        raise AssertionError(
            f"Signal length {len(raw)} != close length {len(close_arr)} for {variant.variant_id}"
        )
    sig = np.where(np.isnan(raw), 0.0, raw)
    sig = np.clip(sig, -1.0, 1.0)
    return np.sign(sig)


@register_signal("sma", "price_vs_sma")
def _sma_price_vs_sma(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    sma = compute_sma_series(close, int(params["window"]))
    return np.where(close > sma, 1.0, np.where(close < sma, -1.0, 0.0))


@register_signal("sma", "sma_cross")
def _sma_cross(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    fast = compute_sma_series(close, int(params["fast"]))
    slow = compute_sma_series(close, int(params["slow"]))
    return np.where(fast > slow, 1.0, np.where(fast < slow, -1.0, 0.0))


@register_signal("sma", "slope_confirmed")
def _sma_slope_confirmed(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    window = int(params["window"])
    lookback = int(params["slope_lookback"])
    sma = compute_sma_series(close, window)
    slope = np.full(len(close), np.nan, dtype=np.float64)
    slope[lookback:] = sma[lookback:] - sma[:-lookback]
    return np.where((close > sma) & (slope > 0), 1.0, np.where((close < sma) & (slope < 0), -1.0, 0.0))


@register_signal("ema", "price_vs_ema")
def _ema_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    ema_arr = compute_ema_series(close, int(params["window"]))
    return np.where(close > ema_arr, 1.0, np.where(close < ema_arr, -1.0, 0.0))


@register_signal("ema_cross", "ema_cross")
def _ema_cross_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    fast, slow = compute_ema_cross_series(close, int(params["fast"]), int(params["slow"]))
    return np.where(fast > slow, 1.0, np.where(fast < slow, -1.0, 0.0))


@register_signal("ichimoku", "ichi_cloud")
def _ichimoku_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    high_arr, low_arr = _require_high_low(high, low, "ichimoku")
    ichi = compute_ichimoku_series(
        high_arr,
        low_arr,
        close,
        int(params["tenkan"]),
        int(params["kijun"]),
        int(params["senkou_b"]),
    )
    bullish = (close > ichi["cloud_top"]) & (ichi["tenkan_sen"] > ichi["kijun_sen"])
    bearish = (close < ichi["cloud_bottom"]) & (ichi["tenkan_sen"] < ichi["kijun_sen"])
    return np.where(bullish, 1.0, np.where(bearish, -1.0, 0.0))


@register_signal("psar", "psar_trend")
def _psar_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    high_arr, low_arr = _require_high_low(high, low, "psar")
    sar = compute_psar_series(high_arr, low_arr, close, float(params["af_step"]), float(params["af_max"]))
    return np.where(close > sar, 1.0, np.where(close < sar, -1.0, 0.0))


@register_signal("rsi", "rsi_level")
def _rsi_level(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    rsi_vals = compute_rsi_series(close, int(params["period"]))
    oversold = float(params["oversold"])
    overbought = float(params["overbought"])
    return np.where(rsi_vals < oversold, 1.0, np.where(rsi_vals > overbought, -1.0, 0.0))


@register_signal("macd", "macd_cross")
def _macd_cross_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    macd_line, signal_line, _hist = compute_macd_pack_series(
        close,
        int(params["fast"]),
        int(params["slow"]),
        int(params["signal"]),
    )
    return np.where(macd_line > signal_line, 1.0, np.where(macd_line < signal_line, -1.0, 0.0))


@register_signal("roc", "roc_zero")
def _roc_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    roc = compute_roc_series(close, int(params["period"]))
    return np.where(roc > 0.0, 1.0, np.where(roc < 0.0, -1.0, 0.0))


@register_signal("trix", "trix_zero")
def _trix_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    trix = compute_trix_series(close, int(params["period"]))
    return np.where(trix > 0.0, 1.0, np.where(trix < 0.0, -1.0, 0.0))


@register_signal("adx", "adx_trend")
def _adx_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    high_arr, low_arr = _require_high_low(high, low, "adx")
    plus_di, minus_di, adx = compute_adx_series(high_arr, low_arr, close, int(params["period"]))
    threshold = float(params["adx_threshold"])
    bullish = (plus_di > minus_di) & (adx > threshold)
    bearish = (minus_di > plus_di) & (adx > threshold)
    return np.where(bullish, 1.0, np.where(bearish, -1.0, 0.0))


@register_signal("tsi", "tsi_zero")
def _tsi_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    long_period = int(params.get("long_period", params["quarterly_period"]))
    short_period = int(params.get("short_period", params["weekly_period"]))
    tsi = compute_tsi_series(close, long_period, short_period)
    return np.where(tsi > 0.0, 1.0, np.where(tsi < 0.0, -1.0, 0.0))


@register_signal("stochastic", "stoch_level")
def _stochastic_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    high_arr, low_arr = _require_high_low(high, low, "stochastic")
    k_vals, d_vals = compute_stochastic_series(high_arr, low_arr, close, int(params["k_period"]), int(params["d_period"]))
    buy = (k_vals < 20.0) & (k_vals > d_vals)
    sell = (k_vals > 80.0) & (k_vals < d_vals)
    return np.where(buy, 1.0, np.where(sell, -1.0, 0.0))


@register_signal("cci", "cci_level")
def _cci_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    high_arr, low_arr = _require_high_low(high, low, "cci")
    cci = compute_cci_series(high_arr, low_arr, close, int(params["period"]))
    return np.where(cci < -100.0, 1.0, np.where(cci > 100.0, -1.0, 0.0))


@register_signal("mfi", "mfi_level")
def _mfi_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    high_arr, low_arr = _require_high_low(high, low, "mfi")
    mfi = compute_mfi_series(high_arr, low_arr, close, volume, int(params["period"]))
    oversold = float(params["oversold"])
    overbought = float(params["overbought"])
    return np.where(mfi < oversold, 1.0, np.where(mfi > overbought, -1.0, 0.0))


@register_signal("uo", "uo_level")
def _uo_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    high_arr, low_arr = _require_high_low(high, low, "uo")
    uo = compute_uo_series(
        high_arr,
        low_arr,
        close,
        int(params["period_1"]),
        int(params["period_2"]),
        int(params["period_3"]),
    )
    return np.where(uo < 30.0, 1.0, np.where(uo > 70.0, -1.0, 0.0))


@register_signal("obv", "obv_trend")
def _obv_trend(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    deviation = compute_obv_deviation(close, volume, int(params["ema_period"]))
    return np.where(deviation > 0.0, 1.0, np.where(deviation < 0.0, -1.0, 0.0))


@register_signal("cmf", "cmf_flow")
def _cmf_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    high_arr, low_arr = _require_high_low(high, low, "cmf")
    cmf = compute_cmf_series(high_arr, low_arr, close, volume, int(params["period"]))
    return np.where(cmf > 0.05, 1.0, np.where(cmf < -0.05, -1.0, 0.0))


@register_signal("ad", "ad_trend")
def _ad_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    high_arr, low_arr = _require_high_low(high, low, "ad")
    ad_line = compute_ad_series(high_arr, low_arr, close, volume)
    ad_ema = np.asarray(ema(ad_line, int(params["ema_period"])), dtype=np.float64)
    warmup = max(int(params["ema_period"]) - 1, 0)
    if warmup > 0:
        ad_ema[:warmup] = np.nan
    return np.where(ad_line > ad_ema, 1.0, np.where(ad_line < ad_ema, -1.0, 0.0))


@register_signal("vwap", "vwap_dev")
def _vwap_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    vwap = compute_vwap_series(close, volume, int(params["period"]))
    threshold = float(params["threshold_pct"]) / 100.0
    upper = vwap * (1.0 + threshold)
    lower = vwap * (1.0 - threshold)
    return np.where(close > upper, 1.0, np.where(close < lower, -1.0, 0.0))


@register_signal("fi", "fi_trend")
def _fi_signal(close: np.ndarray, params: dict, volume: np.ndarray, *, high=None, low=None) -> np.ndarray:
    fi = compute_force_index_series(close, volume, int(params["period"]))
    return np.where(fi > 0.0, 1.0, np.where(fi < 0.0, -1.0, 0.0))


_EVENT_SIGNAL_ARCHETYPES = frozenset(
    {
        "sma_cross",
        "macd_cross",
        "rsi_level",
        "stoch_level",
        "cci_level",
        "mfi_level",
        "uo_level",
    }
)


def variant_uses_event_signals(variant: VariantDef) -> bool:
    return variant.archetype in _EVENT_SIGNAL_ARCHETYPES


def _actions_to_positions(actions: np.ndarray) -> np.ndarray:
    """Convert long-only action signals to carried positions."""
    positions = np.zeros_like(actions)
    pos = 0.0
    for idx, action in enumerate(actions):
        if action > 0.0:
            pos = 1.0
        elif action < 0.0:
            pos = 0.0
        positions[idx] = pos
    return positions


def signal_to_long_only_positions(signal: np.ndarray, variant: VariantDef) -> np.ndarray:
    """Convert a raw variant signal stream to long-only carried positions."""
    if variant_uses_event_signals(variant):
        return _actions_to_positions(signal)
    return np.where(signal > 0.0, 1.0, 0.0).astype(float, copy=False)


def apply_cooldown(sig: np.ndarray, cooldown_bars: int) -> np.ndarray:
    """Return a copy of *sig* with cooldown applied."""
    out = sig.copy()
    if cooldown_bars <= 0:
        return out
    idx = 1
    while idx < len(out):
        if out[idx] != out[idx - 1]:
            end = min(idx + 1 + cooldown_bars, len(out))
            out[idx + 1 : end] = out[idx]
            idx = end
        else:
            idx += 1
    return out


def _max_drawdown(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return 0.0
    equity = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / np.where(peak > 0.0, peak, 1.0)
    return float(np.nanmax(drawdown)) if len(drawdown) > 0 else 0.0


def evaluate_variant_oos(
    close: np.ndarray,
    variant: VariantDef,
    horizon: str,
    cost_bps: float = DEFAULT_COST_BPS_PER_SIDE,
    *,
    cooldown_bars: int = 0,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    window_config: MethodologyWindow | None = None,
    min_valid_windows: int = 3,
    min_test_bars_valid: int = 20,
    precomputed_signal: np.ndarray | None = None,
) -> list[OOSWindowResult]:
    """Rolling walk-forward OOS evaluation.

    precomputed_signal: when provided (Phase 2 factor-conditioned variants),
        skips compute_signal_array and uses this array directly. The caller is
        responsible for ensuring it is already AND-composed and calendar-aligned.
    """
    if horizon not in VALID_HORIZONS:
        raise ValueError(f"Unknown horizon {horizon!r}")

    hp = HORIZON_PARAMS[horizon]
    if window_config is None:
        train_len = hp["train"]
        test_len = hp["test"]
        step = hp["step"]
    else:
        train_len = int(window_config.train)
        test_len = int(window_config.test)
        step = int(window_config.step)
    n = len(close)
    if n < (train_len + test_len + 1):
        return []

    if precomputed_signal is not None:
        sig = np.asarray(precomputed_signal, dtype=float)
    else:
        sig = compute_signal_array(close, variant, volume=volume, high=high, low=low)
    cost_factor = cost_bps / 10_000.0
    results: list[OOSWindowResult] = []
    window_idx = 0

    for start in range(0, n - train_len - test_len, step):
        train_end = start + train_len
        test_start = train_end
        test_end = min(test_start + test_len, n - 1)
        oos_len = test_end - test_start
        if oos_len < 2:
            continue

        sig_raw = apply_cooldown(sig[test_start:test_end], cooldown_bars)
        close_oos = close[test_start : test_end + 1]
        price_ret = close_oos[1:] / close_oos[:-1] - 1.0
        sig_oos = signal_to_long_only_positions(sig_raw, variant)
        sig_change = np.abs(np.diff(sig_oos, prepend=0.0))
        ret = sig_oos * price_ret - (cost_factor * sig_change)

        n_trades = int(np.sum(sig_change > 0.0))
        n_bars = len(ret)
        mean_ret = float(np.mean(ret)) if n_bars > 0 else 0.0
        frac_pos = float(np.mean(ret > 0.0)) if n_bars > 0 else 0.0
        sr = sharpe_ratio(ret)
        if not math.isfinite(sr):
            sr = 0.0
        mdd = _max_drawdown(ret)
        is_valid = n_bars >= min_test_bars_valid
        total_return = float(np.prod(1.0 + ret) - 1.0)
        window_cagr = (1.0 + total_return) ** (252.0 / max(n_bars, 1)) - 1.0 if total_return > -1.0 else -1.0
        window_pnl = 100_000.0 * total_return

        results.append(
            OOSWindowResult(
                window_index=window_idx,
                train_start=start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                n_trades=n_trades,
                mean_return_net=mean_ret,
                sharpe=sr,
                max_drawdown=mdd,
                fraction_positive_bars=frac_pos,
                n_bars=n_bars,
                is_valid=is_valid,
                total_return=total_return,
                cagr=window_cagr,
                pnl=window_pnl,
            )
        )
        window_idx += 1

    if sum(1 for row in results if row.is_valid) < min_valid_windows:
        return []
    return results
