from __future__ import annotations

import pytest

from quant_core.fundamentals.valuation import (
    DEFAULT_ASSUMPTIONS,
    SCENARIO_DEFAULT_OVERRIDES,
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
    assert provenance["wacc"] == "symbol"


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
    assert resolved["terminal_growth"] == SCENARIO_DEFAULT_OVERRIDES["bear"]["terminal_growth"]
    assert provenance["terminal_growth"] == "scenario"
    assert resolved["wacc"] == pytest.approx(0.11)
    assert provenance["wacc"] == "symbol"
