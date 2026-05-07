from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from core.quant_core.signal_engine.ensemble import compute_family_score_timeseries


def _summary(variant_id: str, reliability: float) -> SimpleNamespace:
    return SimpleNamespace(
        variant=SimpleNamespace(variant_id=variant_id),
        reliability_score=reliability,
    )


def test_compute_family_score_timeseries_static_current_reps_matches_weighted_baseline(monkeypatch) -> None:
    calls: list[str] = []

    def fake_compute_variant_signal_array(close, variant, *, volume=None, high=None, low=None, cooldown_bars=0):
        calls.append(str(variant.variant_id))
        if variant.variant_id == "rep_a":
            return np.full(len(close), 1.0, dtype="float64")
        return np.full(len(close), -1.0, dtype="float64")

    monkeypatch.setattr(
        "core.quant_core.signal_engine.variant_detail.compute_variant_signal_array",
        fake_compute_variant_signal_array,
    )

    detail = SimpleNamespace(
        signal=SimpleNamespace(family="sma", symbol="IAM", horizon="medium", timeframe="1D"),
        all_summaries=[_summary("rep_a", 2.0), _summary("rep_b", 1.0)],
        representative_ids={"rep_a", "rep_b"},
        fallback_variant_ids=set(),
    )
    close = np.array([100.0, 101.0, 102.0], dtype="float64")

    out = compute_family_score_timeseries(detail, close)

    # ((2 * +1) + (1 * -1)) / 3 * 100 = 33.333...
    assert np.allclose(out, np.full(3, 100.0 / 3.0, dtype="float64"))
    assert sorted(calls) == ["rep_a", "rep_b"]


def test_compute_family_score_timeseries_dynamic_reselects_representatives_per_bar(monkeypatch) -> None:
    run_lengths: list[int] = []

    def fake_run_family_ensemble_full(
        family,
        close,
        *,
        volume=None,
        high=None,
        low=None,
        symbol,
        horizon="medium",
        timeframe="1D",
        cost_bps=10.0,
        cooldown_bars=0,
    ):
        run_lengths.append(len(close))
        rep_id = "rep_a" if len(close) <= 2 else "rep_b"
        return SimpleNamespace(
            all_summaries=[_summary("rep_a", 1.0), _summary("rep_b", 1.0)],
            representative_ids={rep_id},
            fallback_variant_ids=set(),
        )

    def fake_compute_variant_signal_array(close, variant, *, volume=None, high=None, low=None, cooldown_bars=0):
        value = 1.0 if variant.variant_id == "rep_a" else -1.0
        return np.full(len(close), value, dtype="float64")

    monkeypatch.setattr(
        "core.quant_core.signal_engine.ensemble.run_family_ensemble_full",
        fake_run_family_ensemble_full,
    )
    monkeypatch.setattr(
        "core.quant_core.signal_engine.variant_detail.compute_variant_signal_array",
        fake_compute_variant_signal_array,
    )

    detail = SimpleNamespace(
        signal=SimpleNamespace(family="sma", symbol="IAM", horizon="medium", timeframe="1D"),
        all_summaries=[],
        representative_ids=set(),
        fallback_variant_ids=set(),
    )
    close = np.array([100.0, 101.0, 102.0, 103.0], dtype="float64")

    out = compute_family_score_timeseries(
        detail,
        close,
        family_history_mode="dynamic_point_in_time",
        symbol="IAM",
        horizon="medium",
        timeframe="1D",
        signal_cost_bps=0.0,
    )

    assert run_lengths == [1, 2, 3, 4]
    assert np.allclose(out, np.array([100.0, 100.0, -100.0, -100.0], dtype="float64"))
