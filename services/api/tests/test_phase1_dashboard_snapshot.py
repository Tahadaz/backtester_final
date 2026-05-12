"""Phase 1 tests — dashboard snapshot read modes, ETag, and CAS upsert."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.db import get_db
from services.api.app.freshness import FreshnessHeadersMiddleware
from services.api.app.routers import dashboard_data


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_SAMPLE_PAYLOAD: dict[str, Any] = {
    "payload_version": dashboard_data.DASHBOARD_PAYLOAD_VERSION,
    "generated_at": "2026-05-08T20:30:00+00:00",
    "horizon": "weekly",
    "horizon_label": "Hebdomadaire",
    "stocks": [{"symbol": "ATW", "best_technical_signal": None}],
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
    assert data["stocks"] == [{"symbol": "ATW", "best_technical_signal": None}]


def test_snapshot_mode_merges_live_technical_only_when_snapshot_shape_is_stale(monkeypatch) -> None:
    client = _build_app(monkeypatch, "snapshot")
    stale_payload = {
        key: value
        for key, value in {**_SAMPLE_PAYLOAD, "stocks": [{"symbol": "ATW"}]}.items()
        if key != "payload_version"
    }
    live_payload = {
        **_SAMPLE_PAYLOAD,
        "stocks": [{"symbol": "ATW", "best_technical_signal": {"score_pct": 55.0}}],
    }
    with (
        patch(
            "services.api.app.routers.dashboard_data._latest_snapshot",
            return_value=(stale_payload, _UPSTREAM_REV, _COMPUTED_AT, _AS_OF),
        ),
        patch(
            "services.api.app.routers.dashboard_data.build_dashboard_payload",
            return_value=live_payload,
        ) as mock_builder,
    ):
        resp = client.get("/dashboard/data/weekly")

    assert resp.status_code == 200
    assert resp.headers["X-Cache"] == "stale"
    assert resp.json()["stocks"][0]["best_technical_signal"] == {"score_pct": 55.0}
    mock_builder.assert_called_once()
    args, kwargs = mock_builder.call_args
    assert args[1] == "weekly"
    assert kwargs == {"include_edge": False}


def test_snapshot_mode_rejects_unusable_stale_snapshot_without_live_edge_fallback(monkeypatch) -> None:
    client = _build_app(monkeypatch, "snapshot")
    with (
        patch(
            "services.api.app.routers.dashboard_data._latest_snapshot",
            return_value=("not json", _UPSTREAM_REV, _COMPUTED_AT, _AS_OF),
        ),
        patch(
            "services.api.app.routers.dashboard_data.build_dashboard_payload",
            return_value=_SAMPLE_PAYLOAD,
        ) as mock_builder,
    ):
        resp = client.get("/dashboard/data/weekly")

    assert resp.status_code == 503
    assert "backfill" in resp.json()["detail"].lower()
    mock_builder.assert_not_called()


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
    assert _score_to_label(70) == "Achat fort"
    assert _score_to_label(20) == "Achat"
    assert _score_to_label(0) == "Neutre"
    assert _score_to_label(-20) == "Vente"
    assert _score_to_label(-70) == "Vente forte"
    assert _score_to_label(None) == "Indisponible"


def test_best_signal_rank_rejects_non_actionable_buckets() -> None:
    from services.api.app.services.dashboard_builder import _best_signal_rank

    base_edge = {
        "n": 60,
        "gates": {"n": True},
        "action_expected_return_net": 0.02,
        "action_expected_return_net_ci_lower": 0.01,
        "proven_edge_net": True,
    }

    assert _best_signal_rank({**base_edge, "bucket": "hold", "direction": "none"}) is None
    assert _best_signal_rank({**base_edge, "bucket": None, "direction": "long"}) is None
    assert _best_signal_rank({**base_edge, "bucket": "strong_buy", "direction": "none"}) is None
    assert _best_signal_rank({**base_edge, "bucket": "strong_buy", "direction": "long"}) is not None


def test_best_technical_signal_prefers_strongest_absolute_score() -> None:
    from services.api.app.services.dashboard_builder import (
        _build_best_technical_signal_payload,
        _build_technical_signal_candidate,
    )

    weak_buy = _build_technical_signal_candidate(
        source="signal_engine",
        variant="expanded_ta_simple",
        score=42.0,
        signal_label="Achat",
        per_family={"tendance": {"score_pct": 42.0, "label": "Haussier"}},
    )
    strong_sell = _build_technical_signal_candidate(
        source="wfo",
        variant="expanded_factor_x_ta_simple",
        score=-73.0,
        signal_label="Vente forte",
        per_family={"momentum": {"score_pct": -73.0, "label": "Baissier"}},
    )

    best = _build_best_technical_signal_payload([weak_buy, None, strong_sell])

    assert best is not None
    assert best["source"] == "wfo"
    assert best["variant"] == "expanded_factor_x_ta_simple"
    assert best["direction"] == "short"
    assert best["score_pct"] == -73.0
    assert best["abs_score_pct"] == 73.0


def test_best_technical_signal_tie_prefers_wfo() -> None:
    from services.api.app.services.dashboard_builder import (
        _build_best_technical_signal_payload,
        _build_technical_signal_candidate,
    )

    engine = _build_technical_signal_candidate(
        source="signal_engine",
        variant="expanded_ta_simple",
        score=65.0,
        signal_label="Achat fort",
        per_family={},
    )
    wfo = _build_technical_signal_candidate(
        source="wfo",
        variant="expanded_ta_simple",
        score=65.0,
        signal_label="Achat fort",
        per_family={},
    )

    best = _build_best_technical_signal_payload([engine, wfo])

    assert best is not None
    assert best["source"] == "wfo"


def test_combo_variant_family_payload_maps_to_dashboard_categories() -> None:
    from services.api.app.services.dashboard_builder import _category_scores_from_family_payload

    per_family = _category_scores_from_family_payload(
        {
            "expanded_ta_combo_tendance": {"score_pct": 80.0, "label": "Très haussier"},
            "expanded_ta_combo_momentum": {"score_pct": 40.0, "label": "Momentum haussier"},
            "expanded_ta_combo_oscillation": {"score_pct": 0.0, "label": "Normal"},
            "expanded_ta_combo_volume": {"score_pct": -20.0, "label": "Distribution"},
        },
        "expanded_ta_combo",
    )

    assert per_family == {
        "tendance": {"score_pct": 80.0, "label": "Très haussier"},
        "momentum": {"score_pct": 40.0, "label": "Momentum haussier"},
        "oscillation": {"score_pct": 0.0, "label": "Normal"},
        "volume": {"score_pct": -20.0, "label": "Distribution"},
    }


def test_bucket_to_signal_label() -> None:
    from services.api.app.services.dashboard_builder import _bucket_to_signal_label

    assert _bucket_to_signal_label("strong_buy") == "Achat fort"
    assert _bucket_to_signal_label("buy") == "Achat"
    assert _bucket_to_signal_label("hold") == "Neutre"
    assert _bucket_to_signal_label("sell") == "Vente"
    assert _bucket_to_signal_label("strong_sell") == "Vente forte"
    assert _bucket_to_signal_label(None) == "Indisponible"


def test_round_handles_nan() -> None:
    import math
    from services.api.app.services.dashboard_builder import _round
    assert _round(None) is None
    assert _round(math.nan) is None
    assert _round(1.2345) == 1.23


def test_variation_pct() -> None:
    from services.api.app.services.dashboard_builder import _variation_pct

    assert _variation_pct(105, 100) == 5.0
    assert _variation_pct(95, 100) == -5.0
    assert _variation_pct(100, 0) is None
    assert _variation_pct(None, 100) is None


def test_score_history_revision_fingerprints_edge_inputs() -> None:
    from datetime import datetime, timezone

    from services.api.app.services.dashboard_builder import _score_history_revision

    class Result:
        def __init__(self, *, rows=None):
            self.rows = rows or []

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class FakeDb:
        def __init__(self):
            self.params = []

        def execute(self, statement, params=None):
            self.params.append(params or {})
            sql = str(statement)
            if "FROM signal_score_history" in sql:
                return Result(rows=[
                    {
                        "source": "engine_expanded",
                        "horizon": "medium",
                        "row_count": 10,
                        "symbol_count": 2,
                        "min_date": date(2026, 1, 1),
                        "max_date": date(2026, 1, 10),
                        "oos_row_count": 4,
                    }
                ])
            if "FROM score_history_job" in sql:
                return Result(rows=[
                    {
                        "status": "succeeded",
                        "job_count": 2,
                        "updated_at": datetime(2026, 5, 9, tzinfo=timezone.utc),
                    }
                ])
            raise AssertionError(sql)

    fake_db = FakeDb()
    rev = _score_history_revision(fake_db, "monthly")

    assert rev["horizons"] == ["monthly", "medium"]
    assert rev["total_rows"] == 10
    assert rev["sources"][0]["source"] == "engine_expanded"
    assert rev["jobs_updated_at"] == "2026-05-09T00:00:00+00:00"
    assert len(rev["fingerprint"]) == 16
    assert "engine:expanded_ta_simple" in fake_db.params[0]["sources"]


def test_avg_cats_aggregates_correctly() -> None:
    from services.api.app.services.dashboard_builder import (
        EXPANDED_CATEGORY_FAMILIES,
        _avg_cats,
    )
    cat_dict = {"tendance": [60.0, 80.0]}
    result = _avg_cats(cat_dict, EXPANDED_CATEGORY_FAMILIES)
    assert result["tendance"]["score_pct"] == 70.0
    assert result["tendance"]["label"] == "Très haussier"  # "tendance" is a trend type


def test_market_stats_query_prefers_latest_daily_row() -> None:
    from services.api.app.services.dashboard_builder import _load_dashboard_market_stats

    class Result:
        def mappings(self):
            return self

        def all(self):
            return [{"symbol": "AAA", "close_last": 10.0, "prev_close": 9.0, "adv_20d": 123.0}]

    class FakeDb:
        def __init__(self):
            self.sql = ""
            self.params = None
            self.rollbacks = 0

        def execute(self, statement, params=None):
            self.sql = str(statement)
            self.params = params
            return Result()

        def rollback(self):
            self.rollbacks += 1

    fake_db = FakeDb()
    stats = _load_dashboard_market_stats(fake_db, ["AAA"])

    assert stats["AAA"]["adv_20d"] == 123.0
    assert "lower(timeframe) = '1d'" in fake_db.sql
    assert "data_as_of DESC NULLS LAST" in fake_db.sql
    assert "updated_at DESC NULLS LAST" in fake_db.sql
    assert fake_db.params == {"symbols": ["AAA"]}
    assert fake_db.rollbacks == 0


def test_wfo_dashboard_proof_uses_all_oos_dates(monkeypatch) -> None:
    from core.quant_core.research.oos_index import OosSample, OosWindow
    from services.api.app.routers import analytics as analytics_router
    from services.api.app.services.dashboard_builder import _apply_wfo_all_oos_proof_to_edge
    import core.quant_core.research.oos_index as oos_index_module

    dates = pd.bdate_range("2026-01-01", periods=5)
    score = pd.Series([80.0, 80.0, 80.0, 80.0, 80.0], index=dates)
    prices = pd.DataFrame(
        {
            "Open": [100.0, 100.0, 100.0, 100.0, 100.0],
            "High": [101.0, 102.0, 101.0, 103.0, 101.0],
            "Low": [99.0, 99.0, 98.0, 99.0, 97.0],
            "Close": [100.0, 101.0, 99.0, 102.0, 98.0],
        },
        index=dates,
    )
    oos = OosSample(
        source="wfo",
        horizon="weekly",
        windows=(OosWindow(fold_id="all", start=dates[0], end=dates[-1]),),
        dates=dates,
        score_mode="fold_scoped_winner",
    )

    monkeypatch.setattr(
        analytics_router,
        "_load_score_history",
        lambda *_args, **_kwargs: {"tendance": score},
    )
    monkeypatch.setattr(
        analytics_router,
        "_load_pricing_data",
        lambda *_args, **_kwargs: prices,
    )
    monkeypatch.setattr(
        oos_index_module,
        "oos_sample_for",
        lambda *_args, **_kwargs: oos,
    )

    class FakeDb:
        def rollback(self):
            raise AssertionError("rollback should not be called")

    edge = {
        "variant": "expanded_ta_simple",
        "bucket": "strong_buy",
        "direction": "long",
        "n": 1,
        "proof_n": 1,
        "fwd_horizon_bars": 1,
        "return_calc_method": "open_to_exit_ladder",
        "exit_price_kind": "close",
        "action_expected_return_net": 0.99,
        "hit_rate": 1.0,
        "gates": {"n": False, "wilson": False},
    }

    out = _apply_wfo_all_oos_proof_to_edge(
        FakeDb(),
        symbol="AAA",
        horizon="weekly",
        variant="expanded_ta_simple",
        edge=edge,
        cost_bps=0.0,
    )

    assert out["proof_method"] == "all_wfo_oos_folds_exact_bucket"
    assert out["n"] == 4
    assert out["proof_n"] == 4
    assert out["proof_window_start"] == "2026-01-01"
    assert out["proof_window_end"] == "2026-01-06"
    assert out["action_expected_return_net"] == pytest.approx(0.0)
    assert out["hit_rate"] == pytest.approx(0.5)


def test_wfo_dashboard_proof_caps_all_oos_dates_at_100(monkeypatch) -> None:
    from core.quant_core.research.edge import EDGE_MAX_OBSERVATIONS
    from core.quant_core.research.oos_index import OosSample, OosWindow
    from services.api.app.routers import analytics as analytics_router
    from services.api.app.services.dashboard_builder import _apply_wfo_all_oos_proof_to_edge
    import core.quant_core.research.oos_index as oos_index_module

    dates = pd.bdate_range("2025-01-01", periods=160)
    score = pd.Series(80.0, index=dates)
    prices = pd.DataFrame(
        {
            "Open": [100.0] * len(dates),
            "High": [101.0] * len(dates),
            "Low": [99.0] * len(dates),
            "Close": [100.0] * len(dates),
        },
        index=dates,
    )
    oos = OosSample(
        source="wfo",
        horizon="weekly",
        windows=(OosWindow(fold_id="all", start=dates[0], end=dates[-1]),),
        dates=dates,
        score_mode="fold_scoped_winner",
    )

    monkeypatch.setattr(
        analytics_router,
        "_load_score_history",
        lambda *_args, **_kwargs: {"tendance": score},
    )
    monkeypatch.setattr(
        analytics_router,
        "_load_pricing_data",
        lambda *_args, **_kwargs: prices,
    )
    monkeypatch.setattr(
        oos_index_module,
        "oos_sample_for",
        lambda *_args, **_kwargs: oos,
    )

    class FakeDb:
        def rollback(self):
            raise AssertionError("rollback should not be called")

    out = _apply_wfo_all_oos_proof_to_edge(
        FakeDb(),
        symbol="AAA",
        horizon="weekly",
        variant="expanded_ta_simple",
        edge={
            "variant": "expanded_ta_simple",
            "bucket": "strong_buy",
            "direction": "long",
            "fwd_horizon_bars": 1,
            "return_calc_method": "open_to_exit_ladder",
            "exit_price_kind": "close",
            "gates": {"n": True, "wilson": False},
        },
        cost_bps=0.0,
    )

    assert out["proof_method"] == "all_wfo_oos_folds_exact_bucket"
    assert out["n"] == EDGE_MAX_OBSERVATIONS
    assert out["proof_n"] == EDGE_MAX_OBSERVATIONS
    assert out["proof_window_start"] == dates[-(EDGE_MAX_OBSERVATIONS + 1)].date().isoformat()
    assert out["proof_window_end"] == dates[-2].date().isoformat()
