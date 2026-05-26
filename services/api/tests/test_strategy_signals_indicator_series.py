from __future__ import annotations

import os

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("MARKET_REFRESH_CRON_ENABLED", "0")

from services.api.app.db import get_db
from services.api.app.routers import strategy_signals


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(strategy_signals.router)

    def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    return app


def _ohlcv(*, include_volume: bool = True) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=160, freq="D")
    close = np.linspace(100.0, 140.0, len(dates)) + 3.0 * np.sin(np.linspace(0.0, 12.0, len(dates)))
    data = {
        "Open": close,
        "High": close + 2.0,
        "Low": close - 2.0,
        "Close": close,
    }
    if include_volume:
        data["Volume"] = np.linspace(100_000.0, 200_000.0, len(dates))
    return pd.DataFrame(data, index=dates)


def _ohlcv_choppy(*, include_volume: bool = True) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=220, freq="D")
    t = np.linspace(0.0, 24.0, len(dates))
    close = 100.0 + 8.0 * np.sin(t)
    data = {
        "Open": close + 0.2 * np.cos(t),
        "High": close + 1.8,
        "Low": close - 1.8,
        "Close": close,
    }
    if include_volume:
        data["Volume"] = 150_000.0 + 25_000.0 * np.cos(0.5 * t)
    return pd.DataFrame(data, index=dates)


def _ohlcv_string_numbers() -> pd.DataFrame:
    frame = _ohlcv()
    return frame.astype(str)


def test_indicator_series_supports_ichimoku_payload(monkeypatch) -> None:
    app = _app()
    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: _ohlcv())

    client = TestClient(app)
    response = client.post(
        "/strategy/signal/indicator-series",
        json={
            "symbol": "AAA",
            "indicator": "ichimoku",
            "params": {"tenkan": 9, "kijun": 26, "senkou_b": 52},
            "timeframe": "1D",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["indicator"] == "ichimoku"
    assert payload["plot_payload"]["type"] == "overlay_cloud"
    assert "tenkan_sen" in payload["plot_payload"]
    assert payload["current_label"] in {"Haussier", "Baissier", "Neutre"}


def test_indicator_series_rejects_invalid_uo_param_order(monkeypatch) -> None:
    app = _app()
    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: _ohlcv())

    client = TestClient(app)
    response = client.post(
        "/strategy/signal/indicator-series",
        json={
            "symbol": "AAA",
            "indicator": "uo",
            "params": {"period_1": 14, "period_2": 7, "period_3": 28},
            "timeframe": "1D",
        },
    )

    assert response.status_code == 422
    assert "period_1 < period_2 < period_3" in response.text


def test_indicator_series_requires_volume_for_mfi(monkeypatch) -> None:
    app = _app()
    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: _ohlcv(include_volume=False))

    client = TestClient(app)
    response = client.post(
        "/strategy/signal/indicator-series",
        json={
            "symbol": "AAA",
            "indicator": "mfi",
            "params": {"period": 14, "oversold": 20, "overbought": 80},
            "timeframe": "1D",
        },
    )

    assert response.status_code == 422
    assert "Volume data missing" in response.text


