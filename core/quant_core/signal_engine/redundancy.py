"""Layer E — Redundancy reduction via greedy signal-correlation clustering.

Keeps the highest-reliability variant from each cluster of correlated signals.
"""

from __future__ import annotations

import numpy as np

from .domain import VariantRobustnessSummary
from .oos_eval import compute_signal_array


def reduce_redundancy(
    survivors: list[VariantRobustnessSummary],
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    max_corr: float = 0.85,
    max_reps: int = 10,
) -> tuple[
    list[VariantRobustnessSummary],
    dict[str, tuple[str, float]],
    dict[str, dict[str, float]],
]:
    """Greedy selection: keep if max |corr| with all selected <= max_corr.

    Returns
    -------
    representatives : selected variants
    redundancy_info : {eliminated_id: (correlated_with_id, corr_value)}
    correlation_matrix : {variant_id: {variant_id: corr_value}} for all survivors
    """
    if len(survivors) == 0:
        return [], {}, {}
    if len(survivors) == 1:
        vid = survivors[0].variant.variant_id
        return list(survivors), {}, {vid: {vid: 1.0}}

    # Sort by reliability descending
    ranked = sorted(survivors, key=lambda s: s.reliability_score, reverse=True)

    # Pre-compute signal arrays
    sig_arrays: list[np.ndarray] = [
        compute_signal_array(close, s.variant, volume=volume, high=high, low=low) for s in ranked
    ]
    variant_ids = [s.variant.variant_id for s in ranked]

    # Build pairwise correlation matrix
    n = len(ranked)
    corr_matrix_raw = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            c = _pearson_corr(sig_arrays[i], sig_arrays[j])
            corr_matrix_raw[i, j] = c
            corr_matrix_raw[j, i] = c

    # Convert to dict form
    correlation_matrix: dict[str, dict[str, float]] = {}
    for i in range(n):
        row: dict[str, float] = {}
        for j in range(n):
            row[variant_ids[j]] = round(float(corr_matrix_raw[i, j]), 4)
        correlation_matrix[variant_ids[i]] = row

    # Greedy selection with redundancy tracking
    selected_idx: list[int] = [0]  # start with best
    redundancy_info: dict[str, tuple[str, float]] = {}

    for i in range(1, len(ranked)):
        if len(selected_idx) >= max_reps:
            break
        is_redundant = False
        max_corr_with = ""
        max_corr_val = 0.0
        for j in selected_idx:
            corr = abs(corr_matrix_raw[i, j])
            if corr > max_corr_val:
                max_corr_val = corr
                max_corr_with = variant_ids[j]
            if corr > max_corr:
                is_redundant = True
                break
        if is_redundant:
            redundancy_info[variant_ids[i]] = (max_corr_with, round(max_corr_val, 4))
        else:
            selected_idx.append(i)

    representatives = [ranked[i] for i in selected_idx]
    return representatives, redundancy_info, correlation_matrix


def _pearson_corr(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation, handling constant arrays gracefully."""
    if len(a) != len(b) or len(a) < 2:
        return 0.0
    a_std = np.std(a)
    b_std = np.std(b)
    if a_std == 0 or b_std == 0:
        return 1.0 if np.array_equal(a, b) else 0.0
    return float(np.corrcoef(a, b)[0, 1])
