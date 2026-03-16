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
    max_corr: float = 0.85,
    max_reps: int = 6,
) -> list[VariantRobustnessSummary]:
    """Greedy selection: keep if max |corr| with all selected <= max_corr."""
    if len(survivors) <= 1:
        return list(survivors)

    # Sort by reliability descending
    ranked = sorted(survivors, key=lambda s: s.reliability_score, reverse=True)

    # Pre-compute signal arrays
    sig_arrays: list[np.ndarray] = [
        compute_signal_array(close, s.variant) for s in ranked
    ]

    selected_idx: list[int] = [0]  # start with best

    for i in range(1, len(ranked)):
        if len(selected_idx) >= max_reps:
            break
        candidate_sig = sig_arrays[i]
        is_redundant = False
        for j in selected_idx:
            corr = _pearson_corr(candidate_sig, sig_arrays[j])
            if abs(corr) > max_corr:
                is_redundant = True
                break
        if not is_redundant:
            selected_idx.append(i)

    return [ranked[i] for i in selected_idx]


def _pearson_corr(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation, handling constant arrays gracefully."""
    if len(a) != len(b) or len(a) < 2:
        return 0.0
    a_std = np.std(a)
    b_std = np.std(b)
    if a_std == 0 or b_std == 0:
        return 1.0 if np.array_equal(a, b) else 0.0
    return float(np.corrcoef(a, b)[0, 1])
