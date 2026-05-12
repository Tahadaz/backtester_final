import numpy as np

from core.quant_core.signal_engine.candidates import generate_candidates
from core.quant_core.signal_engine.domain import FactorConditionMeta, LEGACY_CATEGORY_FAMILIES
from core.quant_core.signal_engine.factor_x_ta import build_factor_x_ta_combo_pool_for_category
from core.quant_core.signal_engine.modes import resolve_signal_mode, signal_mode_storage_name
from core.quant_core.signal_engine.oos_eval import compute_signal_array
from core.quant_core.signal_engine.ta_combo import is_combo_variant, variant_from_component


def test_signal_mode_aliases_resolve_to_canonical_names():
    assert signal_mode_storage_name("legacy") == "legacy_ta_simple"
    assert signal_mode_storage_name("expanded") == "expanded_ta_simple"
    assert signal_mode_storage_name("factor_x_ta") == "expanded_factor_x_ta_simple"
    assert resolve_signal_mode("legacy_factor_x_ta_combo").is_combo
    assert resolve_signal_mode("legacy_factor_x_ta_combo").is_factor_x_ta


def test_ta_combo_candidates_are_cross_family_pairs():
    candidates = generate_candidates("legacy_ta_combo_tendance", "weekly")

    assert candidates
    first = candidates[0]
    assert is_combo_variant(first)
    components = [variant_from_component(payload) for payload in first.params["components"]]
    assert len({component.family for component in components}) == 2
    assert first.params["operator"] == "strict_and"
    assert first.params["primary_category"] == "tendance"


def test_pure_ta_combo_signal_requires_same_direction_components():
    close = np.linspace(100.0, 130.0, 80)
    combo = generate_candidates("legacy_ta_combo_tendance", "weekly")[0]

    combo_signal = compute_signal_array(close, combo)
    components = [variant_from_component(payload) for payload in combo.params["components"]]
    left = compute_signal_array(close, components[0])
    right = compute_signal_array(close, components[1])

    expected = np.where(
        (left > 0.0) & (right > 0.0),
        1.0,
        np.where((left < 0.0) & (right < 0.0), -1.0, 0.0),
    )
    np.testing.assert_allclose(combo_signal, expected)


def test_factor_x_ta_combo_pool_uses_conditioned_components():
    close = np.linspace(100.0, 130.0, 120)
    volume = np.full_like(close, 1_000.0)
    high = close + 1.0
    low = close - 1.0
    condition = FactorConditionMeta(
        condition_id="gate",
        factor_ticker="FACTOR",
        form="level",
        lookback=1,
        threshold=0.0,
        direction="above",
    )

    pool, precomputed = build_factor_x_ta_combo_pool_for_category(
        category="tendance",
        combo_family="legacy_fx_combo_tendance",
        category_families=LEGACY_CATEGORY_FAMILIES,
        horizon="weekly",
        close=close,
        aligned_factor_arrays={"FACTOR": np.ones_like(close)},
        conditions=[condition],
        volume=volume,
        high=high,
        low=low,
    )

    assert pool
    assert pool[0].variant_id in precomputed
    components = [variant_from_component(payload) for payload in pool[0].params["components"]]
    assert all(component.factor_condition is not None for component in components)
    assert precomputed[pool[0].variant_id].shape == close.shape
