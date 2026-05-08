"""Phase 0 scaffolding tests.

Covers:
  * `FreshnessHeadersMiddleware` emits ``X-Computed-At`` / ``X-Upstream-Rev`` /
    ``X-Cache`` when an endpoint stashes them on ``request.state``.
  * `SNAPSHOT_READ_MODE` parsing + per-surface override.
  * `require_admin` accepts a dedicated admin key, rejects general callers.
  * Per-IP rate limiter throttles after the configured threshold.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Freshness headers middleware
# ---------------------------------------------------------------------------


def _build_freshness_app() -> TestClient:
    from services.api.app.freshness import FreshnessHeadersMiddleware, set_freshness

    app = FastAPI()
    app.add_middleware(FreshnessHeadersMiddleware)

    @app.get("/with-meta")
    def with_meta(request: Request):
        set_freshness(
            request,
            computed_at=datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc),
            upstream_rev={"data_as_of": "2026-05-07", "engine_run_id": "abc"},
            cache="hit",
        )
        return {"ok": True}

    @app.get("/without-meta")
    def without_meta():
        return {"ok": True}

    return TestClient(app)


def test_freshness_headers_emitted() -> None:
    client = _build_freshness_app()
    resp = client.get("/with-meta")
    assert resp.status_code == 200
    assert resp.headers["X-Computed-At"] == "2026-05-08T12:00:00+00:00"
    # JSON encodes deterministically (sorted keys, no whitespace).
    assert resp.headers["X-Upstream-Rev"] == '{"data_as_of":"2026-05-07","engine_run_id":"abc"}'
    assert resp.headers["X-Cache"] == "hit"


def test_freshness_headers_absent_when_not_set() -> None:
    client = _build_freshness_app()
    resp = client.get("/without-meta")
    assert resp.status_code == 200
    assert "X-Computed-At" not in resp.headers
    assert "X-Upstream-Rev" not in resp.headers
    assert "X-Cache" not in resp.headers


# ---------------------------------------------------------------------------
# SNAPSHOT_READ_MODE config parsing
# ---------------------------------------------------------------------------


def test_snapshot_read_mode_parsing() -> None:
    from services.api.app.config import _parse_snapshot_read_mode

    assert _parse_snapshot_read_mode(None) == "legacy"
    assert _parse_snapshot_read_mode("") == "legacy"
    assert _parse_snapshot_read_mode("snapshot") == "snapshot"
    assert _parse_snapshot_read_mode("Shadow") == "shadow"
    assert _parse_snapshot_read_mode("garbage") == "legacy"


def test_snapshot_read_mode_overrides_kv() -> None:
    from services.api.app.config import _parse_snapshot_read_mode_overrides

    out = _parse_snapshot_read_mode_overrides("dashboard=snapshot,analytics=shadow,bogus=invalid")
    assert out == {"dashboard": "snapshot", "analytics": "shadow"}


def test_snapshot_read_mode_overrides_json() -> None:
    from services.api.app.config import _parse_snapshot_read_mode_overrides

    out = _parse_snapshot_read_mode_overrides('{"dashboard": "snapshot"}')
    assert out == {"dashboard": "snapshot"}


def test_settings_snapshot_read_mode_for_surface(monkeypatch) -> None:
    monkeypatch.setenv("SNAPSHOT_READ_MODE", "shadow")
    monkeypatch.setenv("SNAPSHOT_READ_MODE_OVERRIDES", "dashboard=snapshot")
    import services.api.app.config as config_module

    importlib.reload(config_module)
    try:
        assert config_module.settings.SNAPSHOT_READ_MODE == "shadow"
        assert config_module.settings.snapshot_read_mode_for("dashboard") == "snapshot"
        assert config_module.settings.snapshot_read_mode_for("analytics") == "shadow"
    finally:
        # Reset env so reload restores defaults for other tests.
        monkeypatch.delenv("SNAPSHOT_READ_MODE", raising=False)
        monkeypatch.delenv("SNAPSHOT_READ_MODE_OVERRIDES", raising=False)
        importlib.reload(config_module)


# ---------------------------------------------------------------------------
# require_admin
# ---------------------------------------------------------------------------


def _build_admin_app() -> TestClient:
    from services.api.app.auth import require_admin

    app = FastAPI()

    @app.get("/admin")
    def admin_endpoint(_admin: None = Depends(require_admin)):
        return {"ok": True}

    return TestClient(app)


def test_require_admin_allows_dev_mode_when_unconfigured(monkeypatch) -> None:
    # Dev mode: nothing configured.
    monkeypatch.setattr("services.api.app.auth.settings.API_KEY", "")
    monkeypatch.setattr("services.api.app.auth.settings.INTERNAL_JWT_SECRET", "")
    monkeypatch.setattr("services.api.app.auth.settings.ADMIN_API_KEY", "")
    client = _build_admin_app()
    assert client.get("/admin").status_code == 200


def test_require_admin_rejects_when_no_admin_credentials(monkeypatch) -> None:
    monkeypatch.setattr("services.api.app.auth.settings.API_KEY", "")
    monkeypatch.setattr("services.api.app.auth.settings.INTERNAL_JWT_SECRET", "")
    monkeypatch.setattr("services.api.app.auth.settings.ADMIN_API_KEY", "supersecret")
    client = _build_admin_app()
    resp = client.get("/admin")
    assert resp.status_code == 403


def test_require_admin_accepts_admin_api_key(monkeypatch) -> None:
    monkeypatch.setattr("services.api.app.auth.settings.API_KEY", "")
    monkeypatch.setattr("services.api.app.auth.settings.INTERNAL_JWT_SECRET", "")
    monkeypatch.setattr("services.api.app.auth.settings.ADMIN_API_KEY", "supersecret")
    client = _build_admin_app()
    resp = client.get("/admin", headers={"X-Admin-Api-Key": "supersecret"})
    assert resp.status_code == 200


def test_require_admin_rejects_general_api_key_when_admin_key_configured(monkeypatch) -> None:
    """If a dedicated ADMIN_API_KEY exists, the general API key must NOT grant admin."""
    monkeypatch.setattr("services.api.app.auth.settings.API_KEY", "user-key")
    monkeypatch.setattr("services.api.app.auth.settings.INTERNAL_JWT_SECRET", "")
    monkeypatch.setattr("services.api.app.auth.settings.ADMIN_API_KEY", "supersecret")
    client = _build_admin_app()
    resp = client.get("/admin", headers={"X-Api-Key": "user-key"})
    assert resp.status_code == 403


def test_require_admin_falls_back_to_general_key_when_no_admin_key(monkeypatch) -> None:
    """Single-tenant deployments without a dedicated admin key still work."""
    monkeypatch.setattr("services.api.app.auth.settings.API_KEY", "user-key")
    monkeypatch.setattr("services.api.app.auth.settings.INTERNAL_JWT_SECRET", "")
    monkeypatch.setattr("services.api.app.auth.settings.ADMIN_API_KEY", "")
    client = _build_admin_app()
    resp = client.get("/admin", headers={"X-Api-Key": "user-key"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


def test_rate_limit_trigger_throttles(monkeypatch) -> None:
    # Force the limiter to fall back to in-memory by making Redis unreachable.
    monkeypatch.setattr(
        "services.api.app.auth._redis_rate_limit",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr("services.api.app.auth.settings.TRIGGER_RATE_LIMIT_PER_MIN", 3)
    monkeypatch.setattr("services.api.app.auth.settings.TRIGGER_RATE_LIMIT_WINDOW_SECONDS", 60)

    # Reset the in-memory limiter so the test starts from a clean state.
    from services.api.app.auth import _LIMITER, rate_limit_trigger

    _LIMITER._buckets.clear()

    app = FastAPI()

    @app.post("/trigger")
    def trigger_endpoint(_rl: None = Depends(rate_limit_trigger)):
        return {"ok": True}

    client = TestClient(app)
    for _ in range(3):
        assert client.post("/trigger").status_code == 200
    blocked = client.post("/trigger")
    assert blocked.status_code == 429
    assert "rate limit" in blocked.json()["detail"].lower()


def test_rate_limit_trigger_disabled_when_limit_zero(monkeypatch) -> None:
    monkeypatch.setattr("services.api.app.auth._redis_rate_limit", lambda *a, **kw: None)
    monkeypatch.setattr("services.api.app.auth.settings.TRIGGER_RATE_LIMIT_PER_MIN", 0)

    from services.api.app.auth import _LIMITER, rate_limit_trigger

    _LIMITER._buckets.clear()

    app = FastAPI()

    @app.post("/trigger")
    def trigger_endpoint(_rl: None = Depends(rate_limit_trigger)):
        return {"ok": True}

    client = TestClient(app)
    for _ in range(20):
        assert client.post("/trigger").status_code == 200


# ---------------------------------------------------------------------------
# PipelineRevision model is registered
# ---------------------------------------------------------------------------


def test_pipeline_revision_model_registered() -> None:
    from services.api.app.db import Base
    from services.api.app.models import PipelineRevision  # noqa: F401

    assert "pipeline_revision" in Base.metadata.tables
    table = Base.metadata.tables["pipeline_revision"]
    cols = {c.name for c in table.columns}
    assert {"id", "stage", "upstream_rev", "content_hash", "created_at"} <= cols


def test_snapshot_columns_mixin_exports() -> None:
    from services.api.app.models import SnapshotColumns

    # Mixin declares the three lineage columns Phase 1+ tables will inherit.
    assert hasattr(SnapshotColumns, "upstream_rev")
    assert hasattr(SnapshotColumns, "computed_at")
    assert hasattr(SnapshotColumns, "as_of_date")
