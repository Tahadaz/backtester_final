"""Layer H — Regime-aware signal conditioning via Kaufman Efficiency Ratio.

Kaufman (1995): ER = |direction| / volatility, range [0,1].
  - ER → 1: trending (SMA/MACD families favored)
  - ER → 0: ranging (RSI family favored)

Validation: walk-forward OOS using the same HORIZON_PARAMS windows as Layers A-G.
Regime weighting is only activated if it beats equal-weight OOS (conservative gate).

Sources:
  - Kaufman (1995/2013), Trading Systems and Methods
  - Pardo (2008), walk-forward validation
  - Ang & Timmermann (2012), regime-dependent behavior
  - De Prado (2018), separation of signal conditioning from portfolio construction
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from core.quant_core.significance import sharpe_ratio

from .domain import HORIZON_PARAMS, RegimeResult


# ---------------------------------------------------------------------------
# Kaufman Efficiency Ratio
# ---------------------------------------------------------------------------

def kaufman_er(close: np.ndarray, window: int = 20) -> np.ndarray:
    """Compute Kaufman Efficiency Ratio.

    ER[t] = |close[t] - close[t-window]| / sum(|close[i] - close[i-1]|, i=t-window+1..t)

    Returns array of same length as *close*.  First *window* values are NaN.
    """
    n = len(close)
    er = np.full(n, np.nan)
    if n <= window:
        return er

    # Absolute bar-to-bar changes
    abs_changes = np.abs(np.diff(close))  # length n-1

    # Rolling sum of absolute changes over *window* bars
    cum = np.cumsum(abs_changes)
    # volatility[t] = sum of |changes| from (t-window+1) to t  (using 0-based on abs_changes)
    # For index t in close (t >= window):
    #   volatility = cum[t-1] - cum[t-1-window]  (sum of window elements)
    for t in range(window, n):
        direction = abs(close[t] - close[t - window])
        volatility = cum[t - 1] - (cum[t - 1 - window] if t - 1 - window >= 0 else 0.0)
        if volatility > 0:
            er[t] = direction / volatility
        else:
            # Zero volatility → perfectly trending (all same-sign moves)
            er[t] = 1.0

    return er


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _family_returns(
    close: np.ndarray,
    signal: np.ndarray,
    cost_bps: float,
) -> np.ndarray:
    """Compute bar-by-bar returns for a family signal (Chan 2008 cost model).

    Returns array of length len(close)-1.
    """
    price_ret = close[1:] / close[:-1] - 1.0
    sig = signal[:-1]  # signal at close[t], return from t to t+1
    cost_factor = cost_bps / 10_000.0
    sig_change = np.abs(np.diff(sig, prepend=0.0))
    return sig * price_ret - cost_factor * sig_change


def _sharpe(returns: np.ndarray) -> float:
    """Annualized Sharpe, safe for empty or constant arrays."""
    if len(returns) < 2:
        return 0.0
    sr = sharpe_ratio(returns)
    return sr if math.isfinite(sr) else 0.0


def _regime_weights_from_sharpes(
    family_sharpes: dict[str, float],
) -> dict[str, float]:
    """Convert per-family Sharpes to normalized weights.

    w[f] = max(0, sharpe[f]) / sum(max(0, sharpe[all]))
    If all Sharpes ≤ 0 → equal weight (never zero-weight a family).
    """
    positives = {f: max(0.0, s) for f, s in family_sharpes.items()}
    total = sum(positives.values())
    n = len(family_sharpes)
    if total <= 0 or n == 0:
        return {f: 1.0 / n for f in family_sharpes} if n > 0 else {}
    return {f: positives[f] / total for f in family_sharpes}


# ---------------------------------------------------------------------------
# OOS regime validation
# ---------------------------------------------------------------------------

def validate_regime_oos(
    close: np.ndarray,
    family_signals: dict[str, np.ndarray],
    horizon: str,
    cost_bps: float,
    er_window: int = 20,
) -> RegimeResult:
    """Walk-forward OOS validation of regime-weighted vs equal-weight consensus.

    Uses the same WFO windows as the main signal pipeline (HORIZON_PARAMS).
    Returns RegimeResult with regime_active=True only if regime weighting
    beats equal-weight on average across OOS test windows.
    """
    families = sorted(family_signals.keys())
    n_families = len(families)
    n = len(close)

    # -- insufficient data guard --
    params = HORIZON_PARAMS.get(horizon)
    if params is None or n_families == 0:
        return _inactive_result("insufficient_data", n_families)

    train_len = params["train"]
    test_len = params["test"]
    step = params["step"]

    if n_families < 2:
        return _inactive_result("single_family", n_families)

    min_bars = train_len + test_len + 1

    if n < min_bars:
        return _inactive_result("insufficient_data", n_families)

    # -- compute ER once on full series --
    er = kaufman_er(close, window=er_window)

    # -- compute per-family returns once on full series --
    fam_returns: dict[str, np.ndarray] = {}
    for f in families:
        fam_returns[f] = _family_returns(close, family_signals[f], cost_bps)

    # -- walk-forward loop --
    window_results: list[dict[str, Any]] = []
    regime_sharpes: list[float] = []
    equal_sharpes: list[float] = []

    last_er_low = 0.0
    last_er_high = 0.0

    for start in range(0, n - train_len - test_len, step):
        train_end = start + train_len
        test_start = train_end
        test_end = min(test_start + test_len, n - 1)  # need returns[t] → close[t+1]
        oos_len = test_end - test_start
        if oos_len < 2:
            continue

        # --- TRAIN: compute tercile bounds & per-regime Sharpes ---
        er_train = er[start:train_end]
        valid_er = er_train[~np.isnan(er_train)]
        if len(valid_er) < 10:
            continue  # not enough ER data in this train window

        er_low = float(np.percentile(valid_er, 33))
        er_high = float(np.percentile(valid_er, 67))
        last_er_low, last_er_high = er_low, er_high

        # Classify train bars into regimes
        trending_mask = er_train > er_high
        ranging_mask = er_train < er_low
        # Note: er_train has NaN for first er_window bars; treat as neither
        trending_mask = trending_mask & ~np.isnan(er_train)
        ranging_mask = ranging_mask & ~np.isnan(er_train)

        # Per-family Sharpe by regime on train bars
        # Returns are length n-1 (shifted by 1 vs close), so slice [start:train_end-1]
        train_ret_slice = slice(start, train_end - 1)
        trending_ret_mask = trending_mask[:-1] if len(trending_mask) > 1 else trending_mask
        ranging_ret_mask = ranging_mask[:-1] if len(ranging_mask) > 1 else ranging_mask

        trending_sharpes: dict[str, float] = {}
        ranging_sharpes: dict[str, float] = {}
        for f in families:
            f_ret = fam_returns[f][train_ret_slice]
            # Ensure mask matches returns length
            t_mask = trending_ret_mask[:len(f_ret)]
            r_mask = ranging_ret_mask[:len(f_ret)]
            trending_sharpes[f] = _sharpe(f_ret[t_mask]) if np.any(t_mask) else 0.0
            ranging_sharpes[f] = _sharpe(f_ret[r_mask]) if np.any(r_mask) else 0.0

        trending_weights = _regime_weights_from_sharpes(trending_sharpes)
        ranging_weights = _regime_weights_from_sharpes(ranging_sharpes)

        # --- TEST: classify & compute returns ---
        er_test = er[test_start:test_end]

        # Per-bar regime weights (with linear blending for mixed)
        test_n = test_end - test_start
        if test_n < 1:
            continue

        regime_ret = np.zeros(test_n)
        equal_ret = np.zeros(test_n)

        for i in range(test_n):
            bar_er = er_test[i] if i < len(er_test) else np.nan

            # Determine weights for this bar
            if np.isnan(bar_er):
                bar_weights = {f: 1.0 / n_families for f in families}
            elif bar_er > er_high:
                bar_weights = trending_weights
            elif bar_er < er_low:
                bar_weights = ranging_weights
            else:
                # Linear blend
                alpha = (bar_er - er_low) / (er_high - er_low) if er_high > er_low else 0.5
                bar_weights = {
                    f: alpha * trending_weights[f] + (1 - alpha) * ranging_weights[f]
                    for f in families
                }

            # Weighted return vs equal-weight return
            for f in families:
                idx = test_start + i
                if idx < len(fam_returns[f]):
                    regime_ret[i] += bar_weights[f] * fam_returns[f][idx]
                    equal_ret[i] += (1.0 / n_families) * fam_returns[f][idx]

        r_sharpe = _sharpe(regime_ret)
        e_sharpe = _sharpe(equal_ret)
        regime_sharpes.append(r_sharpe)
        equal_sharpes.append(e_sharpe)

        window_results.append({
            "train_start": start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
            "er_low": round(er_low, 4),
            "er_high": round(er_high, 4),
            "regime_sharpe": round(r_sharpe, 4),
            "equal_sharpe": round(e_sharpe, 4),
            "trending_weights": {f: round(w, 4) for f, w in trending_weights.items()},
            "ranging_weights": {f: round(w, 4) for f, w in ranging_weights.items()},
        })

    # -- aggregate results --
    if not window_results:
        return _inactive_result("insufficient_data", n_families)

    improvements = [r - e for r, e in zip(regime_sharpes, equal_sharpes)]
    mean_improvement = float(np.mean(improvements))
    regime_active = mean_improvement > 0

    # Current ER and regime label
    current_er = _last_valid(er)
    if current_er is None:
        regime_label = "insufficient_data"
    elif current_er > last_er_high:
        regime_label = "trending"
    elif current_er < last_er_low:
        regime_label = "ranging"
    else:
        regime_label = "mixed"

    # Compute current regime weights from last fold
    if regime_active and window_results:
        last_fold = window_results[-1]
        if regime_label == "trending":
            current_weights = last_fold["trending_weights"]
        elif regime_label == "ranging":
            current_weights = last_fold["ranging_weights"]
        else:
            # Blend
            alpha = ((current_er - last_er_low) / (last_er_high - last_er_low)
                     if last_er_high > last_er_low else 0.5)
            current_weights = {
                f: round(alpha * last_fold["trending_weights"].get(f, 1.0 / n_families)
                         + (1 - alpha) * last_fold["ranging_weights"].get(f, 1.0 / n_families), 4)
                for f in families
            }
    else:
        current_weights = {f: round(1.0 / n_families, 4) for f in families}

    return RegimeResult(
        regime_active=regime_active,
        regime_label=regime_label if regime_active else ("inactive" if current_er is not None else "insufficient_data"),
        regime_weights=current_weights,
        er_value=round(current_er, 4) if current_er is not None else None,
        improvement=round(mean_improvement, 4),
        tercile_bounds=(round(last_er_low, 4), round(last_er_high, 4)),
        window_results=window_results,
        n_families=n_families,
    )


# ---------------------------------------------------------------------------
# Regime consensus (final output)
# ---------------------------------------------------------------------------

def compute_regime_consensus(
    per_family_scores: dict[str, float],
    regime_result: RegimeResult,
) -> dict[str, Any]:
    """Compute final consensus score using regime weights or equal-weight fallback.

    per_family_scores: {family: score_pct}  (e.g. {"sma": 42.5, "rsi": -10.0, ...})
    Returns dict with consensus, family_weights, per_family, regime metadata.
    """
    available = {
        f: per_family_scores[f]
        for f in per_family_scores
        if per_family_scores[f] is not None
    }
    if not available:
        return {
            "final_consensus": None,
            "family_weights": {},
            "per_family": {},
            "regime_active": regime_result.regime_active,
            "regime_label": regime_result.regime_label,
            "er_value": regime_result.er_value,
            "improvement": regime_result.improvement,
            "tercile_bounds": regime_result.tercile_bounds,
        }

    n = len(available)

    if regime_result.regime_active:
        # Use regime weights, normalized to available families only
        raw = {f: regime_result.regime_weights.get(f, 1.0 / n) for f in available}
        total = sum(raw.values())
        weights = {f: raw[f] / total for f in available} if total > 0 else {f: 1.0 / n for f in available}
    else:
        weights = {f: 1.0 / n for f in available}

    consensus = sum(available[f] * weights[f] for f in available)

    per_family = {
        f: {"score_pct": round(available[f], 2), "weight": round(weights[f], 4)}
        for f in available
    }

    return {
        "final_consensus": round(consensus, 2),
        "family_weights": {f: round(w, 4) for f, w in weights.items()},
        "per_family": per_family,
        "regime_active": regime_result.regime_active,
        "regime_label": regime_result.regime_label,
        "er_value": regime_result.er_value,
        "improvement": regime_result.improvement,
        "tercile_bounds": regime_result.tercile_bounds,
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _last_valid(arr: np.ndarray) -> float | None:
    """Return last non-NaN value, or None."""
    for i in range(len(arr) - 1, -1, -1):
        if not np.isnan(arr[i]):
            return float(arr[i])
    return None


def _inactive_result(label: str, n_families: int) -> RegimeResult:
    """Build an inactive RegimeResult with equal weights."""
    return RegimeResult(
        regime_active=False,
        regime_label=label,
        regime_weights={},
        er_value=None,
        improvement=0.0,
        tercile_bounds=(0.33, 0.67),
        window_results=[],
        n_families=n_families,
    )
