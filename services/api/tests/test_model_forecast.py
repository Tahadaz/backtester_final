"""Unit tests for model_forecast.py -- brief 54 §3 Phase 4 wiring.

Focus: the service-layer merge/priority contract (consensus always wins;
the model only fills forward_revenue/forward_net_income gaps) and the
DB->AnnualMetricRow panel loading, using an in-memory sqlite DB (mirroring
test_fundamentals_pit.py's fixture style).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.services import model_forecast
from services.api.app.services.consensus import (
    ASSUMPTIONS_FORWARD_NI,
    ASSUMPTIONS_FORWARD_REV,
    ASSUMPTIONS_FORWARD_SOURCE,
    ASSUMPTIONS_FORWARD_YEAR,
)
from services.api.app.services.model_forecast import (
    clear_model_forecast_cache,
    load_model_forecast_view,
)


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
    for table in (
        models.FundamentalImport.__table__,
        models.FundamentalAnnualMetric.__table__,
        models.StockMaster.__table__,
    ):
        table.create(engine)
    try:
        yield SessionLocal
    finally:
        engine.dispose()


def _import_row(db) -> uuid.UUID:
    run = models.FundamentalImport(
        filename="test.xlsx",
        source_hash="hash",
        data_source="bvc",
        status="succeeded",
    )
    db.add(run)
    db.flush()
    return run.id


def _annual(db, import_id, symbol, year, metric, value, company="Test Co") -> None:
    db.add(
        models.FundamentalAnnualMetric(
            import_id=import_id,
            symbol=symbol,
            company_name=company,
            statement_year=year,
            metric_name=metric,
            metric_value=value,
        )
    )


def _sector(db, symbol, sector) -> None:
    db.add(models.StockMaster(symbol=symbol, sector=sector, asset_type="equity", track_source="bourse_direct"))


def _seed_universe(db, import_id, sector="Banques") -> None:
    """A dozen same-sector symbols with 6 clean years (2017-2022) of
    revenue/NI history each -- 5 year-transitions x 12 symbols = 60 possible
    training rows, comfortably above MIN_TRAIN_OBSERVATIONS (20), so a live
    forecast (as_of_year=2022) has enough panel to fit.

    Symbol "AAA" is the one used as the live prediction target in most tests
    below; the rest are peers whose sole job is to give the model enough
    cross-sectional rows to train on.
    """
    symbols = ["AAA"] + [f"PEER{i}" for i in range(11)]
    years = range(2017, 2023)
    for idx, sym in enumerate(symbols):
        _sector(db, sym, sector)
        base_revenue = 100.0 * (idx + 1)
        base_ni = 10.0 * (idx + 1)
        growth = 0.05 + 0.01 * (idx % 4)
        for offset, year in enumerate(years):
            _annual(db, import_id, sym, year, "Revenue", base_revenue * (1.0 + growth) ** offset)
            _annual(db, import_id, sym, year, "NetIncome", base_ni * (1.0 + growth) ** offset)
    db.flush()


class TestLoadModelForecastView:
    def test_returns_empty_when_consensus_covers_both_keys(self, session_factory):
        db = session_factory()
        import_id = _import_row(db)
        _seed_universe(db, import_id)
        existing = {ASSUMPTIONS_FORWARD_REV: 999.0, ASSUMPTIONS_FORWARD_NI: 99.0}
        result = load_model_forecast_view(
            db, "AAA", import_id=import_id, fiscal_year=2023, as_of_year=2022, existing_forward_view=existing,
        )
        assert result == {}

    def test_fills_both_keys_when_no_consensus(self, session_factory):
        db = session_factory()
        import_id = _import_row(db)
        _seed_universe(db, import_id)
        clear_model_forecast_cache()
        result = load_model_forecast_view(
            db, "AAA", import_id=import_id, fiscal_year=2023, as_of_year=2022, existing_forward_view={},
        )
        assert ASSUMPTIONS_FORWARD_REV in result
        assert ASSUMPTIONS_FORWARD_NI in result
        assert result[ASSUMPTIONS_FORWARD_YEAR] == 2023
        assert result[ASSUMPTIONS_FORWARD_SOURCE] == model_forecast.MODEL_SOURCE_TAG
        # Forward revenue/NI must be positive absolute levels, not growth rates.
        assert result[ASSUMPTIONS_FORWARD_REV] > 0
        assert result[ASSUMPTIONS_FORWARD_NI] > 0

    def test_fills_only_missing_key_when_consensus_partially_covers(self, session_factory):
        db = session_factory()
        import_id = _import_row(db)
        _seed_universe(db, import_id)
        clear_model_forecast_cache()
        existing = {ASSUMPTIONS_FORWARD_NI: 14.0, ASSUMPTIONS_FORWARD_SOURCE: "bkgr"}
        result = load_model_forecast_view(
            db, "AAA", import_id=import_id, fiscal_year=2023, as_of_year=2022, existing_forward_view=existing,
        )
        assert ASSUMPTIONS_FORWARD_REV in result
        assert ASSUMPTIONS_FORWARD_NI not in result  # consensus already had it -- model must not add it
        assert result[ASSUMPTIONS_FORWARD_SOURCE] == f"bkgr,{model_forecast.MODEL_SOURCE_TAG}"

    def test_consensus_wins_on_merge_when_caller_combines_views(self, session_factory):
        """Mirrors the merge fundamentals.py performs:
        {**model_view, **existing_forward_view} -- consensus keys must survive
        even though the model independently computed a different value."""
        db = session_factory()
        import_id = _import_row(db)
        _seed_universe(db, import_id)
        clear_model_forecast_cache()
        existing = {ASSUMPTIONS_FORWARD_REV: 12345.0}
        model_view = load_model_forecast_view(
            db, "AAA", import_id=import_id, fiscal_year=2023, as_of_year=2022, existing_forward_view=existing,
        )
        merged = {**model_view, **existing}
        assert merged[ASSUMPTIONS_FORWARD_REV] == 12345.0

    def test_returns_empty_for_unknown_symbol(self, session_factory):
        db = session_factory()
        import_id = _import_row(db)
        _seed_universe(db, import_id)
        clear_model_forecast_cache()
        result = load_model_forecast_view(
            db, "ZZZ", import_id=import_id, fiscal_year=2023, as_of_year=2022, existing_forward_view={},
        )
        assert result == {}

    def test_returns_empty_when_panel_too_thin_to_fit(self, session_factory):
        """Only one symbol in the whole universe -> nowhere near
        MIN_TRAIN_OBSERVATIONS; the model must decline rather than guess."""
        db = session_factory()
        import_id = _import_row(db)
        _sector(db, "AAA", "Banques")
        for year, value in {2019: 100, 2020: 110, 2021: 120, 2022: 132}.items():
            _annual(db, import_id, "AAA", year, "Revenue", value)
        db.flush()
        clear_model_forecast_cache()
        result = load_model_forecast_view(
            db, "AAA", import_id=import_id, fiscal_year=2023, as_of_year=2022, existing_forward_view={},
        )
        assert result == {}

    def test_cache_is_reused_across_calls_for_same_import(self, session_factory):
        db = session_factory()
        import_id = _import_row(db)
        _seed_universe(db, import_id)
        clear_model_forecast_cache()
        load_model_forecast_view(db, "AAA", import_id=import_id, fiscal_year=2023, as_of_year=2022, existing_forward_view={})
        assert import_id in model_forecast._panel_cache
        cached_before = model_forecast._panel_cache[import_id]
        load_model_forecast_view(db, "BBB", import_id=import_id, fiscal_year=2023, as_of_year=2022, existing_forward_view={})
        assert model_forecast._panel_cache[import_id] is cached_before

    def test_clear_cache_forces_reload(self, session_factory):
        db = session_factory()
        import_id = _import_row(db)
        _seed_universe(db, import_id)
        clear_model_forecast_cache()
        load_model_forecast_view(db, "AAA", import_id=import_id, fiscal_year=2023, as_of_year=2022, existing_forward_view={})
        assert import_id in model_forecast._panel_cache
        clear_model_forecast_cache()
        assert import_id not in model_forecast._panel_cache
