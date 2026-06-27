"""Unit tests for _augment_workbook_with_ratios in refresh_stockanalysis_fundamentals.

Uses stub db and stock objects so the full DB path is exercised without a real
database, catching AttributeError-class bugs (e.g. wrong model for price lookup)
at test time rather than on the live ingestion run.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.quant_core.fundamentals.domain import (
    AnnualMetricRow,
    FundamentalSnapshot,
    FundamentalWorkbook,
)
from services.worker.tasks.refresh_stockanalysis_fundamentals import _augment_workbook_with_ratios


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workbook(
    symbol: str,
    annual_raw: dict[int, dict[str, float | None]],
) -> FundamentalWorkbook:
    rows = [
        AnnualMetricRow(
            symbol=symbol,
            company_name="Test Co",
            statement_year=year,
            metric_name=metric,
            metric_value=value,
            raw_metric_name=metric,
            source_sheet="stockanalysis",
            source_field=metric,
            is_proxy=False,
        )
        for year, metrics in annual_raw.items()
        for metric, value in metrics.items()
    ]
    latest_year = max(annual_raw)
    latest_metrics: dict[str, float | None] = {}
    for year in sorted(annual_raw):
        latest_metrics.update(annual_raw[year])
    snapshot = FundamentalSnapshot(
        symbol=symbol,
        company_name="Test Co",
        latest_statement_year=latest_year,
        metrics=latest_metrics,
        source={},
        diagnostics={},
    )
    return FundamentalWorkbook(
        mappings=[],
        annual_metrics=rows,
        latest_snapshots=[snapshot],
        summary={},
    )


def _fake_db(close_last: float | None) -> MagicMock:
    """Stub db whose .query(...).filter(...).first() returns (close_last,) or None."""
    db = MagicMock()
    result = (close_last,) if close_last is not None else None
    db.query.return_value.filter.return_value.first.return_value = result
    return db


def _fake_stock(symbol: str, shares: float | None = 10_000_000.0) -> SimpleNamespace:
    return SimpleNamespace(symbol=symbol, shares_outstanding=shares, display_name=symbol)


# ---------------------------------------------------------------------------
# Minimal industrial fixture — two years so growth ratios are computable
# ---------------------------------------------------------------------------

_IND_RAW: dict[int, dict[str, float | None]] = {
    2023: {
        "Revenue": 4_000_000_000.0,
        "EBIT": 650_000_000.0,
        "NetIncome": 320_000_000.0,
        "Total_Assets": 7_500_000_000.0,
        "Total_Equity": 2_300_000_000.0,
        "Total_Debt": 1_000_000_000.0,
        "Net_Debt": 600_000_000.0,
        "Cash": 400_000_000.0,
        "Current_Assets": 1_500_000_000.0,
        "Current_Liabilities": 900_000_000.0,
        "Operating_Cash_Flow": 480_000_000.0,
        "Free_Cash_Flow": 260_000_000.0,
        "EBITDA": 850_000_000.0,
        "Interest_Expense": 80_000_000.0,
        "Dividendes": 160_000_000.0,
    },
    2024: {
        "Revenue": 4_200_000_000.0,
        "EBIT": 700_000_000.0,
        "NetIncome": 350_000_000.0,
        "Total_Assets": 8_000_000_000.0,
        "Total_Equity": 2_500_000_000.0,
        "Total_Debt": 1_000_000_000.0,
        "Net_Debt": 600_000_000.0,
        "Cash": 400_000_000.0,
        "Current_Assets": 1_500_000_000.0,
        "Current_Liabilities": 900_000_000.0,
        "Operating_Cash_Flow": 500_000_000.0,
        "Free_Cash_Flow": 280_000_000.0,
        "EBITDA": 900_000_000.0,
        "Interest_Expense": 80_000_000.0,
        "Dividendes": 175_000_000.0,
    },
}

_PRICE = 420.0
_SHARES = 10_000_000.0


# ---------------------------------------------------------------------------
# Tests: price found
# ---------------------------------------------------------------------------

class TestAugmentWithPrice:
    def test_ratio_rows_appended_to_annual_metrics(self) -> None:
        wb = _make_workbook("TST", _IND_RAW)
        original_count = len(wb.annual_metrics)

        result = _augment_workbook_with_ratios(wb, _fake_stock("TST", _SHARES), _fake_db(_PRICE))

        assert len(result.annual_metrics) > original_count
        ratio_names = {r.metric_name for r in result.annual_metrics if r.is_proxy}
        assert "Operating_Margin" in ratio_names
        assert "ROE" in ratio_names

    def test_ratio_rows_tagged_correctly(self) -> None:
        wb = _make_workbook("TST", _IND_RAW)
        result = _augment_workbook_with_ratios(wb, _fake_stock("TST", _SHARES), _fake_db(_PRICE))

        for row in result.annual_metrics:
            if row.is_proxy:
                assert row.source_sheet == "ratios_computed"
                assert row.raw_metric_name == f"computed:{row.metric_name}"
                assert row.symbol == "TST"

    def test_latest_snapshot_metrics_contain_ratios(self) -> None:
        wb = _make_workbook("TST", _IND_RAW)
        result = _augment_workbook_with_ratios(wb, _fake_stock("TST", _SHARES), _fake_db(_PRICE))

        snap = result.latest_snapshots[0]
        assert "Operating_Margin" in snap.metrics
        assert "ROE" in snap.metrics
        assert "PER" in snap.metrics  # price-derived

    def test_price_derived_ratios_computed(self) -> None:
        wb = _make_workbook("TST", _IND_RAW)
        result = _augment_workbook_with_ratios(wb, _fake_stock("TST", _SHARES), _fake_db(_PRICE))

        snap = result.latest_snapshots[0]
        market_cap = _PRICE * _SHARES
        assert snap.metrics["PER"] == pytest.approx(market_cap / 350_000_000)
        assert snap.metrics["Price_to_Book"] == pytest.approx(market_cap / 2_500_000_000)

    def test_archetype_stashed_in_source_and_diagnostics(self) -> None:
        wb = _make_workbook("TST", _IND_RAW)
        result = _augment_workbook_with_ratios(wb, _fake_stock("TST", _SHARES), _fake_db(_PRICE))

        snap = result.latest_snapshots[0]
        assert "archetype" in snap.source
        assert "archetype" in snap.diagnostics

    def test_original_workbook_not_mutated_except_snapshot(self) -> None:
        wb = _make_workbook("TST", _IND_RAW)
        original_count = len(wb.annual_metrics)
        _augment_workbook_with_ratios(wb, _fake_stock("TST", _SHARES), _fake_db(_PRICE))
        # FundamentalWorkbook is frozen — annual_metrics list must be unchanged on original
        assert len(wb.annual_metrics) == original_count


# ---------------------------------------------------------------------------
# Tests: price absent (MarketDataStore row missing or close_last is NULL)
# ---------------------------------------------------------------------------

class TestAugmentWithoutPrice:
    def test_no_price_derived_ratios_when_db_returns_none(self) -> None:
        wb = _make_workbook("TST", _IND_RAW)
        result = _augment_workbook_with_ratios(wb, _fake_stock("TST", _SHARES), _fake_db(None))

        snap = result.latest_snapshots[0]
        for key in ("PER", "Price_to_Book", "Price_to_Sales", "EV_to_EBITDA",
                    "FCF_Yield", "Dividend_Yield", "Market_Cap_Calc", "EV_Calc"):
            assert key not in snap.metrics, f"{key} must be absent when price is None"

    def test_non_price_ratios_still_computed_without_price(self) -> None:
        wb = _make_workbook("TST", _IND_RAW)
        result = _augment_workbook_with_ratios(wb, _fake_stock("TST", _SHARES), _fake_db(None))

        snap = result.latest_snapshots[0]
        assert "Operating_Margin" in snap.metrics
        assert "ROE" in snap.metrics
        assert "Current_Ratio" in snap.metrics

    def test_no_price_derived_ratios_when_close_last_is_null_row(self) -> None:
        # close_last column exists but IS NULL — db returns (None,) not None
        wb = _make_workbook("TST", _IND_RAW)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = (None,)
        result = _augment_workbook_with_ratios(wb, _fake_stock("TST", _SHARES), db)

        snap = result.latest_snapshots[0]
        assert "PER" not in snap.metrics


# ---------------------------------------------------------------------------
# Test: bank archetype routes correctly
# ---------------------------------------------------------------------------

_BANK_RAW: dict[int, dict[str, float | None]] = {
    2023: {
        "NetIncome": 1_300_000_000.0,
        "Total_Assets": 160_000_000_000.0,
        "Total_Equity": 13_500_000_000.0,
        "Net_Interest_Income": 4_200_000_000.0,
        "Operating_Expenses": 1_900_000_000.0,
        "Revenue": 5_500_000_000.0,
        "Loans_Net": 90_000_000_000.0,
        "Customer_Deposits": 110_000_000_000.0,
        "Provision_for_Loan_Losses": 500_000_000.0,
        "Dividendes": 650_000_000.0,
    },
    2024: {
        "NetIncome": 1_500_000_000.0,
        "Total_Assets": 180_000_000_000.0,
        "Total_Equity": 15_000_000_000.0,
        "Net_Interest_Income": 4_800_000_000.0,
        "Operating_Expenses": 2_100_000_000.0,
        "Revenue": 6_000_000_000.0,
        "Loans_Net": 100_000_000_000.0,
        "Customer_Deposits": 120_000_000_000.0,
        "Provision_for_Loan_Losses": 600_000_000.0,
        "Dividendes": 750_000_000.0,
    },
}


def test_bank_archetype_emits_bank_ratios_only() -> None:
    wb = _make_workbook("ATW", _BANK_RAW)
    result = _augment_workbook_with_ratios(wb, _fake_stock("ATW", 15_000_000.0), _fake_db(5_200.0))

    snap = result.latest_snapshots[0]
    assert snap.source["archetype"] == "bank"
    assert "Net_Interest_Margin" in snap.metrics
    assert "Loans_to_Deposits" in snap.metrics
    assert "Cout_du_risque" in snap.metrics
    # industrial ratios must be absent for banks
    for key in ("Operating_Margin", "Debt_to_Equity", "Current_Ratio",
                "EV_to_EBITDA", "FCF_Yield"):
        assert key not in snap.metrics, f"bank output must not contain {key!r}"


def test_empty_workbook_returns_unchanged() -> None:
    wb = FundamentalWorkbook(mappings=[], annual_metrics=[], latest_snapshots=[], summary={})
    result = _augment_workbook_with_ratios(wb, _fake_stock("X"), _fake_db(100.0))
    assert result is wb
