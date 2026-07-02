"""Unit tests for forecast_model.py -- brief 54 §3 Phase 4 model forecaster.

Focus: pure-function correctness (panel construction, sanity-band filtering,
Ridge fit/predict, expanding-window backtest mechanics). No DB required --
all data is synthetic, mirroring test_pit_ic_backtest.py's style.

The honest out-of-sample validation against real MASI data (the actual
Phase-4 gate: does the model beat naive CAGR?) lives in
services/api/scripts/forecast_model_validation.py, which needs a live DB and
therefore isn't part of the unit-test suite; its result is documented in the
forecast_model.py module docstring and the brief-54 plan doc.
"""
from __future__ import annotations

import numpy as np
import pytest

from quant_core.fundamentals.domain import AnnualMetricRow
from quant_core.fundamentals.forecast_model import (
    MIN_TRAIN_OBSERVATIONS,
    GrowthObservation,
    attach_sector_momentum,
    build_growth_observations,
    fit_growth_forecaster,
    forecast_symbol_growth,
    mechanical_momentum,
    predict_growth,
    run_expanding_window_backtest,
)
from quant_core.fundamentals.pit_ic_backtest import _filter_pit_history


def _row(symbol: str, year: int, metric: str, value: float, company: str = "Test Co") -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol=symbol,
        company_name=company,
        statement_year=year,
        metric_name=metric,
        metric_value=value,
    )


def _revenue_series(symbol: str, values: dict[int, float]) -> list[AnnualMetricRow]:
    return [_row(symbol, year, "Revenue", value) for year, value in sorted(values.items())]


# ─── mechanical_momentum ──────────────────────────────────────────────────────

class TestMechanicalMomentum:
    def test_matches_manual_blend_of_cagr_and_last_year_growth(self):
        # Revenue: 2020=100, 2021=110, 2022=121, 2023=139.15 (10% CAGR, then a
        # 15% jump in the last year).
        series = [(2020, 100.0), (2021, 110.0), (2022, 121.0), (2023, 139.15)]
        cagr_3y = (139.15 / 100.0) ** (1.0 / 3) - 1.0
        last_year_growth = 139.15 / 121.0 - 1.0
        expected = 0.5 * cagr_3y + 0.5 * last_year_growth
        assert mechanical_momentum(series) == pytest.approx(expected, rel=1e-9)

    def test_returns_none_for_single_point_series(self):
        assert mechanical_momentum([(2023, 100.0)]) is None

    def test_returns_none_for_empty_series(self):
        assert mechanical_momentum([]) is None

    def test_two_point_series_still_computable(self):
        # len(series) == 2 -> _growth_series has one point, _cagr also
        # computable from the same two points; blend of the two (which may
        # coincide).
        series = [(2022, 100.0), (2023, 110.0)]
        result = mechanical_momentum(series)
        assert result == pytest.approx(0.10, rel=1e-9)


# ─── build_growth_observations ────────────────────────────────────────────────

