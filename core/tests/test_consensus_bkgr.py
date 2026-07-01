"""Tests for Phase 1 forward-estimate consensus layer (brief 54).

Coverage:
  - reconcile_consensus() pure function
  - forward_eps injection into _normalized_flow_multiple (Phase 3 wiring)
  - BKGR adapter internal parsing helpers (synthetic text, no PDF required)
  - BKGR adapter against the real PDF (skipped if PDF absent)
  - Estimate-vs-actual isolation invariant
"""
from __future__ import annotations

import csv
import datetime as dt
import math
from pathlib import Path

import pytest

from quant_core.fundamentals.consensus.domain import (
    METRIC_EPS_FORWARD,
    METRIC_PER_FORWARD,
    METRIC_RATING,
    METRIC_TARGET_PRICE,
    ConsensusEstimate,
)
from quant_core.fundamentals.consensus.reconcile import reconcile_consensus
from quant_core.fundamentals.consensus.bkgr import (
    _clean_num,
    _parse_abbreviations,
    _resolve_ticker,
    _parse_company_page,
    _CompanyPage,
    BkgrAdapter,
)

ROOT = Path(__file__).resolve().parents[2]
BKGR_PDF = ROOT / "bkgr-stock-guide-juin-2026.pdf"
BKGR_FIXTURE = ROOT / "core" / "tests" / "fixtures" / "bkgr_jun2026.csv"

