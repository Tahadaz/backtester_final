from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pytest

from quant_core.fundamentals.valuation import (
    DEFAULT_ASSUMPTIONS,
    SCENARIO_DEFAULT_OVERRIDES,
    resolve_assumptions,
)
from services.api.app import models
from services.api.app.services.fundamentals import make_bulk_overrides_loader


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


def test_resolve_returns_defaults_when_no_override() -> None:
    resolved, provenance = resolve_assumptions("ATW", "bull")

    expected = {**DEFAULT_ASSUMPTIONS, **SCENARIO_DEFAULT_OVERRIDES["bull"]}
    assert resolved == expected
    for key in DEFAULT_ASSUMPTIONS:
        expected_layer = "scenario" if key in SCENARIO_DEFAULT_OVERRIDES["bull"] else "default"
        assert provenance[key] == expected_layer


def test_resolve_applies_symbol_override() -> None:
    resolved, provenance = resolve_assumptions(
        "ATW",
        "bull",
        overrides_loader=lambda symbol, scenario: {"wacc": 0.10} if (symbol, scenario) == ("ATW", "bull") else None,
    )

    assert resolved["wacc"] == pytest.approx(0.10)
    assert provenance["wacc"] == "symbol"


def test_resolve_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="unknown assumption key: foo"):
        resolve_assumptions("ATW", "base", overrides_loader=lambda _symbol, _scenario: {"foo": 1.0})


def test_resolve_provenance_layering() -> None:
    resolved, provenance = resolve_assumptions(
        "ATW",
        "bear",
        overrides_loader=lambda _symbol, _scenario: {"wacc": 0.11},
    )

    assert resolved["risk_free_rate"] == DEFAULT_ASSUMPTIONS["risk_free_rate"]
    assert provenance["risk_free_rate"] == "default"
    assert resolved["terminal_growth"] == SCENARIO_DEFAULT_OVERRIDES["bear"]["terminal_growth"]
    assert provenance["terminal_growth"] == "scenario"
    assert resolved["wacc"] == pytest.approx(0.11)
    assert provenance["wacc"] == "symbol"


def test_bulk_loader_one_query_for_many_symbols() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    models.FundamentalAssumptionOverride.__table__.create(engine)
    db = SessionLocal()
    try:
        db.add(
            models.FundamentalAssumptionOverride(
                symbol="SYM001",
                scenario="bull",
                overrides={"wacc": 0.10},
                note="test",
                created_by="tester",
                is_current=True,
            )
        )
        db.commit()

        statements: list[str] = []

        def count_select(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = statement.lower()
            if normalized.lstrip().startswith("select") and "fundamental_assumption_override" in normalized:
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", count_select)
        symbols = [f"SYM{index:03d}" for index in range(50)]
        loader = make_bulk_overrides_loader(db, symbols)
        for symbol in symbols:
            for scenario in ("bear", "base", "bull"):
                loader(symbol, scenario)

        assert len(statements) == 1
        assert loader("SYM001", "bull") == {"wacc": 0.10}
    finally:
        db.close()
        engine.dispose()
