"""Layer D — Survivor filtering.

Two-stage filter: viability gate (from Layer C) + competitive percentile.
"""

from __future__ import annotations

from .domain import VariantRobustnessSummary


def filter_survivors(
    summaries: list[VariantRobustnessSummary],
    *,
    competitive_percentile: float = 0.40,
    min_competitive_score: float = 0.25,
) -> list[VariantRobustnessSummary]:
    """Return survivors sorted descending by reliability_score."""
    # Stage 1: viability gate (set by robustness.py)
    viable = [s for s in summaries if s.is_viable]

    # Stage 2a: absolute floor
    above_floor = [s for s in viable if s.reliability_score >= min_competitive_score]
    if not above_floor:
        return []

    # Stage 2b: competitive percentile — keep top (1 - percentile) fraction
    above_floor.sort(key=lambda s: s.reliability_score, reverse=True)
    n_keep = max(1, int(len(above_floor) * (1.0 - competitive_percentile) + 0.5))
    return above_floor[:n_keep]
