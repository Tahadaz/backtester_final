"""Tests for Phase 2: MarketScreener paced-scraper adapter (brief 54).

Coverage:
  - HTML fixture parse: IAM known values (EPS, revenue, net income, P/E, target, rating)
  - Forward year detection (Announcement Date row)
  - Quota-wall isolation: nopopin redirect → [] with no exception
  - Per-source isolation: MarketScreener failure does not affect BKGR output
  - Multi-source reconciliation with BKGR estimates
"""
from __future__ import annotations

import datetime as dt
import shutil
import tempfile
from pathlib import Path

import pytest

from quant_core.fundamentals.consensus.domain import (
    METRIC_EPS_FORWARD,
    METRIC_NI_FORWARD,
    METRIC_PER_FORWARD,
    METRIC_RATING,
    METRIC_REV_FORWARD,
    METRIC_TARGET_PRICE,
    ConsensusEstimate,
)
from quant_core.fundamentals.consensus.marketscreener import (
    MarketScreenerAdapter,
    _extract_ticker,
    _parse_consensus_card,
    _parse_table,
    parse_finances_html,
)
from quant_core.fundamentals.consensus.reconcile import reconcile_consensus

ROOT = Path(__file__).resolve().parents[2]
IAM_FIXTURE = ROOT / "core" / "tests" / "fixtures" / "ms_iam_finances.html"

