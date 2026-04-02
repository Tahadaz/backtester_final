"""Tests for execution plan computation."""

import pytest
from quant_core.strategy_plan.execution import compute_execution_plan


# Shared fixtures
SUPPORTS = [
    {"price": 95.0, "bar_index": 80, "strength": 3},
    {"price": 88.0, "bar_index": 60, "strength": 2},
]
RESISTANCES = [
    {"price": 110.0, "bar_index": 85, "strength": 4},
    {"price": 120.0, "bar_index": 70, "strength": 2},
]


class TestExecutionPlan:
    """Unit tests for compute_execution_plan()."""

    def test_no_setup_low_conviction(self):
        """Consensus below threshold → no_setup."""
        plan = compute_execution_plan(
            consensus=10.0,
            side_policy="long_only",
            nearest_support=95.0,
            nearest_resistance=110.0,
            supports=SUPPORTS,
            resistances=RESISTANCES,
            atr=3.0,
            current_close=100.0,
            entry_threshold=20.0,
        )
        assert plan["status"] == "no_setup"
        assert plan["direction"] is None
        assert "insuffisante" in plan["explain"]

    def test_no_setup_none_consensus(self):
        """Consensus is None → no_setup."""
        plan = compute_execution_plan(
            consensus=None,
            side_policy="long_only",
            nearest_support=95.0,
            nearest_resistance=110.0,
            supports=SUPPORTS,
            resistances=RESISTANCES,
            atr=3.0,
            current_close=100.0,
        )
        assert plan["status"] == "no_setup"
        assert "indisponible" in plan["explain"]

    def test_long_only_blocks_short(self):
        """Negative consensus + long_only → no_setup, not short."""
        plan = compute_execution_plan(
            consensus=-50.0,
            side_policy="long_only",
            nearest_support=95.0,
            nearest_resistance=110.0,
            supports=SUPPORTS,
            resistances=RESISTANCES,
            atr=3.0,
            current_close=100.0,
        )
        assert plan["status"] == "no_setup"
        assert plan["direction"] is None
        assert "Long Only" in plan["explain"]

    def test_long_entry_zone(self):
        """Price within [support, support+ATR] → entry_zone."""
        plan = compute_execution_plan(
            consensus=60.0,
            side_policy="long_only",
            nearest_support=98.0,
            nearest_resistance=115.0,
            supports=[{"price": 98.0, "bar_index": 80, "strength": 3}],
            resistances=[{"price": 115.0, "bar_index": 85, "strength": 4}],
            atr=3.0,
            current_close=100.0,  # in [98, 101]
            min_rr=1.0,
        )
        assert plan["status"] == "entry_zone"
        assert plan["direction"] == "long"
        assert plan["entry_price"] == pytest.approx(100.0)
        assert plan["entry_zone_low"] == pytest.approx(98.0)
        assert plan["entry_zone_high"] == pytest.approx(101.0)

    def test_long_watching(self):
        """Price outside entry zone → watching."""
        plan = compute_execution_plan(
            consensus=60.0,
            side_policy="long_only",
            nearest_support=90.0,
            nearest_resistance=110.0,
            supports=[{"price": 90.0, "bar_index": 80, "strength": 3}],
            resistances=RESISTANCES,
            atr=3.0,
            current_close=100.0,  # NOT in [90, 93]
        )
        assert plan["status"] == "watching"
        assert plan["direction"] == "long"

    def test_short_entry_zone(self):
        """Short setup — price in [resistance-ATR, resistance] → entry_zone."""
        plan = compute_execution_plan(
            consensus=-55.0,
            side_policy="long_short",
            nearest_support=85.0,
            nearest_resistance=102.0,
            supports=[{"price": 85.0, "bar_index": 60, "strength": 2}],
            resistances=[{"price": 102.0, "bar_index": 85, "strength": 4}],
            atr=3.0,
            current_close=100.0,  # in [99, 102]
            min_rr=1.0,
        )
        assert plan["status"] == "entry_zone"
        assert plan["direction"] == "short"

    def test_unfavorable_rr(self):
        """R:R below min_rr → unfavorable_rr."""
        # target_1 (resistance) is very close to entry, stop is far
        plan = compute_execution_plan(
            consensus=60.0,
            side_policy="long_only",
            nearest_support=98.0,
            nearest_resistance=101.0,
            supports=[{"price": 98.0, "bar_index": 80, "strength": 3}],
            resistances=[{"price": 101.0, "bar_index": 85, "strength": 4}],
            atr=5.0,
            current_close=100.0,
            min_rr=2.0,
            atr_multiplier=1.5,
        )
        assert plan["status"] == "unfavorable_rr"
        assert plan["rr_ratio"] is not None
        assert plan["rr_ratio"] < 2.0

    def test_stop_uses_more_protective(self):
        """Long stop should be min(structural, volatility)."""
        # Price 99 is in zone [97, 99] → entry_price = 99 (current_close)
        plan = compute_execution_plan(
            consensus=60.0,
            side_policy="long_only",
            nearest_support=97.0,
            nearest_resistance=115.0,
            supports=[{"price": 97.0, "bar_index": 80, "strength": 3}],
            resistances=[{"price": 115.0, "bar_index": 85, "strength": 4}],
            atr=2.0,
            current_close=99.0,
            atr_multiplier=1.5,
            buffer_pct=0.005,
        )
        # structural = 97 * (1 - 0.005) = 96.515
        # volatility = 99 - 2*1.5 = 96.0
        # stop = min(96.515, 96.0) = 96.0
        assert plan["stop_loss"] == pytest.approx(96.0, abs=0.01)
        assert plan["status"] == "entry_zone"

    def test_targets_from_levels(self):
        """Targets come from resistance levels (long) or support levels (short)."""
        plan = compute_execution_plan(
            consensus=60.0,
            side_policy="long_only",
            nearest_support=95.0,
            nearest_resistance=110.0,
            supports=SUPPORTS,
            resistances=RESISTANCES,
            atr=3.0,
            current_close=96.0,  # in [95, 98] entry zone
        )
        assert plan["target_1"] == pytest.approx(110.0)
        assert plan["target_2"] == pytest.approx(120.0)

    def test_no_levels_fallback(self):
        """No support/resistance → uses ATR-based fallback zone."""
        plan = compute_execution_plan(
            consensus=60.0,
            side_policy="long_only",
            nearest_support=None,
            nearest_resistance=None,
            supports=[],
            resistances=[],
            atr=3.0,
            current_close=100.0,
        )
        assert plan["direction"] == "long"
        assert plan["entry_zone_low"] == pytest.approx(97.0)
        assert plan["entry_zone_high"] == pytest.approx(100.0)
        assert plan["target_1"] is None
        assert plan["stop_loss"] is not None
        assert plan["status"] == "no_setup"
        assert "cible structurelle" in plan["explain"]
