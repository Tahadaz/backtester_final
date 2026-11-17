"""Gap audit, backfill planning, self-healing refresh window. No network, no DB, no S3."""
from __future__ import annotations

import datetime as dt
import importlib
from pathlib import Path

import pandas as pd
import pytest

from core.quant_core import data as core_data
from services.worker.tasks import backfill_bourse_history as bf
from services.worker.tasks.ingest_market_data import _merge_overwrite_if_different

rmd = importlib.import_module("services.worker.tasks.refresh_market_data")

TODAY = dt.date(2026, 11, 17)


def _bars(rows: dict[str, float], tz: str | None = "UTC") -> pd.DataFrame:
    idx = pd.DatetimeIndex(list(rows), tz=tz)
    close = pd.Series(list(rows.values()), index=idx)
    return pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 100.0}, index=idx
    )


def _cal(*days: str) -> set[dt.date]:
    return {dt.date.fromisoformat(d) for d in days}


def test_merge_inserts_interior_missing_date_not_only_tail():
    old = _bars({"2026-09-01": 10, "2026-09-03": 12})
    incoming = _bars({"2026-09-02": 11, "2026-09-03": 12})
    merged, summary = _merge_overwrite_if_different(old, incoming)
    assert [ts.date().isoformat() for ts in merged.index] == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert summary["inserted_count"] == 1 and summary["overwritten_overlap_count"] == 0


def test_audit_classifies_real_gap_vs_exchange_absent():
    cal = _cal("2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-09")
    old = _bars({"2026-11-02": 10, "2026-11-05": 13, "2026-11-09": 14})
    # Exchange has 11-03 but not 11-04 (suspended/untraded for this name).
    exch = _bars({"2026-11-02": 10, "2026-11-03": 11, "2026-11-05": 13, "2026-11-09": 14})
    rep = bf.audit_series(old, exch, cal, today=TODAY, lookback_days=45)
    assert rep["missing_count"] == 1 and rep["missing_dates"] == ["2026-11-03"]
    assert rep["first_missing"] == rep["last_missing"] == "2026-11-03"
    assert rep["exchange_absent_dates"] == ["2026-11-04"] and rep["exchange_absent_count"] == 1
    assert rep["mismatch_count"] == 0


def test_audit_does_not_count_dates_before_first_stored_bar():
    cal = _cal("2026-10-01", "2026-10-02", "2026-10-05")
    old = _bars({"2026-10-02": 1, "2026-10-05": 2})
    exch = _bars({"2026-10-01": 1, "2026-10-02": 1, "2026-10-05": 2})
    assert bf.audit_series(old, exch, cal, today=TODAY, lookback_days=45)["missing_count"] == 0


def test_audit_reports_close_mismatch_and_splits_older_than_lookback():
    cal = _cal("2026-08-03", "2026-11-10")
    old = _bars({"2026-08-03": 10.0, "2026-11-10": 20.0})
    exch = _bars({"2026-08-03": 10.5, "2026-11-10": 20.5})
    rep = bf.audit_series(old, exch, cal, today=TODAY, lookback_days=45)
    assert rep["mismatch_count"] == 2 and rep["mismatch_older_than_lookback"] == 1
    assert {m["date"] for m in rep["mismatch_sample"]} == {"2026-08-03", "2026-11-10"}


def test_plan_insert_only_for_old_dates_overwrite_inside_lookback():
    # lookback window starts 2026-10-03 for TODAY=2026-11-17, lookback=45
    old = _bars({"2026-08-03": 10.0, "2026-11-10": 20.0})
    exch = _bars({
        "2026-07-01": 5.0,    # before first stored bar -> not prepended
        "2026-08-03": 99.0,   # old + differing -> must NOT be overwritten
        "2026-08-04": 11.0,   # old + missing   -> inserted
        "2026-11-10": 21.0,   # inside window + differing -> overwritten
        "2026-11-11": 22.0,   # inside window + missing   -> inserted
    })
    incoming = bf.plan_incoming(old, exch, today=TODAY, lookback_days=45)
    merged, summary = _merge_overwrite_if_different(old, incoming)

    closes = {ts.date().isoformat(): c for ts, c in merged["Close"].items()}
    assert closes == {"2026-08-03": 10.0, "2026-08-04": 11.0, "2026-11-10": 21.0, "2026-11-11": 22.0}
    assert summary["inserted_count"] == 2 and summary["overwritten_overlap_count"] == 1


