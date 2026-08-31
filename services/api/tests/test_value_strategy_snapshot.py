from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.services.value_strategy_snapshot import (
    AGING_MAX_AGE_DAYS,
    FRESH_MAX_AGE_DAYS,
    ValueStrategyComputeError,
    _ensure_s3_env_vars,
    _resolved_desk_cost_config,
    snapshot_freshness,
    value_strategy_desk_payload,
)


def test_v2_snapshot_rejects_unsourced_legacy_cost(monkeypatch):
    monkeypatch.delenv("VALUE_STRATEGY_COST_BPS", raising=False)
    monkeypatch.delenv("VALUE_STRATEGY_COST_SOURCE", raising=False)
    with pytest.raises(ValueStrategyComputeError, match="requires VALUE_STRATEGY_COST_BPS"):
        _resolved_desk_cost_config()


def test_v2_snapshot_accepts_explicit_sourced_cost(monkeypatch):
    monkeypatch.setenv("VALUE_STRATEGY_COST_BPS", "27.5")
    monkeypatch.setenv("VALUE_STRATEGY_COST_SOURCE", "desk_schedule_2026-08-30")
    config, source = _resolved_desk_cost_config()
    assert config.cost_bps == pytest.approx(27.5)
    assert source == "desk_schedule_2026-08-30"


def test_desk_payload_uses_persisted_evidence_without_random_inputs(monkeypatch):
    monkeypatch.setenv("VALUE_STRATEGY_COST_BPS", "33")
    monkeypatch.setenv("VALUE_STRATEGY_COST_SOURCE", "desk-certified workbook")
    payload = value_strategy_desk_payload({
        "universe_summary": {"eligible_bm_count": 12, "eligible_cfp_count": 0},
        "strategy_metrics": {
            "S1_bm": {"periods": 4, "cumulative_return": 0.01},
            "S2_cfp": {"periods": 0, "insufficient_data": True},
        },
    })
    assert payload["transaction_cost_bps"] == 33
    assert payload["factor_research"][0]["latest_eligible_count"] == 12
    assert payload["factor_research"][1]["decision"] == "insufficient_data"
    assert payload["portfolio_rules"]["execution_lag_status"] == "not_yet_applied"
    assert len(payload["pipeline_steps"]) == 6
from services.api.app.routers.value_signal import get_value_strategy_snapshot


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    models.FundamentalValueStrategySnapshot.__table__.create(engine)
    models.SignalEngineBatchJob.__table__.create(engine)
    try:
        yield SessionLocal
    finally:
        engine.dispose()


