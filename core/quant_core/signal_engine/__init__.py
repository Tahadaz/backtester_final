"""Signal generation engine — family-agnostic pipeline A→G."""

from .domain import (
    HORIZON_PARAMS,
    FamilyCombinedSignal,
    MethodologyContext,
    MethodologyWindow,
    OOSWindowResult,
    VariantCurrentSignal,
    VariantDef,
    VariantRobustnessSummary,
)
from .ensemble import run_sma_ensemble, run_family_ensemble, run_family_ensemble_full

__all__ = [
    "HORIZON_PARAMS",
    "FamilyCombinedSignal",
    "MethodologyContext",
    "MethodologyWindow",
    "OOSWindowResult",
    "VariantCurrentSignal",
    "VariantDef",
    "VariantRobustnessSummary",
    "run_sma_ensemble",
    "run_family_ensemble",
    "run_family_ensemble_full",
]