def test_apply_is_idempotent_second_audit_reports_no_gaps():
    cal = _cal("2026-08-03", "2026-08-04", "2026-08-05", "2026-11-10")
    old = _bars({"2026-08-03": 10.0, "2026-11-10": 20.0})
    exch = _bars({"2026-08-03": 10.0, "2026-08-04": 11.0, "2026-11-10": 20.0})  # 08-05: exchange absent
    assert bf.audit_series(old, exch, cal, today=TODAY, lookback_days=45)["missing_count"] == 1
    merged, _ = _merge_overwrite_if_different(old, bf.plan_incoming(old, exch, today=TODAY, lookback_days=45))
    again = bf.audit_series(merged, exch, cal, today=TODAY, lookback_days=45)
    assert again["missing_count"] == 0 and again["exchange_absent_dates"] == ["2026-08-05"]
    merged2, summary2 = _merge_overwrite_if_different(merged, bf.plan_incoming(merged, exch, today=TODAY, lookback_days=45))
    assert summary2["status"] == "unchanged"


def test_plan_with_no_stored_series_takes_everything():
    exch = _bars({"2026-11-09": 1.0, "2026-11-10": 2.0})
    assert len(bf.plan_incoming(None, exch, today=TODAY, lookback_days=45)) == 2


def test_synthesize_index_open_uses_previous_close_per_bar():
    old = _bars({"2026-11-09": 100.0, "2026-11-10": 110.0})
    incoming = pd.DataFrame(
        {"Close": [111.0, 115.0, 120.0], "High": [112.0, 116.0, 121.0], "Low": [109.0, 114.0, 118.0]},
        index=pd.DatetimeIndex(["2026-11-10", "2026-11-11", "2026-11-12"], tz="GMT"),
    )
    out = rmd.synthesize_index_open(old, incoming)
    # 11-10 is overwritten: its Open is the 11-09 close, not its own (or the last stored) close.
    assert list(out["Open"]) == [100.0, 111.0, 115.0]


def test_synthesize_index_open_first_bar_without_history_falls_back_to_close():
    incoming = pd.DataFrame(
        {"Close": [5.0, 6.0], "High": [5.0, 6.0], "Low": [5.0, 6.0]},
        index=pd.DatetimeIndex(["2026-11-10", "2026-11-11"], tz="GMT"),
    )
    assert list(rmd.synthesize_index_open(None, incoming)["Open"]) == [5.0, 5.0]


def test_synthesize_index_open_handles_naive_stored_index():
    old = _bars({"2026-11-09": 100.0}, tz=None)
    incoming = pd.DataFrame(
        {"Close": [101.0], "High": [102.0], "Low": [99.0]}, index=pd.DatetimeIndex(["2026-11-10"], tz="GMT")
    )
    assert list(rmd.synthesize_index_open(old, incoming)["Open"]) == [100.0]


def test_missing_sessions_window_and_first_stored_bar():
    cal = _cal("2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05")
    stored = _cal("2026-11-03", "2026-11-05")
    got = rmd.missing_sessions(stored, cal, window_start=dt.date(2026, 11, 1), window_end=dt.date(2026, 11, 5))
    assert got == [dt.date(2026, 11, 4)]  # 11-02 precedes the first stored bar
    assert rmd.missing_sessions(stored, cal, window_start=dt.date(2026, 11, 1), window_end=dt.date(2026, 11, 3)) == []
    assert rmd.missing_sessions(set(), cal, window_start=dt.date(2026, 11, 1), window_end=dt.date(2026, 11, 5)) == []


def test_refresh_lookback_days_env(monkeypatch):
    monkeypatch.delenv("REFRESH_LOOKBACK_DAYS", raising=False)
    assert rmd.refresh_lookback_days() == 45
    monkeypatch.setenv("REFRESH_LOOKBACK_DAYS", "10")
    assert rmd.refresh_lookback_days() == 10
    monkeypatch.setenv("REFRESH_LOOKBACK_DAYS", "junk")
    assert rmd.refresh_lookback_days() == 45


