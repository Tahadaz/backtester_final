"""Domain types for the forward-estimate consensus layer (brief 54)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# Canonical metric names stored in fundamental_consensus_estimate.
METRIC_EPS_FORWARD = "EPS_Forward"
METRIC_NI_FORWARD = "NetIncome_Forward"
METRIC_REV_FORWARD = "Revenue_Forward"
METRIC_PER_FORWARD = "PER_Forward"
METRIC_TARGET_PRICE = "Target_Price"
METRIC_RATING = "Rating"

CANONICAL_METRICS = frozenset({
    METRIC_EPS_FORWARD,
    METRIC_NI_FORWARD,
    METRIC_REV_FORWARD,
    METRIC_PER_FORWARD,
    METRIC_TARGET_PRICE,
    METRIC_RATING,
})

# Upsert key: (symbol, fiscal_year, metric, source) — latest as_of_date wins.
# is_estimate is always True; these rows are NEVER commingled with reported actuals.


@dataclass(frozen=True)
class ConsensusEstimate:
    """One forward-estimate value for a (symbol, fiscal_year, metric, source) tuple."""

    symbol: str
    fiscal_year: int
    period_type: str           # "annual" (always for now)
    metric: str                # one of CANONICAL_METRICS
    value: float | None        # None for qualitative metrics like Rating stored as raw_label
    source: str                # e.g. "bkgr", "marketscreener"
    as_of_date: dt.date        # priced-as-of date from the source document
    currency: str = "MAD"
    raw_label: str | None = None    # original text value (ratings, units)
    analyst_count: int | None = None


@dataclass
class ReconciliationResult:
    """Output of reconcile_consensus() for a (symbol, fiscal_year, metric) triplet."""

    symbol: str
    fiscal_year: int
    metric: str
    reconciled_value: float | None   # median across sources
    source_values: dict[str, float | None] = field(default_factory=dict)
    contributing_sources: list[str] = field(default_factory=list)
    as_of_date: dt.date | None = None


@runtime_checkable
class ConsensusSource(Protocol):
    """Pluggable forward-estimate adapter (brief 54 §3 Phase 1)."""

    name: str

    def fetch(self, symbols: list[str] | None = None) -> list[ConsensusEstimate]:
        """Return estimates for the given symbols (None = all available)."""
        ...
