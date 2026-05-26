from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import pytest

from services.api.app.services import dashboard_live
from services.api.app.services.bourse_live_quotes import LiveQuoteView


def _session() -> dict[str, Any]:
    return {
        "timezone": "Africa/Casablanca",
        "local_time": "2026-05-25T10:30:00+01:00",
        "session_date": "2026-05-25",
        "phase": "continuous",
        "is_live_session": True,
    }


def _quote(*, last_price: float = 120.0, prev_close: float = 100.0) -> LiveQuoteView:
    now = datetime(2026, 5, 25, 9, 30, tzinfo=timezone.utc)
    return LiveQuoteView(
        symbol="AAA",
        session_date=date(2026, 5, 25),
        quote_timestamp=now,
        open_price=105.0,
        last_price=last_price,
        high_price=max(last_price, 121.0),
        low_price=99.0,
        prev_close=prev_close,
        volume=12_345.0,
        source_provider="test",
        source_url="https://example.test/AAA",
        updated_at=now,
        is_fresh=True,
        age_seconds=1.0,
    )


def _official_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [97.0, 101.0],
            "High": [101.0, 108.0],
            "Low": [96.0, 99.0],
            "Close": [98.0, 100.0],
            "Volume": [10_000.0, 11_000.0],
        },
        index=pd.to_datetime(["2026-05-22", "2026-05-25"]),
    )


def test_dashboard_live_refresh_recomputes_price_and_signal_overlays(monkeypatch: pytest.MonkeyPatch) -> None:
    quote = _quote(last_price=120.0, prev_close=100.0)
    captured: dict[str, Any] = {}

    monkeypatch.setattr(dashboard_live, "bourse_session_status", _session)
    monkeypatch.setattr(
        dashboard_live,
        "get_or_refresh_live_quotes",
        lambda _db, symbols, **_kwargs: {"AAA": quote},
    )
    monkeypatch.setattr(dashboard_live, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: _official_frame())

    def fake_signal_engine_candidates(_db, *, close, volume, high, low, **_kwargs):
        captured["signal_engine_close"] = float(close[-1])
        return [{"source": "signal_engine", "score_pct": 35.0}]

    def fake_wfo_candidates(_db, *, close, volume, high, low, **_kwargs):
        captured["wfo_close"] = float(close[-1])
        return ([{"source": "wfo", "score_pct": -82.0}], {"expanded_ta_simple": -82.0})

    def fake_best_technical(candidates):
        captured["technical_candidates"] = list(candidates)
        return {
            "source": "wfo",
            "variant": "expanded_ta_simple",
            "label": "WFO expanded",
            "signal_label": "Vente forte",
            "direction": "short",
            "score_pct": -82.0,
            "abs_score_pct": 82.0,
            "per_family": {},
        }

    def fake_classic(frame):
        captured["classic_close"] = float(frame["Close"].iloc[-1])
        return {
            "source": "signal_engine",
            "variant": "classic_ta",
            "label": "Classic TA",
            "signal_label": "Vente",
            "direction": "short",
            "score_pct": -50.0,
            "abs_score_pct": 50.0,
            "per_family": {},
        }

    def fake_best_signal(_db, *, live_wfo_scores, **_kwargs):
        captured["live_wfo_scores"] = dict(live_wfo_scores)
        return {
            "source": "wfo",
            "variant": "expanded_ta_simple",
            "label": "WFO expanded",
            "signal_label": "Vente forte",
            "bucket": "strong_sell",
            "direction": "short",
            "score": -82.0,
            "live_adjusted": True,
            "live_score_pct": -82.0,
        }

    monkeypatch.setattr(dashboard_live, "_signal_engine_live_candidates", fake_signal_engine_candidates)
    monkeypatch.setattr(dashboard_live, "_wfo_live_candidates", fake_wfo_candidates)
    monkeypatch.setattr(dashboard_live, "_build_best_technical_signal_payload", fake_best_technical)
    monkeypatch.setattr(dashboard_live, "_build_classic_technical_signal_payload_from_ohlcv", fake_classic)
    monkeypatch.setattr(dashboard_live, "_live_best_signal_payload", fake_best_signal)

    payload = dashboard_live.build_dashboard_live_refresh(
        object(),
        symbols=["aaa"],
        horizon="monthly",
        max_age_seconds=60,
        persist_history=True,
    )

    overlay = payload["overlays"][0]
    assert overlay["symbol"] == "AAA"
    assert overlay["last_price"] == 120.0
    assert overlay["prev_close"] == 100.0
    assert overlay["var1j_pct"] == 20.0
    assert overlay["performance"]["one_day"]["pct"] == 20.0
    assert overlay["performance"]["open_to_now"]["pct"] == pytest.approx(14.29)
    assert overlay["live_quote"]["last_price"] == 120.0
    assert overlay["best_technical_signal"]["score_pct"] == -82.0
    assert overlay["best_technical_signal"]["live_adjusted"] is True
    assert overlay["best_technical_signal"]["live_price"] == 120.0
    assert overlay["classic_technical_signal"]["score_pct"] == -50.0
    assert overlay["classic_technical_signal"]["live_adjusted"] is True
    assert overlay["best_signal"]["bucket"] == "strong_sell"
    assert overlay["live_adjusted"] is True
    assert captured["signal_engine_close"] == 120.0
    assert captured["wfo_close"] == 120.0
    assert captured["classic_close"] == 120.0
    assert captured["live_wfo_scores"] == {"expanded_ta_simple": -82.0}


def test_dashboard_live_refresh_can_clear_stale_best_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    quote = _quote(last_price=100.5, prev_close=100.0)

    monkeypatch.setattr(dashboard_live, "bourse_session_status", _session)
    monkeypatch.setattr(
        dashboard_live,
        "get_or_refresh_live_quotes",
        lambda _db, symbols, **_kwargs: {"AAA": quote},
    )
    monkeypatch.setattr(dashboard_live, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: _official_frame())
    monkeypatch.setattr(dashboard_live, "_signal_engine_live_candidates", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        dashboard_live,
        "_wfo_live_candidates",
        lambda *_args, **_kwargs: ([], {"expanded_ta_simple": 0.0}),
    )
    monkeypatch.setattr(dashboard_live, "_build_best_technical_signal_payload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dashboard_live, "_build_classic_technical_signal_payload_from_ohlcv", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dashboard_live, "_live_best_signal_payload", lambda *_args, **_kwargs: None)

    payload = dashboard_live.build_dashboard_live_refresh(
        object(),
        symbols=["AAA"],
        horizon="monthly",
        max_age_seconds=60,
        persist_history=True,
    )

    overlay = payload["overlays"][0]
    assert overlay["last_price"] == 100.5
    assert "best_signal" in overlay
    assert overlay["best_signal"] is None
    assert overlay["classic_technical_signal"] is None
    assert overlay["live_adjusted"] is False
