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

from quant_core.optimize import sma_cumsum
from quant_core.significance import sharpe_ratio

from .domain import HORIZON_PARAMS, VALID_HORIZONS, OOSWindowResult, VariantDef

# ---------------------------------------------------------------------------
# Family-agnostic signal dispatch registry
# ---------------------------------------------------------------------------

_SIGNAL_DISPATCHERS: dict[tuple[str, str], Callable[[np.ndarray, dict], np.ndarray]] = {}


def register_signal(family: str, archetype: str):
    """Decorator: register a signal function for (family, archetype)."""
    def _wrap(fn: Callable[[np.ndarray, dict], np.ndarray]):
        _SIGNAL_DISPATCHERS[(family, archetype)] = fn
        return fn
    return _wrap


def compute_signal_array(close: np.ndarray, variant: VariantDef) -> np.ndarray:
    """Compute the signal array for *variant* on *close*.

    Returns an array of the same length as *close* with values in {-1.0, 0.0, +1.0}.
    Warmup / NaN bars are forced to 0.0 (flat policy).
    """
    key = (variant.family, variant.archetype)
    fn = _SIGNAL_DISPATCHERS.get(key)
    if fn is None:
        raise ValueError(f"No signal dispatcher for {key!r}")

    raw = fn(close, variant.params)

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
def _sma_price_vs_sma(close: np.ndarray, params: dict) -> np.ndarray:
    w = int(params["window"])
    sma = sma_cumsum(close, w)
    return np.where(close > sma, 1.0, np.where(close < sma, -1.0, 0.0))


@register_signal("sma", "sma_cross")
def _sma_cross(close: np.ndarray, params: dict) -> np.ndarray:
    fast = sma_cumsum(close, int(params["fast"]))
    slow = sma_cumsum(close, int(params["slow"]))
    return np.where(fast > slow, 1.0, np.where(fast < slow, -1.0, 0.0))


@register_signal("sma", "slope_confirmed")
def _sma_slope_confirmed(close: np.ndarray, params: dict) -> np.ndarray:
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
# Walk-forward OOS evaluation
# ---------------------------------------------------------------------------

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
) -> list[OOSWindowResult]:
    """Rolling walk-forward OOS evaluation.

    Returns a list of OOSWindowResult.  Empty if fewer than 3 valid windows.
    Signal at close(t), return = close[t+1]/close[t] - 1.  No look-ahead.
    """
    if horizon not in VALID_HORIZONS:
        raise ValueError(f"Unknown horizon {horizon!r}")

    hp = HORIZON_PARAMS[horizon]
    train_len = hp["train"]
    test_len = hp["test"]
    step = hp["step"]
    n = len(close)

    # Need at least train + test + 1 bars (the +1 is for the next-bar return)
    min_bars = train_len + test_len + 1
    if n < min_bars:
        return []

    # Compute signal once on full close array (no look-ahead: sma_cumsum is causal)
    sig = compute_signal_array(close, variant)

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

        sig_oos = sig[test_start:test_end]
        close_oos = close[test_start:test_end + 1]  # +1 for next-bar return

        # Bar returns: r[t] = sig[t] * (close[t+1]/close[t] - 1) - cost * |delta_sig|
        price_ret = close_oos[1:] / close_oos[:-1] - 1.0
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

        is_valid = n_bars >= 20

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
        ))
        window_idx += 1

    # Require at least 3 valid windows
    n_valid = sum(1 for w in results if w.is_valid)
    if n_valid < 3:
        return []

    return results
