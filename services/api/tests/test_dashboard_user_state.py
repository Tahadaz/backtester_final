from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.schemas.dashboard_portfolio import (
    DashboardDailyBlotterRequest,
    DashboardPortfolioPositionsRequest,
)
from services.api.app.services import dashboard_portfolio as svc


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover - sqlite harness
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(_type, _compiler, **_kw):  # pragma: no cover - sqlite harness
    return "CHAR(32)"


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    models.DeskPortfolioPosition.__table__.create(engine)
    try:
        yield SessionLocal
    finally:
        engine.dispose()


def test_dashboard_positions_are_owner_scoped(session_factory) -> None:
    db = session_factory()
    try:
        svc.replace_dashboard_positions(
            db,
            DashboardPortfolioPositionsRequest(
                positions=[{"symbol": "AAA", "quantity": 10, "average_price_mad": 100.0}]
            ),
            owner_user_id="user-a",
        )
        svc.replace_dashboard_positions(
            db,
            DashboardPortfolioPositionsRequest(
                positions=[{"symbol": "BBB", "quantity": 20, "average_price_mad": 200.0}]
            ),
            owner_user_id="user-b",
        )

        user_a = svc.list_dashboard_positions(db, owner_user_id="user-a").positions
        user_b = svc.list_dashboard_positions(db, owner_user_id="user-b").positions
        assert [position.symbol for position in user_a] == ["AAA"]
        assert [position.symbol for position in user_b] == ["BBB"]

        svc.replace_dashboard_positions(
            db,
            DashboardPortfolioPositionsRequest(positions=[]),
            owner_user_id="user-a",
        )

        assert svc.list_dashboard_positions(db, owner_user_id="user-a").positions == []
        assert [position.symbol for position in svc.list_dashboard_positions(db, owner_user_id="user-b").positions] == ["BBB"]
    finally:
        db.close()


def test_blotter_saved_position_fallback_uses_owner(session_factory) -> None:
    db = session_factory()
    try:
        svc.replace_dashboard_positions(
            db,
            DashboardPortfolioPositionsRequest(
                positions=[{"symbol": "AAA", "quantity": 10, "average_price_mad": 100.0}]
            ),
            owner_user_id="user-a",
        )
        svc.replace_dashboard_positions(
            db,
            DashboardPortfolioPositionsRequest(
                positions=[{"symbol": "BBB", "quantity": 20, "average_price_mad": 200.0}]
            ),
            owner_user_id="user-b",
        )

        body = DashboardDailyBlotterRequest(symbols=[])
        user_b_positions = svc._manual_positions_for_blotter(db, body, owner_user_id="user-b")
        anonymous_positions = svc._manual_positions_for_blotter(db, body, owner_user_id=None)

        assert list(user_b_positions) == ["BBB"]
        assert anonymous_positions == {}
    finally:
        db.close()
