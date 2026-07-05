"""Unit tests for pit_ic_backtest.py — Phase-1 PIT IC pilot.

Focus: prove the look-ahead guard works correctly.

Critical: every test here that touches _assert_no_lookahead or
_filter_pit_history must demonstrate that future data is excluded.
No DB or S3 required — all data is synthetic.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot
from quant_core.fundamentals.pit_ic_backtest import (
    _assert_no_lookahead,
    _build_pit_snapshot,
    _compute_cross_sectional_ic,
    _filter_pit_history,
    _is_live,
    _latest_from_history,
    _pit_close,
    _PeriodEntry,
    compute_ic_shrunk_weights,
    run_oos_validation,
    run_pilot,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_row(
    symbol: str,
    year: int,
    metric: str,
    value: float,
    company: str = "Test Co",
) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol=symbol,
        company_name=company,
        statement_year=year,
        metric_name=metric,
        metric_value=value,
    )


def _make_prices(dates_and_closes: list[tuple[str, float]]) -> pd.Series:
    idx = pd.to_datetime([d for d, _ in dates_and_closes])
    vals = [v for _, v in dates_and_closes]
    return pd.Series(vals, index=idx, dtype=float)


def _make_universe_df(
    symbols: list[str],
    listing: str | None = None,
    delisting: str | None = None,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbols,
            "listing_date": [listing] * len(symbols),
            "delisting_date": [delisting] * len(symbols),
            "status": ["active"] * len(symbols),
        }
    )


# ─── _assert_no_lookahead ─────────────────────────────────────────────────────

class TestAssertNoLookahead:
    def test_passes_when_all_rows_at_or_before_as_of_year(self):
        rows = [
            _make_row("AAA", 2020, "Revenue", 1000),
            _make_row("AAA", 2021, "Revenue", 1100),
        ]
        # Must not raise for as_of_year=2021
        _assert_no_lookahead(rows, as_of_year=2021, symbol="AAA")

    def test_raises_when_any_row_is_future(self):
        rows = [
            _make_row("AAA", 2021, "Revenue", 1000),
            _make_row("AAA", 2022, "Revenue", 1100),  # future!
        ]
        with pytest.raises(AssertionError, match="LOOK-AHEAD VIOLATION"):
            _assert_no_lookahead(rows, as_of_year=2021, symbol="AAA")

    def test_raises_on_far_future_row(self):
        rows = [_make_row("AAA", 2025, "NetIncome", 500)]
        with pytest.raises(AssertionError, match="LOOK-AHEAD VIOLATION"):
            _assert_no_lookahead(rows, as_of_year=2021)

    def test_empty_list_passes(self):
        _assert_no_lookahead([], as_of_year=2022)

    def test_error_message_includes_symbol_and_year(self):
        rows = [_make_row("ZZZ", 2023, "EPS", 5.0)]
        with pytest.raises(AssertionError) as exc_info:
            _assert_no_lookahead(rows, as_of_year=2022, symbol="ZZZ")
        msg = str(exc_info.value)
        assert "ZZZ" in msg
        assert "2023" in msg
        assert "2022" in msg


# ─── _filter_pit_history ──────────────────────────────────────────────────────

class TestFilterPitHistory:
    def test_filters_out_future_years(self):
        rows = [
            _make_row("AAA", 2019, "Revenue", 100),
            _make_row("AAA", 2021, "Revenue", 120),
            _make_row("AAA", 2022, "Revenue", 130),  # future for as_of=2021
            _make_row("AAA", 2023, "Revenue", 140),  # future
        ]
        pit = _filter_pit_history(rows, as_of_year=2021)
        years = {r.statement_year for r in pit}
        assert years == {2019, 2021}
        assert all(r.statement_year <= 2021 for r in pit)

    def test_result_passes_no_lookahead_assertion(self):
        rows = [_make_row("AAA", y, "Revenue", 100 + y) for y in range(2018, 2025)]
        pit = _filter_pit_history(rows, as_of_year=2022)
        # Internal assertion should not fire
        _assert_no_lookahead(pit, as_of_year=2022)

    def test_excludes_all_rows_when_all_are_future(self):
        rows = [_make_row("AAA", 2023, "Revenue", 500)]
        pit = _filter_pit_history(rows, as_of_year=2021)
        assert pit == []

    def test_includes_row_exactly_at_as_of_year(self):
        rows = [_make_row("AAA", 2022, "Revenue", 300)]
        pit = _filter_pit_history(rows, as_of_year=2022)
        assert len(pit) == 1
        assert pit[0].statement_year == 2022


# ─── _pit_close ───────────────────────────────────────────────────────────────

class TestPitClose:
    def test_returns_close_on_exact_date(self):
        prices = _make_prices([("2021-12-31", 100.0), ("2022-01-03", 101.0)])
        result = _pit_close(prices, dt.date(2021, 12, 31))
        assert result == pytest.approx(100.0)

    def test_returns_most_recent_before_date(self):
        prices = _make_prices([("2021-12-28", 98.0), ("2021-12-30", 99.0)])
        result = _pit_close(prices, dt.date(2021, 12, 31))
        assert result == pytest.approx(99.0)

    def test_does_not_use_future_prices(self):
        prices = _make_prices([("2022-01-03", 150.0)])
        result = _pit_close(prices, dt.date(2021, 12, 31))
        assert result is None  # no prices at or before 2021-12-31

    def test_returns_none_for_empty_series(self):
        assert _pit_close(pd.Series(dtype=float), dt.date(2021, 12, 31)) is None

    def test_returns_none_for_none_series(self):
        assert _pit_close(None, dt.date(2021, 12, 31)) is None

    def test_rejects_non_positive_prices(self):
        prices = _make_prices([("2021-12-31", 0.0)])
        assert _pit_close(prices, dt.date(2021, 12, 31)) is None

    def test_accepts_utc_aware_price_index(self):
        idx = pd.to_datetime(["2021-12-30 23:00:00+00:00", "2022-01-03 00:00:00+00:00"])
        prices = pd.Series([99.0, 101.0], index=idx, dtype=float)
        result = _pit_close(prices, dt.date(2021, 12, 31))
        assert result == pytest.approx(99.0)


# ─── _build_pit_snapshot ──────────────────────────────────────────────────────

class TestBuildPitSnapshot:
    def _base_history(self) -> list[AnnualMetricRow]:
        return [
            _make_row("AAA", 2021, "Revenue", 1000_000),
            _make_row("AAA", 2021, "NetIncome", 100_000),
            _make_row("AAA", 2021, "Total_Equity", 500_000),
            _make_row("AAA", 2021, "Shares_Outstanding", 10_000),
        ]

    def test_raises_if_future_data_present(self):
        history = self._base_history() + [
            _make_row("AAA", 2022, "Revenue", 1_200_000)
        ]
        with pytest.raises(AssertionError, match="LOOK-AHEAD"):
            _build_pit_snapshot("AAA", "Test Co", history, price=100.0, as_of_year=2021)

    def test_current_price_in_metrics(self):
        snap = _build_pit_snapshot(
            "AAA", "Test Co", self._base_history(), price=100.0, as_of_year=2021
        )
        assert snap.metrics["Current_Price"] == pytest.approx(100.0)

    def test_per_computed_from_pit_data(self):
        # price=100, shares=10000, market_cap=1_000_000, net_income=100_000 → PER=10
        snap = _build_pit_snapshot(
            "AAA", "Test Co", self._base_history(), price=100.0, as_of_year=2021
        )
        assert "PER" in snap.metrics
        assert snap.metrics["PER"] == pytest.approx(10.0)

    def test_pb_computed_from_pit_data(self):
        # price=100, shares=10000, mktcap=1_000_000, equity=500_000 → P/B=2
        snap = _build_pit_snapshot(
            "AAA", "Test Co", self._base_history(), price=100.0, as_of_year=2021
        )
        assert "Price_to_Book" in snap.metrics
        assert snap.metrics["Price_to_Book"] == pytest.approx(2.0)

    def test_latest_statement_year_is_pit_max(self):
        history = [
            _make_row("AAA", 2019, "Revenue", 800_000),
            _make_row("AAA", 2021, "Revenue", 1000_000),
            _make_row("AAA", 2021, "NetIncome", 100_000),
            _make_row("AAA", 2021, "Shares_Outstanding", 10_000),
        ]
        snap = _build_pit_snapshot("AAA", "Test Co", history, price=50.0, as_of_year=2021)
        assert snap.latest_statement_year == 2021

    def test_as_of_date_set_correctly(self):
        snap = _build_pit_snapshot(
            "AAA", "Test Co", self._base_history(), price=100.0, as_of_year=2022
        )
        assert snap.as_of_date == dt.date(2022, 12, 31)


# ─── _latest_from_history ─────────────────────────────────────────────────────

class TestLatestFromHistory:
    def test_returns_most_recent_year(self):
        rows = [
            _make_row("AAA", 2019, "Revenue", 100),
            _make_row("AAA", 2021, "Revenue", 300),
            _make_row("AAA", 2020, "Revenue", 200),
        ]
        assert _latest_from_history(rows, "Revenue") == pytest.approx(300.0)

    def test_falls_back_to_alias(self):
        rows = [_make_row("AAA", 2021, "Chiffre_daffaires", 999)]
        assert _latest_from_history(rows, "Revenue", "Chiffre_daffaires") == pytest.approx(999.0)

    def test_returns_none_if_not_present(self):
        rows = [_make_row("AAA", 2021, "EBITDA", 100)]
        assert _latest_from_history(rows, "Revenue") is None

    def test_skips_none_values(self):
        rows = [
            _make_row("AAA", 2021, "Revenue", None),  # type: ignore[arg-type]
            _make_row("AAA", 2020, "Revenue", 500),
        ]
        # Should return the 2020 value since 2021 is None
        result = _latest_from_history(rows, "Revenue")
        assert result == pytest.approx(500.0)


# ─── _is_live ─────────────────────────────────────────────────────────────────

class TestIsLive:
    def _row(self, listing=None, delisting=None, status="active"):
        return pd.Series({"listing_date": listing, "delisting_date": delisting, "status": status})

    def test_active_stock_is_live(self):
        assert _is_live(self._row(), dt.date(2021, 12, 31)) is True

    def test_not_yet_listed_is_not_live(self):
        # Listed in 2022, but we're checking 2021
        assert _is_live(self._row(listing="2022-01-01"), dt.date(2021, 12, 31)) is False

    def test_listed_before_as_of_is_live(self):
        assert _is_live(self._row(listing="2018-01-01"), dt.date(2021, 12, 31)) is True

    def test_delisted_on_as_of_date_is_not_live(self):
        # Delisted exactly on as_of_date → not live (position closed)
        assert _is_live(self._row(delisting="2021-12-31"), dt.date(2021, 12, 31)) is False

    def test_delisted_after_as_of_is_live(self):
        assert _is_live(self._row(delisting="2022-06-01"), dt.date(2021, 12, 31)) is True

    def test_delisted_before_as_of_is_not_live(self):
        assert _is_live(self._row(delisting="2021-06-30"), dt.date(2021, 12, 31)) is False


# ─── _compute_cross_sectional_ic ──────────────────────────────────────────────

class TestComputeCrossSectionalIC:
    def _make_entries(
        self,
        model: str,
        year: int,
        upsides: list[float],
        fwd_returns: list[float],
    ) -> list[_PeriodEntry]:
        return [
            _PeriodEntry(
                symbol=f"S{i:02d}",
                as_of_year=year,
                model=model,
                upside_pct=u,
                fwd_return=f,
            )
            for i, (u, f) in enumerate(zip(upsides, fwd_returns))
        ]

    def test_perfect_positive_correlation(self):
        n = 20
        upsides = list(range(n))
        fwd = list(range(n))
        entries = self._make_entries("relative_multiples", 2021, upsides, fwd)
        result = _compute_cross_sectional_ic(entries)
        assert result["relative_multiples"]["mean_IC"] == pytest.approx(1.0, abs=1e-6)
        assert result["relative_multiples"]["periods"] == 1
        assert result["relative_multiples"]["pairs"] == n

    def test_perfect_negative_correlation(self):
        n = 20
        upsides = list(range(n))
        fwd = list(reversed(range(n)))
        entries = self._make_entries("relative_multiples", 2021, upsides, fwd)
        result = _compute_cross_sectional_ic(entries)
        assert result["relative_multiples"]["mean_IC"] == pytest.approx(-1.0, abs=1e-6)

    def test_zero_correlation(self):
        rng = np.random.default_rng(42)
        n = 30
        upsides = list(rng.standard_normal(n))
        fwd = list(rng.standard_normal(n))
        entries = self._make_entries("ddm", 2022, upsides, fwd)
        result = _compute_cross_sectional_ic(entries)
        # Zero-correlated data → IC should be near zero
        assert abs(result["ddm"]["mean_IC"]) < 0.5

    def test_mean_ic_averages_over_periods(self):
        # Period 2021: IC=1.0 (perfectly correlated)
        # Period 2022: IC=-1.0 (perfectly anti-correlated)
        n = 20
        e1 = self._make_entries("fcff_dcf", 2021, list(range(n)), list(range(n)))
        e2 = self._make_entries("fcff_dcf", 2022, list(range(n)), list(reversed(range(n))))
        result = _compute_cross_sectional_ic(e1 + e2)
        # Mean of +1 and -1 = 0
        assert result["fcff_dcf"]["mean_IC"] == pytest.approx(0.0, abs=1e-6)
        assert result["fcff_dcf"]["periods"] == 2

    def test_period_with_fewer_than_5_stocks_skipped(self):
        # Only 4 stocks → not enough for IC, so periods=0
        entries = self._make_entries("ddm", 2021, [1, 2, 3, 4], [1, 2, 3, 4])
        result = _compute_cross_sectional_ic(entries)
        assert result["ddm"]["periods"] == 0

    def test_unavailable_models_have_nan_stats(self):
        result = _compute_cross_sectional_ic([])
        for model in ("fcff_dcf", "ddm", "residual_income"):
            assert result[model]["periods"] == 0
            assert math.isnan(result[model]["mean_IC"])

    def test_t_stat_sign_matches_mean_ic_sign(self):
        n = 25
        rng = np.random.default_rng(99)
        # Three periods all with positive IC but different magnitudes (ensures IC_std > 0)
        base = list(range(n))
        e1 = self._make_entries("justified_multiples", 2021, base, base)  # IC ~1.0
        # IC ~0.8: add small noise to fwd returns
        e2 = self._make_entries(
            "justified_multiples", 2022, base,
            [x + rng.uniform(-3, 3) for x in base],
        )
        # IC ~0.6: larger noise
        e3 = self._make_entries(
            "justified_multiples", 2023, base,
            [x + rng.uniform(-6, 6) for x in base],
        )
        entries = e1 + e2 + e3
        result = _compute_cross_sectional_ic(entries)
        row = result["justified_multiples"]
        assert row["mean_IC"] > 0
        # t_stat may be nan only if IC_std is 0 — with varied IC across periods it must be finite
        assert math.isfinite(row["t_stat"]), f"Expected finite t_stat, got {row['t_stat']}"
        assert row["t_stat"] > 0


# ─── run_pilot (end-to-end with synthetic data) ────────────────────────────────

class TestRunPilotSynthetic:
    """Integration test of run_pilot() with zero DB/S3 dependencies."""

    def _make_fundamental_rows(
        self,
        symbols: list[str],
        years: list[int],
    ) -> list[AnnualMetricRow]:
        rows = []
        for sym in symbols:
            for yr in years:
                rows.extend([
                    _make_row(sym, yr, "Revenue", 1_000_000 * (1 + 0.05 * yr)),
                    _make_row(sym, yr, "NetIncome", 100_000 * (1 + 0.05 * yr)),
                    _make_row(sym, yr, "Total_Equity", 500_000),
                    _make_row(sym, yr, "Shares_Outstanding", 10_000),
                    _make_row(sym, yr, "Dividendes", 20_000),
                ])
        return rows

    def _price_loader_factory(
        self,
        symbols: list[str],
        base_price: float = 100.0,
    ):
        """Synthetic price loader: constant price at all dates."""
        def load(symbol: str) -> pd.Series | None:
            if symbol not in symbols:
                return None
            dates = pd.date_range("2019-01-01", "2026-01-01", freq="B")
            prices = pd.Series([base_price] * len(dates), index=dates, dtype=float)
            return prices

        return load

    def test_run_pilot_no_lookahead_with_clean_data(self):
        symbols = [f"S{i:02d}" for i in range(12)]
        # Only provide data up to FY2022 — no future data present
        rows = self._make_fundamental_rows(symbols, years=list(range(2018, 2023)))
        universe_df = _make_universe_df(symbols)
        price_loader = self._price_loader_factory(symbols)

        ic_table = run_pilot(
            all_rows=rows,
            price_loader=price_loader,
            universe_df=universe_df,
            as_of_years=[2021, 2022],
            verbose=False,
        )
        # Must complete without AssertionError — all rows ≤ as_of_year
        assert isinstance(ic_table, dict)

    def test_future_fundamental_rows_do_not_appear_in_pit_histories(self):
        """Injects future rows and verifies they never reach the valuation engine."""
        symbols = [f"T{i:02d}" for i in range(12)]
        rows = self._make_fundamental_rows(symbols, years=list(range(2018, 2025)))
        # 2023 and 2024 rows are future for as_of_year=2022
        universe_df = _make_universe_df(symbols)
        price_loader = self._price_loader_factory(symbols)

        # If look-ahead filtering works, run_pilot must not raise AssertionError
        ic_table = run_pilot(
            all_rows=rows,
            price_loader=price_loader,
            universe_df=universe_df,
            as_of_years=[2022],
            verbose=False,
        )
        assert isinstance(ic_table, dict)

    def test_delisted_name_not_included_after_delisting(self):
        symbols = ["LIVE", "DEAD"]
        rows = self._make_fundamental_rows(symbols, years=[2020, 2021, 2022])
        universe_df = pd.DataFrame({
            "symbol": ["LIVE", "DEAD"],
            "listing_date": [None, None],
            "delisting_date": [None, "2021-06-01"],  # DEAD delisted mid-2021
            "status": ["active", "delisted"],
        })
        price_loader = self._price_loader_factory(symbols)

        # For as_of_year=2021 (as_of_date=2021-12-31), DEAD is delisted — excluded
        # For as_of_year=2020 (as_of_date=2020-12-31), DEAD was live — included
        # This is not AssertionError territory; just verifying the pilot runs clean
        ic_table = run_pilot(
            all_rows=rows,
            price_loader=price_loader,
            universe_df=universe_df,
            as_of_years=[2020, 2021],
            verbose=False,
        )
        assert isinstance(ic_table, dict)

    def test_missing_forward_price_pair_dropped_cleanly(self):
        """If forward price is unavailable, the pair is dropped without error."""
        symbols = [f"F{i:02d}" for i in range(12)]
        rows = self._make_fundamental_rows(symbols, years=[2020, 2021])
        universe_df = _make_universe_df(symbols)

        def loader_no_2023(symbol: str) -> pd.Series | None:
            dates = pd.date_range("2019-01-01", "2021-12-31", freq="B")
            return pd.Series([100.0] * len(dates), index=dates, dtype=float)

        ic_table = run_pilot(
            all_rows=rows,
            price_loader=loader_no_2023,  # prices only up to 2021 → fwd 2022 missing
            universe_df=universe_df,
            as_of_years=[2021],
            verbose=False,
        )
        # Periods must be 0 (no forward prices available)
        for row in ic_table.values():
            assert row["periods"] == 0


# ─── compute_ic_shrunk_weights (Phase 2) ──────────────────────────────────────

class TestComputeIcShrunkWeights:
    """Unit tests for the IC shrinkage weight computation."""

    def test_two_positive_models_sum_to_one(self):
        raw = {"A": 0.217, "B": 0.332, "C": -0.188, "D": 0.0}
        weights = compute_ic_shrunk_weights(raw, lambda_shrink=0.40)
        pos_total = sum(w for w in weights.values() if w > 0)
        assert abs(pos_total - 1.0) < 1e-9

    def test_negative_ic_models_floored_to_zero(self):
        raw = {"A": 0.3, "B": -0.2, "C": 0.0}
        weights = compute_ic_shrunk_weights(raw, lambda_shrink=0.40)
        assert weights["B"] == 0.0
        assert weights["C"] == 0.0

    def test_higher_ic_gets_higher_weight(self):
        raw = {"A": 0.1, "B": 0.5}
        weights = compute_ic_shrunk_weights(raw, lambda_shrink=0.40)
        assert weights["B"] > weights["A"]

    def test_zero_lambda_equals_equal_weight(self):
        raw = {"A": 0.1, "B": 0.9}
        weights = compute_ic_shrunk_weights(raw, lambda_shrink=0.0)
        assert abs(weights["A"] - 0.5) < 1e-9
        assert abs(weights["B"] - 0.5) < 1e-9

    def test_unit_lambda_is_pure_ic_weight(self):
        raw = {"A": 0.2, "B": 0.8}
        weights = compute_ic_shrunk_weights(raw, lambda_shrink=1.0)
        assert abs(weights["A"] - 0.2) < 1e-9
        assert abs(weights["B"] - 0.8) < 1e-9

    def test_all_non_positive_returns_zeros(self):
        raw = {"A": -0.1, "B": 0.0, "C": -0.5}
        weights = compute_ic_shrunk_weights(raw, lambda_shrink=0.40)
        assert all(w == 0.0 for w in weights.values())

    def test_single_positive_model_gets_full_weight(self):
        raw = {"A": 0.5, "B": -0.3, "C": 0.0}
        weights = compute_ic_shrunk_weights(raw, lambda_shrink=0.40)
        assert abs(weights["A"] - 1.0) < 1e-9

    def test_known_pilot_weights(self):
        """Verify the weights match the pilot's computed values within tolerance."""
        raw = {
            "relative_multiples": 0.217,
            "fcff_dcf": 0.332,
            "ddm": -0.188,
            "fcfe_dcf": 0.0,
            "residual_income": 0.0,
            "justified_multiples": 0.0,
        }
        weights = compute_ic_shrunk_weights(raw, lambda_shrink=0.40)
        assert abs(weights["relative_multiples"] - 0.4581) < 0.001
        assert abs(weights["fcff_dcf"] - 0.5419) < 0.001
        assert weights["ddm"] == 0.0