def test_has_recent_hole_detects_hole_inside_lookback(monkeypatch):
    cal = _cal("2026-11-12", "2026-11-13", "2026-11-16", "2026-11-17")
    monkeypatch.setattr(rmd, "exchange_session_dates", lambda start, today=None: cal)
    stored = _bars({"2026-11-12": 1, "2026-11-16": 2})  # hole on 11-13
    monkeypatch.setattr(rmd, "_try_load_existing_parquet", lambda key: stored)
    assert rmd._has_recent_hole("k", TODAY, before_cutoff=True) is True
    full = _bars({"2026-11-12": 1, "2026-11-13": 1, "2026-11-16": 2})
    monkeypatch.setattr(rmd, "_try_load_existing_parquet", lambda key: full)
    # today's in-progress session (11-17) is not a hole before the 17:00 cutoff
    assert rmd._has_recent_hole("k", TODAY, before_cutoff=True) is False
    assert rmd._has_recent_hole("k", TODAY, before_cutoff=False) is True
    # calendar unavailable -> never blocks the legacy skip
    monkeypatch.setattr(rmd, "exchange_session_dates", lambda start, today=None: set())
    assert rmd._has_recent_hole("k", TODAY, before_cutoff=True) is False


# ---- _do_refresh_symbol routing ------------------------------------------------

class _Mappings:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class _RefreshDB:
    def __init__(self, store_row):
        self.store_row = store_row

    def execute(self, statement, params=None):
        sql = str(statement)
        if "FROM market_data_store" in sql:
            return _Mappings(self.store_row)
        return _Mappings(None)  # provider_symbol_map lookup etc.

    def commit(self):
        pass

    def rollback(self):
        pass


class _AdapterStub:
    instances: list = []

    def __init__(self, frame, label=None):
        self.frame, self.calls, self.meta = frame, [], ({"IAM": {"display_name": label}} if label else {})

    def load(self, symbols, start=None, end=None, interval="1d"):
        self.calls.append(start)
        return type("MD", (), {"bars": {symbols[0]: self.frame}})()


@pytest.fixture
def refresh_env(monkeypatch):
    saved = {}
    monkeypatch.setattr(rmd, "_resolve_provider_symbol", lambda db, s, p: s)
    monkeypatch.setattr(rmd, "boursenova_today", lambda: TODAY)
    monkeypatch.setattr(rmd, "ensure_bucket", lambda: None)
    monkeypatch.setattr(rmd, "_try_load_existing_parquet", lambda key: saved.get("old"))
    monkeypatch.setattr(rmd, "_save_parquet", lambda key, df: saved.__setitem__("saved", df))
    monkeypatch.setattr(rmd, "_persist_stock_frame", lambda *a, **k: {"row_count": len(a[4])})
    monkeypatch.setattr(rmd, "_update_stock_share_count_from_frame", lambda *a, **k: None)
    monkeypatch.setattr(rmd, "is_before_bourse_refresh_cutoff", lambda: False)
    monkeypatch.setattr(rmd, "_update_stock_metadata_from_bourse", lambda db, s, n: saved.__setitem__("name", n))
    monkeypatch.delenv("BOURSE_DIRECT_URL_TEMPLATE", raising=False)
    monkeypatch.delenv("REFRESH_LOOKBACK_DAYS", raising=False)
    return saved


def test_do_refresh_fetches_rolling_lookback_window_not_tail(monkeypatch, refresh_env):
    new = _bars({"2026-11-16": 11.0, "2026-11-17": 12.0})
    adapter = _AdapterStub(new, label="ITISSALAT AL-MAGHRIB")
    monkeypatch.setattr(rmd, "BoursenovaHistoryAdapter", lambda **k: adapter)
    refresh_env["old"] = _bars({"2026-11-13": 10.0})  # stored through 11-13, interior/tail holes after
    db = _RefreshDB({"end_ts": dt.datetime(2026, 11, 13), "data_as_of": dt.date(2026, 11, 13)})

    out = rmd._do_refresh_symbol(db, None, "IAM", "1D", "bourse_direct")

    assert adapter.calls == ["2026-09-29"]  # min(end_ts, today) - 45d, not end_ts + 1
    assert out["status"] == "updated" and out["inserted_count"] == 2
    assert refresh_env["name"] == "ITISSALAT AL-MAGHRIB"


