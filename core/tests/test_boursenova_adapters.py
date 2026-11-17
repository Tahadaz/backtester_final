"""Bourse de Casablanca boursenova adapters: parsing, window clamp, retries. No network."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_core import data as d  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "boursenova"
STOCK = json.loads((FIXTURES / "stock_historical_iam.json").read_text(encoding="utf-8"))
INDEX = json.loads((FIXTURES / "indices_historical_masi.json").read_text(encoding="utf-8"))


class _Resp:
    def __init__(self, payload=None, exc=None):
        self._payload, self._exc = payload, exc

    def raise_for_status(self):
        if self._exc:
            raise self._exc

    def json(self):
        return self._payload


class _FakeHttp:
    """Serves ``responder(path, params)`` and records every call."""

    def __init__(self, responder):
        self.responder = responder
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, params=None, timeout=None):
        path = url.replace(d.BOURSENOVA_BASE_URL, "")
        self.calls.append((path, dict(params or {})))
        out = self.responder(path, params or {})
        if isinstance(out, Exception):
            return _Resp(exc=out)
        return _Resp(out)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda *_: None)


def _patch_http(monkeypatch, responder) -> _FakeHttp:
    http = _FakeHttp(responder)
    monkeypatch.setattr(d, "_boursenova_session", lambda: http)
    return http


def test_fixture_is_newest_first_with_padded_symbol_and_holiday_gap():
    assert STOCK["items"][0]["symbol"] == "IAM  "
    seances = [i["seance"] for i in STOCK["items"]]
    assert seances == sorted(seances, key=lambda s: dt.datetime.strptime(s, "%d/%m/%Y"), reverse=True)
    assert "06/11/2026" not in seances  # Green March holiday


def test_parse_stock_items_maps_fields_and_sorts_ascending():
    df = d.parse_boursenova_stock_items(STOCK["items"])
    assert df.index.is_monotonic_increasing
    assert [ts.date() for ts in df.index] == [
        dt.date(2026, 11, 5), dt.date(2026, 11, 9), dt.date(2026, 11, 10), dt.date(2026, 11, 11), dt.date(2026, 11, 12)
    ]
    newest = STOCK["items"][0]
    row = df.loc["2026-11-12"]
    assert row["Open"] == newest["ouverture"]
    assert row["High"] == newest["plusHaut"]
    assert row["Low"] == newest["plusBas"]
    assert row["Close"] == newest["dernierCours"]
    assert row["Volume"] == newest["titresEchanges"]
    assert row["NombreTitres"] == round(newest["capitalisation"] / newest["dernierCours"])


def test_parse_stock_items_rejects_rows_without_parseable_session_date_or_close():
    items = [
        {**STOCK["items"][0], "seance": None},
        {**STOCK["items"][1], "seance": "not-a-date"},
        {**STOCK["items"][2], "dernierCours": None},
        STOCK["items"][3],
    ]
    df = d.parse_boursenova_stock_items(items)
    assert len(df) == 1
    assert df.index[0].date() == dt.date(2026, 11, 9)


def test_clamp_window_to_three_year_ceiling():
    today = dt.date(2026, 11, 17)
    assert d.clamp_boursenova_window("2015-01-01", None, today=today) == (dt.date(2023, 11, 19), today)
    assert d.clamp_boursenova_window(None, "2030-01-01", today=today) == (dt.date(2023, 11, 19), today)
    assert d.clamp_boursenova_window("2026-10-01", "2026-10-31", today=today) == (dt.date(2026, 10, 1), dt.date(2026, 10, 31))
    assert d.clamp_boursenova_window(None, None, today=dt.date(2028, 2, 29))[0] == dt.date(2025, 3, 2)


def test_history_adapter_load_sends_clamped_window_and_returns_utc_frame(monkeypatch):
    http = _patch_http(monkeypatch, lambda path, params: STOCK)
    monkeypatch.setattr(d, "boursenova_today", lambda: dt.date(2026, 11, 17))
    adapter = d.BoursenovaHistoryAdapter(timezone="UTC", use_cache=False)

    bars = adapter.load(["IAM"], start="2010-01-01", end=None, interval="1d").bars["IAM"]

    path, params = http.calls[0]
    assert path == "/stock-historical"
    assert params["instrument"] == "IAM"
    assert params["startDate"] == "2023-11-19" and params["endDate"] == "2026-11-17"
    assert params["isCoursAjuste"] == "false" and params["market"] == "comptant"
    assert len(bars) == 5 and str(bars.index.tz) == "UTC"
    assert adapter.fill_adj_close is False and "Adj Close" not in bars.columns
    assert adapter.meta["IAM"]["display_name"] == "ITISSALAT AL-MAGHRIB"


def test_history_adapter_start_end_are_honoured(monkeypatch):
    _patch_http(monkeypatch, lambda path, params: STOCK)
    adapter = d.BoursenovaHistoryAdapter(timezone="UTC", use_cache=False)
    bars = adapter.load(["IAM"], start="2026-11-10", end="2026-11-11", interval="1d").bars["IAM"]
    assert [ts.date() for ts in bars.index] == [dt.date(2026, 11, 10), dt.date(2026, 11, 11)]


def test_history_adapter_zero_count_response_is_empty_frame(monkeypatch):
    _patch_http(monkeypatch, lambda path, params: {"totalCount": 0, "items": []})
    bars = d.BoursenovaHistoryAdapter(timezone="UTC", use_cache=False).load(["IAM"], start=None).bars
    assert bars["IAM"].empty


def test_http_failure_retries_twice_then_returns_empty_frame(monkeypatch):
    http = _patch_http(monkeypatch, lambda path, params: RuntimeError("boom"))
    with pytest.warns(UserWarning, match="boursenova GET"):
        bars = d.BoursenovaHistoryAdapter(timezone="UTC", use_cache=False).load(["IAM"], start=None).bars
    assert bars["IAM"].empty
    assert len(http.calls) == 3  # 1 try + 2 retries


def test_paging_is_used_only_when_response_is_capped_at_one_page(monkeypatch):
    def item(n):
        day = dt.date(2025, 1, 1) + dt.timedelta(days=n)
        return {**STOCK["items"][0], "seance": day.strftime("%d/%m/%Y")}

    everything = [item(n) for n in range(150)]

    def responder(path, params):
        if "pageNumber" not in params:
            return {"totalCount": 150, "items": everything[:100]}
        lo = (params["pageNumber"] - 1) * params["pageSize"]
        return {"totalCount": 150, "items": everything[lo : lo + params["pageSize"]]}

    http = _patch_http(monkeypatch, responder)
    items = d._boursenova_fetch_items(http, "/stock-historical", {"instrument": "IAM"})
    assert len(items) == 150
    assert [c[1].get("pageNumber") for c in http.calls] == [None, 1, 2]

    # A full-window response (len > page size, totalCount off by one) is NOT re-paged.
    big = {"totalCount": 737, "items": [item(n) for n in range(736)]}
    http2 = _FakeHttp(lambda p, q: big)
    assert len(d._boursenova_fetch_items(http2, "/indices/historical", {})) == 736
    assert len(http2.calls) == 1


def test_index_parse_items_shape_and_display_name():
    df = d.BoursenovaIndicesAdapter.parse_items(INDEX["items"], "MASI")
    assert list(df.columns) == ["Close", "High", "Low", "display_name"]
    assert df.index.name == "Date" and df.index.is_monotonic_increasing and len(df) == 5
    newest = INDEX["items"][0]["indices"]["MASI"]
    assert df["Close"].iloc[-1] == newest["valeur"]
    assert df["High"].iloc[-1] == newest["plusHaut"] and df["Low"].iloc[-1] == newest["plusBas"]
    assert df["display_name"].iloc[0] == "MASI"


def test_index_adapter_fetch_maps_app_symbols_and_skips_unmapped(monkeypatch):
    def responder(path, params):
        code = params["code"]
        items = [
            {**it, "indices": {code: {**it["indices"]["MASI"], "code": code, "libelle": {"fr": "MASI 20"}}}}
            for it in INDEX["items"]
        ]
        return {"totalCount": len(items), "items": items}

    http = _patch_http(monkeypatch, responder)
    adapter = d.BoursenovaIndicesAdapter()
    out = adapter.fetch(["MASI", "FTSE_CSE_MOROCCO_15", "MASI_20"], start="2026-11-01", end="2026-11-17")
    assert set(out) == {"MASI", "MASI_20"}
    assert out["MASI_20"]["display_name"].iloc[0] == "MASI 20"
    assert [c[1]["code"] for c in http.calls] == ["MASI", "MSI20"]
    assert adapter.skipped == ["FTSE_CSE_MOROCCO_15"]
    adapter.fetch(["FTSE_CSE_MOROCCO_15"])
    assert adapter.skipped == ["FTSE_CSE_MOROCCO_15"]  # logged once


def test_index_adapter_empty_response_omits_symbol(monkeypatch):
    _patch_http(monkeypatch, lambda path, params: {"totalCount": 0, "items": []})
    assert d.BoursenovaIndicesAdapter().fetch(["MASI"]) == {}


def test_app_symbol_to_boursenova_code_map_is_explicit_and_unique():
    m = d.BOURSENOVA_APP_SYMBOL_TO_CODE
    assert len(m) == len(d.BOURSENOVA_INDEX_LABELS) == 26
    assert {
        "MASI": "MASI",
        "MASI_20": "MSI20",
        "MASI_ESG": "ESGI",
        "MASI_USD": "MASID",
        "MASI_EUR": "MASIE",
        "MASI_RENTABILITE_BRUT": "MASIR",
        "MASI_RENTABILITE_NET": "MASRN",
        "MASI_MID_AND_SMALL_CAP": "MASIMS",
    }.items() <= m.items()
    assert "FTSE_CSE_MOROCCO_15" not in m and "FTSE_CSE_MOROCCO_ALL_LIQUID" not in m
    assert len(set(m.values())) == len(m)


def test_session_never_disables_tls_verification(monkeypatch):
    monkeypatch.delenv("BOURSENOVA_CA_BUNDLE", raising=False)
    assert d._boursenova_session().verify is True
    monkeypatch.setenv("BOURSENOVA_CA_BUNDLE", "/etc/ssl/bundle.pem")
    http = d._boursenova_session()
    try:
        import truststore  # noqa: F401
    except ImportError:
        assert http.verify == "/etc/ssl/bundle.pem"
    else:
        assert http.verify is True  # OS trust store takes precedence
