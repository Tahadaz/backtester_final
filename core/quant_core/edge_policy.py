from __future__ import annotations

from typing import Any, Mapping, Sequence


EDGE_CONDITIONS = (
    "sample_size",
    "positive_expectancy",
    "positive_ci_lower",
    "hit_rate_ci",
    "mc_luck",
    "label_shuffle",
    "freshness",
    "proven_edge",
)

DEFAULT_EDGE_CONDITIONS = ("sample_size", "positive_expectancy")


def _first(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def passes_edge_policy(
    payload: Mapping[str, Any],
    *,
    min_edge_score: float = 50.0,
    required_conditions: Sequence[str] = DEFAULT_EDGE_CONDITIONS,
) -> bool:
    """Evaluate user-selectable Edge gates against snapshot or PIT provenance."""

    score = _first(payload, "edge_score")
    if score is None or float(score) < max(0.0, min(100.0, float(min_edge_score))):
        return False
    required = set(required_conditions)
    if not required.issubset(EDGE_CONDITIONS):
        return False
    checks = edge_condition_results(payload)
    return all(checks[name] for name in required)


def edge_condition_results(payload: Mapping[str, Any]) -> dict[str, bool]:
    """Return every named Edge gate using snapshot/PIT-compatible field names."""

    return {
        "sample_size": float(_first(payload, "n", "proof_n") or 0) >= 30,
        "positive_expectancy": float(
            _first(payload, "action_expected_return_net", "expected_return_net") or 0
        ) > 0,
        "positive_ci_lower": float(
            _first(payload, "action_expected_return_net_ci_lower", "ci_lower_net") or 0
        ) > 0,
        "hit_rate_ci": float(_first(payload, "hit_ci_lower") or 0) > 0.5,
        "mc_luck": float(
            1 if _first(payload, "mc_luck_pvalue_net_adj") is None
            else _first(payload, "mc_luck_pvalue_net_adj")
        ) <= 0.05,
        "label_shuffle": float(
            1 if _first(payload, "label_shuffle_pvalue_net_adj") is None
            else _first(payload, "label_shuffle_pvalue_net_adj")
        ) <= 0.05,
        "freshness": str(_first(payload, "freshness_status") or "").lower() == "passed",
        "proven_edge": bool(_first(payload, "proven_edge_net")),
    }
