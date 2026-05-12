"""Technical-indicator combo variant helpers."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable

import numpy as np

from ._hashing import compute_variant_id
from .domain import FactorConditionMeta, VariantDef

CATEGORY_ORDER = ("tendance", "momentum", "oscillation", "volume")
COMBO_ARCHETYPE = "strict_and_pair"
COMBO_OPERATOR = "strict_and"
PURE_COMBO_PREFIXES = ("legacy_ta_combo", "expanded_ta_combo")
FX_COMBO_PREFIXES = ("legacy_fx_combo", "expanded_fx_combo")


def combo_family(prefix: str, category: str) -> str:
    return f"{prefix}_{category}"


def is_combo_family(family: str) -> bool:
    return any(str(family).startswith(f"{prefix}_") for prefix in (*PURE_COMBO_PREFIXES, *FX_COMBO_PREFIXES))


def is_combo_variant(variant: VariantDef) -> bool:
    components = variant.params.get("components") if isinstance(variant.params, dict) else None
    return variant.archetype == COMBO_ARCHETYPE and isinstance(components, list) and len(components) == 2


def primary_category_for_families(
    component_families: list[str],
    family_to_category: dict[str, str],
) -> str:
    categories = {family_to_category.get(family.split("@")[0], "") for family in component_families}
    for category in CATEGORY_ORDER:
        if category in categories:
            return category
    return CATEGORY_ORDER[0]


def factor_condition_to_dict(condition: FactorConditionMeta | None) -> dict[str, Any] | None:
    if condition is None:
        return None
    if is_dataclass(condition):
        return asdict(condition)
    return None


def component_payload(variant: VariantDef) -> dict[str, Any]:
    payload = {
        "family": variant.family,
        "archetype": variant.archetype,
        "variant_id": variant.variant_id,
        "params": dict(variant.params or {}),
        "description": variant.description,
    }
    condition = factor_condition_to_dict(variant.factor_condition)
    if condition is not None:
        payload["factor_condition"] = condition
    return payload


def factor_condition_from_payload(payload: dict[str, Any]) -> FactorConditionMeta | None:
    raw = payload.get("factor_condition")
    if not isinstance(raw, dict):
        return None
    try:
        return FactorConditionMeta(
            condition_id=str(raw["condition_id"]),
            factor_ticker=str(raw["factor_ticker"]),
            form=str(raw["form"]),
            lookback=int(raw["lookback"]),
            threshold=float(raw["threshold"]),
            direction=str(raw["direction"]),
        )
    except Exception:
        return None


def variant_from_component(payload: dict[str, Any]) -> VariantDef:
    return VariantDef(
        variant_id=str(payload["variant_id"]),
        family=str(payload["family"]),
        archetype=str(payload["archetype"]),
        params=dict(payload.get("params") or {}),
        description=str(payload.get("description") or ""),
        factor_condition=factor_condition_from_payload(payload),
    )


def make_combo_variant(
    *,
    family: str,
    components: list[VariantDef],
    primary_category: str,
    horizon: str,
    conditioning: str = "ta",
) -> VariantDef:
    if len(components) != 2:
        raise ValueError("Combo variants require exactly two components in V1")
    if any(is_combo_variant(component) for component in components):
        raise ValueError("Nested combo variants are not supported")
    component_families = [component.family for component in components]
    params: dict[str, Any] = {
        "operator": COMBO_OPERATOR,
        "components": [component_payload(component) for component in components],
        "primary_category": primary_category,
        "component_families": component_families,
        "conditioning": conditioning,
    }
    hash_params = {
        "archetype": COMBO_ARCHETYPE,
        "operator": COMBO_OPERATOR,
        "components": [component.variant_id for component in components],
        "conditioning": conditioning,
    }
    description = " AND ".join(component.description or component.variant_id for component in components)
    return VariantDef(
        variant_id=compute_variant_id(family, hash_params),
        family=family,
        archetype=COMBO_ARCHETYPE,
        params=params,
        description=f"{description} ({horizon})",
    )


def compute_strict_and_combo_signal(
    close: np.ndarray,
    variant: VariantDef,
    *,
    compute_component_signal: Callable[[VariantDef], np.ndarray],
) -> np.ndarray:
    if not is_combo_variant(variant):
        raise ValueError(f"Variant {variant.variant_id!r} is not a supported combo")
    components_raw = variant.params.get("components") or []
    components = [variant_from_component(payload) for payload in components_raw]
    if any(is_combo_variant(component) for component in components):
        raise ValueError("Nested combo variants are not supported")
    signals = [np.asarray(compute_component_signal(component), dtype=np.float64) for component in components]
    n = len(close)
    if any(len(sig) != n for sig in signals):
        raise ValueError("Combo component signal length mismatch")
    bullish = (signals[0] > 0.0) & (signals[1] > 0.0)
    bearish = (signals[0] < 0.0) & (signals[1] < 0.0)
    return np.where(bullish, 1.0, np.where(bearish, -1.0, 0.0))