def test_do_refresh_first_load_has_no_start(monkeypatch, refresh_env):
    adapter = _AdapterStub(_bars({"2026-11-17": 12.0}))
    monkeypatch.setattr(rmd, "BoursenovaHistoryAdapter", lambda **k: adapter)
    rmd._do_refresh_symbol(_RefreshDB(None), None, "IAM", "1D", "bourse_direct")
    assert adapter.calls == [None]


def test_do_refresh_bmce_excel_routes_to_boursenova_and_falls_back_to_bmce_live(monkeypatch, refresh_env):
    primary = _AdapterStub(pd.DataFrame())
    fallback = _AdapterStub(_bars({"2026-11-17": 12.0}))
    monkeypatch.setattr(rmd, "BoursenovaHistoryAdapter", lambda **k: primary)
    monkeypatch.setattr(rmd, "BMCECapitalLiveAdapter", type("B", (), {
        "__new__": lambda cls, **k: fallback,
        "listing_id_for": staticmethod(lambda s: "1,2,3"),
    }))
    out = rmd._do_refresh_symbol(_RefreshDB(None), None, "IAM", "1D", "bmce_excel")
    assert primary.calls == [None] and fallback.calls == [None]
    assert out["status"] == "created"


def test_do_refresh_no_data_anywhere_returns_no_new_data(monkeypatch, refresh_env):
    monkeypatch.setattr(rmd, "BoursenovaHistoryAdapter", lambda **k: _AdapterStub(pd.DataFrame()))
    monkeypatch.setattr(rmd.BMCECapitalLiveAdapter, "listing_id_for", staticmethod(lambda s: None))
    assert rmd._do_refresh_symbol(_RefreshDB(None), None, "IAM", "1D", "bourse_direct")["status"] == "no_new_data"


def test_preclose_skip_is_overridden_by_a_hole_but_kept_when_complete(monkeypatch, refresh_env):
    adapter = _AdapterStub(_bars({"2026-11-16": 11.0}))
    monkeypatch.setattr(rmd, "BoursenovaHistoryAdapter", lambda **k: adapter)
    monkeypatch.setattr(rmd, "is_before_bourse_refresh_cutoff", lambda: True)
    monkeypatch.setattr(rmd, "needs_bourse_refresh", lambda d: False)
    db = _RefreshDB({"end_ts": dt.datetime(2026, 11, 16), "data_as_of": dt.date(2026, 11, 16)})

    monkeypatch.setattr(rmd, "_has_recent_hole", lambda *a, **k: True)
    assert rmd._do_refresh_symbol(db, None, "IAM", "1D", "bourse_direct")["status"] != "skipped_preclose_current"

    monkeypatch.setattr(rmd, "_has_recent_hole", lambda *a, **k: False)
    assert rmd._do_refresh_symbol(db, None, "IAM", "1D", "bourse_direct")["status"] == "skipped_preclose_current"


def test_render_table_and_script_importable():
    report = {
        "symbols": {"IAM": {"kind": "stock", "stored_rows": 5, "exchange_rows": 6, "missing_count": 1,
                            "first_missing": "2026-11-03", "last_missing": "2026-11-03",
                            "exchange_absent_count": 0, "mismatch_count": 0, "inserted": 0, "overwritten": 0},
                    "FTSE_CSE_MOROCCO_15": {"kind": "index", "status": "no_boursenova_code"}},
        "errors": {"XYZ": "boom"},
        "summary": {"missing_total": 1},
    }
    text = bf.render_table(report)
    assert "IAM" in text and "2026-11-03" in text and "no_boursenova_code" in text and "ERROR boom" in text
    script = Path(__file__).resolve().parents[3] / "scripts" / "backfill_bourse_history.py"
    assert script.exists() and "--apply" in script.read_text(encoding="utf-8")


# ---- timestamp convention / duplicate-date guards -------------------------------

def _process_with(monkeypatch, old, exch, apply=True):
    saved = []
    monkeypatch.setattr(bf, "_try_load_existing_parquet", lambda key: old)
    monkeypatch.setattr(bf, "_save_parquet", lambda key, df: saved.append(df))
    monkeypatch.setattr(bf, "_persist_stock_frame", lambda *a, **k: {})
    monkeypatch.setattr(bf, "_existing_provider", lambda *a: "bourse_direct")

    class _DB:
        def commit(self):
            pass

    entry = bf._process(
        _DB(), symbol="IAM", kind="stock", exchange_loader=lambda o: exch,
        calendar=_cal("2026-11-09", "2026-11-10"), today=TODAY, lookback=45, apply=apply,
    )
    return entry, saved


