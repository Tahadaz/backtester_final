"""Forward-estimate consensus layer (brief 54)."""
from .bkgr import BkgrAdapter
from .domain import (
    CANONICAL_METRICS,
    METRIC_EPS_FORWARD,
    METRIC_NI_FORWARD,
    METRIC_PER_FORWARD,
    METRIC_RATING,
    METRIC_REV_FORWARD,
    METRIC_TARGET_PRICE,
    ConsensusEstimate,
    ConsensusSource,
    ReconciliationResult,
)
from .reconcile import reconcile_consensus

__all__ = [
    "BkgrAdapter",
    "CANONICAL_METRICS",
    "METRIC_EPS_FORWARD",
    "METRIC_NI_FORWARD",
    "METRIC_PER_FORWARD",
    "METRIC_RATING",
    "METRIC_REV_FORWARD",
    "METRIC_TARGET_PRICE",
    "ConsensusEstimate",
    "ConsensusSource",
    "ReconciliationResult",
    "reconcile_consensus",
]
