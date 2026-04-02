"""Tests for strategy_plan.universe — stock universe filtering."""

import pytest

from core.quant_core.strategy_plan.universe import filter_universe


def _make_stock(symbol: str, row_count: int = 500, sector: str = "Banques", adv20: float | None = 100_000.0) -> dict:
    return {
        "symbol": symbol,
        "display_name": f"{symbol} SA",
        "sector": sector,
        "row_count": row_count,
        "data_as_of": "2026-03-20",
        "adv20": adv20,
    }


def _make_scores(*pairs: tuple[str, float]) -> dict:
    """Build signal_scores dict from (symbol, score) pairs."""
    return {
        sym: {
            "aggregate_score_pct": score,
            "aggregate_signal_label": "Neutre",
            "per_family": {"sma": {"score_pct": score}},
        }
        for sym, score in pairs
    }


class TestFilterUniverse:
    def test_basic_enrichment(self):
        stocks = [_make_stock("AAA")]
        scores = _make_scores(("AAA", 42.5))
        result = filter_universe(stocks, scores)
        assert len(result) == 1
        assert result[0]["signal_score"] == 42.5
        assert result[0]["eligible"] is True
        assert result[0]["exclusion_reason"] is None

    def test_min_bars_filter(self):
        stocks = [_make_stock("AAA", row_count=100)]
        scores = _make_scores(("AAA", 50.0))
        result = filter_universe(stocks, scores, min_bars=252)
        assert result[0]["eligible"] is False
        assert "Historique" in result[0]["exclusion_reason"]

    def test_signal_threshold(self):
        stocks = [_make_stock("AAA"), _make_stock("BBB")]
        scores = _make_scores(("AAA", 10.0), ("BBB", 60.0))
        result = filter_universe(stocks, scores, min_abs_signal=30.0)
        eligible = [r for r in result if r["eligible"]]
        assert len(eligible) == 1
        assert eligible[0]["symbol"] == "BBB"

    def test_sector_filter(self):
        stocks = [
            _make_stock("AAA", sector="Banques"),
            _make_stock("BBB", sector="Mines"),
        ]
        scores = _make_scores(("AAA", 50.0), ("BBB", 50.0))
        result = filter_universe(stocks, scores, sector_filter=["Banques"])
        eligible = [r for r in result if r["eligible"]]
        assert len(eligible) == 1
        assert eligible[0]["symbol"] == "AAA"

    def test_sector_filter_with_official_bourse_labels(self):
        stocks = [
            _make_stock("AAA", sector="Santé"),
            _make_stock("BBB", sector="Services de transport"),
        ]
        scores = _make_scores(("AAA", 50.0), ("BBB", 50.0))
        result = filter_universe(stocks, scores, sector_filter=["Santé"])
        eligible = [r for r in result if r["eligible"]]
        assert len(eligible) == 1
        assert eligible[0]["symbol"] == "AAA"

    def test_missing_score(self):
        stocks = [_make_stock("AAA")]
        result = filter_universe(stocks, {})
        assert result[0]["eligible"] is False
        assert "indisponible" in result[0]["exclusion_reason"]

    def test_sorting_by_abs_signal(self):
        stocks = [_make_stock("AAA"), _make_stock("BBB"), _make_stock("CCC")]
        scores = _make_scores(("AAA", 10.0), ("BBB", -80.0), ("CCC", 50.0))
        result = filter_universe(stocks, scores, sort_by="signal_score", sort_dir="desc")
        symbols = [r["symbol"] for r in result]
        # Sorted by |score| desc: BBB(80) > CCC(50) > AAA(10)
        assert symbols == ["BBB", "CCC", "AAA"]

    def test_empty_input(self):
        assert filter_universe([], {}) == []

    def test_eligible_before_ineligible(self):
        stocks = [_make_stock("AAA", row_count=100), _make_stock("BBB")]
        scores = _make_scores(("AAA", 90.0), ("BBB", 10.0))
        result = filter_universe(stocks, scores, min_bars=252)
        # BBB eligible (10.0), AAA ineligible (90.0 but too few bars)
        assert result[0]["symbol"] == "BBB"
        assert result[0]["eligible"] is True
        assert result[1]["symbol"] == "AAA"
        assert result[1]["eligible"] is False

    def test_adv20_filter(self):
        stocks = [_make_stock("AAA", adv20=25_000), _make_stock("BBB", adv20=250_000)]
        scores = _make_scores(("AAA", 60.0), ("BBB", 20.0))
        result = filter_universe(stocks, scores, min_adv20=100_000)
        eligible = [row["symbol"] for row in result if row["eligible"]]
        assert eligible == ["BBB"]

    def test_sorting_by_adv20_desc(self):
        stocks = [
            _make_stock("AAA", adv20=100_000),
            _make_stock("BBB", adv20=300_000),
            _make_stock("CCC", adv20=200_000),
        ]
        scores = _make_scores(("AAA", 5.0), ("BBB", 5.0), ("CCC", 5.0))
        result = filter_universe(stocks, scores, sort_by="adv20", sort_dir="desc")
        assert [row["symbol"] for row in result] == ["BBB", "CCC", "AAA"]