def _make_snapshot(db, *, age_days: float) -> models.FundamentalValueStrategySnapshot:
    computed_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=age_days)
    row = models.FundamentalValueStrategySnapshot(
        config_hash="testhash",
        params_json={},
        result_json={"as_of_date": "2026-06-30", "model_version": "Fundamental Value Strategy v2.1"},
        computed_at=computed_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_no_snapshot_state():
    freshness = snapshot_freshness(None)
    assert freshness["state"] == "no_snapshot"
    assert freshness["age_days"] is None


def test_fresh_state_within_threshold(session_factory):
    db = session_factory()
    row = _make_snapshot(db, age_days=FRESH_MAX_AGE_DAYS - 1)
    freshness = snapshot_freshness(row)
    assert freshness["state"] == "fresh"


def test_aging_state_between_thresholds(session_factory):
    db = session_factory()
    row = _make_snapshot(db, age_days=FRESH_MAX_AGE_DAYS + 5)
    freshness = snapshot_freshness(row)
    assert freshness["state"] == "aging"


def test_stale_state_beyond_aging_threshold(session_factory):
    db = session_factory()
    row = _make_snapshot(db, age_days=AGING_MAX_AGE_DAYS + 10)
    freshness = snapshot_freshness(row)
    assert freshness["state"] == "stale"


def test_failed_refresh_state_overrides_age_even_if_last_snapshot_is_fresh(session_factory):
    """A fresh, valid snapshot must still surface a failed_refresh warning if the most recent
    recompute ATTEMPT failed -- the old valid data is preserved and shown, but the failure is
    not hidden."""
    db = session_factory()
    row = _make_snapshot(db, age_days=1)
    freshness = snapshot_freshness(row, latest_job_status="failed")
    assert freshness["state"] == "failed_refresh"
    # The underlying snapshot data itself is untouched -- only the label changes.
    assert freshness["last_successful_computed_at"] is not None


def test_failed_job_never_replaces_latest_valid_snapshot_row(session_factory):
    """Simulates the exact failure-injection scenario: a first snapshot succeeds and is
    persisted; a second recompute attempt raises before any row is added. The `latest`
    lookup must still return the first (only) row -- a crash never leaves a partial/corrupt
    'latest' row, because persistence is a single all-or-nothing INSERT, not an in-place
    update of a 'current' row."""
    db = session_factory()
    good_row = _make_snapshot(db, age_days=2)

    class FakeException(Exception):
        pass

    def _failing_compute():
        raise FakeException("simulated compute failure (e.g. missing universe file)")

    with pytest.raises(FakeException):
        _failing_compute()
        db.add(models.FundamentalValueStrategySnapshot(config_hash="testhash", params_json={}, result_json={}, computed_at=dt.datetime.now(dt.timezone.utc)))
        db.commit()

    latest = (
        db.query(models.FundamentalValueStrategySnapshot)
        .filter(models.FundamentalValueStrategySnapshot.config_hash == "testhash")
        .order_by(models.FundamentalValueStrategySnapshot.computed_at.desc())
        .first()
    )
    assert latest is not None
    assert latest.id == good_row.id


def test_s3_env_var_bridging_maps_container_names_to_research_code_names(monkeypatch):
    """Regression test for a real 2026-07-06 bug: the worker container sets
    S3_ENDPOINT/S3_ACCESS_KEY/S3_SECRET_KEY, but the research code's fallback defaults look for
    S3_ENDPOINT_URL/AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY, silently defaulting to an
    unreachable 127.0.0.1:9000 inside the container and cascading into an empty-but-succeeded
    strategy snapshot."""
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.setenv("S3_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("S3_ACCESS_KEY", "minio")
    monkeypatch.setenv("S3_SECRET_KEY", "minio12345")
    _ensure_s3_env_vars()
    import os

    assert os.environ["S3_ENDPOINT_URL"] == "http://minio:9000"
    assert os.environ["AWS_ACCESS_KEY_ID"] == "minio"
    assert os.environ["AWS_SECRET_ACCESS_KEY"] == "minio12345"


def test_empty_panel_raises_instead_of_silently_succeeding(monkeypatch):
    """The compute function must raise (so the worker task marks the job failed) rather than
    return a hollow {"error": ...} dict that a naive caller could mistake for success."""
    import services.api.app.services.value_strategy_snapshot as mod

    monkeypatch.setattr(mod, "_build_full_history_panel", lambda db: __import__("pandas").DataFrame())
    with pytest.raises(ValueStrategyComputeError):
        mod.compute_value_strategy_snapshot(db=None)


def test_concurrent_recompute_produces_two_rows_not_corruption(session_factory):
    """Two 'concurrent' successful recomputes each insert their own immutable row (RQ jobs are
    processed serially by a single worker per queue slot in this deployment, but even if two
    somehow ran, INSERT-only persistence means the 'latest' pointer is just 'max(computed_at)'
    -- no partial-write corruption is possible, unlike an in-place UPDATE would risk)."""
    db = session_factory()
    first = _make_snapshot(db, age_days=1)
    import time

    time.sleep(0.01)
    second = _make_snapshot(db, age_days=0)
    rows = db.query(models.FundamentalValueStrategySnapshot).filter_by(config_hash="testhash").all()
    assert len(rows) == 2
    latest = max(rows, key=lambda r: r.computed_at)
    assert latest.id == second.id
    assert first.id != second.id


def test_persisted_snapshot_cannot_override_current_live_authorization(session_factory):
    db = session_factory()
    row = _make_snapshot(db, age_days=1)
    row.result_json = {
        "live_trading_authorized": True,
        "production_readiness": {"status": "LIVE_AUTHORIZED"},
    }
    db.commit()

    response = get_value_strategy_snapshot(db)

    assert response.live_trading_authorized is False
    assert response.production_readiness["status"] == "RESEARCH_ONLY"
    assert response.production_readiness["blocker_ids"]
    assert response.research_pipeline
    assert response.factor_research
    assert response.methodology_version
