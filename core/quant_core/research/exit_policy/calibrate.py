"""Walk-forward MAE/MFE calibration and Kelly sizing for exit policies.

No-look-ahead invariant: for trade i, calibration uses only trades 0..i-1.
The shuffle-invariance test in test_exit_policy_calibration.py verifies this.
"""
from __future__ import annotations

import numpy as np

from .paths import TradePath
from .policies import ExitResult, simulate_B, DEFAULT_K_SL, DEFAULT_K_TP

_MIN_CALIB_TRADES: int = 20
_MIN_KELLY_TRADES: int = 3


# ── MAE/MFE → k-multiple calibration ─────────────────────────────────────────

def _calibrate_k_from_history(
    past_paths: list[TradePath],
    *,
    k_sl_pct: float = 0.90,
    k_tp_pct: float = 0.50,
) -> tuple[float, float]:
    """Compute (k_sl, k_tp) from past paths' MAE/MFE distributions.

    k_sl: the k_sl_pct percentile of |MAE|/ATR from WINNING trades.
    k_tp: the k_tp_pct percentile of  MFE/ATR  from ALL trades.
    Winning = pnl_return > 0 (natural signal return, not the bracketed return).
    """
    winning_mae_k: list[float] = []
    mfe_k: list[float] = []

    for path in past_paths:
        if path.atr_entry <= 0.0 or path.open_price == 0.0:
            continue
        atr = path.atr_entry
        entry = abs(path.open_price)

        # MFE k (all trades)
        if path.mfe > 0.0:
            mfe_k.append(path.mfe * entry / atr)

        # MAE k (winning trades only)
        if path.pnl_return > 0.0 and path.mae < 0.0:
            winning_mae_k.append(abs(path.mae) * entry / atr)

    k_sl = float(np.nanpercentile(winning_mae_k, k_sl_pct * 100)) if winning_mae_k else DEFAULT_K_SL
    k_tp = float(np.nanpercentile(mfe_k, k_tp_pct * 100)) if mfe_k else DEFAULT_K_TP
    k_sl = float(np.clip(k_sl, 0.5, 5.0))
    k_tp = float(np.clip(k_tp, 0.5, 5.0))
    return k_sl, k_tp


def walk_forward_c_params(
    paths: list[TradePath],
    *,
    min_calib_trades: int = _MIN_CALIB_TRADES,
    k_sl_pct: float = 0.90,
    k_tp_pct: float = 0.50,
) -> list[tuple[float, float]]:
    """Return (k_sl, k_tp) per trade, calibrated solely from prior trades.

    Trade i calibrates from paths[0..i-1].
    Falls back to static defaults when fewer than min_calib_trades are available.
    """
    k_values: list[tuple[float, float]] = []

    for i in range(len(paths)):
        if i < min_calib_trades:
            k_values.append((DEFAULT_K_SL, DEFAULT_K_TP))
        else:
            k_sl, k_tp = _calibrate_k_from_history(
                paths[:i],
                k_sl_pct=k_sl_pct,
                k_tp_pct=k_tp_pct,
            )
            k_values.append((k_sl, k_tp))

    return k_values


# ── Kelly sizing ──────────────────────────────────────────────────────────────

def compute_half_kelly(returns: list[float]) -> float:
    """Half-Kelly fraction from a list of past trade returns.

    Formula: f* = (p*(b+1) - 1) / b  (full Kelly); half = f*/2.
    Clamped to [0.01, 0.5]. Returns 0.1 if insufficient data.
    """
    if not returns:
        return 0.1
    arr = np.asarray(returns, dtype=np.float64)
    wins = arr[arr > 0.0]
    losses = arr[arr < 0.0]
    p = len(wins) / len(arr)
    if len(wins) == 0 or len(losses) == 0:
        return 0.01
    b = float(wins.mean()) / float(abs(losses.mean()))
    if b <= 0.0:
        return 0.01
    full_kelly = (p * (b + 1.0) - 1.0) / b
    half = max(0.0, full_kelly) / 2.0
    return float(np.clip(half, 0.01, 0.5))


def walk_forward_kelly(
    effective_returns: list[float],
    *,
    min_trades: int = _MIN_KELLY_TRADES,
    initial: float = 0.1,
) -> list[float]:
    """Kelly fraction per trade, calibrated from all prior trades' effective returns.

    Returns list of length len(effective_returns); element i uses returns[0..i-1].
    """
    fractions: list[float] = []
    for i in range(len(effective_returns)):
        if i < min_trades:
            fractions.append(initial)
        else:
            fractions.append(compute_half_kelly(effective_returns[:i]))
    return fractions
