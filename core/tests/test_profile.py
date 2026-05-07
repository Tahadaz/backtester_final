from __future__ import annotations

from core.quant_core.wfo.profile import evaluate_optimization_profile


def test_profile_rejects_catastrophic_landscape() -> None:
    raw = {f"p{i}": (-0.2 if i < 20 else 0.01) for i in range(21)}
    smoothed = dict(raw)
    smoothed["p20"] = 0.02
    result = evaluate_optimization_profile(raw, smoothed, "p20")
    assert not result.passes
    assert result.reason == "catastrophic"


def test_profile_rejects_outlier_winner() -> None:
    raw = {"a": 0.1, "b": 0.12, "c": 0.13, "d": 0.8, "e": 0.11}
    smoothed = {"a": 0.11, "b": 0.12, "c": 0.13, "d": 0.9, "e": 0.12}
    result = evaluate_optimization_profile(raw, smoothed, "d")
    assert not result.passes
    assert result.reason == "outlier"


def test_profile_passes_and_warns_on_high_cv() -> None:
    raw = {"a": 0.12, "b": 0.15, "c": 0.14, "d": 0.16, "e": 0.11}
    smoothed = {"a": 0.13, "b": 0.145, "c": 0.142, "d": 0.146, "e": 0.12}
    result = evaluate_optimization_profile(raw, smoothed, "d", neighbor_values=[0.001, 1.0, 0.002, 10.0])
    assert result.passes
    assert result.warnings
