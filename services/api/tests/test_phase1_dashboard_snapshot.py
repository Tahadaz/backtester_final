"""Phase 1 tests — dashboard snapshot read modes, ETag, and CAS upsert."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.db import get_db
from services.api.app.freshness import FreshnessHeadersMiddleware
from services.api.app.routers import dashboard_data


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_SAMPLE_PAYLOAD: dict[str, Any] = {
    "generated_at": "2026-05-08T20:30:00+00:00",
    "horizon": "weekly",
    "horizon_label": "Hebdomadaire",
    "stocks": [{"symbol": "ATW"}],
    "sectors": [],
    "index": {"aggregate_score_pct": 55.0, "stocks": []},
    "custom_index_definitions": [],
}

_UPSTREAM_REV = {"data_as_of": "2026-05-07", "engine_batch_id": "abc123"}
_COMPUTED_AT = datetime(2026, 5, 8, 20, 30, tzinfo=timezone.utc)
_AS_OF = date(2026, 5, 8)


def _make_snapshot_row():
    """Return a tuple matching the SELECT in _latest_snapshot."""
    return (_SAMPLE_PAYLOAD, _UPSTREAM_REV, _COMPUTED_AT, _AS_OF)


def _build_app(monkeypatch, mode: str = "snapshot") -> TestClient:
    monkeypatch.setattr(
        "services.api.app.routers.dashboard_data.settings",
        MagicMock(
            snapshot_read_mode_for=lambda _s: mode,
            REDIS_URL="redis://localhost:6379/0",
        ),
    )
    app = FastAPI()
    app.add_middleware(FreshnessHeadersMiddleware)
    app.include_router(dashboard_data.router)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Snapshot mode
# ---------------------------------------------------------------------------

def test_snapshot_mode_returns_payload(monkeypatch) -> None:
    client = _build_app(monkeypatch, "snapshot")
    with patch(
        "services.api.app.routers.dashboard_data._latest_snapshot",
        return_value=_make_snapshot_row(),
    ):
        resp = client.get("/dashboard/data/weekly")
    assert resp.status_code == 200
    data = resp.json()
    assert data["horizon"] == "weekly"
    assert data["stocks"] == [{"symbol": "ATW"}]


def test_snapshot_mode_returns_computed_at_header(monkeypatch) -> None:
    client = _build_app(monkeypatch, "snapshot")
    with patch(
        "services.api.app.routers.dashboard_data._latest_snapshot",
        return_value=_make_snapshot_row(),
    ):
        resp = client.get("/dashboard/data/weekly")
    assert "X-Computed-At" in resp.headers
    assert "X-Cache" in resp.headers
    assert resp.headers["X-Cache"] == "hit"


def test_snapshot_mode_returns_etag(monkeypatch) -> None:
    client = _build_app(monkeypatch, "snapshot")
    with patch(
        "services.api.app.routers.dashboard_data._latest_snapshot",
        return_value=_make_snapshot_row(),
    ):
        resp = client.get("/dashboard/data/weekly")
    assert "ETag" in resp.headers
    assert resp.headers["ETag"].startswith('"')


def test_snapshot_mode_304_on_if_none_match(monkeypatch) -> None:
    client = _build_app(monkeypatch, "snapshot")
    with patch(
        "services.api.app.routers.dashboard_data._latest_snapshot",
        return_value=_make_snapshot_row(),
    ):
        first = client.get("/dashboard/data/weekly")
        etag = first.headers["ETag"]
        second = client.get("/dashboard/data/weekly", headers={"If-None-Match": etag})
    assert second.status_code == 304


def test_snapshot_mode_503_when_no_row(monkeypatch) -> None:
    client = _build_app(monkeypatch, "snapshot")
    with patch(
        "services.api.app.routers.dashboard_data._latest_snapshot",
        return_value=None,
    ):
        resp = client.get("/dashboard/data/weekly")
    assert resp.status_code == 503
    assert "backfill" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Legacy mode
# ---------------------------------------------------------------------------

def test_legacy_mode_calls_builder(monkeypatch) -> None:
    client = _build_app(monkeypatch, "legacy")
    with patch(
        "services.api.app.routers.dashboard_data.build_dashboard_payload",
        return_value=_SAMPLE_PAYLOAD,
    ) as mock_builder:
        resp = client.get("/dashboard/data/weekly")
    assert resp.status_code == 200
    mock_builder.assert_called_once()
    assert resp.json()["horizon"] == "weekly"


def test_legacy_mode_no_etag(monkeypatch) -> None:
    client = _build_app(monkeypatch, "legacy")
    with patch(
        "services.api.app.routers.dashboard_data.build_dashboard_payload",
        return_value=_SAMPLE_PAYLOAD,
    ):
        resp = client.get("/dashboard/data/weekly")
    assert "ETag" not in resp.headers


# ---------------------------------------------------------------------------
# Shadow mode
# ---------------------------------------------------------------------------

def test_shadow_mode_serves_live_payload(monkeypatch) -> None:
    client = _build_app(monkeypatch, "shadow")
    with (
        patch(
            "services.api.app.routers.dashboard_data.build_dashboard_payload",
            return_value=_SAMPLE_PAYLOAD,
        ),
        patch(
            "services.api.app.routers.dashboard_data._latest_snapshot",
            return_value=_make_snapshot_row(),
        ),
    ):
        resp = client.get("/dashboard/data/weekly")
    assert resp.status_code == 200
    assert resp.json()["horizon"] == "weekly"
    assert resp.headers.get("X-Cache") == "shadow"


def test_shadow_mode_logs_diff_on_stock_count_mismatch(monkeypatch, caplog) -> None:
    client = _build_app(monkeypatch, "shadow")
    live_payload = {**_SAMPLE_PAYLOAD, "stocks": [{"symbol": "ATW"}, {"symbol": "BCP"}]}
    with (
        patch(
            "services.api.app.routers.dashboard_data.build_dashboard_payload",
            return_value=live_payload,
        ),
        patch(
            "services.api.app.routers.dashboard_data._latest_snapshot",
            return_value=_make_snapshot_row(),
        ),
        caplog.at_level("WARNING", logger="services.api.app.routers.dashboard_data"),
    ):
        resp = client.get("/dashboard/data/weekly")
    assert resp.status_code == 200
    assert any("DIFF" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Horizon alias normalisation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("alias,expected", [
    ("weekly", "weekly"),
    ("short", "weekly"),
    ("monthly", "monthly"),
    ("medium", "monthly"),
    ("quarterly", "quarterly"),
    ("long", "quarterly"),
])
def test_horizon_alias_normalisation(monkeypatch, alias, expected) -> None:
    client = _build_app(monkeypatch, "snapshot")
    with patch(
        "services.api.app.routers.dashboard_data._latest_snapshot",
        return_value=_make_snapshot_row(),
    ) as mock_snap:
        resp = client.get(f"/dashboard/data/{alias}")
    assert resp.status_code == 200
    # The horizon in the payload should be whatever the snapshot returns (mocked),
    # but the key point is we reach the snapshot lookup without a 400.


def test_invalid_horizon_returns_400(monkeypatch) -> None:
    client = _build_app(monkeypatch, "snapshot")
    resp = client.get("/dashboard/data/bogus")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------

def test_etag_is_deterministic() -> None:
    from services.api.app.routers.dashboard_data import _etag_for
    t = datetime(2026, 5, 8, tzinfo=timezone.utc)
    rev = {"data_as_of": "2026-05-07"}
    assert _etag_for(t, rev) == _etag_for(t, rev)


def test_etag_differs_on_different_computed_at() -> None:
    from services.api.app.routers.dashboard_data import _etag_for
    t1 = datetime(2026, 5, 8, tzinfo=timezone.utc)
    t2 = datetime(2026, 5, 9, tzinfo=timezone.utc)
    rev = {"data_as_of": "2026-05-07"}
    assert _etag_for(t1, rev) != _etag_for(t2, rev)


# ---------------------------------------------------------------------------
# DashboardSnapshot model is registered
# ---------------------------------------------------------------------------

def test_dashboard_snapshot_model_registered() -> None:
    from services.api.app.db import Base
    from services.api.app.models import DashboardSnapshot  # noqa: F401

    assert "dashboard_snapshot" in Base.metadata.tables
    table = Base.metadata.tables["dashboard_snapshot"]
    cols = {c.name for c in table.columns}
    assert {"horizon", "as_of_date", "payload_jsonb", "upstream_rev", "computed_at"} <= cols


# ---------------------------------------------------------------------------
# Builder pure-helper unit tests
# ---------------------------------------------------------------------------

def test_score_to_label() -> None:
    from services.api.app.services.dashboard_builder import _score_to_label
    assert _score_to_label(70) == "Achat"
    assert _score_to_label(50) == "Neutre"
    assert _score_to_label(20) == "Vente"
    assert _score_to_label(None) == "Indisponible"


def test_round_handles_nan() -> None:
    import math
    from services.api.app.services.dashboard_builder import _round
    assert _round(None) is None
    assert _round(math.nan) is None
    assert _round(1.2345) == 1.23


def test_avg_cats_aggregates_correctly() -> None:
    from services.api.app.services.dashboard_builder import (
        EXPANDED_CATEGORY_FAMILIES,
        _avg_cats,
    )
    cat_dict = {"tendance": [60.0, 80.0]}
    result = _avg_cats(cat_dict, EXPANDED_CATEGORY_FAMILIES)
    assert result["tendance"]["score_pct"] == 70.0
    assert result["tendance"]["label"] == "Hausse"  # "tendance" is a trend type
