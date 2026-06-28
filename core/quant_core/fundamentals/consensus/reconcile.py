"""Pure reconciliation logic for forward estimates (brief 54 §3 Phase 1).

reconcile_consensus() is a DB-free, pure function: it takes raw ConsensusEstimate
rows and returns one ReconciliationResult per (symbol, fiscal_year, metric).

Policy: median across sources (per brief 54 §3 Phase 1: swappable to source-priority).
Latest as_of_date wins when the same source provides multiple values for the same key.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

from .domain import ConsensusEstimate, ReconciliationResult


def reconcile_consensus(
    estimates: list[ConsensusEstimate],
) -> list[ReconciliationResult]:
    """Median-reconcile raw estimates across sources.

    Groups by (symbol, fiscal_year, metric).  Within each group, keeps only the
    latest as_of_date per source (upsert semantics), then takes the median of
    non-None numeric values.  All raw per-source values are preserved for audit.
    """
    # Group → latest per (symbol, fiscal_year, metric, source)
    latest: dict[tuple[str, int, str, str], ConsensusEstimate] = {}
    for est in estimates:
        key = (est.symbol, est.fiscal_year, est.metric, est.source)
        prior = latest.get(key)
        if prior is None or est.as_of_date >= prior.as_of_date:
            latest[key] = est

    # Group by (symbol, fiscal_year, metric) across sources
    groups: dict[tuple[str, int, str], list[ConsensusEstimate]] = defaultdict(list)
    for est in latest.values():
        groups[(est.symbol, est.fiscal_year, est.metric)].append(est)

    results: list[ReconciliationResult] = []
    for (symbol, fiscal_year, metric), group in sorted(groups.items()):
        numeric_vals = [e.value for e in group if e.value is not None]
        reconciled = median(numeric_vals) if numeric_vals else None
        latest_date = max((e.as_of_date for e in group), default=None)
        results.append(ReconciliationResult(
            symbol=symbol,
            fiscal_year=fiscal_year,
            metric=metric,
            reconciled_value=reconciled,
            source_values={e.source: e.value for e in group},
            contributing_sources=[e.source for e in group if e.value is not None],
            as_of_date=latest_date,
        ))
    return results
