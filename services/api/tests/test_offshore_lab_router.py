from fastapi.testclient import TestClient

from services.api.app.main import app


def _request(quote=None):
    return {"bond": {"face_value": 100, "currency": "USD", "coupon_rate": 0.06, "coupon_frequency": 1, "maturity_date": "2031-07-15", "day_count": "30E/360", "redemption": 100}, "settlement_date": "2026-07-15", "quote": quote or {"type": "yield", "value": 0.04}, "notional": 1_000_000}


def test_analytics_full_envelope_and_price_quote_agree():
    client = TestClient(app)
    first = client.post("/offshore-lab/bond/analytics", json=_request())
    assert first.status_code == 200
    payload = first.json()
    assert set(payload) == {"inputs", "methodology", "data_source", "calculation_date", "assumptions", "units", "warnings", "results", "interpretation"}
    assert payload["results"]["cashflows"]
    assert payload["results"]["modified_duration"] > 0
    price = payload["results"]["clean_price"]
    second = client.post("/offshore-lab/bond/analytics", json=_request({"type": "clean_price", "value": price}))
    assert second.status_code == 200
    assert abs(second.json()["results"]["ytm"] - 0.04) < 1e-8


def test_scenarios_and_structured_bad_quote():
    client = TestClient(app)
    body = {**_request(), "shocks_bp": [-100, 0, 100], "holding_period_days": 30}
    response = client.post("/offshore-lab/bond/scenarios", json=body)
    assert response.status_code == 200
    rows = response.json()["results"]["shock_table"]
    assert len(rows) == 3
    assert rows[1]["exact_pnl_per_100"] == 0
    bad = client.post("/offshore-lab/bond/analytics", json=_request({"type": "clean_price", "value": -1}))
    assert bad.status_code == 422
    assert "quote.value" in str(bad.json())
