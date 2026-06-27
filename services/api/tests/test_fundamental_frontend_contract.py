from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_frontend_scenario_probabilities_are_api_driven() -> None:
    source = (ROOT / "frontend/components/strategy/signal-fundamental-view.tsx").read_text(encoding="utf-8")

    assert "probability: 0.25" not in source
    assert "probability: 0.55" not in source
    assert "probability: 0.20" not in source
    assert "detail.scenario_probabilities" in source
    assert "scenario_probability_" in source


def test_frontend_year_headline_uses_official_target_not_forward_projection() -> None:
    source = (ROOT / "frontend/components/strategy/signal-fundamental-view.tsx").read_text(encoding="utf-8")

    assert "const officialTargetPrice =" in source
    assert 'activeHorizon === "year" ? officialTargetPrice' in source
    assert "Cible officielle" in source
    assert "Selection active" in source
    assert "valuationExcludedFromWorkingTarget" in source
