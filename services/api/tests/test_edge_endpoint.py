from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.db import get_db
from services.api.app.routers import analytics


def _app() -> TestClient:
    app = FastAPI()
    app.include_router(analytics.router)

    def override_get_db():
        yield object()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_happy_path(monkeypatch) -> None:
    payload = {
        "symbol": "ATW",
        "horizon": "monthly",
        "source": "signal_engine",
        "bucket": "buy",
        "direction": "long",
        "n": 42,
        "window_start": "2026-01-01",
        "window_end": "2026-03-01",
        "expected_return_gross": 0.01,
        "expected_return_net": 0.0034,
        "hit_rate": 0.62,
        "hit_ci_lower": 0.51,
        "hit_ci_upper": 0.72,
        "expectancy_gross": {"p_win": 0.62, "avg_win": 0.02, "p_loss": 0.38, "avg_loss": -0.01, "expectancy": 0.01},
        "expectancy_net": {"p_win": 0.62, "avg_win": 0.0134, "p_loss": 0.38, "avg_loss": -0.0166, "expectancy": 0.0034},
        "edge_ratio_gross": 0.4,
        "edge_ratio_net": 0.14,
        "profit_factor_gross": 1.8,
        "profit_factor_net": 1.2,
        "mc_luck_pvalue_gross": 0.004,
        "mc_luck_pvalue_net": 0.008,
        "label_shuffle_pvalue_gross": 0.02,
        "label_shuffle_pvalue_net": 0.03,
        "proven_edge_gross": True,
        "proven_edge_net": True,
        "gates": {"mc_gross": True, "mc_net": True, "wilson": True, "n": True},
        "cost_bps_per_side": 33.0,
        "methodology_version": "2026-05-07",
    }

    monkeypatch.setattr(
        analytics,
        "_edge_cache_payload",
        lambda **kwargs: (payload, "hit"),
    )

    client = _app()
    res = client.get("/analytics/edge?symbol=ATW&horizon=monthly&source=signal_engine")
    assert res.status_code == 200
    assert res.headers["X-Edge-Cache"] == "hit"
    assert res.json()["symbol"] == "ATW"
    assert res.json()["gates"]["mc_net"] is True


def test_cold_cache_returns_null_with_header(monkeypatch) -> None:
    monkeypatch.setattr(
        analytics,
        "_edge_cache_payload",
        lambda **kwargs: (None, "cold"),
    )

    client = _app()
    res = client.get("/analytics/edge?symbol=ATW&horizon=monthly&source=signal_engine")
    assert res.status_code == 200
    assert res.headers["X-Edge-Cache"] == "cold"
    assert res.json() is None
