"""Raw indicator-series helpers shared by the signal engine and API."""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.quant_core.optimize import ema, macd_pack, obv_array, rsi_wilder, sma_cumsum


def _as_float(arr: np.ndarray | list[float]) -> np.ndarray:
    return np.asarray(arr, dtype=np.float64)


def _nan_array(length: int) -> np.ndarray:
    return np.full(length, np.nan, dtype=np.float64)


def _rolling_max(values: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(values).rolling(window=window, min_periods=window).max().to_numpy(dtype=np.float64)


def _rolling_min(values: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(values).rolling(window=window, min_periods=window).min().to_numpy(dtype=np.float64)


def _rolling_sum(values: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(values).rolling(window=window, min_periods=window).sum().to_numpy(dtype=np.float64)


def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(values).rolling(window=window, min_periods=window).mean().to_numpy(dtype=np.float64)


def _mean_deviation(values: np.ndarray, period: int) -> np.ndarray:
    series = pd.Series(values)
    return series.rolling(window=period, min_periods=period).apply(
        lambda x: float(np.mean(np.abs(x - np.mean(x)))), raw=True
    ).to_numpy(dtype=np.float64)


def _apply_warmup(values: np.ndarray, warmup: int) -> np.ndarray:
    out = np.asarray(values, dtype=np.float64).copy()
    if warmup > 0:
        out[: min(len(out), warmup)] = np.nan
    return out


def _wilder_smooth(values: np.ndarray, period: int) -> np.ndarray:
    values = _as_float(values)
    out = _nan_array(len(values))
    if period <= 0 or len(values) < period:
        return out
    initial = float(np.nansum(values[:period]))
    out[period - 1] = initial
    for idx in range(period, len(values)):
        out[idx] = out[idx - 1] - (out[idx - 1] / period) + values[idx]
    return out


def compute_sma_series(close: np.ndarray, period: int) -> np.ndarray:
    """Return SMA(period) aligned to *close* with NaN warmup bars."""
    return sma_cumsum(_as_float(close), int(period))


def compute_ema_series(close: np.ndarray, period: int) -> np.ndarray:
    """Return EMA(period) aligned to *close* with NaN warmup bars."""
    close_arr = _as_float(close)
    out = _as_float(ema(close_arr, int(period)))
    return _apply_warmup(out, max(int(period) - 1, 0))


def compute_ema_cross_series(close: np.ndarray, fast: int, slow: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (fast_ema, slow_ema) arrays."""
    return compute_ema_series(close, fast), compute_ema_series(close, slow)


def compute_rsi_series(close: np.ndarray, period: int) -> np.ndarray:
    """Return RSI(period) aligned to *close* with NaN warmup bars."""
    return rsi_wilder(_as_float(close), int(period))


def compute_macd_series(close: np.ndarray, fast: int, slow: int, signal: int) -> tuple[np.ndarray, np.ndarray]:
    """Return MACD histogram and signal line aligned to *close*."""
    _macd_line, signal_line, histogram = macd_pack(_as_float(close), int(fast), int(slow), int(signal))
    return histogram, signal_line


def compute_macd_pack_series(close: np.ndarray, fast: int, slow: int, signal: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (macd_line, signal_line, histogram) aligned to *close*."""
    return macd_pack(_as_float(close), int(fast), int(slow), int(signal))


def compute_obv_deviation(close: np.ndarray, volume: np.ndarray, ema_period: int) -> np.ndarray:
    """Return OBV deviation from its EMA as a self-normalized fraction."""
    close_arr = _as_float(close)
    volume_arr = _as_float(volume)
    obv = obv_array(close_arr, volume_arr)
    obv_ema = compute_ema_series(obv, int(ema_period))
    out = _nan_array(len(obv))
    mask = np.isfinite(obv) & np.isfinite(obv_ema) & (obv_ema != 0.0)
    out[mask] = (obv[mask] - obv_ema[mask]) / obv_ema[mask]
    return out


def compute_atr_series(high: np.ndarray, low: np.ndarray, close: np.ndarray, window: int = 14) -> np.ndarray:
    """Return rolling ATR(window) aligned to *close* with NaN warmup bars."""
    high_arr = _as_float(high)
    low_arr = _as_float(low)
    close_arr = _as_float(close)
    n = len(close_arr)
    out = _nan_array(n)
    if n == 0 or window <= 0 or window > n:
        return out

    prev_close = np.empty(n, dtype=np.float64)
    prev_close[0] = close_arr[0]
    prev_close[1:] = close_arr[:-1]
    tr = np.maximum(high_arr - low_arr, np.maximum(np.abs(high_arr - prev_close), np.abs(low_arr - prev_close)))
    csum = np.cumsum(np.insert(tr, 0, 0.0))
    out[window - 1 :] = (csum[window:] - csum[:-window]) / window
    return out


def compute_ichimoku_series(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    tenkan: int,
    kijun: int,
    senkou_b: int,
) -> dict[str, np.ndarray]:
    """Return Ichimoku series for current-bar signal computation."""
    high_arr = _as_float(high)
    low_arr = _as_float(low)
    _ = _as_float(close)
    tenkan_sen = (_rolling_max(high_arr, tenkan) + _rolling_min(low_arr, tenkan)) / 2.0
    kijun_sen = (_rolling_max(high_arr, kijun) + _rolling_min(low_arr, kijun)) / 2.0
    senkou_a = (tenkan_sen + kijun_sen) / 2.0
    senkou_b_arr = (_rolling_max(high_arr, senkou_b) + _rolling_min(low_arr, senkou_b)) / 2.0
    cloud_top = np.maximum(senkou_a, senkou_b_arr)
    cloud_bottom = np.minimum(senkou_a, senkou_b_arr)
    return {
        "tenkan_sen": tenkan_sen,
        "kijun_sen": kijun_sen,
        "senkou_a": senkou_a,
        "senkou_b": senkou_b_arr,
        "cloud_top": cloud_top,
        "cloud_bottom": cloud_bottom,
    }


def compute_psar_series(high: np.ndarray, low: np.ndarray, close: np.ndarray, af_step: float, af_max: float) -> np.ndarray:
    """Return standard Wilder Parabolic SAR."""
    high_arr = _as_float(high)
    low_arr = _as_float(low)
    close_arr = _as_float(close)
    n = len(close_arr)
    sar = _nan_array(n)
    if n == 0:
        return sar
    if n == 1:
        sar[0] = low_arr[0]
        return sar

    long_trend = True
    sar[0] = low_arr[0]
    ep = high_arr[0]
    af = float(af_step)

    for idx in range(1, n):
        prev_sar = sar[idx - 1]
        current = prev_sar + af * (ep - prev_sar)
        if long_trend:
            if idx >= 2:
                current = min(current, low_arr[idx - 1], low_arr[idx - 2])
            else:
                current = min(current, low_arr[idx - 1])
            if low_arr[idx] < current:
                long_trend = False
                current = ep
                ep = low_arr[idx]
                af = float(af_step)
            else:
                if high_arr[idx] > ep:
                    ep = high_arr[idx]
                    af = min(af + float(af_step), float(af_max))
        else:
            if idx >= 2:
                current = max(current, high_arr[idx - 1], high_arr[idx - 2])
            else:
                current = max(current, high_arr[idx - 1])
            if high_arr[idx] > current:
                long_trend = True
                current = ep
                ep = high_arr[idx]
                af = float(af_step)
            else:
                if low_arr[idx] < ep:
                    ep = low_arr[idx]
                    af = min(af + float(af_step), float(af_max))
        sar[idx] = current

    return sar


def compute_roc_series(close: np.ndarray, period: int) -> np.ndarray:
    """ROC = (close - close[n]) / close[n] * 100."""
    close_arr = _as_float(close)
    out = _nan_array(len(close_arr))
    if period <= 0 or len(close_arr) <= period:
        return out
    base = close_arr[:-period]
    target = close_arr[period:]
    mask = base != 0.0
    vals = _nan_array(len(target))
    vals[mask] = ((target[mask] - base[mask]) / base[mask]) * 100.0
    out[period:] = vals
    return out


def compute_trix_series(close: np.ndarray, period: int) -> np.ndarray:
    """TRIX = 100 * (EMA3[i] - EMA3[i-1]) / EMA3[i-1]."""
    close_arr = _as_float(close)
    ema1 = compute_ema_series(close_arr, period)
    ema2 = compute_ema_series(ema1, period)
    ema3 = compute_ema_series(ema2, period)
    out = _nan_array(len(close_arr))
    if len(close_arr) < 2:
        return out
    prev = ema3[:-1]
    curr = ema3[1:]
    mask = np.isfinite(prev) & np.isfinite(curr) & (prev != 0.0)
    out[1:][mask] = ((curr[mask] - prev[mask]) / prev[mask]) * 100.0
    warmup = max((3 * int(period)) - 1, 0)
    return _apply_warmup(out, warmup)


def compute_adx_series(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (+DI, -DI, ADX) arrays using Wilder smoothing."""
    high_arr = _as_float(high)
    low_arr = _as_float(low)
    close_arr = _as_float(close)
    n = len(close_arr)
    plus_dm = np.zeros(n, dtype=np.float64)
    minus_dm = np.zeros(n, dtype=np.float64)
    tr = np.zeros(n, dtype=np.float64)
    if n == 0:
        empty = _nan_array(0)
        return empty, empty, empty

    prev_close = np.empty(n, dtype=np.float64)
    prev_close[0] = close_arr[0]
    prev_close[1:] = close_arr[:-1]

    up_move = high_arr[1:] - high_arr[:-1]
    down_move = low_arr[:-1] - low_arr[1:]
    plus_dm[1:] = np.where((up_move > down_move) & (up_move > 0.0), up_move, 0.0)
    minus_dm[1:] = np.where((down_move > up_move) & (down_move > 0.0), down_move, 0.0)
    tr = np.maximum(high_arr - low_arr, np.maximum(np.abs(high_arr - prev_close), np.abs(low_arr - prev_close)))

    tr_smooth = _wilder_smooth(tr, period)
    plus_smooth = _wilder_smooth(plus_dm, period)
    minus_smooth = _wilder_smooth(minus_dm, period)

    plus_di = _nan_array(n)
    minus_di = _nan_array(n)
    valid = np.isfinite(tr_smooth) & (tr_smooth != 0.0)
    plus_di[valid] = 100.0 * plus_smooth[valid] / tr_smooth[valid]
    minus_di[valid] = 100.0 * minus_smooth[valid] / tr_smooth[valid]

    dx = _nan_array(n)
    denom = plus_di + minus_di
    dx_valid = np.isfinite(plus_di) & np.isfinite(minus_di) & (denom != 0.0)
    dx[dx_valid] = 100.0 * np.abs(plus_di[dx_valid] - minus_di[dx_valid]) / denom[dx_valid]
    adx = _wilder_smooth(np.nan_to_num(dx, nan=0.0), period)
    adx[~np.isfinite(dx)] = np.nan
    return plus_di, minus_di, _apply_warmup(adx, max((2 * int(period)) - 1, 0))


def compute_tsi_series(close: np.ndarray, long_period: int, short_period: int) -> np.ndarray:
    """TSI = 100 * EMA(EMA(momentum, long), short) / EMA(EMA(|momentum|, long), short)."""
    close_arr = _as_float(close)
    momentum = _nan_array(len(close_arr))
    if len(close_arr) > 1:
        momentum[1:] = close_arr[1:] - close_arr[:-1]
    ema1 = compute_ema_series(np.nan_to_num(momentum, nan=0.0), long_period)
    ema2 = compute_ema_series(ema1, short_period)
    abs_ema1 = compute_ema_series(np.abs(np.nan_to_num(momentum, nan=0.0)), long_period)
    abs_ema2 = compute_ema_series(abs_ema1, short_period)
    out = _nan_array(len(close_arr))
    mask = np.isfinite(ema2) & np.isfinite(abs_ema2) & (abs_ema2 != 0.0)
    out[mask] = 100.0 * ema2[mask] / abs_ema2[mask]
    return _apply_warmup(out, max(int(long_period) + int(short_period) - 1, 0))


def compute_stochastic_series(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    k_period: int,
    d_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (%K, %D) arrays."""
    high_arr = _as_float(high)
    low_arr = _as_float(low)
    close_arr = _as_float(close)
    hh = _rolling_max(high_arr, k_period)
    ll = _rolling_min(low_arr, k_period)
    denom = hh - ll
    k = _nan_array(len(close_arr))
    mask = np.isfinite(hh) & np.isfinite(ll) & (denom != 0.0)
    k[mask] = 100.0 * (close_arr[mask] - ll[mask]) / denom[mask]
    d = _rolling_mean(k, d_period)
    return k, d


def compute_cci_series(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Return CCI(period)."""
    high_arr = _as_float(high)
    low_arr = _as_float(low)
    close_arr = _as_float(close)
    typical = (high_arr + low_arr + close_arr) / 3.0
    sma = _rolling_mean(typical, period)
    mean_dev = _mean_deviation(typical, period)
    out = _nan_array(len(close_arr))
    denom = 0.015 * mean_dev
    mask = np.isfinite(sma) & np.isfinite(denom) & (denom != 0.0)
    out[mask] = (typical[mask] - sma[mask]) / denom[mask]
    return out


def compute_mfi_series(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray, period: int) -> np.ndarray:
    """Return MFI(period)."""
    high_arr = _as_float(high)
    low_arr = _as_float(low)
    close_arr = _as_float(close)
    volume_arr = _as_float(volume)
    typical = (high_arr + low_arr + close_arr) / 3.0
    flow = typical * volume_arr
    positive = np.zeros(len(close_arr), dtype=np.float64)
    negative = np.zeros(len(close_arr), dtype=np.float64)
    delta = typical[1:] - typical[:-1]
    positive[1:] = np.where(delta > 0.0, flow[1:], 0.0)
    negative[1:] = np.where(delta < 0.0, flow[1:], 0.0)
    pos_sum = _rolling_sum(positive, period)
    neg_sum = _rolling_sum(negative, period)
    out = _nan_array(len(close_arr))
    pos_only = np.isfinite(pos_sum) & np.isfinite(neg_sum) & (neg_sum == 0.0) & (pos_sum > 0.0)
    out[pos_only] = 100.0
    mask = np.isfinite(pos_sum) & np.isfinite(neg_sum) & (neg_sum != 0.0)
    ratio = _nan_array(len(close_arr))
    ratio[mask] = pos_sum[mask] / neg_sum[mask]
    out[mask] = 100.0 - (100.0 / (1.0 + ratio[mask]))
    return out


def compute_uo_series(high: np.ndarray, low: np.ndarray, close: np.ndarray, p1: int, p2: int, p3: int) -> np.ndarray:
    """Return Ultimate Oscillator."""
    high_arr = _as_float(high)
    low_arr = _as_float(low)
    close_arr = _as_float(close)
    prev_close = np.empty(len(close_arr), dtype=np.float64)
    prev_close[0] = close_arr[0]
    prev_close[1:] = close_arr[:-1]
    buying_pressure = close_arr - np.minimum(low_arr, prev_close)
    true_range = np.maximum(high_arr, prev_close) - np.minimum(low_arr, prev_close)
    avg1 = _rolling_sum(buying_pressure, p1) / _rolling_sum(true_range, p1)
    avg2 = _rolling_sum(buying_pressure, p2) / _rolling_sum(true_range, p2)
    avg3 = _rolling_sum(buying_pressure, p3) / _rolling_sum(true_range, p3)
    out = 100.0 * ((4.0 * avg1) + (2.0 * avg2) + avg3) / 7.0
    return _apply_warmup(out, max(int(p3) - 1, 0))


def compute_cmf_series(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray, period: int) -> np.ndarray:
    """Return Chaikin Money Flow."""
    high_arr = _as_float(high)
    low_arr = _as_float(low)
    close_arr = _as_float(close)
    volume_arr = _as_float(volume)
    denom = high_arr - low_arr
    clv = np.zeros(len(close_arr), dtype=np.float64)
    valid = denom != 0.0
    clv[valid] = ((close_arr[valid] - low_arr[valid]) - (high_arr[valid] - close_arr[valid])) / denom[valid]
    mfv = clv * volume_arr
    vol_sum = _rolling_sum(volume_arr, period)
    out = _nan_array(len(close_arr))
    mask = np.isfinite(vol_sum) & (vol_sum != 0.0)
    out[mask] = _rolling_sum(mfv, period)[mask] / vol_sum[mask]
    return out


def compute_ad_series(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """Return cumulative A/D line."""
    high_arr = _as_float(high)
    low_arr = _as_float(low)
    close_arr = _as_float(close)
    volume_arr = _as_float(volume)
    denom = high_arr - low_arr
    clv = np.zeros(len(close_arr), dtype=np.float64)
    valid = denom != 0.0
    clv[valid] = ((close_arr[valid] - low_arr[valid]) - (high_arr[valid] - close_arr[valid])) / denom[valid]
    return np.cumsum(clv * volume_arr)


def compute_vwap_series(close: np.ndarray, volume: np.ndarray, period: int) -> np.ndarray:
    """Return rolling VWAP."""
    close_arr = _as_float(close)
    volume_arr = _as_float(volume)
    numerator = _rolling_sum(close_arr * volume_arr, period)
    denominator = _rolling_sum(volume_arr, period)
    out = _nan_array(len(close_arr))
    mask = np.isfinite(numerator) & np.isfinite(denominator) & (denominator != 0.0)
    out[mask] = numerator[mask] / denominator[mask]
    return out


def compute_force_index_series(close: np.ndarray, volume: np.ndarray, period: int) -> np.ndarray:
    """Return EMA-smoothed Force Index."""
    close_arr = _as_float(close)
    volume_arr = _as_float(volume)
    force = np.zeros(len(close_arr), dtype=np.float64)
    if len(close_arr) > 1:
        force[1:] = (close_arr[1:] - close_arr[:-1]) * volume_arr[1:]
    return compute_ema_series(force, period)
