"""Tests for signal consensus computation."""

import pytest
from quant_core.strategy_plan.signal_policy import compute_consensus


class TestComputeConsensus:
    """Unit tests for compute_consensus()."""

    def test_equal_weight_4_families(self):
        scores = {"sma": 40.0, "rsi": -20.0, "macd": 60.0, "obv": 10.0}
        result = compute_consensus(scores, ["sma", "rsi", "macd", "obv"])

        assert result["final_consensus"] == pytest.approx(22.5)
        assert len(result["family_weights"]) == 4
        for w in result["family_weights"].values():
            assert w == pytest.approx(0.25)

    def test_2_families_disabled(self):
        scores = {"sma": 40.0, "rsi": -20.0, "macd": 60.0, "obv": 10.0}
        result = compute_consensus(scores, ["sma", "rsi"])

        assert result["final_consensus"] == pytest.approx(10.0)
        assert len(result["family_weights"]) == 2
        assert "macd" not in result["family_weights"]
        assert "obv" not in result["family_weights"]

    def test_all_disabled(self):
        scores = {"sma": 40.0, "rsi": -20.0}
        result = compute_consensus(scores, [])

        assert result["final_consensus"] is None
        assert result["family_weights"] == {}
        assert result["per_family"] == {}

    def test_missing_score_renormalize(self):
        # 4 enabled but only 3 have scores (obv missing)
        scores = {"sma": 30.0, "rsi": -30.0, "macd": 60.0}
        result = compute_consensus(scores, ["sma", "rsi", "macd", "obv"])

        # Should equal-weight among 3 available
        assert result["final_consensus"] == pytest.approx(20.0)
        assert len(result["family_weights"]) == 3
        for w in result["family_weights"].values():
            assert w == pytest.approx(1.0 / 3, abs=0.001)

    def test_single_family(self):
        scores = {"rsi": -45.0}
        result = compute_consensus(scores, ["rsi"])

        assert result["final_consensus"] == pytest.approx(-45.0)
        assert result["family_weights"]["rsi"] == pytest.approx(1.0)

    def test_per_family_output(self):
        scores = {"sma": 42.5, "rsi": -18.3}
        result = compute_consensus(scores, ["sma", "rsi"])

        assert "sma" in result["per_family"]
        assert result["per_family"]["sma"]["score_pct"] == 42.5
        assert result["per_family"]["sma"]["weight"] == pytest.approx(0.5)
