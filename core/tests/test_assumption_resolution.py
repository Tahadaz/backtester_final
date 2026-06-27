from __future__ import annotations

import pytest

from quant_core.fundamentals.valuation import (
    DEFAULT_ASSUMPTIONS,
    SCENARIO_PROBABILITY_KEYS,
    SCENARIO_PROBABILITY_RENORMALIZED_WARNING,
    SCENARIO_DEFAULT_OVERRIDES,
    normalize_scenario_probabilities,
    resolve_assumptions,
)


def test_resolve_returns_defaults_when_no_override() -> None:
    resolved, provenance = resolve_assumptions("ATW", "bull")

    expected = {**DEFAULT_ASSUMPTIONS, **SCENARIO_DEFAULT_OVERRIDES["bull"]}
    assert resolved == expected
    for key in DEFAULT_ASSUMPTIONS:
        expected_layer = "scenario" if key in SCENARIO_DEFAULT_OVERRIDES["bull"] else "default"
        assert provenance[key] == expected_layer


def test_resolve_applies_symbol_override() -> None:
    resolved, provenance = resolve_assumptions(
        "ATW",
        "bull",
        overrides_loader=lambda symbol, scenario: {"wacc": 0.10} if (symbol, scenario) == ("ATW", "bull") else None,
    )

    assert resolved["wacc"] == pytest.approx(0.10)
    assert provenance["wacc"] == "user_override"


def test_resolve_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="unknown assumption key: foo"):
        resolve_assumptions("ATW", "base", overrides_loader=lambda _symbol, _scenario: {"foo": 1.0})


def test_resolve_provenance_layering() -> None:
    resolved, provenance = resolve_assumptions(
        "ATW",
        "bear",
        overrides_loader=lambda _symbol, _scenario: {"wacc": 0.11},
    )

    assert resolved["risk_free_rate"] == DEFAULT_ASSUMPTIONS["risk_free_rate"]
    assert provenance["risk_free_rate"] == "default"
    assert "terminal_growth" not in SCENARIO_DEFAULT_OVERRIDES["bear"]
    assert resolved["terminal_growth"] == DEFAULT_ASSUMPTIONS["terminal_growth"]
    assert provenance["terminal_growth"] == "default"
    assert resolved["wacc"] == pytest.approx(0.11)
    assert provenance["wacc"] == "user_override"


def test_scenario_probabilities_default_to_desk_policy() -> None:
    resolved, provenance = resolve_assumptions("ATW", "base")

    probabilities = {scenario: resolved[key] for scenario, key in SCENARIO_PROBABILITY_KEYS.items()}
    assert probabilities == {"bear": pytest.approx(0.25), "base": pytest.approx(0.55), "bull": pytest.approx(0.20)}
    assert sum(probabilities.values()) == pytest.approx(1.0)
    assert {provenance[key] for key in SCENARIO_PROBABILITY_KEYS.values()} == {"default"}


def test_scenario_probabilities_are_renormalized_after_override() -> None:
    resolved, provenance = resolve_assumptions(
        "ATW",
        "base",
        overrides_loader=lambda _symbol, _scenario: {
            "scenario_probability_bear": 0.40,
            "scenario_probability_base": 0.40,
            "scenario_probability_bull": 0.40,
        },
    )

    assert resolved["scenario_probability_bear"] == pytest.approx(1 / 3)
    assert resolved["scenario_probability_base"] == pytest.approx(1 / 3)
    assert resolved["scenario_probability_bull"] == pytest.approx(1 / 3)
    assert {provenance[key] for key in SCENARIO_PROBABILITY_KEYS.values()} == {"computed"}

    _normalized, _provenance, warnings = normalize_scenario_probabilities(
        {
            "scenario_probability_bear": 0.40,
            "scenario_probability_base": 0.40,
            "scenario_probability_bull": 0.40,
        }
    )
    assert warnings == [SCENARIO_PROBABILITY_RENORMALIZED_WARNING]
