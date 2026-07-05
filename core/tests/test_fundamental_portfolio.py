from __future__ import annotations

from quant_core.research.fundamental_portfolio import SfcPortfolioMember, build_sfc_target_weights, sfc_direction


def test_sfc_direction_never_maps_bottom_to_short() -> None:
    assert sfc_direction("top") == "long"
    assert sfc_direction("middle") == "neutral"
    assert sfc_direction("bottom") == "avoid"


def test_sfc_target_weights_zero_bottom_and_normalize_positive_names() -> None:
    weights = build_sfc_target_weights(
        [
            SfcPortfolioMember("AAA", "top", benchmark_weight=0.10),
            SfcPortfolioMember("BBB", "middle", benchmark_weight=0.10),
            SfcPortfolioMember("CCC", "bottom", benchmark_weight=0.10),
        ],
        active_cap=0.03,
    )

    assert weights["CCC"] == 0.0
    assert weights["AAA"] > weights["BBB"] > weights["CCC"]
    assert round(sum(weights.values()), 12) == 1.0


def test_sfc_target_weights_do_not_infer_shorts_when_all_bottom() -> None:
    weights = build_sfc_target_weights([SfcPortfolioMember("AAA", "bottom"), SfcPortfolioMember("BBB", "bottom")])

    assert weights == {"AAA": 0.0, "BBB": 0.0}