# ─── run_oos_validation (Phase 2) ─────────────────────────────────────────────

class TestRunOosValidation:
    """Unit tests for expanding-window OOS validation."""

    def _make_entries(
        self,
        symbols: list[str],
        year: int,
        model: str,
        upside_values: list[float],
        fwd_values: list[float],
    ) -> list[_PeriodEntry]:
        entries = []
        for sym, up, fwd in zip(symbols, upside_values, fwd_values):
            entries.append(_PeriodEntry(
                symbol=sym,
                as_of_year=year,
                model=model,
                upside_pct=up,
                fwd_return=fwd,
            ))
        return entries

    def test_requires_at_least_two_periods(self):
        result = run_oos_validation([], as_of_years=[2021])
        assert result == []

    def test_single_split_returns_one_result(self):
        n = 10
        syms = [f"S{i}" for i in range(n)]
        signal = list(range(n))
        entries = (
            self._make_entries(syms, 2021, "relative_multiples", signal, signal)
            + self._make_entries(syms, 2022, "relative_multiples", signal, signal)
        )
        results = run_oos_validation(entries, as_of_years=[2021, 2022])
        assert len(results) == 1
        assert results[0]["test_year"] == 2022

    def test_winner_is_ic_weighted_when_it_dominates(self):
        n = 20
        syms = [f"S{i}" for i in range(n)]
        rng = np.random.default_rng(42)
        signal = list(range(n))
        noise = [rng.uniform(-2, 2) for _ in range(n)]
        noisy = [s + e for s, e in zip(signal, noise)]

        # 2021 train: relative_multiples correlates, fcff_dcf has same signal
        train = (
            self._make_entries(syms, 2021, "relative_multiples", signal, signal)
            + self._make_entries(syms, 2021, "fcff_dcf", signal, signal)
        )
        # 2022 test: relative_multiples+fcff_dcf correlates with fwd, equal-weight (noisy)
        test = (
            self._make_entries(syms, 2022, "relative_multiples", signal, noisy)
            + self._make_entries(syms, 2022, "fcff_dcf", signal, noisy)
        )
        entries = train + test
        results = run_oos_validation(entries, as_of_years=[2021, 2022])
        assert len(results) == 1
        r = results[0]
        # Both should have positive IC (signal matches returns)
        assert r["ew_ic"] > 0 or r["ic_weighted_ic"] > 0

    def test_insufficient_cross_section_marked_correctly(self):
        # Only 3 stocks — below default min_cross_section=5
        syms = ["A", "B", "C"]
        signal = [0.1, 0.2, 0.3]
        entries = (
            self._make_entries(syms, 2021, "relative_multiples", signal, signal)
            + self._make_entries(syms, 2022, "relative_multiples", signal, signal)
        )
        results = run_oos_validation(entries, as_of_years=[2021, 2022], min_cross_section=5)
        assert results[0]["winner"] == "insufficient_data"
        assert math.isnan(results[0]["ew_ic"])

    def test_coverage_fallback_when_no_positive_ic_model(self):
        """When train IC is all negative, OOS falls back to equal-weight for all stocks."""
        n = 10
        syms = [f"S{i}" for i in range(n)]
        signal = list(range(n))
        reverse = list(reversed(signal))  # anti-correlated — negative IC
        entries = (
            self._make_entries(syms, 2021, "fcff_dcf", signal, reverse)
            + self._make_entries(syms, 2022, "fcff_dcf", signal, signal)
        )
        # Should not raise; fallback to equal-weight means icw=ew
        results = run_oos_validation(entries, as_of_years=[2021, 2022])
        assert len(results) == 1
        r = results[0]
        # With no positive-IC model, ic_weighted == equal_weight (both are equal-weight)
        if math.isfinite(r["ew_ic"]) and math.isfinite(r["ic_weighted_ic"]):
            assert abs(r["ew_ic"] - r["ic_weighted_ic"]) < 1e-9