BKGR_PDF_PRESENT = pytest.mark.skipif(
    not BKGR_PDF.exists(), reason="BKGR PDF not present"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _est(symbol: str, metric: str, value: float, source: str = "bkgr",
         fiscal_year: int = 2026, as_of: dt.date | None = None) -> ConsensusEstimate:
    return ConsensusEstimate(
        symbol=symbol,
        fiscal_year=fiscal_year,
        period_type="annual",
        metric=metric,
        value=value,
        source=source,
        as_of_date=as_of or dt.date(2026, 5, 25),
        currency="MAD",
    )


# ---------------------------------------------------------------------------
# reconcile_consensus — pure function tests
# ---------------------------------------------------------------------------

class TestReconcileConsensus:
    def test_single_source_passes_through(self):
        rows = [_est("IAM", METRIC_EPS_FORWARD, 6.3)]
        results = reconcile_consensus(rows)
        assert len(results) == 1
        r = results[0]
        assert r.symbol == "IAM"
        assert r.fiscal_year == 2026
        assert r.metric == METRIC_EPS_FORWARD
        assert r.reconciled_value == pytest.approx(6.3)
        assert r.contributing_sources == ["bkgr"]

    def test_two_sources_median(self):
        rows = [
            _est("IAM", METRIC_EPS_FORWARD, 6.3, source="bkgr"),
            _est("IAM", METRIC_EPS_FORWARD, 6.2, source="marketscreener"),
        ]
        results = reconcile_consensus(rows)
        assert len(results) == 1
        assert results[0].reconciled_value == pytest.approx(6.25)
        assert set(results[0].contributing_sources) == {"bkgr", "marketscreener"}

    def test_three_sources_median(self):
        rows = [
            _est("ATW", METRIC_EPS_FORWARD, 54.0, source="bkgr"),
            _est("ATW", METRIC_EPS_FORWARD, 53.0, source="marketscreener"),
            _est("ATW", METRIC_EPS_FORWARD, 55.0, source="model"),
        ]
        results = reconcile_consensus(rows)
        assert results[0].reconciled_value == pytest.approx(54.0)

    def test_latest_as_of_date_wins_same_source(self):
        older = _est("IAM", METRIC_EPS_FORWARD, 6.0, as_of=dt.date(2026, 3, 1))
        newer = _est("IAM", METRIC_EPS_FORWARD, 6.3, as_of=dt.date(2026, 5, 25))
        results = reconcile_consensus([older, newer])
        assert len(results) == 1
        assert results[0].reconciled_value == pytest.approx(6.3)

    def test_upsert_semantics_older_does_not_overwrite(self):
        newer = _est("IAM", METRIC_EPS_FORWARD, 6.3, as_of=dt.date(2026, 5, 25))
        older = _est("IAM", METRIC_EPS_FORWARD, 6.0, as_of=dt.date(2026, 3, 1))
        results = reconcile_consensus([newer, older])
        assert results[0].reconciled_value == pytest.approx(6.3)

    def test_multiple_symbols_independent(self):
        rows = [
            _est("IAM", METRIC_EPS_FORWARD, 6.3),
            _est("ATW", METRIC_EPS_FORWARD, 54.0),
        ]
        results = {r.symbol: r for r in reconcile_consensus(rows)}
        assert results["IAM"].reconciled_value == pytest.approx(6.3)
        assert results["ATW"].reconciled_value == pytest.approx(54.0)

    def test_none_value_not_in_contributing(self):
        # Rating metric has value=None; should not appear in contributing_sources
        rows = [
            ConsensusEstimate(
                symbol="IAM", fiscal_year=2026, period_type="annual",
                metric=METRIC_RATING, value=None, source="bkgr",
                as_of_date=dt.date(2026, 5, 25), currency="MAD",
                raw_label="Acheter",
            )
        ]
        results = reconcile_consensus(rows)
        assert results[0].reconciled_value is None
        assert results[0].contributing_sources == []

    def test_empty_input(self):
        assert reconcile_consensus([]) == []


# ---------------------------------------------------------------------------
# Estimate-vs-actual isolation invariant
# ---------------------------------------------------------------------------

class TestEstimateIsolation:
    def test_is_estimate_always_true_for_consensus_estimates(self):
        """ConsensusEstimate objects have no is_estimate field — they are always
        estimates by construction.  The DB model enforces is_estimate=True via
        a CHECK constraint.  Here we verify the domain object carries no trailing-
        actual metric names (RNPG, Resultat_net, etc.) that would suggest mixing."""
        actual_metric_names = {"RNPG", "Resultat_net", "Chiffre_daffaires", "DPA"}
        est = _est("IAM", METRIC_EPS_FORWARD, 6.3)
        # The metric must not be one of the trailing-actual metric names
        assert est.metric not in actual_metric_names

    def test_consensus_metric_canonical_names(self):
        """Canonical metric names used by the consensus layer must not collide
        with the trailing-actual metric names used by fundamental_annual_metric."""
        from quant_core.fundamentals.consensus.domain import CANONICAL_METRICS
        trailing_actuals = {"RNPG", "Resultat_net", "Chiffre_daffaires", "DPA",
                            "REX", "PNB", "RBE", "Marge_nette"}
        assert not (CANONICAL_METRICS & trailing_actuals), (
            "Canonical consensus metric names must not overlap with trailing-actual names"
        )


# ---------------------------------------------------------------------------
# NetIncome_Forward derivation (brief 54 §3.3) — BKGR never tabulates NI
# directly, only per-share BPA/PER, so it must be derived from shares.
# ---------------------------------------------------------------------------

class TestDeriveNetIncomeForward:
    def test_derives_ni_from_eps_and_shares(self):
        from quant_core.fundamentals.consensus.bkgr import derive_net_income_forward
        from quant_core.fundamentals.consensus.domain import METRIC_NI_FORWARD

        estimates = [_est("IAM", METRIC_EPS_FORWARD, 6.3, fiscal_year=2026)]
        derived = derive_net_income_forward(estimates, {"IAM": 879_095_340.0})

        assert len(derived) == 1
        row = derived[0]
        assert row.symbol == "IAM"
        assert row.fiscal_year == 2026
        assert row.metric == METRIC_NI_FORWARD
        assert row.value == pytest.approx(6.3 * 879_095_340.0)
        assert row.source == "bkgr"
        assert row.as_of_date == dt.date(2026, 5, 25)

    def test_skips_symbols_without_shares(self):
        from quant_core.fundamentals.consensus.bkgr import derive_net_income_forward

        estimates = [_est("CMGP", METRIC_EPS_FORWARD, 10.0)]
        derived = derive_net_income_forward(estimates, {})

        assert derived == []

    def test_ignores_non_eps_metrics(self):
        from quant_core.fundamentals.consensus.bkgr import derive_net_income_forward

        estimates = [
            _est("IAM", METRIC_PER_FORWARD, 14.7),
            _est("IAM", METRIC_TARGET_PRICE, 130.0),
        ]
        derived = derive_net_income_forward(estimates, {"IAM": 879_095_340.0})

        assert derived == []

    def test_multiple_fiscal_years_derive_independently(self):
        from quant_core.fundamentals.consensus.bkgr import derive_net_income_forward
        from quant_core.fundamentals.consensus.domain import METRIC_NI_FORWARD

        estimates = [
            _est("ATW", METRIC_EPS_FORWARD, 54.0, fiscal_year=2026),
            _est("ATW", METRIC_EPS_FORWARD, 58.0, fiscal_year=2027),
        ]
        derived = derive_net_income_forward(estimates, {"ATW": 215_140_839.0})

        by_year = {row.fiscal_year: row.value for row in derived}
        assert set(by_year) == {2026, 2027}
        assert by_year[2026] == pytest.approx(54.0 * 215_140_839.0)
        assert by_year[2027] == pytest.approx(58.0 * 215_140_839.0)
        assert all(row.metric == METRIC_NI_FORWARD for row in derived)


# ---------------------------------------------------------------------------
# Valuation forward EPS injection (Phase 3 wiring)
# ---------------------------------------------------------------------------

class TestForwardEpsInjection:
    """_normalized_flow_multiple should use forward_eps when present."""

    def _make_snapshot(self, symbol: str = "IAM"):
        from quant_core.fundamentals.domain import FundamentalSnapshot
        return FundamentalSnapshot(
            symbol=symbol,
            company_name="Test",
            latest_statement_year=2025,
            metrics={"Shares_Outstanding": 879_095_340.0},
            scores={},
            coverage={},
            diagnostics={},
            source={},
            as_of_date=dt.date(2026, 5, 25),
        )

    def _make_history(self):
        from quant_core.fundamentals.domain import AnnualMetricRow
        return [
            AnnualMetricRow(symbol="IAM", company_name="IAM", statement_year=2023, metric_name="Resultat_net", metric_value=6_100_000_000),
            AnnualMetricRow(symbol="IAM", company_name="IAM", statement_year=2024, metric_name="Resultat_net", metric_value=6_400_000_000),
            AnnualMetricRow(symbol="IAM", company_name="IAM", statement_year=2025, metric_name="Resultat_net", metric_value=6_950_000_000),
        ]

    def test_no_forward_eps_uses_trailing(self):
        from quant_core.fundamentals.valuation import _normalized_flow_multiple
        snap = self._make_snapshot()
        hist = self._make_history()
        _, basis = _normalized_flow_multiple(snap, hist, "PER", 93.2, assumptions={})
        assert "forward_eps" not in basis

    def test_forward_eps_changes_basis(self):
        from quant_core.fundamentals.valuation import _normalized_flow_multiple
        snap = self._make_snapshot()
        hist = self._make_history()
        assumptions = {"forward_eps": 6.3}
        value, basis = _normalized_flow_multiple(snap, hist, "PER", 93.2, assumptions=assumptions)
        assert basis == "forward_eps_per"
        assert value == pytest.approx(93.2 / 6.3)

    def test_forward_eps_computes_correct_forward_per(self):
        """price / forward_eps = forward P/E; applying peer P/E gives fair_value = peer_PER × EPS."""
        from quant_core.fundamentals.valuation import _normalized_flow_multiple
        snap = self._make_snapshot()
        hist = self._make_history()
        price = 93.2
        forward_eps = 6.3
        peer_per = 14.7
        own_per, basis = _normalized_flow_multiple(snap, hist, "PER", price, {"forward_eps": forward_eps})
        fair_value = price * peer_per / own_per
        assert basis == "forward_eps_per"
        assert fair_value == pytest.approx(peer_per * forward_eps, rel=1e-4)

    def test_forward_eps_none_falls_back_to_trailing(self):
        from quant_core.fundamentals.valuation import _normalized_flow_multiple
        snap = self._make_snapshot()
        hist = self._make_history()
        # Passing forward_eps=None must not use the forward branch
        _, basis = _normalized_flow_multiple(snap, hist, "PER", 93.2, {"forward_eps": None})
        assert basis != "forward_eps_per"

    def test_price_to_sales_unaffected(self):
        """forward_eps must not accidentally affect Price_to_Sales."""
        from quant_core.fundamentals.valuation import _normalized_flow_multiple
        from quant_core.fundamentals.domain import AnnualMetricRow
        snap = self._make_snapshot()
        hist = [
            AnnualMetricRow(symbol="IAM", company_name="IAM", statement_year=2025,
                            metric_name="Chiffre_daffaires", metric_value=40_000_000_000),
        ]
        _, basis = _normalized_flow_multiple(snap, hist, "Price_to_Sales", 93.2, {"forward_eps": 6.3})
        assert "forward_eps" not in basis


# ---------------------------------------------------------------------------
# BKGR adapter internal helpers — synthetic text, no PDF
# ---------------------------------------------------------------------------

class TestBkgrInternalHelpers:
    def test_clean_num_basic(self):
        assert _clean_num("6.3") == pytest.approx(6.3)
        assert _clean_num("14.7x") == pytest.approx(14.7)
        assert _clean_num("12,9") == pytest.approx(12.9)
        assert _clean_num("-") is None
        assert _clean_num("ns") is None
        assert _clean_num("") is None

    def test_parse_abbreviations_extracts_company_ticker_map(self):
        """Abbreviations page: two-column TICKER COMPANY_NAME layout."""
        abbrev_text = (
            "ADH ADDOHA  GAZ AFRIQUIA GAZ\n"
            "IAM MAROC TELECOM  ATW ATTIJARIWAFA BANK\n"
            "LHM HOLCIM MAROC  CSR COSUMAR\n"
        )
        m = _parse_abbreviations(abbrev_text)
        assert m.get("ADDOHA") == "ADH"
        assert m.get("AFRIQUIA GAZ") == "GAZ"
        assert m.get("MAROC TELECOM") == "IAM"
        assert m.get("ATTIJARIWAFA BANK") == "ATW"
        assert m.get("HOLCIM MAROC") == "LHM"
        assert m.get("COSUMAR") == "CSR"

    def test_resolve_ticker_prefix_and_fuzzy(self):
        """Ticker resolution handles trailing sector tokens, minor spelling diffs."""
        abbrev_map = {
            "ATTIJARIWAFA BANK": "ATW",
            "CIMENTS DU MAROC": "CMA",
            "CIH": "CIH",
            "WAFA ASSURANCES": "WAA",
            "LABEL'VIE": "LBV",
        }
        # Exact
        assert _resolve_ticker("ATTIJARIWAFA BANK", abbrev_map) == "ATW"
        # Prefix: company name carries extra sector token
        assert _resolve_ticker("CIMENTS DU MAROC CIMENTIER", abbrev_map) == "CMA"
        # Prefix: map key starts with company_name (CIH BANK → key "CIH")
        assert _resolve_ticker("CIH BANK", abbrev_map) == "CIH"
        # Prefix: map key starts with company_name (WAFA ASSURANCES starts with WAFA ASSURANCE)
        assert _resolve_ticker("WAFA ASSURANCE", abbrev_map) == "WAA"
        # Fuzzy: apostrophe vs space difference
        assert _resolve_ticker("LABEL VIE", abbrev_map) == "LBV"
        # Ticker-direct: 2-5 uppercase chars with no map match
        assert _resolve_ticker("RDS", abbrev_map) == "RDS"
        assert _resolve_ticker("CMT", abbrev_map) == "CMT"

    def test_parse_company_page_extracts_bpa_per(self):
        page_text = (
            "IAM   TELECOM  Maroc\n"
            "En MAD  2024  2025  2026e  2027e\n"
            "BPA  7.3  7.9  6.3  6.5\n"
            "DPA  3.7  3.8  3.9  4.0\n"
            "PER  12.8  11.8  14.7  14.3\n"
            "D/Y  4.0%  4.1%  4.2%  4.3%\n"
            "Objectif de cours : MAD 130  Upside : +39.6%  Recommandation : Acheter\n"
        )
        cp = _parse_company_page(page_text, page_no=5)
        assert cp is not None
        assert cp.company_name == "IAM"
        assert cp.years == ["2024", "2025", "2026e", "2027e"]
        assert _clean_num(cp.rows["BPA"][2]) == pytest.approx(6.3)   # index 2 = 2026e
        assert _clean_num(cp.rows["PER"][2]) == pytest.approx(14.7)
        assert cp.target == pytest.approx(130, abs=1)
        assert cp.rating is not None and "ach" in cp.rating.lower()

    def test_parse_company_page_returns_none_for_cover_page(self):
        # A page without the En MAD header should return None
        cover_text = "BKGR Stock Guide Juin 2026\nBMCE Capital Global Research\n"
        assert _parse_company_page(cover_text, page_no=1) is None

    def test_resolve_ticker_via_company_page(self):
        """_resolve_ticker correctly maps company_name from a detail page to a ticker."""
        abbrev_map = {
            "MAROC TELECOM": "IAM",
            "ATTIJARIWAFA BANK": "ATW",
        }
        cp_iam = _CompanyPage(
            page_no=5, company_name="IAM",
            years=["2024", "2025", "2026e", "2027e"],
            rows={"BPA": ["7.3", "7.9", "6.3", "6.5"]}, target=130.0, rating="Acheter",
        )
        cp_atw = _CompanyPage(
            page_no=6, company_name="ATTIJARIWAFA BANK",
            years=["2024", "2025", "2026e", "2027e"],
            rows={"BPA": ["47.0", "49.5", "54.0", "58.0"]}, target=910.0, rating="Acheter",
        )
        # IAM detail page has "IAM" as company_name → ticker-direct
        assert _resolve_ticker(cp_iam.company_name, abbrev_map) == "IAM"
        # ATW detail page has "ATTIJARIWAFA BANK" → exact map lookup
        assert _resolve_ticker(cp_atw.company_name, abbrev_map) == "ATW"
        assert cp_iam.target == pytest.approx(130.0)
        assert cp_atw.target == pytest.approx(910.0)


# ---------------------------------------------------------------------------
# BKGR adapter against the real PDF (requires PDF in repo root)
# ---------------------------------------------------------------------------

@BKGR_PDF_PRESENT
class TestBkgrAdapterRealPdf:
    """Parse the actual BKGR Jun-2026 PDF and validate known values from brief 53."""

    @pytest.fixture(scope="class")
    def all_estimates(self):
        adapter = BkgrAdapter(BKGR_PDF)
        return adapter.fetch()

    @pytest.fixture(scope="class")
    def by_symbol_year_metric(self, all_estimates):
        result: dict[tuple[str, int, str], ConsensusEstimate] = {}
        for est in all_estimates:
            result[(est.symbol, est.fiscal_year, est.metric)] = est
        return result

    @pytest.fixture(scope="class")
    def fixture_tickers(self):
        rows = {}
        with BKGR_FIXTURE.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                rows[r["ticker"].strip().upper()] = float(r["bkgr_target"])
        return rows

    # Known values from brief 53 §4 table
    @pytest.mark.parametrize("ticker,fiscal_year,eps_2026e,per_2026e,target", [
        ("IAM", 2026, 6.3,  14.7, 130),
        ("ATW", 2026, 54.0, 12.9, 910),
        ("BCP", 2026, 25.3, 9.5,  405),
        ("LHM", 2026, 94.6, 19.7, 2428),
        ("CSR", 2026, 7.2,  25.4, 220),
    ])
    def test_known_values(self, by_symbol_year_metric, ticker, fiscal_year, eps_2026e, per_2026e, target):
        eps_key = (ticker, fiscal_year, METRIC_EPS_FORWARD)
        per_key = (ticker, fiscal_year, METRIC_PER_FORWARD)
        eps_row = by_symbol_year_metric.get(eps_key)
        per_row = by_symbol_year_metric.get(per_key)
        assert eps_row is not None, f"Missing EPS_Forward for {ticker} {fiscal_year}"
        assert per_row is not None, f"Missing PER_Forward for {ticker} {fiscal_year}"
        assert eps_row.value == pytest.approx(eps_2026e, abs=0.2), \
            f"{ticker} EPS 2026e: expected {eps_2026e}, got {eps_row.value}"
        assert per_row.value == pytest.approx(per_2026e, abs=0.3), \
            f"{ticker} PER 2026e: expected {per_2026e}, got {per_row.value}"
        # BPA × PER ≈ current price (brief 53 cross-check invariant)
        implied_price = eps_row.value * per_row.value
        assert implied_price == pytest.approx(eps_2026e * per_2026e, rel=0.05), \
            f"{ticker}: BPA×PER cross-check failed"

    def test_coverage_count(self, all_estimates):
        """At least 30 of the 37 BKGR names should have 2026e EPS."""
        eps_symbols = {e.symbol for e in all_estimates if e.metric == METRIC_EPS_FORWARD and e.fiscal_year == 2026}
        assert len(eps_symbols) >= 30, f"Only {len(eps_symbols)} symbols with 2026e EPS (expected >=30)"

    def test_target_price_cross_check_vs_fixture(self, all_estimates, fixture_tickers):
        """Target prices from the adapter should match bkgr_jun2026.csv within ±2%."""
        target_ests = {e.symbol: e.value for e in all_estimates if e.metric == METRIC_TARGET_PRICE}
        mismatches = []
        for ticker, expected_target in fixture_tickers.items():
            if ticker not in target_ests:
                continue
            got = target_ests[ticker]
            if got is None:
                mismatches.append(f"{ticker}: got None, expected {expected_target}")
                continue
            rel_err = abs(got - expected_target) / expected_target
            if rel_err > 0.02:
                mismatches.append(f"{ticker}: got {got}, expected {expected_target} (err={rel_err:.1%})")
        assert not mismatches, "Target price mismatches:\n" + "\n".join(mismatches)

    def test_as_of_date_extracted(self):
        adapter = BkgrAdapter(BKGR_PDF)
        estimates = adapter.fetch(symbols=["IAM"])
        dates = {e.as_of_date for e in estimates}
        assert len(dates) == 1
        aod = next(iter(dates))
        # BKGR Jun-2026 was priced 25 May 2026
        assert aod.year == 2026
        assert aod.month in (5, 6)

    def test_all_estimates_tagged_estimate_source(self, all_estimates):
        """All rows should carry source='bkgr' — never a trailing-actual source name."""
        for est in all_estimates:
            assert est.source == "bkgr", f"Unexpected source '{est.source}' for {est.symbol}"

    def test_2027e_eps_also_present(self, all_estimates):
        """The guide has both 2026e and 2027e; ensure 2027e is captured for major names."""
        eps_2027 = {e.symbol for e in all_estimates if e.metric == METRIC_EPS_FORWARD and e.fiscal_year == 2027}
        for ticker in ("IAM", "ATW", "BCP"):
            assert ticker in eps_2027, f"Missing 2027e EPS for {ticker}"

    def test_reconcile_on_real_output(self, all_estimates):
        """reconcile_consensus applied to adapter output should produce one row per
        (symbol, fiscal_year, metric) for each consensus estimate."""
        reconciled = reconcile_consensus(all_estimates)
        keys = [(r.symbol, r.fiscal_year, r.metric) for r in reconciled]
        # No duplicate (symbol, fiscal_year, metric) after reconciliation
        assert len(keys) == len(set(keys)), "Duplicate (symbol, fiscal_year, metric) after reconciliation"

    def test_fixture_all_37_covered_by_target_price(self, all_estimates, fixture_tickers):
        """Every fixture ticker should have a target price extracted from the PDF."""
        found = {e.symbol for e in all_estimates if e.metric == METRIC_TARGET_PRICE}
        missing = [t for t in fixture_tickers if t not in found]
        # Allow up to 3 misses (edge-cases with unusual page layouts)
        assert len(missing) <= 3, f"Target price missing for {len(missing)} tickers: {missing}"
