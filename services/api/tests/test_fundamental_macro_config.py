from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.services.fundamental_macro import (
    DEFAULT_MACRO_CONFIG,
    geometric_mean_annual_return,
    resolve_macro_config,
)


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
    models.FundamentalMacroConfig.__table__.create(engine)
    models.IndexMaster.__table__.create(engine)
    return engine, SessionLocal


def _close_series(*, annual_return: float, years: int = 10) -> pd.Series:
    dates = pd.date_range("2016-01-01", periods=years + 1, freq="365D")
    values = [100.0 * ((1.0 + annual_return) ** idx) for idx in range(years + 1)]
    return pd.Series(values, index=dates)


def test_geometric_mean_annual_return_matches_index_total_return() -> None:
    close = _close_series(annual_return=0.085, years=10)

    assert geometric_mean_annual_return(close, lookback_years=10) == pytest.approx(0.085, abs=2e-4)


def test_default_macro_config_reproduces_current_base_inputs() -> None:
    engine, SessionLocal = _session()
    db = SessionLocal()
    try:
        macro = resolve_macro_config(db)

        assert macro.risk_free_rate == pytest.approx(0.035)
        assert macro.equity_risk_premium == pytest.approx(DEFAULT_MACRO_CONFIG["manual_equity_risk_premium"])
        assert macro.country_risk_premium == pytest.approx(0.0)
        assert macro.inputs["risk_free_source"] == "treasury_curve:10Y"
        assert macro.inputs["erp_source"] == "manual"
        assert macro.inputs["country_risk_source"] == "auto:masi_embedded"
    finally:
        db.close()
        engine.dispose()


def test_tenor_switch_and_manual_risk_free_override() -> None:
    engine, SessionLocal = _session()
    db = SessionLocal()
    try:
        db.add(
            models.FundamentalMacroConfig(
                risk_free_mode="tenor",
                treasury_tenor="5Y",
                treasury_curve_json={"5Y": 0.031, "10Y": 0.035},
                erp_mode="manual",
                manual_equity_risk_premium=0.060,
                is_active=True,
            )
        )
        db.commit()

        tenor = resolve_macro_config(db)
        assert tenor.risk_free_rate == pytest.approx(0.031)

        row = db.query(models.FundamentalMacroConfig).one()
        row.risk_free_mode = "manual"
        row.manual_risk_free_rate = 0.042
        db.commit()

        manual = resolve_macro_config(db)
        assert manual.risk_free_rate == pytest.approx(0.042)
        assert manual.inputs["risk_free_source"] == "manual"
    finally:
        db.close()
        engine.dispose()


def test_index_mode_computes_erp_as_geometric_return_minus_risk_free() -> None:
    engine, SessionLocal = _session()
    db = SessionLocal()
    try:
        db.add(
            models.FundamentalMacroConfig(
                risk_free_mode="manual",
                manual_risk_free_rate=0.030,
                erp_mode="index",
                erp_index_symbol="MASI",
                erp_index_asset_class="index",
                erp_lookback_years=10.0,
                country_risk_mode="auto",
                morocco_country_risk_premium=0.032,
                is_active=True,
            )
        )
        db.commit()

        macro = resolve_macro_config(
            db,
            close_loader=lambda _db, _symbol, _asset_class: _close_series(annual_return=0.090, years=10),
        )

        assert macro.equity_risk_premium == pytest.approx(0.060, abs=2e-4)
        assert macro.inputs["expected_index_return"] == pytest.approx(0.090, abs=2e-4)
        assert macro.country_risk_premium == pytest.approx(0.0)
        assert macro.inputs["country_risk_source"] == "auto:masi_embedded"
    finally:
        db.close()
        engine.dispose()


def test_crp_couples_to_global_index_and_manual_override_wins() -> None:
    engine, SessionLocal = _session()
    db = SessionLocal()
    try:
        db.add(
            models.FundamentalMacroConfig(
                risk_free_mode="manual",
                manual_risk_free_rate=0.035,
                erp_mode="index",
                erp_index_symbol="SP500",
                erp_index_asset_class="factor",
                erp_lookback_years=10.0,
                country_risk_mode="auto",
                morocco_country_risk_premium=0.032,
                is_active=True,
            )
        )
        db.commit()

        global_index = resolve_macro_config(
            db,
            close_loader=lambda _db, _symbol, _asset_class: _close_series(annual_return=0.100, years=10),
        )
        assert global_index.equity_risk_premium == pytest.approx(0.065, abs=2e-4)
        assert global_index.country_risk_premium == pytest.approx(0.032)
        assert global_index.inputs["country_risk_source"] == "auto:morocco_crp_for_global_index"

        row = db.query(models.FundamentalMacroConfig).one()
        row.country_risk_mode = "manual"
        row.manual_country_risk_premium = 0.010
        db.commit()

        manual_crp = resolve_macro_config(
            db,
            close_loader=lambda _db, _symbol, _asset_class: _close_series(annual_return=0.100, years=10),
        )
        assert manual_crp.country_risk_premium == pytest.approx(0.010)
        assert manual_crp.inputs["country_risk_source"] == "manual"
    finally:
        db.close()
        engine.dispose()
