"""Automated data-quality regression tests (Phase 13, 2026-07-06 forensic audit).

These guard against the exact failure modes confirmed and repaired this
session: demo/test-fixture contamination of production tables, entity
mis-mapping via substring matching, and enterprise-value construction
silently dropping the market-cap term. They connect to the live DB and
`pytest.skip` if it is unavailable, matching the existing convention in
`test_valuation_sanity.py`.
"""
import os

import pytest

DEFAULT_DB_URL = "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"


def _connect():
    import psycopg2

    return psycopg2.connect(host="127.0.0.1", port=5555, dbname="quant", user="app", password="app")


@pytest.fixture()
def conn():
    try:
        c = _connect()
    except Exception as exc:
        pytest.skip(f"local fundamental database unavailable: {exc}")
    yield c
    c.close()


def test_no_demo_or_test_fixture_data_in_production_metric_tables(conn):
    """Guards the ATW/IAM demo_fixture contamination found 2026-07-06: test/demo
    imports must never contribute rows to the tables the research panel reads."""
    cur = conn.cursor()
    cur.execute(
        "select count(*) from fundamental_annual_metric fam "
        "join fundamental_import fi on fi.id = fam.import_id "
        "where fi.data_source in ('demo_fixture', 'test_fixture', 'synthetic')"
    )
    (count,) = cur.fetchone()
    assert count == 0, f"{count} fundamental_annual_metric rows sourced from a demo/test import"


def test_no_active_source_documents_mismapped_to_wrong_symbol_by_substring(conn):
    """Guards the REB/Maghreb substring-collision bug: a document whose company_name
    does not contain the traded symbol's registered company name (case-insensitive,
    ignoring the mismapped-and-quarantined rows) should not be status='succeeded'
    for a different real listed company. This is a narrow, deterministic re-check
    of the one confirmed instance (REB), not a general fuzzy-matching validator."""
    cur = conn.cursor()
    cur.execute(
        "select count(*) from fundamental_source_document "
        "where symbol='REB' and status='succeeded' and company_name not ilike '%%rebab%%'"
    )
    (count,) = cur.fetchone()
    assert count == 0, f"{count} active (status='succeeded') REB documents still mismapped to a different company"


def test_no_unflagged_enterprise_value_equals_net_debt_only(conn):
    """Guards the SBM/universe-wide EV bug: EnterpriseValue rows that exactly equal
    Total_Debt - Cash (i.e. the market-cap term was dropped) should either be tagged
    as the 2026-07-06 repair or have a genuinely unavailable market cap (in which case
    they're expected to remain and are excluded here by requiring a MarketCap_Calc
    to exist for that symbol/year before flagging)."""
    cur = conn.cursor()
    cur.execute(
        """
        select count(*)
        from fundamental_annual_metric ev
        join fundamental_annual_metric td on td.symbol=ev.symbol and td.statement_year=ev.statement_year and td.metric_name='Total_Debt'
        join fundamental_annual_metric c on c.symbol=ev.symbol and c.statement_year=ev.statement_year and c.metric_name='Cash'
        join fundamental_annual_metric mc on mc.symbol=ev.symbol and mc.statement_year=ev.statement_year and mc.metric_name='MarketCap_Calc' and mc.metric_value is not null
        where ev.metric_name='EnterpriseValue' and ev.metric_value is not null
        and ev.raw_metric_name <> 'REPAIR_2026-07-06_ev_recompute'
        and abs(ev.metric_value - (td.metric_value - c.metric_value)) < greatest(abs(ev.metric_value)*0.03, 5000)
        """
    )
    (count,) = cur.fetchone()
    assert count == 0, (
        f"{count} EnterpriseValue rows still match the Total_Debt-Cash-only pattern "
        "despite a MarketCap_Calc being available for that symbol/year"
    )


def test_negative_book_equity_rows_are_a_known_bounded_set(conn):
    """Sanity check, not a strict regression gate: confirms the negative-book-equity
    universe hasn't silently grown due to a new mapping bug. If this fails because
    the count grew, investigate the new symbol(s) before assuming it's fine --
    negative book equity is economically real for distressed firms but should be rare."""
    cur = conn.cursor()
    cur.execute(
        """
        select count(distinct symbol) from fundamental_annual_metric
        where metric_name in ('Total_Equity','Shareholders_Equity','Capitaux_propres','Clean_Capitaux_propres','Common_Equity')
        and metric_value < 0
        """
    )
    (symbol_count,) = cur.fetchone()
    assert symbol_count <= 10, (
        f"{symbol_count} distinct symbols now show negative book equity (baseline 2026-07-06 was 4: SNA, STR, MDP, IBC) "
        "-- investigate before assuming this is organic"
    )