class TestBuildGrowthObservations:
    def test_basic_panel_with_sector_momentum(self):
        # Three same-sector symbols with clean revenue histories.
        histories = {
            "AAA": _revenue_series("AAA", {2019: 100, 2020: 110, 2021: 120, 2022: 132}),
            "BBB": _revenue_series("BBB", {2019: 200, 2020: 210, 2021: 230, 2022: 250}),
            "CCC": _revenue_series("CCC", {2019: 50, 2020: 55, 2021: 60, 2022: 63}),
        }
        sectors = {"AAA": "Banques", "BBB": "Banques", "CCC": "Banques"}
        obs = build_growth_observations(histories, sectors, 2022, ("Revenue",))
        assert {o.symbol for o in obs} == {"AAA", "BBB", "CCC"}
        momenta = sorted(o.momentum for o in obs)
        expected_sector_momentum = momenta[1]  # median of 3
        for o in obs:
            assert o.sector_momentum == pytest.approx(expected_sector_momentum)
        # No realized_histories_by_symbol supplied -> all targets None (live row).
        assert all(o.target is None for o in obs)

    def test_target_computed_from_realized_history(self):
        histories = {
            "AAA": _revenue_series("AAA", {2019: 100, 2020: 110, 2021: 120, 2022: 132}),
        }
        realized = {
            "AAA": _revenue_series("AAA", {2019: 100, 2020: 110, 2021: 120, 2022: 132, 2023: 145.2}),
        }
        sectors = {"AAA": "Banques"}
        obs = build_growth_observations(histories, sectors, 2022, ("Revenue",), realized_histories_by_symbol=realized)
        assert len(obs) == 1
        expected_target = 145.2 / 132.0 - 1.0
        assert obs[0].target == pytest.approx(expected_target, rel=1e-9)

    def test_missing_realized_year_leaves_target_none(self):
        histories = {"AAA": _revenue_series("AAA", {2019: 100, 2020: 110, 2021: 120, 2022: 132})}
        # realized history doesn't actually extend to 2023 -- target unknowable.
        realized = {"AAA": _revenue_series("AAA", {2019: 100, 2020: 110, 2021: 120, 2022: 132})}
        obs = build_growth_observations(histories, {"AAA": None}, 2022, ("Revenue",), realized_histories_by_symbol=realized)
        assert obs[0].target is None

    def test_excludes_symbol_with_insufficient_history(self):
        histories = {
            "AAA": _revenue_series("AAA", {2022: 100}),  # single point -> infeasible
            "BBB": _revenue_series("BBB", {2019: 200, 2020: 210, 2021: 230, 2022: 250}),
        }
        obs = build_growth_observations(histories, {}, 2022, ("Revenue",))
        assert {o.symbol for o in obs} == {"BBB"}

    def test_excludes_scale_bug_outlier_from_momentum(self):
        # A ~1e6x scale artifact in the trailing year (mirrors the real
        # IAM/MNG/BOA-class bug found in Phase-4 validation) must be dropped,
        # not treated as a legitimate multi-million-percent growth forecast.
        histories = {
            "ZZZ": _revenue_series("ZZZ", {2019: 1_000_000, 2020: 1_050_000, 2021: 1.05, 2022: 1_100_000}),
        }
        obs = build_growth_observations(histories, {}, 2022, ("Revenue",))
        assert obs == []

    def test_excludes_reversion_gap_outlier(self):
        # A long-ago data-gap growth spike (e.g. a unit-scale change between
        # 2010 and 2011, as seen for real MASI names spanning multi-year
        # reporting gaps) inflates own_trailing_mean far outside recent
        # experience even though recent-year momentum looks perfectly sane.
        # reversion_gap must catch this and the row must be dropped.
        series = {2010: 100.0, 2011: 100_000.0, 2019: 200.0, 2020: 210.0, 2021: 220.0, 2022: 231.0}
        histories = {"AAA": _revenue_series("AAA", series)}
        obs = build_growth_observations(histories, {}, 2022, ("Revenue",))
        assert obs == []

    def test_function_trusts_caller_pit_filtering(self):
        """build_growth_observations does not itself enforce PIT discipline --
        it trusts pit_histories_by_symbol, exactly like _build_pit_snapshot
        trusts its input. Demonstrate the contract: if a caller forgets to
        filter, a "future" row IS used (this is why service-layer callers
        MUST pre-filter via _filter_pit_history, as model_forecast.py does)."""
        unfiltered = _revenue_series("AAA", {2019: 100, 2020: 110, 2021: 120, 2022: 132, 2023: 500})
        obs_unfiltered = build_growth_observations({"AAA": unfiltered}, {}, 2022, ("Revenue",))

        filtered = _filter_pit_history(unfiltered, as_of_year=2022, symbol="AAA")
        obs_filtered = build_growth_observations({"AAA": filtered}, {}, 2022, ("Revenue",))

        assert obs_unfiltered[0].momentum != obs_filtered[0].momentum