MS_FIXTURE_PRESENT = pytest.mark.skipif(
    not IAM_FIXTURE.exists(), reason="MS IAM HTML fixture not present"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _est(symbol, metric, value, source="marketscreener", fiscal_year=2026,
         as_of=None):
    return ConsensusEstimate(
        symbol=symbol, fiscal_year=fiscal_year, period_type="annual",
        metric=metric, value=value, source=source,
        as_of_date=as_of or dt.date(2026, 6, 28), currency="MAD",
    )


def _minimal_html(*, ticker="TST", eps_2026="6.50", eps_2027="7.00",
                  rev_2026="40,000", ni_2026="5,500",
                  pe_2026="14.0", pe_2027="13.5",
                  target="130.00", n_analysts="3", rating="BUY") -> str:
    """Minimal but structurally realistic MarketScreener finances HTML."""
    return f"""<!DOCTYPE html>
<html>
<head><title>Test Company ({ticker}) S.A.: Financial Data | {ticker} | MarketScreener</title></head>
<body>
<h1>Financials Test Company ({ticker}) S.A.</h1>

<!-- Analysts' Consensus card -->
<div class="card mb-15 card--collapsible pos-next">
  <div class="card-content">
    <div>Sell Buy Mean consensus {rating} Number of Analysts {n_analysts}
    Last Close Price 91.70 MAD Average target price {target} MAD
    Spread / Average Target +17.41%</div>
  </div>
</div>

<!-- Annual income statement table -->
<table>
  <tr><th>Fiscal Period: December</th><th>2023</th><th>2024</th><th>2025</th><th>2026</th><th>2027</th></tr>
  <tr><td>Net sales1</td><td>34,000</td><td>36,000</td><td>38,000</td><td>{rev_2026}</td><td>42,000</td></tr>
  <tr><td>Change</td><td>-</td><td>5.88%</td><td>5.56%</td><td>5.26%</td><td>5.00%</td></tr>
  <tr><td>Net income1</td><td>4,000</td><td>4,800</td><td>5,200</td><td>{ni_2026}</td><td>5,900</td></tr>
  <tr><td>Announcement Date</td><td>2/15/24</td><td>2/14/25</td><td>2/13/26</td><td>-</td><td>-</td></tr>
</table>

<!-- Per-share / ratios table -->
<table>
  <tr><th>Fiscal Period: December</th><th>2023</th><th>2024</th><th>2025</th><th>2026</th><th>2027</th></tr>
  <tr><td>EPS1</td><td>5.50</td><td>5.80</td><td>6.10</td><td>{eps_2026}</td><td>{eps_2027}</td></tr>
  <tr><td>Dividend per Share1</td><td>2.00</td><td>2.10</td><td>2.20</td><td>2.30</td><td>2.50</td></tr>
  <tr><td>Announcement Date</td><td>2/15/24</td><td>2/14/25</td><td>2/13/26</td><td>-</td><td>-</td></tr>
</table>

<!-- Forward multiples table -->
<table>
  <tr><th></th><th>2026 *</th><th>2027 *</th></tr>
  <tr><td>P/E</td><td>{pe_2026}x</td><td>{pe_2027}x</td></tr>
  <tr><td>PBR</td><td>3.0x</td><td>2.8x</td></tr>
</table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Unit tests: HTML parser helpers
# ---------------------------------------------------------------------------

class TestMarketScreenerHelpers:
    def test_extract_ticker_from_parens(self):
        from bs4 import BeautifulSoup
        html = "<html><head><title>Company Name (IAM) S.A.: Financial Data | MarketScreener</title></head></html>"
        soup = BeautifulSoup(html, "html.parser")
        assert _extract_ticker(soup) == "IAM"

    def test_extract_ticker_from_pipe(self):
        from bs4 import BeautifulSoup
        html = "<html><head><title>Crédit du Maroc S.A.: Financial Data | CDM </title></head></html>"
        soup = BeautifulSoup(html, "html.parser")
        assert _extract_ticker(soup) == "CDM"

    def test_parse_consensus_card_extracts_all_three(self):
        from bs4 import BeautifulSoup
        html = """<html><body>
        <div class="card-content">
          <div>Sell Buy Mean consensus HOLD Number of Analysts 3
          Last Close Price 91.70 MAD Average target price 107.67 MAD Spread +17%</div>
        </div></body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        count, target, rating = _parse_consensus_card(soup)
        assert count == 3
        assert target == pytest.approx(107.67)
        assert rating == "HOLD"

    def test_parse_table_strips_footnote_digit(self):
        from bs4 import BeautifulSoup
        html = """<table>
          <tr><th>Fiscal Period</th><th>2025</th><th>2026</th></tr>
          <tr><td>EPS1</td><td>7.93</td><td>6.20</td></tr>
          <tr><td>Announcement Date</td><td>2/13/26</td><td>-</td></tr>
        </table>"""
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        years, data = _parse_table(table)
        assert "EPS" in data           # footnote digit stripped
        assert "EPS1" not in data
        assert data["EPS"] == ["7.93", "6.20"]

    def test_parse_minimal_html_eps(self):
        html = _minimal_html(ticker="TST", eps_2026="6.50", eps_2027="7.00")
        ests = parse_finances_html(html, as_of_date=dt.date(2026, 6, 28))
        by = {(e.metric, e.fiscal_year): e for e in ests}
        eps_2026 = by.get((METRIC_EPS_FORWARD, 2026))
        eps_2027 = by.get((METRIC_EPS_FORWARD, 2027))
        assert eps_2026 is not None
        assert eps_2026.value == pytest.approx(6.50)
        assert eps_2027 is not None
        assert eps_2027.value == pytest.approx(7.00)

    def test_parse_minimal_html_revenue_and_ni(self):
        html = _minimal_html(rev_2026="40,000", ni_2026="5,500")
        ests = parse_finances_html(html, as_of_date=dt.date(2026, 6, 28))
        by = {(e.metric, e.fiscal_year): e for e in ests}
        # MAD_M → absolute MAD at ingest (×1_000_000)
        assert by[(METRIC_REV_FORWARD, 2026)].value == pytest.approx(40_000 * 1_000_000)
        assert by[(METRIC_NI_FORWARD, 2026)].value == pytest.approx(5_500 * 1_000_000)
        assert by[(METRIC_REV_FORWARD, 2026)].currency == "MAD"
        assert by[(METRIC_NI_FORWARD, 2026)].currency == "MAD"

    def test_parse_minimal_html_per(self):
        html = _minimal_html(pe_2026="14.0", pe_2027="13.5")
        ests = parse_finances_html(html, as_of_date=dt.date(2026, 6, 28))
        by = {(e.metric, e.fiscal_year): e for e in ests}
        assert by[(METRIC_PER_FORWARD, 2026)].value == pytest.approx(14.0)
        assert by[(METRIC_PER_FORWARD, 2027)].value == pytest.approx(13.5)

    def test_parse_minimal_html_target_and_rating(self):
        html = _minimal_html(target="130.00", n_analysts="4", rating="BUY")
        ests = parse_finances_html(html, as_of_date=dt.date(2026, 6, 28))
        by = {e.metric: e for e in ests if e.fiscal_year == 2026}
        assert by[METRIC_TARGET_PRICE].value == pytest.approx(130.0)
        assert by[METRIC_RATING].raw_label == "BUY"
        assert by[METRIC_EPS_FORWARD].analyst_count == 4

    def test_parse_only_forward_years_emitted(self):
        """Actual years (with announcement dates) must not appear as estimates."""
        html = _minimal_html()
        ests = parse_finances_html(html, as_of_date=dt.date(2026, 6, 28))
        eps_years = {e.fiscal_year for e in ests if e.metric == METRIC_EPS_FORWARD}
        # 2023, 2024, 2025 are actuals (have dates); only 2026, 2027 are forward
        assert 2023 not in eps_years
        assert 2024 not in eps_years
        assert 2025 not in eps_years
        assert 2026 in eps_years
        assert 2027 in eps_years

    def test_all_estimates_tagged_marketscreener_source(self):
        html = _minimal_html()
        ests = parse_finances_html(html, as_of_date=dt.date(2026, 6, 28))
        assert ests, "Expected at least one estimate"
        for e in ests:
            assert e.source == "marketscreener"

    def test_parse_bad_html_returns_empty(self):
        """Garbled HTML must return [] without raising."""
        ests = parse_finances_html("<<not html at all!! >>>", ticker="BAD")
        assert ests == []

    def test_explicit_ticker_overrides_page_title(self):
        """When ticker is supplied, it wins over whatever the page says."""
        html = _minimal_html(ticker="TST")  # title says "TST"
        ests = parse_finances_html(html, ticker="IAM", as_of_date=dt.date(2026, 6, 28))
        assert all(e.symbol == "IAM" for e in ests)


# ---------------------------------------------------------------------------
# Quota-wall isolation
# ---------------------------------------------------------------------------

class TestQuotaWallIsolation:
    def test_quota_wall_returns_empty_list(self, tmp_path):
        """Adapter using a cache dir with no files and a mock fetcher that
        simulates the nopopin redirect must return [] without raising."""
        adapter = MarketScreenerAdapter(
            cache_dir=tmp_path,
            id_map={1408717: "IAM"},
        )
        # Patch _live_fetch to simulate quota wall
        adapter._live_fetch = lambda ms_id: None
        result = adapter.fetch(symbols=["IAM"])
        assert result == []

    def test_per_source_isolation_ms_failure_does_not_affect_bkgr(self):
        """If MarketScreener returns [], BKGR estimates from reconcile_consensus
        are unaffected."""
        bkgr_est = _est("IAM", METRIC_EPS_FORWARD, 6.3, source="bkgr")
        ms_failure: list[ConsensusEstimate] = []  # simulate failed MS fetch
        all_ests = [bkgr_est] + ms_failure
        reconciled = reconcile_consensus(all_ests)
        assert len(reconciled) == 1
        assert reconciled[0].reconciled_value == pytest.approx(6.3)
        assert reconciled[0].contributing_sources == ["bkgr"]


# ---------------------------------------------------------------------------
# Multi-source reconciliation
# ---------------------------------------------------------------------------

class TestMultiSourceReconciliation:
    def test_bkgr_and_ms_median_eps(self):
        """Two sources → reconciled value is the median."""
        ests = [
            _est("IAM", METRIC_EPS_FORWARD, 6.3,  source="bkgr"),
            _est("IAM", METRIC_EPS_FORWARD, 6.195, source="marketscreener"),
        ]
        reconciled = reconcile_consensus(ests)
        assert len(reconciled) == 1
        r = reconciled[0]
        assert r.reconciled_value == pytest.approx((6.3 + 6.195) / 2, rel=1e-4)
        assert set(r.contributing_sources) == {"bkgr", "marketscreener"}

    def test_disagreement_visible_in_source_values(self):
        """Large target divergence (BKGR 130 vs MS 107) must be visible in
        source_values dict so the desk can surface it."""
        ests = [
            _est("IAM", METRIC_TARGET_PRICE, 130.0, source="bkgr"),
            _est("IAM", METRIC_TARGET_PRICE, 107.67, source="marketscreener"),
        ]
        reconciled = reconcile_consensus(ests)
        r = reconciled[0]
        assert "bkgr" in r.source_values
        assert "marketscreener" in r.source_values
        assert r.source_values["bkgr"] == pytest.approx(130.0)
        assert r.source_values["marketscreener"] == pytest.approx(107.67)
        # Median is 118.835
        assert r.reconciled_value == pytest.approx((130.0 + 107.67) / 2, rel=1e-4)

    def test_ms_only_no_bkgr_passes_through(self):
        ests = [_est("CDM", METRIC_EPS_FORWARD, 79.36, source="marketscreener")]
        reconciled = reconcile_consensus(ests)
        assert reconciled[0].reconciled_value == pytest.approx(79.36)
        assert reconciled[0].contributing_sources == ["marketscreener"]

    def test_ms_revenue_does_not_collide_with_bkgr_eps(self):
        """Revenue_Forward and EPS_Forward are different metrics — no collision."""
        ests = [
            # Revenue already in absolute MAD (post-ingest conversion)
            _est("IAM", METRIC_REV_FORWARD, 37_051_000_000.0, source="marketscreener"),
            _est("IAM", METRIC_EPS_FORWARD, 6.195, source="marketscreener"),
            _est("IAM", METRIC_EPS_FORWARD, 6.3, source="bkgr"),
        ]
        by_metric = {r.metric: r for r in reconcile_consensus(ests)}
        assert METRIC_REV_FORWARD in by_metric
        assert METRIC_EPS_FORWARD in by_metric
        # Revenue only from MS, EPS reconciled across both
        assert by_metric[METRIC_REV_FORWARD].contributing_sources == ["marketscreener"]
        assert set(by_metric[METRIC_EPS_FORWARD].contributing_sources) == {"bkgr", "marketscreener"}

    def test_ms_rev_ni_absolute_mad_at_ingest(self):
        """Revenue_Forward and NetIncome_Forward must leave parse_finances_html
        in absolute MAD (not MAD millions) — ingest-time conversion."""
        html = _minimal_html(rev_2026="10,000", ni_2026="1,000")
        ests = parse_finances_html(html, as_of_date=dt.date(2026, 6, 28))
        by = {(e.metric, e.fiscal_year): e for e in ests}
        rev = by[(METRIC_REV_FORWARD, 2026)]
        ni  = by[(METRIC_NI_FORWARD, 2026)]
        # 10,000 MAD M → 10,000,000,000 absolute MAD
        assert rev.value == pytest.approx(10_000_000_000.0)
        assert rev.currency == "MAD"
        # 1,000 MAD M → 1,000,000,000 absolute MAD
        assert ni.value == pytest.approx(1_000_000_000.0)
        assert ni.currency == "MAD"

    def test_bkgr_eps_not_scaled(self):
        """BKGR EPS_Forward is already in MAD/share — reconciliation must not re-scale it."""
        # Simulate BKGR emitting EPS in MAD/share (e.g. 6.30 MAD)
        bkgr_eps = _est("IAM", METRIC_EPS_FORWARD, 6.30, source="bkgr")
        reconciled = reconcile_consensus([bkgr_eps])
        # Must pass through at face value, not multiplied by 1e6
        assert reconciled[0].reconciled_value == pytest.approx(6.30)

    def test_no_double_scale_in_reconciliation(self):
        """When MS Revenue (already absolute MAD) enters reconcile_consensus, the
        reconciled value must equal the original absolute MAD figure, not 1e6× it."""
        abs_rev = 37_051_000_000.0  # 37,051 MAD M already converted to absolute
        ests = [_est("IAM", METRIC_REV_FORWARD, abs_rev, source="marketscreener")]
        reconciled = reconcile_consensus(ests)
        assert reconciled[0].reconciled_value == pytest.approx(abs_rev)


# ---------------------------------------------------------------------------
# Real IAM HTML fixture tests (skipped if fixture absent)
# ---------------------------------------------------------------------------

@MS_FIXTURE_PRESENT
class TestMarketScreenerRealFixture:
    @pytest.fixture(scope="class")
    def iam_estimates(self):
        html = IAM_FIXTURE.read_text(encoding="utf-8")
        return parse_finances_html(html, as_of_date=dt.date(2026, 6, 28))

    @pytest.fixture(scope="class")
    def by_key(self, iam_estimates):
        return {(e.metric, e.fiscal_year): e for e in iam_estimates}

    def test_ticker_extracted_as_iam(self, iam_estimates):
        assert all(e.symbol == "IAM" for e in iam_estimates)

    def test_eps_2026_near_probe_value(self, by_key):
        # Probe said 6.20; actual extracted 6.195
        eps = by_key.get((METRIC_EPS_FORWARD, 2026))
        assert eps is not None, "Missing EPS_Forward 2026"
        assert eps.value == pytest.approx(6.195, abs=0.05)

    def test_eps_2027_present(self, by_key):
        eps = by_key.get((METRIC_EPS_FORWARD, 2027))
        assert eps is not None
        assert eps.value == pytest.approx(6.275, abs=0.05)

    def test_revenue_forward_2026_in_absolute_mad(self, by_key):
        rev = by_key.get((METRIC_REV_FORWARD, 2026))
        assert rev is not None
        # IAM 2026 revenue estimate: ~37,051 MAD M → 37,051,000,000 MAD absolute
        assert rev.value == pytest.approx(37_051 * 1_000_000, rel=0.02)
        assert rev.currency == "MAD"

    def test_ni_forward_2026(self, by_key):
        ni = by_key.get((METRIC_NI_FORWARD, 2026))
        assert ni is not None
        # ~5,444 MAD M → absolute MAD
        assert ni.value == pytest.approx(5_444 * 1_000_000, rel=0.02)
        assert ni.currency == "MAD"

    def test_per_2026_near_probe_value(self, by_key):
        per = by_key.get((METRIC_PER_FORWARD, 2026))
        assert per is not None
        assert per.value == pytest.approx(14.8, abs=0.3)

    def test_target_price(self, by_key):
        tp = by_key.get((METRIC_TARGET_PRICE, 2026))
        assert tp is not None
        assert tp.value == pytest.approx(107.67, abs=1.0)

    def test_rating_hold(self, by_key):
        r = by_key.get((METRIC_RATING, 2026))
        assert r is not None
        assert r.raw_label == "HOLD"

    def test_analyst_count_3(self, iam_estimates):
        eps_ests = [e for e in iam_estimates if e.metric == METRIC_EPS_FORWARD]
        assert eps_ests
        assert all(e.analyst_count == 3 for e in eps_ests)

    def test_no_actual_years_emitted(self, iam_estimates):
        """2021-2025 are actuals for IAM; only 2026+ should appear as estimates."""
        years = {e.fiscal_year for e in iam_estimates
                 if e.metric in (METRIC_EPS_FORWARD, METRIC_NI_FORWARD, METRIC_REV_FORWARD)}
        for actual_year in (2021, 2022, 2023, 2024, 2025):
            assert actual_year not in years, f"Actual year {actual_year} should not be emitted"

    def test_adapter_from_cache(self, tmp_path):
        """Adapter should return estimates when HTML is pre-cached (no live fetch)."""
        # Pre-populate cache
        cache = tmp_path / "ms_cache"
        cache.mkdir()
        shutil.copy(IAM_FIXTURE, cache / "ms_1408717.html")

        adapter = MarketScreenerAdapter(
            cache_dir=cache,
            id_map={1408717: "IAM"},
        )
        ests = adapter.fetch(symbols=["IAM"])
        assert any(e.metric == METRIC_EPS_FORWARD for e in ests)
        eps_2026 = next(
            (e for e in ests if e.metric == METRIC_EPS_FORWARD and e.fiscal_year == 2026),
            None,
        )
        assert eps_2026 is not None
        assert eps_2026.value == pytest.approx(6.195, abs=0.05)
