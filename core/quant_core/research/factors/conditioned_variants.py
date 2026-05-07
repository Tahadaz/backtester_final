"""AND-composition of TA signals with factor conditions (Phase 2).

Core semantic: a factor-conditioned variant fires its underlying TA signal
(+1/-1) only when the factor condition is True on the same evaluation date.
When the condition is False the variant emits 0 (HOLD) — it does NOT invert
the TA signal and does NOT force an exit from an existing position.

Position-keeping rule: the HOLD emission here means "no new signal this bar".
The OOS evaluator downstream converts the signal array to positions using
signal_to_long_only_positions, which holds the previous position on 0, so
existing open positions are kept until a genuine TA exit (-1 from the native
indicator) fires.  This avoids whipsaw on factor-only state flips.
"""
from __future__ import annotations

import numpy as np

from core.quant_core.signal_engine.domain import FactorConditionMeta, VariantDef


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def compose_and_signal(
    ta_signal: np.ndarray,
    condition_mask: np.ndarray,
) -> np.ndarray:
    """Apply AND-gate: emit TA signal only when condition holds.

    Args:
        ta_signal:       1-D float array in {-1, 0, +1} from the native TA variant.
        condition_mask:  1-D bool array from evaluate_condition(); True = gate open.

    Returns:
        1-D float array: ta_signal where condition_mask is True, else 0.0.
    """
    ta = np.asarray(ta_signal, dtype=float)
    mask = np.asarray(condition_mask, dtype=bool)
    if ta.shape != mask.shape:
        raise ValueError(
            f"Shape mismatch: ta_signal {ta.shape} vs condition_mask {mask.shape}"
        )
    return np.where(mask, ta, 0.0)


# ---------------------------------------------------------------------------
# Naming utilities
# ---------------------------------------------------------------------------

FACTOR_X_TA_FAMILY_SUFFIX = "@fx"


def conditioned_family(ta_family: str) -> str:
    """Return the family string for a factor-conditioned variant."""
    return f"{ta_family}{FACTOR_X_TA_FAMILY_SUFFIX}"


def conditioned_description(ta_description: str, condition_id: str) -> str:
    """Return human-readable description for a factor-conditioned variant."""
    return f"{ta_description}@{condition_id}"


def conditioned_variant_id_params(ta_params: dict, condition_id: str) -> dict:
    """Return the params dict that, when hashed, gives a unique variant ID.

    The native TA params plus a 'factor_condition_id' key ensure the hash
    is distinct from the native TA variant's hash.
    """
    return {**ta_params, "factor_condition_id": condition_id}


def make_conditioned_variant(
    ta_variant: VariantDef,
    condition: FactorConditionMeta,
) -> VariantDef:
    """Wrap a native TA VariantDef in a factor condition to produce a new VariantDef.

    The returned variant has:
    - family:          "{ta_family}@fx"  (distinct family namespace)
    - archetype:       same as TA variant
    - params:          TA params + factor_condition_id key (for unique ID hashing)
    - description:     "{ta_desc}@{condition_id}"
    - factor_condition: the FactorConditionMeta
    - variant_id:      re-hashed from the extended params via compute_variant_id

    The native TA variant is NOT modified.
    """
    from core.quant_core.signal_engine._hashing import compute_variant_id

    new_family = conditioned_family(ta_variant.family)
    new_params = conditioned_variant_id_params(ta_variant.params, condition.condition_id)
    new_variant_id = compute_variant_id(new_family, new_params)
    new_description = conditioned_description(ta_variant.description, condition.condition_id)

    return VariantDef(
        variant_id=new_variant_id,
        family=new_family,
        archetype=ta_variant.archetype,
        params=new_params,
        description=new_description,
        factor_condition=condition,
    )