# ─── attach_sector_momentum ───────────────────────────────────────────────────

class TestAttachSectorMomentum:
    def test_median_is_self_inclusive(self):
        obs = [
            GrowthObservation(symbol="A", sector="S", as_of_year=2022, momentum=0.10, reversion_gap=0.0),
            GrowthObservation(symbol="B", sector="S", as_of_year=2022, momentum=0.20, reversion_gap=0.0),
            GrowthObservation(symbol="C", sector="S", as_of_year=2022, momentum=0.30, reversion_gap=0.0),
        ]
        out = attach_sector_momentum(obs)
        assert all(o.sector_momentum == pytest.approx(0.20) for o in out)

    def test_separate_sectors_do_not_mix(self):
        obs = [
            GrowthObservation(symbol="A", sector="Banques", as_of_year=2022, momentum=0.10, reversion_gap=0.0),
            GrowthObservation(symbol="B", sector="Mines", as_of_year=2022, momentum=0.90, reversion_gap=0.0),
        ]
        out = attach_sector_momentum(obs)
        by_symbol = {o.symbol: o.sector_momentum for o in out}
        assert by_symbol["A"] == pytest.approx(0.10)
        assert by_symbol["B"] == pytest.approx(0.90)

    def test_separate_years_do_not_mix(self):
        obs = [
            GrowthObservation(symbol="A", sector="S", as_of_year=2021, momentum=0.10, reversion_gap=0.0),
            GrowthObservation(symbol="A", sector="S", as_of_year=2022, momentum=0.50, reversion_gap=0.0),
        ]
        out = attach_sector_momentum(obs)
        by_year = {o.as_of_year: o.sector_momentum for o in out}
        assert by_year[2021] == pytest.approx(0.10)
        assert by_year[2022] == pytest.approx(0.50)


# ─── fit_growth_forecaster / predict_growth ──────────────────────────────────

def _synthetic_observations(n: int, seed: int = 0) -> list[GrowthObservation]:
    rng = np.random.default_rng(seed)
    obs = []
    for i in range(n):
        momentum = float(rng.normal(0.05, 0.10))
        sector_momentum = float(rng.normal(0.05, 0.05))
        reversion_gap = float(rng.normal(0.0, 0.05))
        # Target strongly driven by sector_momentum with a little noise --
        # gives the Ridge fit something real to recover.
        target = 0.2 * momentum + 0.6 * sector_momentum - 0.1 * reversion_gap + float(rng.normal(0, 0.01))
        obs.append(
            GrowthObservation(
                symbol=f"SYM{i}",
                sector="S",
                as_of_year=2020,
                momentum=momentum,
                reversion_gap=reversion_gap,
                sector_momentum=sector_momentum,
                target=target,
            )
        )
    return obs