def test_indicator_series_supports_sma_period_alias(monkeypatch) -> None:
    app = _app()
    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: _ohlcv())

    client = TestClient(app)
    response = client.post(
        "/strategy/signal/indicator-series",
        json={
            "symbol": "AAA",
            "indicator": "sma",
            "params": {"period": 21},
            "timeframe": "1D",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["params"]["window"] == 21.0
    assert payload["live_bar_applied"] is False
    assert payload["data_as_of"] == "2024-06-08"


def test_indicator_series_live_bar_replaces_same_day(monkeypatch) -> None:
    app = _app()
    frame = _ohlcv()
    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: frame.copy())

    client = TestClient(app)
    response = client.post(
        "/strategy/signal/indicator-series",
        json={
            "symbol": "AAA",
            "indicator": "sma",
            "params": {"period": 20},
            "timeframe": "1D",
            "live_bar": {
                "date": str(frame.index[-1])[:10],
                "open": 139.0,
                "high": 150.0,
                "low": 138.0,
                "close": 200.0,
                "volume": 222_000.0,
                "source": "test",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["live_bar_applied"] is True
    assert len(payload["close"]) == len(frame)
    assert payload["close"][-1] == 200.0
    assert payload["data_as_of"] == str(frame.index[-1])[:10]


def test_indicator_series_live_bar_appends_newer_day(monkeypatch) -> None:
    app = _app()
    frame = _ohlcv()
    next_date = (frame.index[-1] + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: frame.copy())

    client = TestClient(app)
    response = client.post(
        "/strategy/signal/indicator-series",
        json={
            "symbol": "AAA",
            "indicator": "sma",
            "params": {"period": 20},
            "timeframe": "1D",
            "live_bar": {
                "date": next_date,
                "open": 141.0,
                "high": 142.0,
                "low": 140.0,
                "close": 143.0,
                "volume": 222_000.0,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["live_bar_applied"] is True
    assert len(payload["close"]) == len(frame) + 1
    assert payload["dates"][-1] == next_date
    assert payload["close"][-1] == 143.0
    assert payload["data_as_of"] == next_date


def test_indicator_series_live_bar_ignores_stale_day(monkeypatch) -> None:
    app = _app()
    frame = _ohlcv()
    stale_date = (frame.index[-1] - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    original_close = round(float(frame["Close"].iloc[-1]), 4)
    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: frame.copy())

    client = TestClient(app)
    response = client.post(
        "/strategy/signal/indicator-series",
        json={
            "symbol": "AAA",
            "indicator": "sma",
            "params": {"period": 20},
            "timeframe": "1D",
            "live_bar": {
                "date": stale_date,
                "close": 999.0,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["live_bar_applied"] is False
    assert len(payload["close"]) == len(frame)
    assert payload["close"][-1] == original_close


def test_indicator_series_requires_rsi_thresholds(monkeypatch) -> None:
    app = _app()
    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: _ohlcv())

    client = TestClient(app)
    response = client.post(
        "/strategy/signal/indicator-series",
        json={
            "symbol": "AAA",
            "indicator": "rsi",
            "params": {"period": 14},
            "timeframe": "1D",
        },
    )

    assert response.status_code == 422
    assert "period, oversold, overbought" in response.text


def test_indicator_series_supports_rsi_with_thresholds(monkeypatch) -> None:
    app = _app()
    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: _ohlcv_choppy())

    client = TestClient(app)
    response = client.post(
        "/strategy/signal/indicator-series",
        json={
            "symbol": "AAA",
            "indicator": "rsi",
            "params": {"period": 14, "oversold": 30, "overbought": 70},
            "timeframe": "1D",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["params"] == {"period": 14.0, "oversold": 30.0, "overbought": 70.0}


def test_indicator_series_coerces_string_ohlcv_to_numeric(monkeypatch) -> None:
    app = _app()
    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: _ohlcv_string_numbers())

    client = TestClient(app)
    response = client.post(
        "/strategy/signal/indicator-series",
        json={
            "symbol": "AAA",
            "indicator": "sma",
            "params": {"period": 20},
            "timeframe": "1D",
        },
    )

    assert response.status_code == 200


def test_indicator_series_returns_422_when_close_missing(monkeypatch) -> None:
    app = _app()
    broken = _ohlcv().drop(columns=["Close"])
    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: broken)

    client = TestClient(app)
    response = client.post(
        "/strategy/signal/indicator-series",
        json={
            "symbol": "AAA",
            "indicator": "sma",
            "params": {"period": 20},
            "timeframe": "1D",
        },
    )

    assert response.status_code == 422
    assert "Close column missing" in response.text
