"""Signal generation engine — family-agnostic pipeline A→G."""

from .domain import (
    HORIZON_PARAMS,
    FamilyCombinedSignal,
    OOSWindowResult,
    VariantCurrentSignal,
    VariantDef,
    VariantRobustnessSummary,
)
from .ensemble import run_sma_ensemble

__all__ = [
    "HORIZON_PARAMS",
    "FamilyCombinedSignal",
    "OOSWindowResult",
    "VariantCurrentSignal",
    "VariantDef",
    "VariantRobustnessSummary",
    "run_sma_ensemble",
]
