from __future__ import annotations

import datetime as dt
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("MARKET_REFRESH_CRON_ENABLED", "0")
os.environ["FUNDAMENTAL_DISABLE_LIVE_QUOTES"] = "1"

from core.quant_core.fundamentals.domain import FundamentalSnapshot
from core.quant_core.fundamentals.valuation import DEFAULT_ASSUMPTIONS
from services.api.app import models
from services.api.app.services.fundamentals import _apply_live_cost_of_capital


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


def _session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    models.FundamentalBetaHistory.__table__.create(engine)
    return engine, SessionLocal


def _snapshot(symbol: str) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        company_name=symbol,
        latest_statement_year=2025,
        metrics={"Current_Price": 100.0, "MarketCap_Calc": 1_000.0},
        source={"currency": "MAD"},
        as_of_date=dt.date(2026, 3, 31),
    )


def _beta_row(symbol: str, beta: float, *, liquidity_flag: bool = False) -> models.FundamentalBetaHistory:
    return models.FundamentalBetaHistory(
        symbol=symbol,
        as_of=dt.date(2026, 6, 1),
        beta=beta,
        raw_beta=beta,
        method="ols",
        r2=0.20,
        n_obs=104,
        zero_week_frac=0.05,
        liquidity_flag=liquidity_flag,
        proxy="MASI",
        frequency="weekly",
        window_years=2.0,
        warnings_json=[],
    )


def test_live_cost_of_capital_uses_stored_beta_and_floor() -> None:
    engine, SessionLocal = _session()
    db = SessionLocal()
    try:
        db.add(_beta_row("GAZ", 0.44))
        db.commit()

        assumptions, provenance = _apply_live_cost_of_capital(
            db,
            symbol="GAZ",
            assumptions={**DEFAULT_ASSUMPTIONS, "currency": "MAD"},
            provenance={},
            sector="Energie",
            scenario="base",
            snapshot=_snapshot("GAZ"),
            history=[],
        )
        build = assumptions["cost_of_capital_build_up"]

        assert build["beta"] == pytest.approx(0.44)
        assert build["beta_source"] == "beta_history"
        assert build["cost_of_equity_unfloored"] == pytest.approx(0.035 + 0.44 * 0.060)
        assert assumptions["cost_of_equity"] == pytest.approx(0.065)
        assert assumptions["cost_of_equity"] >= assumptions["risk_free_rate"]
        assert provenance["beta"] == "beta_history"
    finally:
        db.close()
        engine.dispose()


def test_negative_beta_is_floored_not_replaced_with_default_beta() -> None:
    engine, SessionLocal = _session()
    db = SessionLocal()
    try:
        db.add(_beta_row("SAH", -0.02))
        db.commit()

        assumptions, _provenance = _apply_live_cost_of_capital(
            db,
            symbol="SAH",
            assumptions={**DEFAULT_ASSUMPTIONS, "currency": "MAD"},
            sector="Assurances",
            scenario="base",
            snapshot=_snapshot("SAH"),
            history=[],
        )
        build = assumptions["cost_of_capital_build_up"]

        assert build["beta"] == pytest.approx(-0.02)
        assert build["beta_source"] == "beta_history"
        assert build["cost_of_equity_unfloored"] == pytest.approx(0.035 - 0.02 * 0.060)
        assert assumptions["cost_of_equity"] == pytest.approx(0.065)
        assert assumptions["cost_of_equity"] != pytest.approx(DEFAULT_ASSUMPTIONS["cost_of_equity"])
    finally:
        db.close()
        engine.dispose()
