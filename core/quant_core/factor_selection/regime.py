"""
Stage 2: structural-break detection with a Bai-Perron-style gate and PELT locations.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import ruptures as rpt
import statsmodels.api as sm


@dataclass(frozen=True)
class RegimeDetectionResult:
    breakpoints: list[pd.Timestamp]
    regime_start: pd.Timestamp | None
    low_confidence: bool
    history_n_days: int
    sup_f_stat: float | None
    break_detected: bool


def _fit_rss(y: np.ndarray) -> float:
    x = np.arange(len(y), dtype=float)
    X = sm.add_constant(x)
    fitted = sm.OLS(y, X).fit()
    return float(np.sum(fitted.resid ** 2))


def bai_perron_sup_f_gate(series: pd.Series, *, min_size: int = 60) -> tuple[bool, float | None]:
    clean = series.dropna()
    n_obs = len(clean)
    if n_obs < min_size * 2:
        return False, None

    y = clean.to_numpy(dtype=float)
    rss_pooled = _fit_rss(y)
    best_f = -np.inf
    for split in range(min_size, n_obs - min_size + 1):
        left = y[:split]
        right = y[split:]
        rss_split = _fit_rss(left) + _fit_rss(right)
        denom = rss_split / max(n_obs - 4, 1)
        if denom <= 0:
            continue
        f_stat = ((rss_pooled - rss_split) / 2.0) / denom
        best_f = max(best_f, f_stat)

    if best_f == -np.inf:
        return False, None

    # Conservative operational threshold for a first ship. This is a gate, not
    # the location detector; locations are delegated to PELT once this fires.
    return bool(best_f >= 8.0), float(best_f)


def detect_structural_breaks(
    series: pd.Series,
    *,
    min_size: int = 60,
    max_breaks: int = 5,
    penalty_scale: float = 3.0,
) -> list[pd.Timestamp]:
    clean_series = series.dropna()
    if len(clean_series) < min_size * 2:
        return []

    signal = clean_series.to_numpy(dtype=float).reshape(-1, 1)
    log_n = np.log(max(len(clean_series), 2))
    penalty = penalty_scale * log_n

    try:
        algo = rpt.Pelt(model="l2", min_size=min_size).fit(signal)
        result = algo.predict(pen=penalty)
    except Exception:
        return []

    points: list[pd.Timestamp] = []
    for idx in result[:-1][:max_breaks]:
        if 0 <= idx < len(clean_series):
            points.append(clean_series.index[idx])
    return points


def detect_regime_window(
    series: pd.Series,
    *,
    min_size: int = 60,
    min_history_days_for_breaks: int = 5 * 252,
) -> RegimeDetectionResult:
    clean = series.dropna()
    history_n_days = int(len(clean))
    if history_n_days == 0:
        return RegimeDetectionResult([], None, True, 0, None, False)

    if history_n_days < min_history_days_for_breaks:
        return RegimeDetectionResult([], clean.index[0], True, history_n_days, None, False)

    break_exists, sup_f_stat = bai_perron_sup_f_gate(clean, min_size=min_size)
    breakpoints = detect_structural_breaks(clean, min_size=min_size) if break_exists else []
    regime_start = breakpoints[-1] if breakpoints else clean.index[0]
    return RegimeDetectionResult(
        breakpoints=breakpoints,
        regime_start=regime_start,
        low_confidence=False,
        history_n_days=history_n_days,
        sup_f_stat=sup_f_stat,
        break_detected=bool(breakpoints),
    )