class TestFitAndPredict:
    def test_returns_none_below_min_train_observations(self):
        obs = _synthetic_observations(MIN_TRAIN_OBSERVATIONS - 1)
        assert fit_growth_forecaster(obs) is None

    def test_fits_with_enough_observations(self):
        obs = _synthetic_observations(MIN_TRAIN_OBSERVATIONS + 10)
        model = fit_growth_forecaster(obs)
        assert model is not None
        assert model.n_train == MIN_TRAIN_OBSERVATIONS + 10

    def test_prediction_tracks_true_signal_direction(self):
        train = _synthetic_observations(200, seed=1)
        model = fit_growth_forecaster(train)
        assert model is not None
        high_signal = GrowthObservation(
            symbol="HOLD", sector="S", as_of_year=2020, momentum=0.05, reversion_gap=0.0, sector_momentum=0.30,
        )
        low_signal = GrowthObservation(
            symbol="HOLD", sector="S", as_of_year=2020, momentum=0.05, reversion_gap=0.0, sector_momentum=-0.30,
        )
        assert predict_growth(model, high_signal) > predict_growth(model, low_signal)

    def test_predict_growth_handles_zero_variance_feature(self):
        # A degenerate training set where reversion_gap is constant must not
        # divide by zero (StandardScaler.scale_ == 0 case).
        obs = [
            GrowthObservation(
                symbol=f"S{i}", sector="X", as_of_year=2020,
                momentum=0.01 * i, reversion_gap=0.0, sector_momentum=0.02 * i,
                target=0.01 * i,
            )
            for i in range(MIN_TRAIN_OBSERVATIONS + 5)
        ]
        model = fit_growth_forecaster(obs)
        assert model is not None
        result = predict_growth(model, obs[0])
        assert np.isfinite(result)

    def test_ignores_rows_without_target_when_fitting(self):
        train = _synthetic_observations(MIN_TRAIN_OBSERVATIONS + 5, seed=2)
        live_row = GrowthObservation(
            symbol="LIVE", sector="S", as_of_year=2021, momentum=0.05, reversion_gap=0.0, sector_momentum=0.05,
            target=None,
        )
        model_without_live = fit_growth_forecaster(train)
        model_with_live_row_present = fit_growth_forecaster(train + [live_row])
        assert model_without_live is not None and model_with_live_row_present is not None
        assert model_without_live.n_train == model_with_live_row_present.n_train


# ─── forecast_symbol_growth ───────────────────────────────────────────────────

class TestForecastSymbolGrowth:
    def test_returns_none_when_symbol_missing(self):
        obs = _synthetic_observations(MIN_TRAIN_OBSERVATIONS + 5)
        assert forecast_symbol_growth("NOT_PRESENT", obs) is None

    def test_returns_none_when_training_too_thin(self):
        obs = _synthetic_observations(5)
        live = GrowthObservation(symbol="LIVE", sector="S", as_of_year=2021, momentum=0.05, reversion_gap=0.0, sector_momentum=0.05)
        assert forecast_symbol_growth("LIVE", obs + [live]) is None

    def test_returns_prediction_when_feasible(self):
        train = _synthetic_observations(MIN_TRAIN_OBSERVATIONS + 20, seed=3)
        live = GrowthObservation(symbol="LIVE", sector="S", as_of_year=2021, momentum=0.05, reversion_gap=0.0, sector_momentum=0.05)
        result = forecast_symbol_growth("LIVE", train + [live])
        assert result is not None
        assert np.isfinite(result)


# ─── run_expanding_window_backtest ────────────────────────────────────────────

class TestRunExpandingWindowBacktest:
    def test_returns_none_with_insufficient_data(self):
        obs = _synthetic_observations(5)
        assert run_expanding_window_backtest(obs, [2021]) is None

    def test_model_beats_naive_on_strong_sector_signal(self):
        """Construct a scenario where the sector-relative signal is
        genuinely informative and each company's own trailing momentum is
        pure noise -- the model (which uses sector_momentum) should clearly
        outperform the naive momentum-only baseline here, demonstrating the
        backtest harness is wired correctly end to end."""
        rng = np.random.default_rng(7)
        panel: list[GrowthObservation] = []
        for year in range(2015, 2024):
            sector_shock = float(rng.normal(0.05, 0.08))
            for i in range(15):
                own_momentum = float(rng.normal(0.0, 0.20))  # pure noise, no info
                reversion_gap = float(rng.normal(0.0, 0.02))
                realized = sector_shock + float(rng.normal(0, 0.01))
                panel.append(
                    GrowthObservation(
                        symbol=f"SYM{i}",
                        sector="S",
                        as_of_year=year,
                        momentum=own_momentum,
                        reversion_gap=reversion_gap,
                        target=realized,
                    )
                )
        panel = attach_sector_momentum(panel)
        test_years = list(range(2020, 2024))
        result = run_expanding_window_backtest(panel, test_years)
        assert result is not None
        assert result["model"].rmse < result["naive_cagr"].rmse
        assert result["model"].mae < result["naive_cagr"].mae
