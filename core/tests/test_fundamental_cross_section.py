from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from quant_core.fundamentals.cross_section.composite import compute_sfc
from quant_core.fundamentals.cross_section.ic_study import benjamini_hochberg, tercile_backtest
from quant_core.fundamentals.cross_section.panel import PanelConfig, assert_metric_rows_no_lookahead, build_pit_panel, publication_coverage_stats
from quant_core.fundamentals.cross_section.pillars import PillarConfig, compute_pillar_scores, mad_winsorized_z


def _universe(symbols: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbols,
            "name": symbols,
            "listing_date": [None] * len(symbols),
            "delisting_date": [None] * len(symbols),
            "status": ["active"] * len(symbols),
        }
    )


def _prices(symbols: list[str]) -> dict[str, pd.Series]:
    idx = pd.date_range("2020-01-01", "2023-12-31", freq="B")
    out = {}
    for i, sym in enumerate(symbols):
        out[sym] = pd.Series(np.linspace(100 + i, 130 + i, len(idx)), index=idx)
    return out


def _annual_rows(symbols: list[str], publication_date: dt.date = dt.date(2021, 4, 1)) -> list[dict]:
    rows = []
    for i, sym in enumerate(symbols):
        rows.extend(
            [
                {
                    "symbol": sym,
                    "company_name": sym,
                    "statement_year": 2020,
                    "metric_name": "PER",
                    "metric_value": 8.0 + i,
                    "publication_date": publication_date,
                },
                {
                    "symbol": sym,
                    "company_name": sym,
                    "statement_year": 2020,
                    "metric_name": "Price_to_Book",
                    "metric_value": 1.0 + i / 10.0,
                    "publication_date": publication_date,
                },
                {
                    "symbol": sym,
                    "company_name": sym,
                    "statement_year": 2020,
                    "metric_name": "ROA",
                    "metric_value": 0.05 + i / 100.0,
                    "publication_date": publication_date,
                },
                {
                    "symbol": sym,
                    "company_name": sym,
                    "statement_year": 2020,
                    "metric_name": "Free_Cash_Flow",
                    "metric_value": 100.0 + i,
                    "publication_date": publication_date,
                },
                {
                    "symbol": sym,
                    "company_name": sym,
                    "statement_year": 2020,
                    "metric_name": "NetIncome",
                    "metric_value": 90.0 + i,
                    "publication_date": publication_date,
                },
                {
                    "symbol": sym,
                    "company_name": sym,
                    "statement_year": 2020,
                    "metric_name": "Revenue_Growth",
                    "metric_value": 0.02 + i / 100.0,
                    "publication_date": publication_date,
                },
            ]
        )
    return rows


def test_lookahead_assertion_fires_on_publication_date_violation() -> None:
    rows = [
        {
            "symbol": "AAA",
            "company_name": "AAA",
            "statement_year": 2021,
            "metric_name": "Revenue",
            "metric_value": 100.0,
            "publication_date": dt.date(2022, 4, 1),
        }
    ]
    with pytest.raises(AssertionError, match="LOOK-AHEAD"):
        assert_metric_rows_no_lookahead(rows, dt.date(2021, 12, 31))


def test_build_panel_uses_publication_date_not_statement_year() -> None:
    symbols = ["AAA"]
    prices = _prices(symbols)
    rows = _annual_rows(symbols, publication_date=dt.date(2021, 4, 1))
    panel = build_pit_panel(
        annual_rows=rows,
        price_loader=lambda symbol: prices[symbol],
        universe_df=_universe(symbols),
    )
    assert panel["as_of_date"].min() >= dt.date(2021, 4, 30)


def test_publication_coverage_stats_counts_real_and_fallback_dates() -> None:
    symbols = ["AAA", "BBB"]
    prices = _prices(symbols)
    rows = _annual_rows(["AAA"], publication_date=dt.date(2021, 4, 1))
    fallback_rows = _annual_rows(["BBB"], publication_date=None)
    panel = build_pit_panel(
        annual_rows=rows + fallback_rows,
        price_loader=lambda symbol: prices[symbol],
        universe_df=_universe(symbols),
        config=PanelConfig(as_of_dates=(dt.date(2021, 12, 31),)),
    )
    stats = publication_coverage_stats(panel)
    assert stats["counts"]["publication_date"] > 0
    assert stats["counts"]["fallback_annual_90d"] > 0


def test_mad_winsorized_z_clips_extreme_outlier() -> None:
    values = pd.Series([1.0, 2.0, 3.0, 4.0, 1000.0])
    z = mad_winsorized_z(values, clip=3.0)
    assert z.iloc[-1] < 2.0
    assert abs(float(z.mean())) < 1e-12


def test_pillar_zscores_are_bucket_neutralized() -> None:
    symbols = [f"S{i:02d}" for i in range(18)]
    prices = _prices(symbols)
    panel = build_pit_panel(
        annual_rows=_annual_rows(symbols),
        price_loader=lambda symbol: prices[symbol],
        universe_df=_universe(symbols),
    )
    one_date = panel[panel["as_of_date"] == panel["as_of_date"].min()].copy()
    scored = compute_pillar_scores(
        one_date,
        price_by_symbol=prices,
        config=PillarConfig(min_bucket=8),
    )
    assert scored["pillar_val"].notna().sum() == 18
    assert abs(float(scored["pillar_val"].mean())) < 1e-12


def test_composite_requires_at_least_two_pillars() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["ONE", "TWO"],
            "pillar_val": [1.0, 1.0],
            "pillar_qual": [np.nan, -1.0],
            "pillar_fmom": [np.nan, np.nan],
            "pillar_pmom": [2.0, 3.0],
        }
    )
    out = compute_sfc(frame)
    assert np.isnan(out.loc[0, "sfc"])
    assert out.loc[1, "sfc"] == pytest.approx(0.0)
    assert out.loc[0, "sfc_legacy"] == pytest.approx(1.5)
    assert out.loc[1, "sfc_legacy"] == pytest.approx(1.0)
    assert out.loc[1, "coverage_ratio"] == pytest.approx(2.0 / 3.0)
    assert out.loc[1, "pmom"] == pytest.approx(3.0)


def test_known_top_rank_enters_top_tercile() -> None:
    frame = pd.DataFrame(
        {
            "as_of_date": [dt.date(2021, 1, 31)] * 9,
            "symbol": [f"S{i}" for i in range(9)],
            "sfc": [9, 8, 7, 6, 5, 4, 3, 2, 1],
            "fwd_return_3m": [0.20, 0.18, 0.16, 0.01, 0.0, -0.01, -0.02, -0.03, -0.04],
        }
    )
    result = tercile_backtest(frame, cost_bps=0.0, horizon="3m")
    assert result["periods"] == 1
    assert result["mean_spread"] > 0
    assert "total_spread" not in result


def test_bh_fdr_hand_computed_example() -> None:
    res = benjamini_hochberg([0.001, 0.02, 0.03, 0.20], alpha=0.10)
    assert [r["reject"] for r in res] == [True, True, True, False]
    assert res[0]["qvalue"] == pytest.approx(0.004)
    assert res[1]["qvalue"] == pytest.approx(0.04)
    assert res[2]["qvalue"] == pytest.approx(0.04)
