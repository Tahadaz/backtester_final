from __future__ import annotations

import datetime as dt

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.services.fundamentals import derive_recommendation, derive_research_overlay


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


def _ensemble(
    fair_value: float,
    *,
    usable_models: int = 5,
    confidence: float = 0.80,
    dispersion_cv: float | None = 0.05,
    scenario: str = "base",
) -> models.FundamentalEnsembleResult:
    return models.FundamentalEnsembleResult(
        symbol="RAT",
        scenario=scenario,
        fair_value_low=fair_value * 0.95,
        fair_value_base=fair_value,
        fair_value_high=fair_value * 1.05,
        current_price=100.0,
        upside_pct=fair_value / 100.0 - 1.0,
        confidence_score=confidence,
        usable_model_count=usable_models,
        excluded_model_count=0,
        model_weights_json={"fcff_dcf": 1.0},
        warnings_json=[],
        model_dispersion_cv=dispersion_cv,
    )


def test_return_vs_cost_of_equity_ladder_maps_all_five_labels() -> None:
    cases = [
        (122.0, "BUY"),
        (116.0, "ACCUMULATE"),
        (111.0, "HOLD"),
        (105.0, "REDUCE"),
        (95.0, "SELL"),
    ]

    for fair_value, expected in cases:
        assert (
            derive_recommendation(
                _ensemble(fair_value),
                current_price=100.0,
                cost_of_equity=0.10,
                forward_dividend_yield=0.0,
            )
            == expected
        )


def test_two_usable_models_do_not_publish_a_rating() -> None:
    assert (
        derive_recommendation(
            _ensemble(140.0, usable_models=2),
            current_price=100.0,
            cost_of_equity=0.10,
            forward_dividend_yield=0.0,
        )
        == "NR"
    )


def test_low_model_agreement_does_not_publish_a_rating() -> None:
    assert (
        derive_recommendation(
            _ensemble(140.0, usable_models=5, dispersion_cv=0.70),
            current_price=100.0,
            cost_of_equity=0.10,
            forward_dividend_yield=0.0,
        )
        == "NR"
    )


def test_headline_rating_is_base_anchored_across_selected_scenarios() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    for table in (
        models.Dataset.__table__,
        models.FundamentalImport.__table__,
        models.FundamentalLatestSnapshot.__table__,
        models.FundamentalPeriodMetric.__table__,
        models.FundamentalAnnualMetric.__table__,
        models.FundamentalValuationResult.__table__,
        models.FundamentalEnsembleResult.__table__,
    ):
        table.create(engine)
    db = SessionLocal()
    try:
        run = models.FundamentalImport(
            filename="ratings.xlsx",
            source_hash="ratings-hash",
            status="succeeded",
            completed_at=dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc),
        )
        db.add(run)
        db.flush()
        db.add(
            models.FundamentalLatestSnapshot(
                import_id=run.id,
                symbol="RAT",
                company_name="Rating Test",
                latest_statement_year=2025,
                metrics_json={"Current_Price": 100.0},
                scores_json={},
                diagnostics_json={},
                coverage_json={},
                model_eligibility_json={},
                source_json={"currency": "MAD"},
                as_of_date=dt.date(2026, 5, 31),
            )
        )
        base = _ensemble(122.0, scenario="base")
        bear = _ensemble(80.0, scenario="bear")
        bull = _ensemble(160.0, scenario="bull")
        for idx, row in enumerate((base, bear, bull), start=1):
            row.id = idx
            row.import_id = run.id
            db.add(row)
        db.add(
            models.FundamentalValuationResult(
                import_id=run.id,
                symbol="RAT",
                scenario="base",
                model="fcff_dcf",
                fair_value=122.0,
                current_price=100.0,
                upside_pct=0.22,
                confidence="high",
                confidence_score=0.80,
                family="intrinsic",
                weight=1.0,
                inputs_json={"cost_of_equity": 0.10, "dividend_yield": 0.0},
                outputs_json={},
                warnings_json=["all_required_inputs_observed"],
                currency="MAD",
            )
        )
        db.commit()

        overlays = {
            row.scenario: derive_research_overlay(
                db,
                symbol="RAT",
                scenario=row.scenario,
                ensemble=row,
                import_row=run,
                current_price=100.0,
            )
            for row in (base, bear, bull)
        }

        assert overlays["base"]["recommendation"] == "BUY"
        assert overlays["base"]["target_price"] == 122.0
        for overlay in overlays.values():
            assert overlay["recommendation"] == overlays["base"]["recommendation"]
            assert overlay["target_price"] == overlays["base"]["target_price"]
            assert overlay["conviction"] == overlays["base"]["conviction"]
    finally:
        db.close()
        engine.dispose()
