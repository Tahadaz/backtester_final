from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import threading
import time
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.quant_core.historical_portfolio import METHODOLOGY_VERSION
from services.api.app import models
from services.api.app.config import settings
from services.worker.tasks.historical_portfolio_backtest import _has_newer_successful_overlap


pytestmark = pytest.mark.postgresql


def _engine():
    if os.getenv("RUN_POSTGRES_INTEGRATION") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION=1 to exercise PostgreSQL locks")
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL required")
    return engine


def test_advisory_transaction_lock_serializes_same_methodology() -> None:
    engine = _engine()
    acquired = threading.Event()
    elapsed = []
    with engine.connect() as first:
        transaction = first.begin()
        first.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:version))"),
            {"version": METHODOLOGY_VERSION},
        )

        def contender():
            with engine.connect() as second:
                with second.begin():
                    started = time.perf_counter()
                    second.execute(
                        text("SELECT pg_advisory_xact_lock(hashtext(:version))"),
                        {"version": METHODOLOGY_VERSION},
                    )
                    elapsed.append(time.perf_counter() - started)
                    acquired.set()

        thread = threading.Thread(target=contender)
        thread.start()
        time.sleep(0.25)
        assert not acquired.is_set()
        transaction.commit()
        thread.join(timeout=5)
    assert acquired.is_set()
    assert elapsed[0] >= 0.2


def test_newer_successful_overlap_prevents_older_commit() -> None:
    engine = _engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    now = datetime.now(timezone.utc)
    older = models.HistoricalOpportunityMaterializationRun(
        id=uuid.uuid4(), status="running", methodology_version=METHODOLOGY_VERSION,
        config_json={"start_date": "2026-01-01", "end_date": "2026-03-31"},
        progress_json={}, coverage_json={}, created_at=now - timedelta(minutes=1),
    )
    newer = models.HistoricalOpportunityMaterializationRun(
        id=uuid.uuid4(), status="succeeded", methodology_version=METHODOLOGY_VERSION,
        config_json={"start_date": "2026-03-01", "end_date": "2026-04-30"},
        progress_json={}, coverage_json={}, created_at=now,
    )
    try:
        db.add_all([older, newer])
        db.flush()
        assert _has_newer_successful_overlap(db, models, older, older.config_json) is True
    finally:
        db.rollback()
        db.close()
