from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.quant_core.fundamentals.cost_of_capital import BetaEstimate
from services.api.app import models
from services.api.app.services.fundamental_beta import upsert_beta_history


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    models.FundamentalBetaHistory.__table__.create(engine)
    try:
        yield SessionLocal
    finally:
        engine.dispose()


def test_upsert_beta_history_persists_as_of(session_factory) -> None:
    db = session_factory()
    try:
        estimate = BetaEstimate(
            symbol="AAA",
            as_of=dt.date(2026, 6, 1),
            beta=1.12,
            raw_beta=1.10,
            method="ols",
            r2=0.64,
            n_obs=104,
            zero_week_frac=0.05,
            liquidity_flag=False,
            proxy="MASI",
            frequency="weekly",
            window_years=2,
            warnings=[],
        )

        row = upsert_beta_history(db, estimate)
        db.commit()

        assert row.id is not None
        assert row.symbol == "AAA"
        assert row.as_of == dt.date(2026, 6, 1)
        assert row.beta == pytest.approx(1.12)
        assert row.proxy == "MASI"

        updated = upsert_beta_history(db, BetaEstimate(**{**estimate.__dict__, "beta": 1.20}))
        db.commit()

        assert updated.id == row.id
        assert updated.beta == pytest.approx(1.20)
        assert db.query(models.FundamentalBetaHistory).count() == 1
    finally:
        db.close()
