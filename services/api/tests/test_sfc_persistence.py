from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.services.fundamental_cross_section import (
    SFC_CONFIG_HASH,
    SFC_METHODOLOGY_VERSION,
    latest_sfc_as_of,
    persist_cross_section_scores,
)
from services.api.app.services.scheduler_registry import SCHEDULE_BY_ID


def _session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.FundamentalCrossSectionScore.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine, SessionLocal


def test_persist_cross_section_scores_replaces_same_methodology_vintage() -> None:
    engine, SessionLocal = _session()
    try:
        db = SessionLocal()
        as_of = dt.date(2026, 7, 5)
        frame = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "sfc": 1.2,
                    "rank": 1,
                    "tercile": "top",
                    "pillar_val": 1.0,
                    "pillar_qual": 0.5,
                    "pillar_fmom": None,
                    "pillar_pmom": 2.0,
                    "coverage_ratio": 0.75,
                    "pillar_attribution": {"val": 1.0, "qual": 0.5, "pmom": 2.0},
                }
            ]
        )
        assert persist_cross_section_scores(db, frame, as_of_date=as_of) == 1
        db.commit()
        assert persist_cross_section_scores(db, frame.assign(sfc=1.4), as_of_date=as_of) == 1
        db.commit()
        rows = db.query(models.FundamentalCrossSectionScore).all()
        assert len(rows) == 1
        assert rows[0].sfc == 1.4
        assert rows[0].config_hash == SFC_CONFIG_HASH
        assert rows[0].methodology_version == SFC_METHODOLOGY_VERSION
        assert latest_sfc_as_of(db) == as_of
    finally:
        engine.dispose()


def test_scheduler_registry_includes_weekly_sfc_cross_section() -> None:
    spec = SCHEDULE_BY_ID["weekly_fundamental_cross_section"]
    assert spec.kind == "fundamental_cross_section"
    assert spec.queue == "market_refresh"
