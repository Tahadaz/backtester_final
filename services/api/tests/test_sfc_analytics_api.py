from __future__ import annotations

import datetime as dt

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.db import get_db
from services.api.app.routers.analytics import router
from services.api.app.services.fundamental_cross_section import SFC_CONFIG_HASH, SFC_METHODOLOGY_VERSION


def _client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.FundamentalCrossSectionScore.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_db
    return TestClient(app), SessionLocal, engine


def _insert_score(db, symbol: str, as_of: dt.date, rank: int, tercile: str, sfc: float) -> None:
    db.add(
        models.FundamentalCrossSectionScore(
            symbol=symbol,
            as_of_date=as_of,
            sfc=sfc,
            rank=rank,
            tercile=tercile,
            pillar_val=0.1 * rank,
            pillar_qual=0.2 * rank,
            pillar_fmom=None,
            pillar_pmom=0.3 * rank,
            coverage_ratio=0.75,
            attribution_json={"VAL": 0.1 * rank},
            config_hash=SFC_CONFIG_HASH,
            methodology_version=SFC_METHODOLOGY_VERSION,
            computed_at=dt.datetime(2026, 7, 5, tzinfo=dt.timezone.utc),
        )
    )


def test_fundamental_cross_section_returns_latest_ranked_rows() -> None:
    client, SessionLocal, engine = _client()
    try:
        db = SessionLocal()
        _insert_score(db, "BBB", dt.date(2026, 7, 1), 2, "middle", 0.2)
        _insert_score(db, "AAA", dt.date(2026, 7, 1), 1, "top", 1.2)
        db.commit()

        response = client.get("/analytics/fundamental-cross-section")

        assert response.status_code == 200
        payload = response.json()
        assert payload["as_of_date"] == "2026-07-01"
        assert payload["validation_label"] == "validé sur 2023–2026 (une seule période de marché)"
        assert [row["symbol"] for row in payload["rows"]] == ["AAA", "BBB"]
        assert payload["rows"][0]["pillars"]["val"] == 0.1
    finally:
        engine.dispose()


def test_fundamental_cross_section_symbol_history_honors_as_of_limit() -> None:
    client, SessionLocal, engine = _client()
    try:
        db = SessionLocal()
        _insert_score(db, "AAA", dt.date(2026, 6, 24), 3, "bottom", -0.5)
        _insert_score(db, "AAA", dt.date(2026, 7, 1), 1, "top", 1.2)
        _insert_score(db, "AAA", dt.date(2026, 7, 8), 2, "middle", 0.4)
        db.commit()

        response = client.get("/analytics/fundamental-cross-section/aaa?as_of=2026-07-01&limit=5")

        assert response.status_code == 200
        payload = response.json()
        assert payload["symbol"] == "AAA"
        assert [row["as_of_date"] for row in payload["history"]] == ["2026-07-01", "2026-06-24"]
    finally:
        engine.dispose()
