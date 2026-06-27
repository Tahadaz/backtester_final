from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.quant_core.fundamentals.domain import FundamentalSnapshot, IntegrityCheck, IntegrityReport
from core.quant_core.fundamentals.projection import Projection
from services.api.app import models
from services.api.app.services import fundamentals as fundamentals_service
from services.api.app.services.fundamentals import recompute_symbol_valuations


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


def _row(import_id, year: int, metric: str, value: float) -> models.FundamentalAnnualMetric:
    return models.FundamentalAnnualMetric(
        import_id=import_id,
        symbol="AAA",
        company_name="Alpha",
        statement_year=year,
        metric_name=metric,
        metric_value=value,
        as_of_date=dt.date(year + 1, 4, 30),
    )


def test_year_horizon_prediction_uses_annual_ensemble_target() -> None:
    snapshot = FundamentalSnapshot(
        symbol="AAA",
        company_name="Alpha",
        latest_statement_year=2025,
        metrics={
            "Shares_Outstanding": 10.0,
            "PER": 80.0,
            "Current_Price": 10.0,
        },
    )
    projection = Projection(
        symbol="AAA",
        scenario="base",
        start_year=2025,
        forecast_years=1,
        as_of=dt.date(2026, 1, 31),
        statements=[{"fiscal_year": 2026, "net_income": 1_000.0}],
        drivers={},
        fcff=[],
        fcfe=[],
        dividends=[],
        book_values=[],
    )
    ensemble = SimpleNamespace(fair_value_base=42.0, current_price=10.0, confidence_score=0.60)

    payload = fundamentals_service._horizon_prediction_payload(
        horizon="year",
        projection=projection,
        snapshot=snapshot,
        valuations=[],
        ensemble=ensemble,
        data_cutoff=dt.date(2026, 1, 31),
        current_price=10.0,
    )

    assert payload is not None
    assert payload["forward_target"] == 42.0
    assert payload["method"] == "annual_ensemble"


