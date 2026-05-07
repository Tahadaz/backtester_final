from __future__ import annotations

import numpy as np

from quant_core.signal_engine.support_resistance import (
    build_ma_anchor_method,
    compute_score_inversion_levels,
    compute_representative_ma_anchor,
    finalize_support_resistance_methods,
)


def test_compute_representative_ma_anchor_uses_weighted_average() -> None:
    payload = compute_representative_ma_anchor(
        {
            "sma": {
                "representatives": [
                    {
                        "variant_id": "sma_20",
                        "archetype": "price_vs_sma",
                        "indicator_value": 98.0,
                        "normalized_weight": 0.75,
                    },
                    {
                        "variant_id": "ema_21",
                        "archetype": "price_vs_ema",
                        "indicator_value": 102.0,
                        "normalized_weight": 0.25,
                    },
                ]
            }
        }
    )

    assert payload["representative_count"] == 2
    assert payload["anchor"] == 99.0


def test_bullish_trend_uses_ma_anchor_as_support_only() -> None:
    method = build_ma_anchor_method({"anchor": 98.5, "representative_count": 2}, trend_score_pct=22.0)

    assert method["status"] == "available"
    assert method["support"] == 98.5
    assert method["resistance"] is None


def test_bearish_trend_uses_ma_anchor_as_resistance_only() -> None:
    method = build_ma_anchor_method({"anchor": 103.5, "representative_count": 2}, trend_score_pct=-22.0)

    assert method["status"] == "available"
    assert method["support"] is None
    assert method["resistance"] == 103.5


def test_neutral_trend_ignores_ma_anchor() -> None:
    method = build_ma_anchor_method({"anchor": 100.0, "representative_count": 1}, trend_score_pct=0.0)

    assert method["status"] == "ignored"
    assert method["support"] is None
    assert method["resistance"] is None


def test_finalize_support_resistance_filters_invalid_candidates() -> None:
    result = finalize_support_resistance_methods(
        100.0,
        [
            {
                "id": "score_inversion",
                "label": "Score",
                "support": 101.0,
                "resistance": 99.0,
                "status": "available",
            }
        ],
    )

    method = result["methods"][0]
    assert method["support"] is None
    assert method["resistance"] is None
    assert method["status"] == "ignored"
    assert result["final_support"] is None
    assert result["final_resistance"] is None


def test_finalize_support_chooses_highest_valid_level() -> None:
    result = finalize_support_resistance_methods(
        100.0,
        [
            {"id": "pivot_points", "label": "Pivots", "support": 94.0, "resistance": 109.0, "status": "available"},
            {"id": "swing_levels", "label": "Swings", "support": 97.0, "resistance": 112.0, "status": "available"},
        ],
    )

    assert result["final_support"] == 97.0
    assert result["selected_support_method_id"] == "swing_levels"


def test_finalize_resistance_chooses_lowest_valid_level() -> None:
    result = finalize_support_resistance_methods(
        100.0,
        [
            {"id": "pivot_points", "label": "Pivots", "support": 95.0, "resistance": 108.0, "status": "available"},
            {"id": "quantile_extrema_atr", "label": "Quantile", "support": 93.0, "resistance": 104.0, "status": "available"},
        ],
    )

    assert result["final_resistance"] == 104.0
    assert result["selected_resistance_method_id"] == "quantile_extrema_atr"


def test_finalize_uses_fixed_tie_break_order() -> None:
    result = finalize_support_resistance_methods(
        100.0,
        [
            {"id": "pivot_points", "label": "Pivots", "support": 95.0, "resistance": 110.0, "status": "available"},
            {"id": "ma_anchor", "label": "MA", "support": 95.0, "resistance": 110.0, "status": "available"},
        ],
    )

    assert result["selected_support_method_id"] == "ma_anchor"
    assert result["selected_resistance_method_id"] == "ma_anchor"


def test_finalize_handles_partial_methods_stably() -> None:
    result = finalize_support_resistance_methods(
        100.0,
        [
            {"id": "ma_anchor", "label": "MA", "support": None, "resistance": None, "status": "unavailable"},
            {"id": "swing_levels", "label": "Swings", "support": 96.0, "resistance": None, "status": "available"},
        ],
    )

    assert result["final_support"] == 96.0
    assert result["selected_support_method_id"] == "swing_levels"
    assert result["final_resistance"] is None
    assert result["selected_resistance_method_id"] is None


def test_score_inversion_budget_flag_is_exposed() -> None:
    close = np.array([98.0, 99.0, 100.0], dtype=float)
    snapshots = {
        "sma": {
            "representatives": [
                {
                    "variant_id": "sma_20",
                    "archetype": "price_vs_sma",
                    "params": {"window": 2},
                    "normalized_weight": 1.0,
                    "indicator_value": 99.0,
                }
            ]
        }
    }

    result = compute_score_inversion_levels(
        close,
        None,
        snapshots,
        scan_points=12,
        refine_steps=2,
        max_evals=1,
    )

    inputs = result.get("inputs") or {}
    assert inputs.get("budget_exceeded") is True
