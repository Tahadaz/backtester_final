from __future__ import annotations

import os

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("MARKET_REFRESH_CRON_ENABLED", "0")

from services.api.app.db import get_db
from services.api.app.routers import strategy_signals


def _bars(with_volume: bool = True) -> pd.DataFrame:
    data = {
        "Open": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
        "High": [101.0, 102.0, 103.0, 104.0, 105.0, 106.0],
        "Low": [99.0, 100.0, 101.0, 102.0, 103.0, 104.0],
        "Close": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
    }
    if with_volume:
        data["Volume"] = [10.0, 12.0, 11.0, 13.0, 12.0, 14.0]
    return pd.DataFrame(data, index=pd.date_range("2024-01-01", periods=6, freq="D"))


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(strategy_signals.router)

    def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    return app


def test_indicator_series_returns_sma_payload(monkeypatch) -> None:
    app = _app()

    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: _bars())

    with TestClient(app) as client:
        response = client.post(
            "/strategy/signal/indicator-series",
            json={
                "symbol": "AAA",
                "indicator": "sma",
                "params": {"period": 5},
                "timeframe": "1D",
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["indicator"] == "sma"
    assert len(payload["dates"]) == 6
    assert len(payload["indicator_values"]) == 6
    assert payload["indicator_overlay"] is None
    assert payload["current_label"] in {"Haussier", "Baissier", "Neutre"}


def test_indicator_series_rejects_invalid_macd_order(monkeypatch) -> None:
    app = _app()

    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: _bars())

    with TestClient(app) as client:
        response = client.post(
            "/strategy/signal/indicator-series",
            json={
                "symbol": "AAA",
                "indicator": "macd",
                "params": {"fast": 26, "slow": 12, "signal": 9},
                "timeframe": "1D",
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "fast < slow" in response.json()["detail"]


def test_indicator_series_requires_volume_for_obv(monkeypatch) -> None:
    app = _app()

    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: _bars(with_volume=False))

    with TestClient(app) as client:
        response = client.post(
            "/strategy/signal/indicator-series",
            json={
                "symbol": "AAA",
                "indicator": "obv",
                "params": {"ema_period": 5},
                "timeframe": "1D",
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "Volume data missing" in response.json()["detail"]