def test_backfill_reports_mismatch_for_23h_prev_day_store_and_writes_nothing(monkeypatch):
    old = _bars({"2026-11-08 23:00": 10.0})  # Yahoo-style: 23:00 UTC of the previous day
    exch = _bars({"2026-11-09": 10.0, "2026-11-10": 11.0})
    entry, saved = _process_with(monkeypatch, old, exch)
    assert entry["status"] == "timestamp_convention_mismatch"
    assert entry["sample"] and "23:00" in entry["sample"][0]
    assert saved == []


def test_backfill_aborts_write_when_merge_would_duplicate_a_date(monkeypatch):
    # Same session date at a different time-of-day -> merge would create two rows for 11-09.
    # Deterministic: no tz database dependence (Africa/Casablanca offsets differ across tzdata builds).
    monkeypatch.setattr(bf, "_align_tz", lambda frame, like: frame.copy())
    old = _bars({"2026-11-09": 10.0})
    exch = _bars({"2026-11-09 01:00": 10.0, "2026-11-10 01:00": 11.0})
    entry, saved = _process_with(monkeypatch, old, exch)
    assert entry["status"] == "duplicate_dates_aborted"
    assert saved == []


def test_refresh_helpers_convention_and_duplicates():
    assert rmd.timestamp_convention_sample(None) == []
    assert rmd.timestamp_convention_sample(_bars({"2026-11-09": 1})) == []
    assert rmd.timestamp_convention_sample(_bars({"2026-11-08 23:00": 1}))
    dup = _bars({"2026-11-09 00:00": 1, "2026-11-09 01:00": 2})
    assert rmd.has_duplicate_dates(dup) and not rmd.has_duplicate_dates(_bars({"2026-11-09": 1}))


def test_do_refresh_does_not_write_into_mismatched_store(monkeypatch, refresh_env):
    monkeypatch.setattr(rmd, "BoursenovaHistoryAdapter", lambda **k: _AdapterStub(_bars({"2026-11-17": 12.0})))
    refresh_env["old"] = _bars({"2026-11-12 23:00": 10.0})
    out = rmd._do_refresh_symbol(_RefreshDB(None), None, "IAM", "1D", "bourse_direct")
    assert out["status"] == "timestamp_convention_mismatch" and "saved" not in refresh_env


def test_do_refresh_aborts_on_duplicate_dates(monkeypatch, refresh_env):
    # same session date at a different time-of-day -> merge would create two rows for 11-17
    monkeypatch.setattr(rmd, "_align_tz", lambda frame, like: frame.copy())
    refresh_env["old"] = _bars({"2026-11-17": 10.0})
    monkeypatch.setattr(rmd, "BoursenovaHistoryAdapter", lambda **k: _AdapterStub(_bars({"2026-11-17 01:00": 12.0})))
    out = rmd._do_refresh_symbol(_RefreshDB(None), None, "IAM", "1D", "bourse_direct")
    assert out["status"] == "duplicate_dates_aborted" and "saved" not in refresh_env


def test_backfill_skips_non_bourse_source_symbols(monkeypatch):
    class _R:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class _DB:
        def execute(self, sql, params=None):
            t = str(sql)
            if "stock_master" in t:
                return _R([("IAM", "bourse_direct"), ("AAPL", "yahoo")])
            return _R([])

        def commit(self):
            pass

        def rollback(self):
            pass

    class _Ind:
        def fetch(self, codes, start=None, end=None):
            return {"MASI": _bars({"2026-11-17": 1.0}).assign(display_name="MASI")}

    monkeypatch.setattr(bf, "BoursenovaIndicesAdapter", _Ind)
    monkeypatch.setattr(bf, "_process", lambda db, **k: {"kind": k["kind"], "missing_count": 0,
                        "exchange_absent_count": 0, "mismatch_count": 0, "inserted": 0, "overwritten": 0})
    rep = bf.run_backfill(db=_DB(), indices=False)
    assert rep["symbols"]["AAPL"]["status"] == "skipped_non_bourse_source"
    assert "missing_count" in rep["symbols"]["IAM"]