def test_recompute_persists_projection_lines_and_integrity() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    for table in (
        models.Dataset.__table__,
        models.MarketDataStore.__table__,
        models.StockMaster.__table__,
        models.FundamentalImport.__table__,
        models.FundamentalSourceDocument.__table__,
        models.FundamentalAnnualMetric.__table__,
        models.FundamentalPeriodMetric.__table__,
        models.FundamentalLatestSnapshot.__table__,
        models.FundamentalAssumptionSet.__table__,
        models.FundamentalAssumptionOverride.__table__,
        models.FundamentalBetaHistory.__table__,
        models.FundamentalValuationResult.__table__,
        models.FundamentalEnsembleResult.__table__,
        models.FundamentalProjection.__table__,
        models.FundamentalIntegrityReport.__table__,
    ):
        table.create(engine)
    db = SessionLocal()
    try:
        run = models.FundamentalImport(
            filename="projection.xlsx",
            source_hash="projection-hash",
            status="succeeded",
            company_count=1,
            symbol_count=1,
            annual_metric_count=0,
            latest_snapshot_count=1,
            completed_at=dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc),
            source_universe="masi",
        )
        db.add(run)
        db.flush()
        db.add(models.StockMaster(symbol="AAA", display_name="Alpha", sector="Industrials", market_region="masi"))
        db.add(
            models.MarketDataStore(
                symbol="AAA",
                timeframe="1D",
                object_key="ohlcv/AAA.parquet",
                asset_class="equity",
                close_last=100.0,
                adv_20d=1_000_000.0,
            )
        )
        db.add(
            models.FundamentalLatestSnapshot(
                import_id=run.id,
                symbol="AAA",
                company_name="Alpha",
                latest_statement_year=2024,
                metrics_json={
                    "Current_Price": 100.0,
                    "Shares_Outstanding": 10.0,
                    "MarketCap_Calc": 1000.0,
                    "PER": 12.0,
                    "Price_to_Book": 4.0,
                    "ROE": 0.15,
                },
                scores_json={},
                diagnostics_json={},
                coverage_json={},
                model_eligibility_json={},
                source_json={"currency": "MAD"},
                as_of_date=dt.date(2025, 4, 30),
            )
        )
        for year, revenue in {2021: 100.0, 2022: 110.0, 2023: 121.0, 2024: 133.1}.items():
            db.add_all(
                [
                    _row(run.id, year, "Revenue", revenue),
                    _row(run.id, year, "EBIT", revenue * 0.12),
                    _row(run.id, year, "Depreciation_Amortization", revenue * 0.03),
                    _row(run.id, year, "Capex", revenue * 0.05),
                    _row(run.id, year, "Working_Capital", revenue * 0.18),
                    _row(run.id, year, "NetIncome", revenue * 0.07),
                    _row(run.id, year, "Dividends_Paid", revenue * 0.025),
                    _row(run.id, year, "Total_Equity", 200.0 + (year - 2021) * 15.0),
                    _row(run.id, year, "Total_Debt", 80.0),
                    _row(run.id, year, "Cash", 25.0 + (year - 2021) * 2.0),
                    _row(run.id, year, "Total_Assets", 330.0 + (year - 2021) * 15.0),
                    _row(run.id, year, "Total_Liabilities", 130.0),
                    _row(run.id, year, "Operating_Cash_Flow", revenue * 0.09),
                    _row(run.id, year, "CF_Investing", -revenue * 0.05),
                    _row(run.id, year, "Free_Cash_Flow", revenue * 0.04),
                ]
            )
        db.add(
            models.FundamentalIntegrityReport(
                import_id=run.id,
                symbol="AAA",
                statement_year=2024,
                overall_status="pass",
                confidence_haircut=0.0,
                checks_json=[],
            )
        )
        db.add(
            models.FundamentalBetaHistory(
                symbol="AAA",
                as_of=dt.date(2026, 6, 1),
                beta=1.33,
                raw_beta=1.30,
                method="ols",
                r2=0.64,
                n_obs=104,
                zero_week_frac=0.04,
                liquidity_flag=False,
                proxy="MASI",
                frequency="weekly",
                window_years=2.0,
                warnings_json=[],
            )
        )
        db.commit()

        rows = recompute_symbol_valuations(db, import_id=run.id, symbol="AAA", scenario="base")
        db.commit()

        assert rows
        projection_rows = (
            db.query(models.FundamentalProjection)
            .filter(models.FundamentalProjection.import_id == run.id, models.FundamentalProjection.symbol == "AAA")
            .all()
        )
        assert projection_rows
        assert {row.line_item for row in projection_rows} >= {"revenue", "fcff", "driver:revenue_growth"}
        assert all(row.as_of == dt.date(2025, 4, 30) for row in projection_rows)
        assert {row.period_type for row in projection_rows} == {"annual"}
        assert {row.period_index for row in projection_rows} == {0}
        growth_row = next(row for row in projection_rows if row.line_item == "driver:revenue_growth")
        assert growth_row.evidence_json["kind"] == "driver_estimate"
        assert "historical_series" in growth_row.evidence_json

        integrity = (
            db.query(models.FundamentalIntegrityReport)
            .filter(models.FundamentalIntegrityReport.import_id == run.id, models.FundamentalIntegrityReport.symbol == "AAA")
            .one()
        )
        assert integrity.projected_statements_json
        assert integrity.projection_checks_json
        fcff = next(row for row in rows if row.model == "fcff_dcf")
        cost_build = fcff.inputs_json["cost_of_capital"]
        assert cost_build["beta_source"] == "beta_history"
        assert cost_build["beta"] == 1.33
        assert cost_build["beta_lookup_as_of"] == "latest"
        assert fcff.outputs_json["projection"]["drivers"]["revenue_growth"]["historical_series"]
        snapshot = db.query(models.FundamentalLatestSnapshot).filter_by(import_id=run.id, symbol="AAA").one()
        assert snapshot.model_eligibility_json["available_horizons"] == ["year"]
        assert snapshot.model_eligibility_json["horizon_predictions"][0]["horizon"] == "year"
    finally:
        db.close()
        engine.dispose()


def test_financial_sector_projection_diagnostics_are_not_industrial_balance_gates() -> None:
    projection = Projection(
        symbol="BNK",
        scenario="base",
        start_year=2024,
        forecast_years=1,
        as_of=dt.date(2026, 5, 31),
        statements=[
            {
                "fiscal_year": 2025,
                "period_label": "FY",
                "total_assets": 1000.0,
                "total_equity": 120.0,
            }
        ],
        drivers={},
        fcff=[],
        fcfe=[],
        dividends=[],
        book_values=[],
        integrity_checks=[
            IntegrityCheck(
                name="projection_bs_balance_2025",
                status="fail",
                delta=250.0,
                rel_delta=0.25,
                inputs={},
                message="industrial check would not apply",
            )
        ],
    )
    adjusted = fundamentals_service._sector_adjusted_projection(projection, sector="Banques")

    assert adjusted.warnings == ["financial_sector_projection_balance_not_applicable"]
    assert len(adjusted.integrity_checks) == 1
    assert adjusted.integrity_checks[0].name == "projection_financial_sector_not_applicable_2025"
    assert adjusted.integrity_checks[0].status == "unavailable"

    source_report = IntegrityReport(
        symbol="BNK",
        statement_year=2024,
        checks=[
            IntegrityCheck(
                name="source_balance_sheet_identity",
                status="pass",
                delta=0.0,
                rel_delta=0.0,
                inputs={},
                message="source statement balances",
            )
        ],
        overall_status="pass",
        confidence_haircut=0.0,
    )
    combined = fundamentals_service._integrity_with_projection(
        report=source_report,
        projection=adjusted,
        symbol="BNK",
        statement_year=2024,
    )

    assert combined.overall_status == "pass"
    assert combined.confidence_haircut == 0.0
    assert combined.projection_checks[0].status == "unavailable"
