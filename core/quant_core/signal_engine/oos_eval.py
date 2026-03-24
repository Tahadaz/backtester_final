"""Layer B — Out-of-sample evaluation with walk-forward windows.

Signal contract (enforced in compute_signal_array):
  - Output length == input close length
  - Values in {-1.0, 0.0, +1.0} only
  - Warmup bars padded with 0.0 (flat policy)
  - Signal at close(t); evaluated on next-bar return close[t+1]/close[t] - 1
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np

from core.quant_core.optimize import sma_cumsum, rsi_wilder, ema, macd_pack, obv_array
from core.quant_core.significance import sharpe_ratio

from .domain import HORIZON_PARAMS, VALID_HORIZONS, MethodologyWindow, OOSWindowResult, VariantDef

# ---------------------------------------------------------------------------
# Family-agnostic signal dispatch registry
# ---------------------------------------------------------------------------

_SIGNAL_DISPATCHERS: dict[tuple[str, str], Callable[[np.ndarray, dict, np.ndarray], np.ndarray]] = {}


def register_signal(family: str, archetype: str):
    """Decorator: register a signal function for (family, archetype)."""
    def _wrap(fn: Callable[[np.ndarray, dict, np.ndarray], np.ndarray]):
        _SIGNAL_DISPATCHERS[(family, archetype)] = fn
        return fn
    return _wrap


def compute_signal_array(
    close: np.ndarray, variant: VariantDef, *, volume: np.ndarray | None = None,
) -> np.ndarray:
    """Compute the signal array for *variant* on *close*.

    Returns an array of the same length as *close* with values in {-1.0, 0.0, +1.0}.
    Warmup / NaN bars are forced to 0.0 (flat policy).
    """
    key = (variant.family, variant.archetype)
    fn = _SIGNAL_DISPATCHERS.get(key)
    if fn is None:
        raise ValueError(f"No signal dispatcher for {key!r}")

    vol = volume if volume is not None else np.zeros(len(close))
    vol = np.where(np.isnan(vol), 0.0, vol)  # missing bar = no trading activity
    raw = fn(close, variant.params, vol)

    # --- enforce signal contract ---
    assert len(raw) == len(close), (
        f"Signal length {len(raw)} != close length {len(close)} "
        f"for {variant.variant_id}"
    )
    sig = np.where(np.isnan(raw), 0.0, raw)
    sig = np.clip(sig, -1.0, 1.0)
    sig = np.sign(sig)  # maps to {-1.0, 0.0, +1.0}
    return sig


# ---------------------------------------------------------------------------
# SMA signal implementations
# ---------------------------------------------------------------------------

@register_signal("sma", "price_vs_sma")
def _sma_price_vs_sma(close: np.ndarray, params: dict, volume: np.ndarray) -> np.ndarray:
    w = int(params["window"])
    sma = sma_cumsum(close, w)
    return np.where(close > sma, 1.0, np.where(close < sma, -1.0, 0.0))


@register_signal("sma", "sma_cross")
def _sma_cross(close: np.ndarray, params: dict, volume: np.ndarray) -> np.ndarray:
    fast = sma_cumsum(close, int(params["fast"]))
    slow = sma_cumsum(close, int(params["slow"]))
    return np.where(fast > slow, 1.0, np.where(fast < slow, -1.0, 0.0))


@register_signal("sma", "slope_confirmed")
def _sma_slope_confirmed(close: np.ndarray, params: dict, volume: np.ndarray) -> np.ndarray:
    w = int(params["window"])
    k = int(params["slope_lookback"])
    sma = sma_cumsum(close, w)
    slope = np.empty_like(sma)
    slope[:k] = np.nan
    slope[k:] = sma[k:] - sma[:-k]
    sig = np.where(
        (close > sma) & (slope > 0), 1.0,
        np.where((close < sma) & (slope < 0), -1.0, 0.0),
    )
    return sig


# ---------------------------------------------------------------------------
# RSI signal implementations
# ---------------------------------------------------------------------------

@register_signal("rsi", "rsi_level")
def _rsi_level(close: np.ndarray, params: dict, volume: np.ndarray) -> np.ndarray:
    period = int(params["period"])
    oversold = float(params["oversold"])
    overbought = float(params["overbought"])
    rsi_vals = rsi_wilder(close, period)
    # Action signal: +1 (oversold/buy), -1 (overbought/sell), 0 (neutral/no action)
    return np.where(rsi_vals < oversold, 1.0, np.where(rsi_vals > overbought, -1.0, 0.0))


# ---------------------------------------------------------------------------
# MACD signal implementations
# ---------------------------------------------------------------------------

@register_signal("macd", "macd_cross")
def _macd_cross_signal(close: np.ndarray, params: dict, volume: np.ndarray) -> np.ndarray:
    fast = int(params["fast"])
    slow = int(params["slow"])
    sig_period = int(params["signal"])
    macd_line, sig_line, _ = macd_pack(close, fast, slow, sig_period)
    return np.where(macd_line > sig_line, 1.0, np.where(macd_line < sig_line, -1.0, 0.0))


# ---------------------------------------------------------------------------
# OBV signal implementations
# ---------------------------------------------------------------------------

@register_signal("obv", "obv_trend")
def _obv_trend(close: np.ndarray, params: dict, volume: np.ndarray) -> np.ndarray:
    ema_period = int(params["ema_period"])
    obv = obv_array(close, volume)
    obv_ema = ema(obv, ema_period)
    return np.where(obv > obv_ema, 1.0, np.where(obv < obv_ema, -1.0, 0.0))


# ---------------------------------------------------------------------------
# Walk-forward OOS evaluation
# ---------------------------------------------------------------------------

# Families whose signals are actions (+1=buy, -1=sell, 0=do nothing)
# rather than positions (+1=long, -1=short).
_ACTION_FAMILIES = frozenset({"rsi"})


def _actions_to_positions(actions: np.ndarray) -> np.ndarray:
    """Convert action signals to position signals via forward-fill.

    +1 (buy) sets position to +1 (long), -1 (sell) sets position to -1 (short),
    0 (no action) keeps the current position.
    """
    positions = np.zeros_like(actions)
    pos = 0.0
    for i in range(len(actions)):
        if actions[i] != 0.0:
            pos = actions[i]
        positions[i] = pos
    return positions


def apply_cooldown(sig: np.ndarray, cooldown_bars: int) -> np.ndarray:
    """Return a copy of *sig* with cooldown applied.

    After any signal change at bar *i*, bars i+1 … i+cooldown_bars are
    forced to hold the same value as bar *i* (further changes suppressed).
    """
    out = sig.copy()
    if cooldown_bars <= 0:
        return out
    i = 1
    while i < len(out):
        if out[i] != out[i - 1]:
            # Signal changed at bar i — hold this value for cooldown_bars
            end = min(i + 1 + cooldown_bars, len(out))
            out[i + 1:end] = out[i]
            i = end
        else:
            i += 1
    return out


def _max_drawdown(returns: np.ndarray) -> float:
    """Max drawdown from a return series (not equity curve)."""
    if len(returns) == 0:
        return 0.0
    equity = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / np.where(peak > 0, peak, 1.0)
    return float(np.nanmax(dd)) if len(dd) > 0 else 0.0


def evaluate_variant_oos(
    close: np.ndarray,
    variant: VariantDef,
    horizon: str,
    cost_bps: float = 10.0,
    *,
    cooldown_bars: int = 0,
    volume: np.ndarray | None = None,
    window_config: MethodologyWindow | None = None,
    min_valid_windows: int = 3,
    min_test_bars_valid: int = 20,
) -> list[OOSWindowResult]:
    """Rolling walk-forward OOS evaluation.

    Returns a list of OOSWindowResult.  Empty if fewer than 3 valid windows.
    Signal at close(t), return = close[t+1]/close[t] - 1.  No look-ahead.
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

    # Need at least train + test + 1 bars (the +1 is for the next-bar return)
    min_bars = train_len + test_len + 1
    if n < min_bars:
        return []

    # Compute signal once on full close array (no look-ahead: indicators are causal)
    sig = compute_signal_array(close, variant, volume=volume)
    is_action = variant.family in _ACTION_FAMILIES

    cost_factor = cost_bps / 10_000.0
    results: list[OOSWindowResult] = []
    window_idx = 0

    for start in range(0, n - train_len - test_len, step):
        train_end = start + train_len           # exclusive
        test_start = train_end                  # no overlap
        test_end = min(test_start + test_len, n - 1)  # need close[t+1]

        oos_len = test_end - test_start
        if oos_len < 2:
            continue

        sig_raw = apply_cooldown(sig[test_start:test_end], cooldown_bars)
        close_oos = close[test_start:test_end + 1]  # +1 for next-bar return

        price_ret = close_oos[1:] / close_oos[:-1] - 1.0

        if is_action:
            # Action signals: +1=buy, -1=sell, 0=do nothing
            # Convert to positions via forward-fill for return calculation
            sig_oos = _actions_to_positions(sig_raw)
        else:
            # Position signals: +1=long, -1=short
            sig_oos = sig_raw

        # Unified cost model: charge on position changes only (Chan 2008)
        sig_change = np.abs(np.diff(sig_oos, prepend=0.0))

        ret = sig_oos * price_ret - cost_factor * sig_change

        n_trades = int(np.sum(sig_change > 0))
        n_bars = len(ret)
        mean_ret = float(np.mean(ret)) if n_bars > 0 else 0.0
        frac_pos = float(np.mean(ret > 0)) if n_bars > 0 else 0.0

        sr = sharpe_ratio(ret)
        if not math.isfinite(sr):
            sr = 0.0

        mdd = _max_drawdown(ret)

        is_valid = n_bars >= min_test_bars_valid

        total_return = float(np.prod(1.0 + ret) - 1.0)
        window_cagr = (1.0 + total_return) ** (252.0 / max(n_bars, 1)) - 1.0 if total_return > -1.0 else -1.0
        window_pnl = 100_000.0 * total_return

        results.append(OOSWindowResult(
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
        ))
        window_idx += 1

    # Require at least the requested number of valid windows
    n_valid = sum(1 for w in results if w.is_valid)
    if n_valid < min_valid_windows:
        return []

    return results
