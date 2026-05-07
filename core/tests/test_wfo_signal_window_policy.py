from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from core.quant_core.signal_engine.domain import VariantCurrentSignal, VariantDef
from core.quant_core.signal_engine.wfo_signal import (
    MANUAL_WINDOW_POLICY,
    _strict_window_candidates,
    run_wfo_category_signal,
)


def test_strict_window_candidates_respect_horizon_band_and_ratio() -> None:
    configs, diagnostics = _strict_window_candidates(
        horizon="short",
        data_length=1_260,
        max_lookback=50,
    )

    assert configs
    assert diagnostics["window_policy_used"] == "strict_fold_driven"
    for config in configs:
        assert 168 <= config.train_bars <= 336
        assert config.effective_step == config.oos_bars
        assert 0.25 <= (config.oos_bars / config.train_bars) <= 0.35


def test_strict_window_candidates_fallback_never_goes_below_floor() -> None:
    configs, diagnostics = _strict_window_candidates(
        horizon="medium",
        data_length=900,
        max_lookback=50,
        requested_min_walk_forwards=5,
        strict_fallback_enabled=True,
        strict_fallback_floor=3,
        top_k_folds=6,
    )

    assert configs
    assert diagnostics["effective_min_walk_forwards"] >= 3
    assert diagnostics["requested_min_walk_forwards"] == 5


def test_run_wfo_category_signal_manual_override_marks_policy(monkeypatch) -> None:
    variant = VariantDef(
        variant_id="sma_5",
        family="sma",
        archetype="price_vs_sma",
        params={"window": 5},
        description="SMA 5",
    )

    monkeypatch.setattr(
        "core.quant_core.signal_engine.wfo_signal.build_category_candidate_grid",
        lambda category, horizon, families=None: [variant],
    )
    monkeypatch.setattr(
        "core.quant_core.signal_engine.wfo_signal.compute_signal_array",
        lambda close, variant, **kwargs: np.ones(len(close), dtype=float),
    )
    monkeypatch.setattr(
        "core.quant_core.signal_engine.wfo_signal.build_current_signal",
        lambda variant, close, **kwargs: VariantCurrentSignal(
            variant_id=variant.variant_id,
            signal=1.0,
            signal_label="HAUSSIER",
            reliability_weight=kwargs.get("reliability_weight", 0.0),
            current_close=float(close[-1]),
            indicator_value=None,
            explanation="",
        ),
    )

    result = run_wfo_category_signal(
        "tendance",
        "short",
        np.linspace(100.0, 200.0, 220),
        train_bars=40,
        oos_bars=10,
        step_bars=10,
    )

    assert result.status == "succeeded"
    assert result.window_diagnostics["window_policy_used"] == MANUAL_WINDOW_POLICY
    assert result.config_used["train_bars"] == 40


def test_run_wfo_category_signal_defaults_to_single_best_rep(monkeypatch) -> None:
    best = VariantDef(
        variant_id="v_best",
        family="sma",
        archetype="price_vs_sma",
        params={"window": 5},
        description="Best",
    )
    second = VariantDef(
        variant_id="v_second",
        family="sma",
        archetype="price_vs_sma",
        params={"window": 10},
        description="Second",
    )
    third = VariantDef(
        variant_id="v_third",
        family="sma",
        archetype="price_vs_sma",
        params={"window": 20},
        description="Third",
    )
    pool = [best, second, third]

    monkeypatch.setattr(
        "core.quant_core.signal_engine.wfo_signal.build_category_candidate_grid",
        lambda category, horizon, families=None: pool,
    )
    monkeypatch.setattr(
        "core.quant_core.signal_engine.wfo_signal.run_wfo_engine",
        lambda **kwargs: SimpleNamespace(
            windows=[
                SimpleNamespace(
                    smoothed_scores={0: 0.9, 1: 0.7, 2: 0.5},
                    oos_return=0.1,
                )
            ],
            wfe=0.6,
            robustness_ratio=0.7,
        ),
    )
    monkeypatch.setattr(
        "core.quant_core.signal_engine.wfo_signal.compute_signal_array",
        lambda close, variant, **kwargs: np.ones(len(close), dtype=float),
    )
    monkeypatch.setattr(
        "core.quant_core.signal_engine.wfo_signal.build_current_signal",
        lambda variant, close, **kwargs: VariantCurrentSignal(
            variant_id=variant.variant_id,
            signal=1.0,
            signal_label="HAUSSIER",
            reliability_weight=kwargs.get("reliability_weight", 1.0),
            current_close=float(close[-1]),
            indicator_value=None,
            explanation=f"{variant.variant_id} signal",
        ),
    )

    result = run_wfo_category_signal(
        "tendance",
        "short",
        np.linspace(100.0, 200.0, 260),
        train_bars=60,
        oos_bars=20,
        step_bars=20,
    )

    assert result.status == "succeeded"
    assert len(result.representatives) == 1
    assert result.representatives[0]["variant_id"] == "v_best"


def test_run_wfo_category_signal_override_allows_multiple_reps(monkeypatch) -> None:
    variants = [
        VariantDef(
            variant_id=f"v_{idx}",
            family="sma",
            archetype="price_vs_sma",
            params={"window": 5 + idx},
            description=f"V{idx}",
        )
        for idx in range(3)
    ]

    monkeypatch.setattr(
        "core.quant_core.signal_engine.wfo_signal.build_category_candidate_grid",
        lambda category, horizon, families=None: variants,
    )
    monkeypatch.setattr(
        "core.quant_core.signal_engine.wfo_signal.run_wfo_engine",
        lambda **kwargs: SimpleNamespace(
            windows=[
                SimpleNamespace(
                    smoothed_scores={0: 0.9, 1: 0.8, 2: 0.7},
                    oos_return=0.1,
                )
            ],
            wfe=0.6,
            robustness_ratio=0.7,
        ),
    )
    monkeypatch.setattr(
        "core.quant_core.signal_engine.wfo_signal.compute_signal_array",
        lambda close, variant, **kwargs: np.array(
            [1.0 if i % 2 == 0 else 0.0 for i in range(len(close))],
            dtype=float,
        ),
    )
    monkeypatch.setattr(
        "core.quant_core.signal_engine.wfo_signal.build_current_signal",
        lambda variant, close, **kwargs: VariantCurrentSignal(
            variant_id=variant.variant_id,
            signal=1.0,
            signal_label="HAUSSIER",
            reliability_weight=kwargs.get("reliability_weight", 1.0),
            current_close=float(close[-1]),
            indicator_value=None,
            explanation=f"{variant.variant_id} signal",
        ),
    )

    result = run_wfo_category_signal(
        "tendance",
        "short",
        np.linspace(100.0, 200.0, 260),
        train_bars=60,
        oos_bars=20,
        step_bars=20,
        max_reps=3,
        max_corr=2.0,
    )

    assert result.status == "succeeded"
    assert len(result.representatives) == 3
