from fastapi.testclient import TestClient
import pytest

from services.api.app.main import app


def _spec():
    return {
        "identity": {"name": "fixture-fx", "version": 1},
        "universe": {"instruments": ["EURUSD"], "base_currency": "USD"},
        "research_source": {"replication_fidelity": "adapted"},
        "signal": {"lookback_months": 1, "lag": 1},
        "position": {"method": "unit", "max_weight": 1.0, "max_gross": 1.0},
    }


def test_data_quality_envelope_and_router_surface():
    client = TestClient(app)
    rows = [{"date": f"2025-01-{day:02d}", "EURUSD": day / 1000} for day in range(1, 12)]
    response = client.post("/cross-asset-research/data-quality", json={"spec": _spec(), "data": rows})
    assert response.status_code == 200
    assert set(response.json()) == {"inputs", "methodology", "data_source", "calculation_date", "assumptions", "units", "warnings", "results", "interpretation"}
    assert response.json()["data_source"] == "fixture"
    paths = {route.path for route in app.routes}
    assert "/cross-asset-research/runs/{run_id}/robustness" in paths
    assert "/cross-asset-research/strategies/{strategy_id}/current-signal" in paths


def test_commodity_curve_is_fixture_labelled_and_never_claims_tradability():
    client = TestClient(app)
    records = [
        {"instrument_id": "GC", "date": "2025-01-02", "field": "settle", "value": value, "currency": "USD", "contract_expiry": expiry, "source": "fixture"}
        for value, expiry in [(2650, "2025-02-25"), (2642, "2025-04-25"), (2638, "2025-06-25"), (2630, "2025-08-25")]
    ]
    response = client.post("/cross-asset-research/commodity/curve", json={"data": records, "as_of": "2025-01-02", "data_tier": "fixture"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_source"] == "fixture"
    assert "non-tradable" in payload["warnings"][0]
    assert payload["results"]["carry"]["front_second"] > 0


def test_rates_curve_lab_reports_spreads_regimes_and_residual_dv01():
    client = TestClient(app)
    observations = [
        {"date": "2025-01-02", "DGS2": 0.043, "DGS5": 0.044, "DGS10": 0.046, "DGS30": 0.048},
        {"date": "2025-02-03", "DGS2": 0.041, "DGS5": 0.043, "DGS10": 0.045, "DGS30": 0.047},
    ]
    response = client.post("/cross-asset-research/rates/curve-lab", json={"observations": observations, "long_notional": 1_000_000, "long_yield_change_bp": -5, "short_yield_change_bp": -10})
    assert response.status_code == 200
    result = response.json()["results"]
    assert result["history"][-1]["2s10s"] == pytest.approx(0.004)
    assert abs(result["trade"]["residual_dv01"]) < 1e-8
    assert "residual" in response.json()["interpretation"].lower()
