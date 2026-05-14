from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.schemas.dashboard_portfolio import (
    DashboardDailyBlotterRequest,
    DashboardPortfolioCreate,
    DashboardPortfolioPositionsRequest,
    DashboardPortfolioReplayRequest,
    DashboardPortfolioTradeIn,
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
    models.DashboardPortfolio.__table__.create(engine)
    models.DeskPortfolioPosition.__table__.create(engine)
    models.DeskPortfolioFill.__table__.create(engine)
    models.SignalScoreHistory.__table__.create(engine)
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


def test_portfolio_trades_weight_cmp_by_entry_quantity(session_factory) -> None:
    db = session_factory()
    try:
        first = svc.record_dashboard_portfolio_trade(
            db,
            DashboardPortfolioTradeIn(symbol="AAA", action="BUY", quantity=10, price_mad=100, fees_mad=2),
            owner_user_id="user-a",
        )
        second = svc.record_dashboard_portfolio_trade(
            db,
            DashboardPortfolioTradeIn(symbol="AAA", action="BUY", quantity=20, price_mad=130, fees_mad=3),
            owner_user_id="user-a",
        )

        position = (
            db.query(models.DeskPortfolioPosition)
            .filter(models.DeskPortfolioPosition.owner_user_id == "user-a")
            .filter(models.DeskPortfolioPosition.symbol == "AAA")
            .filter(models.DeskPortfolioPosition.side == "long")
            .one()
        )
        assert first.realized_pnl_mad == -2
        assert second.realized_pnl_mad == -3
        assert position.quantity == 30
        assert position.average_price_mad == pytest.approx(120.0)
        assert svc._position_realized(position) == -5

        exit_fill = svc.record_dashboard_portfolio_trade(
            db,
            DashboardPortfolioTradeIn(symbol="AAA", action="SELL", quantity=5, price_mad=150, fees_mad=1),
            owner_user_id="user-a",
        )
        db.refresh(position)
        assert exit_fill.realized_pnl_mad == 149
        assert position.quantity == 25
        assert position.average_price_mad == pytest.approx(120.0)
        assert svc._position_realized(position) == 144
    finally:
        db.close()


def test_portfolio_invalid_exit_rolls_back_empty_position(session_factory) -> None:
    db = session_factory()
    try:
        with pytest.raises(ValueError):
            svc.record_dashboard_portfolio_trade(
                db,
                DashboardPortfolioTradeIn(symbol="AAA", action="SELL", quantity=5, price_mad=150),
                owner_user_id="user-a",
            )

        assert db.query(models.DeskPortfolioPosition).count() == 0
        assert db.query(models.DeskPortfolioFill).count() == 0
    finally:
        db.close()


def test_same_symbol_can_live_in_multiple_portfolios(session_factory) -> None:
    db = session_factory()
    try:
        first = svc.create_dashboard_portfolio(
            db,
            DashboardPortfolioCreate(name="Portfolio A", components=[{"symbol": "AAA", "shares": 10}]),
            owner_user_id="user-a",
        )
        second = svc.create_dashboard_portfolio(
            db,
            DashboardPortfolioCreate(name="Portfolio B", components=[{"symbol": "AAA", "shares": 20}]),
            owner_user_id="user-a",
        )

        svc.record_dashboard_portfolio_trade(
            db,
            DashboardPortfolioTradeIn(symbol="AAA", action="BUY", quantity=10, price_mad=100),
            owner_user_id="user-a",
            portfolio_id=first.id,
        )
        svc.record_dashboard_portfolio_trade(
            db,
            DashboardPortfolioTradeIn(symbol="AAA", action="BUY", quantity=20, price_mad=110),
            owner_user_id="user-a",
            portfolio_id=second.id,
        )

        first_positions = svc.list_dashboard_positions(db, owner_user_id="user-a", portfolio_id=first.id).positions
        second_positions = svc.list_dashboard_positions(db, owner_user_id="user-a", portfolio_id=second.id).positions
        assert first_positions[0].quantity == 10
        assert first_positions[0].average_price_mad == 100
        assert second_positions[0].quantity == 20
        assert second_positions[0].average_price_mad == 110
    finally:
        db.close()


def test_replay_long_only_bearish_signal_sells_existing_shares(session_factory, monkeypatch) -> None:
    db = session_factory()
    try:
        bars = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 103.0],
                "High": [101.0, 102.0, 103.0, 104.0],
                "Low": [99.0, 100.0, 101.0, 102.0],
                "Close": [100.5, 101.5, 102.5, 103.5],
                "Volume": [1000, 1000, 1000, 1000],
            },
            index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
        )
        monkeypatch.setattr(svc, "load_ohlcv_for_symbol", lambda _db, _symbol, _timeframe: bars)
        db.add_all(
            [
                models.SignalScoreHistory(
                    date=dt.date(2026, 1, 1),
                    symbol="AAA",
                    source="wfo",
                    category="tendance",
                    horizon="monthly",
                    score_pct=100.0,
                ),
                models.SignalScoreHistory(
                    date=dt.date(2026, 1, 2),
                    symbol="AAA",
                    source="wfo",
                    category="tendance",
                    horizon="monthly",
                    score_pct=-100.0,
                ),
            ]
        )
        db.commit()

        portfolio = svc.create_dashboard_portfolio(
            db,
            DashboardPortfolioCreate(name="Replay", components=[{"symbol": "AAA", "shares": 10}]),
            owner_user_id="user-a",
        )
        result = svc.replay_dashboard_portfolio(
            db,
            portfolio.id,
            DashboardPortfolioReplayRequest(
                start_date=dt.date(2026, 1, 1),
                end_date=dt.date(2026, 1, 2),
                symbols=["AAA"],
                component_shares={"AAA": 10},
                side_policy="long_only",
            ),
            owner_user_id="user-a",
        )

        fills = result.replay["fills"]
        assert [fill["action"] for fill in fills] == ["BUY", "SELL"]
        assert result.replay["positions"] == []
        assert result.replay["summary"]["active_position_count"] == 0
    finally:
        db.close()
