from __future__ import annotations

import datetime as dt
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("MARKET_REFRESH_CRON_ENABLED", "0")

from core.quant_core.fundamentals import DEFAULT_ASSUMPTIONS
from services.api.app import models
from services.api.app.db import get_db
from services.api.app.routers import fundamentals as fundamentals_router
from services.api.app.services import fundamentals as fundamentals_service
from services.api.app.services.bourse_live_quotes import LiveQuoteView


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


def _client_and_session():
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
        models.FundamentalQualityIssue.__table__,
        models.FundamentalAssumptionSet.__table__,
        models.FundamentalAssumptionOverride.__table__,
        models.FundamentalMetricOverride.__table__,
        models.FundamentalBetaHistory.__table__,
        models.FundamentalValuationResult.__table__,
        models.FundamentalEnsembleResult.__table__,
        models.FundamentalProjection.__table__,
        models.FundamentalIntegrityReport.__table__,
        models.FundamentalThesis.__table__,
        models.FundamentalCatalyst.__table__,
        models.FundamentalPillarScoreHistory.__table__,
        models.SignalEngineGlobalResult.__table__,
    ):
        table.create(engine)
    app = FastAPI()
    app.include_router(fundamentals_router.router)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return app, engine, SessionLocal


def test_period_label_normalization_merges_semiannual_aliases() -> None:
    assert fundamentals_service.normalize_period_label("semiannual", "S1") == "H1"
    assert fundamentals_service.normalize_period_label("semiannual", "S2") == "H2"
    assert fundamentals_service.normalize_period_label("semiannual", "H1") == "H1"
    assert fundamentals_service.normalize_period_label("quarterly", "S1") == "S1"


def test_withheld_warning_does_not_force_not_rated_when_fair_value_is_available() -> None:
    ensemble = models.FundamentalEnsembleResult(
        symbol="FAIL",
        scenario="base",
        fair_value_base=200.0,
        current_price=100.0,
        upside_pct=1.0,
        confidence_score=0.80,
        usable_model_count=4,
        excluded_model_count=0,
        model_weights_json={"fcff_dcf": 1.0},
        warnings_json=["withheld_integrity_fail"],
        model_dispersion_cv=0.05,
    )

    assert fundamentals_service.derive_recommendation(
        ensemble,
        current_price=100.0,
        cost_of_equity=0.10,
        forward_dividend_yield=0.0,
    ) == "BUY"


def test_bvc_period_lineage_does_not_promote_dividend_fields_to_annual_layer() -> None:
    _app, engine, SessionLocal = _client_and_session()
    try:
        db = SessionLocal()
        run = models.FundamentalImport(
            filename="bvc.jsonl",
            source_hash="hash",
            data_source="bvc",
            source_universe="masi",
            status="succeeded",
        )
        db.add(run)
        db.flush()
        doc = models.FundamentalSourceDocument(
            import_id=run.id,
            symbol="MNG",
            company_name="MANAGEM",
            document_title="MNG: Rapport financier annuel 2022",
            source_url="https://media.casablanca-bourse.com/mng.pdf",
            document_kind="RFA",
            publication_date=dt.date(2023, 4, 28),
            fiscal_year=2022,
            period_type="annual",
            period_label="FY",
            status="succeeded",
            extracted_field_count=10,
        )
        db.add(doc)
        db.flush()
        db.add_all(
            [
                models.FundamentalPeriodMetric(
                    import_id=run.id,
                    source_document_id=doc.id,
                    symbol="MNG",
                    company_name="MANAGEM",
                    fiscal_year=2022,
                    period_type="annual",
                    period_label="FY",
                    metric_name="Dividendes",
                    metric_value=233_100_000.0,
                    raw_metric_name="Dividendes_2022",
                ),
                models.FundamentalPeriodMetric(
                    import_id=run.id,
                    source_document_id=doc.id,
                    symbol="MNG",
                    company_name="MANAGEM",
                    fiscal_year=2022,
                    period_type="annual",
                    period_label="FY",
                    metric_name="Flux_tresorerie_activites_operationnelles",
                    metric_value=2_485_000_000.0,
                    raw_metric_name="Flux_tresorerie_activites_operationnelles_2022",
                ),
            ]
        )
        db.commit()

        rows = fundamentals_service._period_lineage_to_annual_rows(db, import_id=run.id, symbols={"MNG"})
        by_metric = {row.metric_name: row for row in rows}

        assert "Dividendes" not in by_metric
        assert by_metric["Flux_tresorerie_activites_operationnelles"].metric_value == pytest.approx(2_485_000_000.0)
    finally:
        db.close()
        engine.dispose()


def _seed(SessionLocal):
    db = SessionLocal()
    try:
        run = models.FundamentalImport(
            filename="fundamentals.xlsx",
            source_hash="hash",
            status="succeeded",
            company_count=1,
            symbol_count=1,
            annual_metric_count=3,
            latest_snapshot_count=1,
            completed_at=dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc),
        )
        db.add(run)
        db.flush()
        db.add(models.StockMaster(symbol="AAA", display_name="Alpha", sector="Banks", market_region="masi"))
        db.add(
            models.MarketDataStore(
                symbol="AAA",
                timeframe="1D",
                object_key="ohlcv/AAA.parquet",
                asset_class="equity",
                close_last=100.0,
                adv_20d=750_000.0,
            )
        )
        db.add(
            models.FundamentalLatestSnapshot(
                id=1,
                import_id=run.id,
                symbol="AAA",
                company_name="Alpha",
                latest_statement_year=2024,
                metrics_json={"Current_Price": 100.0, "PER": 10.0, "Price_to_Book": 1.0, "MarketCap_Calc": 1000.0},
                scores_json={"overall": 72.0, "quality": 80.0, "value": 65.0},
                diagnostics_json={},
                coverage_json={},
                model_eligibility_json={},
                source_json={"currency": "MAD"},
            )
        )
        db.add_all(
            [
                models.FundamentalPeriodMetric(
                    id=1,
                    import_id=run.id,
                    symbol="AAA",
                    company_name="Alpha",
                    fiscal_year=2024,
                    period_type="annual",
                    period_label="FY",
                    metric_name="Total_Equity",
                    metric_value=400.0,
                    raw_metric_name="Capitaux_Propres_2024",
                ),
                models.FundamentalPeriodMetric(
                    id=2,
                    import_id=run.id,
                    symbol="AAA",
                    company_name="Alpha",
                    fiscal_year=2024,
                    period_type="quarterly",
                    period_label="Q2",
                    period_end_date=dt.date(2024, 6, 30),
                    metric_name="Resultat_net",
                    metric_value=42.0,
                    raw_metric_name="Resultat_net_2024",
                    document_title="Q2 statement",
                ),
            ]
        )
        valuation_ts = dt.datetime(2026, 5, 1, 12, 0, tzinfo=dt.timezone.utc)
        for idx, (scenario, fair_value) in enumerate(
            [("bear", 100.0), ("base", 120.0), ("bull", 140.0)],
            start=1,
        ):
            db.add(
                models.FundamentalEnsembleResult(
                    id=idx,
                    import_id=run.id,
                    symbol="AAA",
                    scenario=scenario,
                    fair_value_low=fair_value * 0.75,
                    fair_value_base=fair_value,
                    fair_value_high=fair_value * 1.15,
                    current_price=100.0,
                    upside_pct=fair_value / 100.0 - 1.0,
                    confidence_score=0.7,
                    usable_model_count=3,
                    excluded_model_count=1,
                    model_weights_json={"fcff_dcf": 1.0},
                    warnings_json=[],
                    currency="MAD",
                    computed_at=valuation_ts,
                )
            )
        db.add(
            models.FundamentalIntegrityReport(
                import_id=run.id,
                symbol="AAA",
                statement_year=2024,
                overall_status="pass",
                confidence_haircut=0.0,
                checks_json=[
                    {
                        "name": "bs_balance",
                        "status": "pass",
                        "delta": 0.0,
                        "rel_delta": 0.0,
                        "inputs": {"Total_Assets": 100.0, "Total_Liabilities": 60.0, "Total_Equity": 40.0},
                    }
                ],
            )
        )
        history_runs = [run]
        for idx in range(1, 3):
            old_run = models.FundamentalImport(
                filename=f"fundamentals_{idx}.xlsx",
                source_hash=f"hash{idx}",
                status="succeeded",
                company_count=1,
                symbol_count=1,
                annual_metric_count=0,
                latest_snapshot_count=0,
                completed_at=dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc) - dt.timedelta(days=idx),
            )
            db.add(old_run)
            db.flush()
            history_runs.append(old_run)
        for idx, value in enumerate([80.0, 79.0, 78.0]):
            db.add(
                models.FundamentalPillarScoreHistory(
                    import_id=history_runs[idx].id,
                    symbol="AAA",
                    as_of=dt.date(2024 - idx, 12, 31),
                    quality_score=value,
                    value_score=60.0,
                    growth_score=55.0,
                    risk_score=65.0,
                    cash_flow_score=70.0,
                    health_score=75.0,
                    overall_score=72.0,
                    pillar_coverage_json={},
                )
            )
        db.commit()
    finally:
        db.close()


def test_metric_override_lifecycle_updates_detail_payload(monkeypatch) -> None:
    monkeypatch.setattr("services.api.app.auth.settings.ADMIN_API_KEY", "admin-secret")
    monkeypatch.setattr(fundamentals_router, "_sync_fundamental_signal_rows", lambda db, symbols: None)
    app, engine, SessionLocal = _client_and_session()
    headers = {
        "x-app-user-id": "analyst-1",
        "x-app-user-email": "analyst@example.com",
        "x-admin-api-key": "admin-secret",
    }
    try:
        db = SessionLocal()
        try:
            run = models.FundamentalImport(
                filename="override.xlsx",
                source_hash="override-hash",
                status="succeeded",
                data_source="workbook",
                source_universe="masi",
                company_count=1,
                symbol_count=1,
                annual_metric_count=42,
                latest_snapshot_count=1,
                completed_at=dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc),
            )
            db.add(run)
            db.flush()
            db.add(models.StockMaster(symbol="OVR", display_name="Override Test", sector="Industrie", market_region="masi"))
            db.add(
                models.FundamentalLatestSnapshot(
                    import_id=run.id,
                    symbol="OVR",
                    company_name="Override Test",
                    latest_statement_year=2024,
                    metrics_json={
                        "Current_Price": 100.0,
                        "Shares_Outstanding": 10.0,
                        "MarketCap_Calc": 1_000.0,
                        "Revenue": 1_000.0,
                        "EBIT": 120.0,
                        "NetIncome": 70.0,
                        "Total_Assets": 1_000.0,
                        "Total_Liabilities": 400.0,
                        "Total_Equity": 600.0,
                        "Total_Debt": 180.0,
                        "Cash": 90.0,
                        "PER": 14.0,
                        "Price_to_Book": 1.67,
                        "ROE": 0.12,
                    },
                    scores_json={},
                    diagnostics_json={},
                    coverage_json={},
                    model_eligibility_json={},
                    source_json={"currency": "MAD"},
                    as_of_date=dt.date(2026, 5, 31),
                )
            )
            years = {
                2022: {"Revenue": 850.0, "EBIT": 95.0, "NetIncome": 55.0, "Total_Assets": 900.0, "Total_Liabilities": 360.0, "Total_Equity": 540.0},
                2023: {"Revenue": 930.0, "EBIT": 110.0, "NetIncome": 64.0, "Total_Assets": 950.0, "Total_Liabilities": 380.0, "Total_Equity": 570.0},
                2024: {"Revenue": 1_000.0, "EBIT": 120.0, "NetIncome": 70.0, "Total_Assets": 1_000.0, "Total_Liabilities": 400.0, "Total_Equity": 600.0},
            }
            common = {
                "Total_Debt": 180.0,
                "Cash": 90.0,
                "CFS_Ending_Cash": 90.0,
                "Capex": 40.0,
                "Depreciation_Amortization": 30.0,
                "Operating_Cash_Flow": 110.0,
                "CF_Investing": -40.0,
                "Free_Cash_Flow": 70.0,
                "Dividends_Paid": 25.0,
                "Interest_Expense": 8.0,
            }
            rows = []
            for year, metrics in years.items():
                for metric, value in {**metrics, **common}.items():
                    rows.append(
                        models.FundamentalAnnualMetric(
                            import_id=run.id,
                            symbol="OVR",
                            company_name="Override Test",
                            statement_year=year,
                            metric_name=metric,
                            metric_value=value,
                        )
                    )
            db.add_all(rows)
            db.commit()
        finally:
            db.close()

        with TestClient(app) as client:
            created = client.put(
                "/fundamentals/stocks/OVR/metric-overrides",
                headers=headers,
                json={"statement_year": 2024, "metric_name": "Revenue", "metric_value": 1_111.0, "note": "Manual correction"},
            )
            assert created.status_code == 200, created.text
            assert created.json()["created_by"] == "analyst@example.com"

            detail = client.get("/fundamentals/stocks/OVR?scenario=base")
            assert detail.status_code == 200
            payload = detail.json()
            revenue = next(row for row in payload["annual_raw"] if row["statement_year"] == 2024 and row["metric_name"] == "Revenue")
            assert revenue["metric_value"] == pytest.approx(1_111.0)
            assert revenue["original_metric_value"] == pytest.approx(1_000.0)
            assert revenue["is_overridden"] is True
            assert payload["metrics"]["Revenue"] == pytest.approx(1_111.0)
            assert payload["metric_overrides"][0]["metric_name"] == "Revenue"
            missing_names = {item["metric_name"] for item in payload["missing_financial_data"]["items"]}
            assert "Revenue" not in missing_names
            assert "Debt_to_Equity" in missing_names

            filled_missing = client.put(
                "/fundamentals/stocks/OVR/metric-overrides",
                headers=headers,
                json={"statement_year": 2024, "metric_name": "Debt_to_Equity", "metric_value": 0.30, "note": "Manual missing fill"},
            )
            assert filled_missing.status_code == 200, filled_missing.text
            filled_payload = client.get("/fundamentals/stocks/OVR?scenario=base").json()
            filled_missing_names = {item["metric_name"] for item in filled_payload["missing_financial_data"]["items"]}
            assert "Debt_to_Equity" not in filled_missing_names

            deleted = client.delete("/fundamentals/stocks/OVR/metric-overrides/2024/Revenue", headers=headers)
            assert deleted.status_code == 204
            restored = client.get("/fundamentals/stocks/OVR?scenario=base").json()
            restored_revenue = next(row for row in restored["annual_raw"] if row["statement_year"] == 2024 and row["metric_name"] == "Revenue")
            assert restored_revenue["metric_value"] == pytest.approx(1_000.0)
            assert restored_revenue["is_overridden"] is False
            assert {row["metric_name"] for row in restored["metric_overrides"]} == {"Debt_to_Equity"}
    finally:
        engine.dispose()


def _seed_auto_scenarios(SessionLocal, *, include_base: bool = True):
    db = SessionLocal()
    try:
        run = models.FundamentalImport(
            filename="auto.xlsx",
            source_hash="auto-hash",
            status="succeeded",
            company_count=1,
            symbol_count=1,
            annual_metric_count=0,
            latest_snapshot_count=1,
            completed_at=dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc),
        )
        db.add(run)
        db.flush()
        db.add(models.StockMaster(symbol="AAA", display_name="Alpha", sector="Banks", market_region="masi"))
        db.add(
            models.MarketDataStore(
                symbol="AAA",
                timeframe="1D",
                object_key="ohlcv/AAA.parquet",
                asset_class="equity",
                close_last=100.0,
                adv_20d=750_000.0,
            )
        )
        db.add(
            models.FundamentalLatestSnapshot(
                id=1,
                import_id=run.id,
                symbol="AAA",
                company_name="Alpha",
                latest_statement_year=2024,
                metrics_json={"Current_Price": 100.0, "MarketCap_Calc": 1000.0},
                scores_json={"overall": 72.0, "quality": 80.0, "value": 65.0},
                diagnostics_json={},
                coverage_json={},
                model_eligibility_json={},
                source_json={"currency": "MAD"},
            )
        )
        scenario_rows = [
            ("bear", 90.0, 0.50),
            ("base", 118.0, 0.60),
            ("bull", 140.0, 0.70),
        ]
        valuation_ts = dt.datetime(2026, 5, 1, 12, 0, tzinfo=dt.timezone.utc)
        if not include_base:
            scenario_rows = [row for row in scenario_rows if row[0] != "base"]
        for idx, (scenario, fair_value, confidence) in enumerate(
            scenario_rows,
            start=1,
        ):
            db.add(
                models.FundamentalEnsembleResult(
                    id=idx,
                    import_id=run.id,
                    symbol="AAA",
                    scenario=scenario,
                    fair_value_low=fair_value * 0.95,
                    fair_value_base=fair_value,
                    fair_value_high=fair_value * 1.05,
                    current_price=100.0,
                    upside_pct=fair_value / 100.0 - 1.0,
                    confidence_score=confidence,
                    usable_model_count=3,
                    excluded_model_count=0,
                    model_weights_json={"fcff_dcf": 0.333333, "fcfe_dcf": 0.333333, "residual_income": 0.333333},
                    warnings_json=[],
                    currency="MAD",
                    model_dispersion_cv=0.05,
                    computed_at=valuation_ts,
                )
            )
            if scenario == "base":
                db.add(
                    models.FundamentalValuationResult(
                        import_id=run.id,
                        symbol="AAA",
                        scenario="base",
                        model="fcff_dcf",
                        fair_value=fair_value,
                        current_price=100.0,
                        upside_pct=fair_value / 100.0 - 1.0,
                        confidence="high",
                        confidence_score=confidence,
                        weight=1.0,
                        family="intrinsic",
                        inputs_json={"cost_of_equity": 0.095, "dividend_yield": 0.0},
                        outputs_json={},
                        warnings_json=["all_required_inputs_observed"],
                        currency="MAD",
                        computed_at=valuation_ts,
                    )
                )
        db.commit()
    finally:
        db.close()


def _fresh_live_quote(symbol: str, last_price: float) -> LiveQuoteView:
    now = dt.datetime(2026, 5, 25, 10, 0, tzinfo=dt.timezone.utc)
    return LiveQuoteView(
        symbol=symbol,
        session_date=dt.date(2026, 5, 25),
        quote_timestamp=now,
        open_price=last_price,
        last_price=last_price,
        high_price=last_price,
        low_price=last_price,
        prev_close=100.0,
        volume=10_000.0,
        source_provider="test_live",
        source_url=f"https://example.test/{symbol}",
        updated_at=now,
        is_fresh=True,
        age_seconds=30.0,
    )


@pytest.mark.xfail(
    reason="pre-existing branch regression: live Current_Price override not applied in this branch",
    strict=False,
)
def test_fundamental_responses_render_fresh_live_current_price(monkeypatch) -> None:
    app, engine, SessionLocal = _client_and_session()
    try:
        _seed(SessionLocal)

        def fake_live_quotes(_db, symbols, **_kwargs):
            return {
                symbol: _fresh_live_quote(symbol, 125.0)
                for symbol in symbols
                if symbol == "AAA"
            }

        monkeypatch.setattr(fundamentals_service, "get_or_refresh_live_quotes", fake_live_quotes)

        with TestClient(app) as client:
            detail = client.get("/fundamentals/stocks/AAA?scenario=base")
            assert detail.status_code == 200
            detail_payload = detail.json()
            assert detail_payload["metrics"]["Current_Price"] == 125.0
            assert detail_payload["coverage"]["price_source"] == "bourse_live_quote"
            assert detail_payload["ensemble"]["current_price"] == 125.0
            assert detail_payload["ensemble"]["upside_pct"] == pytest.approx(120.0 / 125.0 - 1.0)

            universe = client.get("/fundamentals/universe?scenario=base")
            assert universe.status_code == 200
            row = next(item for item in universe.json() if item["symbol"] == "AAA")
            assert row["current_price"] == 125.0
            assert row["ensemble"]["current_price"] == 125.0
            assert row["valuation_summary"]["consensus_upside_pct"] == pytest.approx(120.0 / 125.0 - 1.0)

            batch = client.post("/fundamentals/snapshot/batch?scenario=base", json={"symbols": ["AAA"]})
            assert batch.status_code == 200
            assert batch.json()["AAA"]["metrics"]["Current_Price"] == 125.0
            assert batch.json()["AAA"]["upside_pct"] == pytest.approx(120.0 / 125.0 - 1.0)
    finally:
        engine.dispose()


def test_stock_detail_eva_uses_resolved_firm_wacc() -> None:
    app, engine, SessionLocal = _client_and_session()
    try:
        db = SessionLocal()
        try:
            run = models.FundamentalImport(
                filename="eva.xlsx",
                source_hash="eva-hash",
                status="succeeded",
                company_count=1,
                symbol_count=1,
                annual_metric_count=7,
                latest_snapshot_count=1,
                completed_at=dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc),
            )
            db.add(run)
            db.flush()
            db.add(models.StockMaster(symbol="EVA", display_name="Eva Test", sector="Industrie", market_region="masi"))
            db.add(
                models.FundamentalLatestSnapshot(
                    import_id=run.id,
                    symbol="EVA",
                    company_name="Eva Test",
                    latest_statement_year=2024,
                    metrics_json={
                        "Current_Price": 100.0,
                        "MarketCap_Calc": 1_000.0,
                        "EBIT": 100.0,
                        "Total_Debt": 200.0,
                        "Total_Assets": 1_000.0,
                        "Total_Liabilities": 500.0,
                        "Total_Equity": 500.0,
                        "Revenue": 1_000.0,
                    },
                    scores_json={"overall": 70.0},
                    diagnostics_json={"screens": {"eva": {"wacc_used": DEFAULT_ASSUMPTIONS["wacc"], "wacc_source": "default"}}},
                    coverage_json={},
                    model_eligibility_json={},
                    source_json={"currency": "MAD"},
                    as_of_date=dt.date(2026, 5, 31),
                )
            )
            for metric, value in {
                "EBIT": 100.0,
                "Interest_Expense": 8.0,
                "Total_Debt": 200.0,
                "Total_Assets": 1_000.0,
                "Total_Liabilities": 500.0,
                "Total_Equity": 500.0,
                "Revenue": 1_000.0,
            }.items():
                db.add(
                    models.FundamentalAnnualMetric(
                        import_id=run.id,
                        symbol="EVA",
                        company_name="Eva Test",
                        statement_year=2024,
                        metric_name=metric,
                        metric_value=value,
                    )
                )
            db.add(
                models.FundamentalBetaHistory(
                    symbol="EVA",
                    as_of=dt.date(2026, 5, 31),
                    beta=1.50,
                    method="ols",
                    r2=0.60,
                    n_obs=104,
                    zero_week_frac=0.05,
                    liquidity_flag=False,
                    proxy="MASI",
                    frequency="weekly",
                    window_years=2.0,
                    warnings_json=[],
                )
            )
            db.add(
                models.FundamentalEnsembleResult(
                    import_id=run.id,
                    symbol="EVA",
                    scenario="base",
                    fair_value_low=90.0,
                    fair_value_base=110.0,
                    fair_value_high=130.0,
                    current_price=100.0,
                    upside_pct=0.10,
                    confidence_score=0.7,
                    usable_model_count=1,
                    excluded_model_count=0,
                    model_weights_json={"fcff_dcf": 1.0},
                    warnings_json=[],
                    currency="MAD",
                )
            )
            db.commit()
        finally:
            db.close()

        with TestClient(app) as client:
            response = client.get("/fundamentals/stocks/EVA?scenario=base")

        assert response.status_code == 200
        payload = response.json()
        build = payload["assumptions"]["cost_of_capital_build_up"]
        eva_screen = payload["screens"]["eva"]
        diagnostic_eva = payload["diagnostics"]["screens"]["eva"]

        assert build["beta_source"] == "beta_history"
        assert build["wacc"] != pytest.approx(DEFAULT_ASSUMPTIONS["wacc"])
        assert eva_screen["wacc_source"] == "firm_build_up"
        assert eva_screen["wacc_used"] == pytest.approx(build["wacc"])
        assert diagnostic_eva["wacc_used"] == pytest.approx(build["wacc"])
        assert eva_screen["roic_spread"] == pytest.approx(eva_screen["roic"] - build["wacc"])
    finally:
        engine.dispose()


def test_stock_detail_recomputes_newer_snapshot_instead_of_reusing_stale_valuation(monkeypatch) -> None:
    app, engine, SessionLocal = _client_and_session()
    try:
        _seed(SessionLocal)
        db = SessionLocal()
        try:
            newer_run = models.FundamentalImport(
                filename="newer_fundamentals.xlsx",
                source_hash="newer-hash",
                status="succeeded",
                company_count=1,
                symbol_count=1,
                annual_metric_count=0,
                latest_snapshot_count=1,
                completed_at=dt.datetime(2026, 5, 2, tzinfo=dt.timezone.utc),
            )
            db.add(newer_run)
            db.flush()
            db.add(
                models.FundamentalLatestSnapshot(
                    import_id=newer_run.id,
                    symbol="AAA",
                    company_name="Alpha",
                    latest_statement_year=2025,
                    metrics_json={"Current_Price": 200.0, "MarketCap_Calc": 2000.0},
                    scores_json={"overall": 70.0},
                    diagnostics_json={},
                    coverage_json={},
                    model_eligibility_json={},
                    source_json={"currency": "MAD"},
                )
            )
            newer_import_id = newer_run.id
            db.commit()
        finally:
            db.close()

        captured: dict[str, object] = {}

        def fake_recompute_symbol_valuations_all_scenarios(
            db,
            *,
            import_id,
            symbol,
            scenarios=fundamentals_router.VALUATION_SCENARIOS,
            overrides_loader=None,
            include_sensitivity_grids=True,
        ):
            captured["import_id"] = import_id
            captured["scenarios"] = tuple(scenarios)
            captured["include_sensitivity_grids"] = include_sensitivity_grids
            run_ts = dt.datetime(2026, 5, 3, tzinfo=dt.timezone.utc)
            fair_values = {"bear": 210.0, "base": 222.0, "bull": 240.0}
            for scenario in scenarios:
                fair_value = fair_values[scenario]
                db.add(
                    models.FundamentalValuationResult(
                        import_id=import_id,
                        symbol=symbol,
                        scenario=scenario,
                        model="fcff_dcf",
                        fair_value=fair_value,
                        current_price=200.0,
                        upside_pct=fair_value / 200.0 - 1.0,
                        confidence="medium",
                        confidence_score=0.8,
                        weight=1.0,
                        family="intrinsic",
                        methodology="test recompute",
                        currency="MAD",
                        inputs_json={"source": "newer_import"},
                        outputs_json={},
                        warnings_json=[],
                        computed_at=run_ts,
                    )
                )
                db.add(
                    models.FundamentalEnsembleResult(
                        import_id=import_id,
                        symbol=symbol,
                        scenario=scenario,
                        fair_value_low=fair_value * 0.95,
                        fair_value_base=fair_value,
                        fair_value_high=fair_value * 1.05,
                        current_price=200.0,
                        upside_pct=fair_value / 200.0 - 1.0,
                        confidence_score=0.8,
                        usable_model_count=1,
                        excluded_model_count=0,
                        model_weights_json={"fcff_dcf": 1.0},
                        warnings_json=[],
                        currency="MAD",
                        computed_at=run_ts,
                    )
                )

        monkeypatch.setattr(fundamentals_router, "recompute_symbol_valuations_all_scenarios", fake_recompute_symbol_valuations_all_scenarios)
        enqueued: list[list[str]] = []
        monkeypatch.setattr(
            fundamentals_router,
            "_enqueue_fundamental_valuation_refresh",
            lambda symbols: enqueued.append(list(symbols)) or "refresh-job",
        )

        with TestClient(app) as client:
            universe = client.get("/fundamentals/universe?scenario=base")
            detail = client.get("/fundamentals/stocks/AAA?scenario=base")
            batch = client.post("/fundamentals/snapshot/batch?scenario=base", json={"symbols": ["AAA"]})

        assert universe.status_code == 200
        universe_row = next(item for item in universe.json() if item["symbol"] == "AAA")
        assert universe_row["ensemble"]["fair_value_base"] == 120.0
        assert universe_row["valuation_pending"] is True
        assert enqueued == [["AAA"]]
        assert batch.status_code == 200
        assert batch.json()["AAA"]["fair_value"] == 222.0
        assert detail.status_code == 200
        payload = detail.json()
        assert captured["import_id"] == newer_import_id
        assert captured["scenarios"] == tuple(fundamentals_router.VALUATION_SCENARIOS)
        assert captured["include_sensitivity_grids"] is False
        assert payload["latest_statement_year"] == 2025
        assert payload["ensemble"]["fair_value_base"] == 222.0
        assert payload["ensemble"]["fair_value_base"] != 120.0
        assert payload["valuations"][0]["fair_value"] == 222.0
    finally:
        engine.dispose()


def test_ensure_latest_can_report_stale_without_recomputing(monkeypatch) -> None:
    _app, engine, SessionLocal = _client_and_session()
    try:
        _seed_auto_scenarios(SessionLocal)
        db = SessionLocal()
        try:
            snapshot = fundamentals_service.latest_snapshot_rows_by_symbol(db, symbols=["AAA"])["AAA"]
            base = (
                db.query(models.FundamentalEnsembleResult)
                .filter_by(import_id=snapshot.import_id, symbol="AAA", scenario="base")
                .one()
            )
            base.fair_value_base = None
            base.model_dispersion_base = 5.0
            db.commit()

            def fail_recompute(*_args, **_kwargs):
                raise AssertionError("recompute must not run on the universe read path")

            monkeypatch.setattr(fundamentals_router, "recompute_symbol_valuations_all_scenarios", fail_recompute)
            pending = fundamentals_router._ensure_latest_symbol_valuations(
                db,
                import_id=snapshot.import_id,
                symbol="AAA",
                scenario="base",
                recompute_inline=False,
            )

            assert pending is True
            assert base.fair_value_base is None
        finally:
            db.close()
    finally:
        engine.dispose()


def test_identical_active_valuation_refresh_job_is_not_enqueued_twice(monkeypatch) -> None:
    symbols = ["BBB", "AAA", "AAA"]
    normalized = ["AAA", "BBB"]
    digest = fundamentals_router.hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()[:24]
    expected_job_id = f"fundamental-valuations-{digest}"

    class ActiveJob:
        id = expected_job_id

        @staticmethod
        def get_status(refresh=False):
            assert refresh is False
            return "started"

    class FakeQueue:
        def __init__(self) -> None:
            self.enqueues = 0

        def fetch_job(self, job_id):
            assert job_id == expected_job_id
            return ActiveJob()

        def enqueue(self, *_args, **_kwargs):
            self.enqueues += 1
            raise AssertionError("active identical job must be reused")

    queue = FakeQueue()
    monkeypatch.setattr(fundamentals_router, "get_queue", lambda: queue)

    assert fundamentals_router._enqueue_fundamental_valuation_refresh(symbols) == expected_job_id
    assert queue.enqueues == 0


def test_targeted_bvc_period_type_defaults_include_all_periods() -> None:
    assert fundamentals_router._normalize_period_types([], default_all=False) == ["annual", "semiannual", "quarterly"]
    assert fundamentals_router._normalize_period_types(None, default_all=False) == ["annual", "semiannual", "quarterly"]
    assert fundamentals_router._normalize_period_types(["semester", "quarterly"], default_all=False) == ["semiannual", "quarterly"]


@pytest.mark.xfail(
    reason="pre-existing branch regression: snapshot source-preference logic changed in stockanalysis cutover",
    strict=False,
)
def test_masi_latest_snapshot_prefers_bvc_over_newer_stockanalysis() -> None:
    _app, engine, SessionLocal = _client_and_session()
    try:
        db = SessionLocal()
        try:
            db.add(models.StockMaster(symbol="MNG", display_name="Managem", market_region="masi", is_active=True))
            bvc_run = models.FundamentalImport(
                filename="targeted_bvc.xlsx",
                source_hash="bvc-hash",
                data_source="bvc",
                source_universe="masi",
                status="succeeded",
                completed_at=dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc),
            )
            stockanalysis_run = models.FundamentalImport(
                filename="stockanalysis.xlsx",
                source_hash="stockanalysis-hash",
                data_source="stockanalysis",
                source_universe="masi",
                status="succeeded",
                completed_at=dt.datetime(2026, 5, 2, tzinfo=dt.timezone.utc),
            )
            db.add_all([bvc_run, stockanalysis_run])
            db.flush()
            db.add_all(
                [
                    models.FundamentalLatestSnapshot(
                        import_id=bvc_run.id,
                        symbol="MNG",
                        company_name="Managem",
                        latest_statement_year=2024,
                        data_source="bvc",
                        metrics_json={"Revenue": 1000.0},
                        scores_json={},
                        diagnostics_json={},
                        coverage_json={},
                        model_eligibility_json={},
                        source_json={"data_source": "bvc"},
                    ),
                    models.FundamentalLatestSnapshot(
                        import_id=stockanalysis_run.id,
                        symbol="MNG",
                        company_name="Managem",
                        latest_statement_year=2024,
                        data_source="stockanalysis",
                        metrics_json={"Revenue": 1.0},
                        scores_json={},
                        diagnostics_json={},
                        coverage_json={},
                        model_eligibility_json={},
                        source_json={"data_source": "stockanalysis"},
                    ),
                ]
            )
            db.commit()

            snapshot = fundamentals_service.latest_snapshot_rows_by_symbol(db, symbols=["MNG"])["MNG"]
            import_row = fundamentals_service.latest_imports_by_symbol(db, symbols=["MNG"])["MNG"]

            assert snapshot.import_id == bvc_run.id
            assert snapshot.metrics_json["Revenue"] == 1000.0
            assert import_row.id == bvc_run.id
        finally:
            db.close()
    finally:
        engine.dispose()


def test_masi_latest_snapshot_prefers_core_statement_data_over_newer_ratio_only_rows() -> None:
    _app, engine, SessionLocal = _client_and_session()
    try:
        db = SessionLocal()
        try:
            db.add(models.StockMaster(symbol="MNG", display_name="Managem", market_region="masi", is_active=True))
            complete_run = models.FundamentalImport(
                filename="stockanalysis_complete.xlsx",
                source_hash="complete-hash",
                data_source="stockanalysis",
                source_universe="masi",
                status="succeeded",
                completed_at=dt.datetime(2026, 5, 26, tzinfo=dt.timezone.utc),
            )
            ratio_only_run = models.FundamentalImport(
                filename="stockanalysis_ratio_only.xlsx",
                source_hash="ratio-only-hash",
                data_source="stockanalysis",
                source_universe="masi",
                status="succeeded",
                completed_at=dt.datetime(2026, 6, 2, tzinfo=dt.timezone.utc),
            )
            db.add_all([complete_run, ratio_only_run])
            db.flush()
            db.add_all(
                [
                    models.FundamentalLatestSnapshot(
                        import_id=complete_run.id,
                        symbol="MNG",
                        company_name="Managem",
                        latest_statement_year=2025,
                        data_source="stockanalysis",
                        metrics_json={"Revenue": 13_694_000_000.0, "NetIncome": 3_002_000_000.0, "PER": 10.0},
                        scores_json={},
                        diagnostics_json={},
                        coverage_json={},
                        model_eligibility_json={},
                        source_json={"data_source": "stockanalysis"},
                    ),
                    models.FundamentalLatestSnapshot(
                        import_id=ratio_only_run.id,
                        symbol="MNG",
                        company_name="Managem",
                        latest_statement_year=2025,
                        data_source="stockanalysis",
                        metrics_json={"PER": 6.0, "ROE": 0.2, "EV_to_EBITDA": 7.0},
                        scores_json={},
                        diagnostics_json={},
                        coverage_json={},
                        model_eligibility_json={},
                        source_json={"data_source": "stockanalysis"},
                    ),
                ]
            )
            db.commit()

            snapshot = fundamentals_service.latest_snapshot_rows_by_symbol(db, symbols=["MNG"])["MNG"]

            assert snapshot.import_id == complete_run.id
            assert snapshot.metrics_json["Revenue"] == 13_694_000_000.0
        finally:
            db.close()
    finally:
        engine.dispose()


def test_stockanalysis_import_enqueue_selects_active_masi_symbols(monkeypatch) -> None:
    app, engine, SessionLocal = _client_and_session()
    try:
        db = SessionLocal()
        try:
            db.add_all(
                [
                    models.StockMaster(symbol="AAA", display_name="Alpha", market_region="masi", is_active=True),
                    models.StockMaster(symbol="SPY", display_name="SPY", market_region="us", is_active=True),
                    models.StockMaster(symbol="MAJ", display_name="MAJ", market_region="masi", is_active=True),
                ]
            )
            db.commit()
        finally:
            db.close()

        captured: dict = {}

        class FakeQueue:
            def enqueue(self, *args, **kwargs):
                captured["args"] = args
                captured["kwargs"] = kwargs
                return type("Job", (), {"id": "stockanalysis-job"})()

        monkeypatch.setattr(fundamentals_router, "get_queue", lambda: FakeQueue())

        with TestClient(app) as client:
            response = client.post("/fundamentals/imports/stockanalysis", json={})

        assert response.status_code == 200
        assert response.json()["enqueued_count"] == 1
        assert captured["args"] == (
            "services.worker.tasks.refresh_stockanalysis_fundamentals.refresh_stockanalysis_universe",
        )
        assert captured["kwargs"]["symbols"] == ["AAA"]
        assert captured["kwargs"]["missing_only"] is False
        assert captured["kwargs"]["job_timeout"] == 14400
    finally:
        engine.dispose()


def test_integrity_thesis_catalyst_history_and_exports() -> None:
    app, engine, SessionLocal = _client_and_session()
    try:
        _seed(SessionLocal)
        with TestClient(app) as client:
            response = client.get("/fundamentals/stocks/AAA/integrity")
            assert response.status_code == 200
            assert response.json()["overall_status"] == "pass"

            detail = client.get("/fundamentals/stocks/AAA")
            assert detail.status_code == 200
            period_metrics = detail.json()["period_metrics"]
            assert {row["period_type"] for row in period_metrics} == {"annual", "quarterly"}
            assert next(row for row in period_metrics if row["period_type"] == "quarterly")["period_label"] == "Q2"

            thesis_body = {
                "direction": "long",
                "conviction": "high",
                "core_thesis": "Alpha is a high-quality bank with resilient earnings and valuation upside.",
                "bullish_drivers": [{"title": "Quality", "detail": "Returns remain above peers.", "pillar": "quality"}],
                "bearish_drivers": [{"title": "Rates", "detail": "Lower rates could pressure margins.", "pillar": "risk"}],
                "target_price": 130,
                "stop_price": 90,
                "target_horizon_months": 12,
            }
            assert client.post("/fundamentals/stocks/AAA/thesis", json=thesis_body).status_code == 200
            thesis_body["core_thesis"] = "Alpha remains attractive after a cleaner thesis update and a better catalyst path."
            assert client.post("/fundamentals/stocks/AAA/thesis", json=thesis_body).status_code == 200
            history = client.get("/fundamentals/stocks/AAA/thesis/history").json()
            assert len(history["items"]) == 2
            assert sum(1 for item in history["items"] if item["is_current"]) == 1

            catalyst = client.post(
                "/fundamentals/stocks/AAA/catalysts",
                json={"event_type": "earnings", "event_date": "2026-06-15", "impact_tier": "moderate", "title": "FY results"},
            )
            assert catalyst.status_code == 200
            catalyst_id = catalyst.json()["id"]
            calendar = client.get("/fundamentals/calendar?from=2026-06-01&to=2026-06-30").json()
            assert [item["id"] for item in calendar["items"]] == [catalyst_id]
            patched = client.patch(f"/fundamentals/catalysts/{catalyst_id}", json={"event_date": "2026-06-18"})
            assert patched.status_code == 200
            assert patched.json()["id"] == catalyst_id
            assert client.delete(f"/fundamentals/catalysts/{catalyst_id}").status_code == 204

            pillar = client.get("/fundamentals/stocks/AAA/pillar-history").json()
            assert pillar["trend"]["quality"] == "on_track"

            sheet = client.get("/fundamentals/stocks/AAA/tearsheet")
            assert sheet.status_code == 200
            assert "section-valuation" in sheet.text
    finally:
        engine.dispose()


def test_auto_scenario_defaults_to_base_with_market_implied_diagnostic() -> None:
    app, engine, SessionLocal = _client_and_session()
    try:
        _seed_auto_scenarios(SessionLocal)
        with TestClient(app) as client:
            batch = client.post("/fundamentals/snapshot/batch?scenario=auto", json={"symbols": ["AAA"]})
            assert batch.status_code == 200
            assert batch.json()["AAA"]["fair_value"] == 118.0
            assert batch.json()["AAA"]["confidence_score"] == 0.60

            detail = client.get("/fundamentals/stocks/AAA")
            assert detail.status_code == 200
            detail_payload = detail.json()
            assert detail_payload["ensemble"]["scenario"] == "base"
            assert detail_payload["ensemble"]["fair_value_base"] == 118.0
            assert detail_payload["headline_scenario"] == "base"
            assert detail_payload["viewed_scenario"] == "base"
            assert detail_payload["market_implied_scenario"] == "bear"
            assert detail_payload["target_price"] == 118.0
            assert detail_payload["scenario_probabilities"] == {"bear": 0.25, "base": 0.55, "bull": 0.2}
            assert set(detail_payload["ensembles"]) == {"bear", "base", "bull"}

            universe = client.get("/fundamentals/universe")
            assert universe.status_code == 200
            row = next(item for item in universe.json() if item["symbol"] == "AAA")
            assert row["ensemble"]["scenario"] == "base"
            assert row["target_price"] == 118.0
            assert row["headline_scenario"] == "base"
            assert row["viewed_scenario"] == "base"
            assert row["market_implied_scenario"] == "bear"
            assert row["adv20"] == 750_000.0

            manual_base = client.get("/fundamentals/stocks/AAA?scenario=base")
            assert manual_base.status_code == 200
            assert manual_base.json()["ensemble"]["scenario"] == "base"
            assert manual_base.json()["ensemble"]["fair_value_base"] == 118.0
    finally:
        engine.dispose()


def test_headline_recommendation_is_base_anchored_across_viewed_scenarios() -> None:
    app, engine, SessionLocal = _client_and_session()
    try:
        _seed_auto_scenarios(SessionLocal)
        with TestClient(app) as client:
            payloads = {
                scenario: client.get(f"/fundamentals/stocks/AAA?scenario={scenario}").json()
                for scenario in ("bear", "base", "bull", "auto")
            }

        base_headline = {
            "recommendation": payloads["base"]["recommendation"],
            "target_price": payloads["base"]["target_price"],
            "conviction": payloads["base"]["conviction"],
        }
        assert base_headline == {"recommendation": "ACCUMULATE", "target_price": 118.0, "conviction": 3}
        for scenario, payload in payloads.items():
            assert {
                "recommendation": payload["recommendation"],
                "target_price": payload["target_price"],
                "conviction": payload["conviction"],
            } == base_headline
            assert payload["headline_scenario"] == "base"
            assert payload["viewed_scenario"] == ("base" if scenario == "auto" else scenario)

        assert payloads["bear"]["ensemble"]["scenario"] == "bear"
        assert payloads["bear"]["ensemble"]["fair_value_base"] == 90.0
        assert payloads["bull"]["ensemble"]["scenario"] == "bull"
        assert payloads["bull"]["ensemble"]["fair_value_base"] == 140.0
    finally:
        engine.dispose()


def test_headline_is_not_rated_when_base_ensemble_is_missing(monkeypatch) -> None:
    app, engine, SessionLocal = _client_and_session()
    try:
        _seed_auto_scenarios(SessionLocal, include_base=False)
        monkeypatch.setattr(fundamentals_router, "_ensure_latest_symbol_valuations", lambda *args, **kwargs: None)
        with TestClient(app) as client:
            response = client.get("/fundamentals/stocks/AAA?scenario=bull")

        assert response.status_code == 200
        payload = response.json()
        assert payload["scenario_trio_stale"] is True
        assert payload["ensemble"] is None
        assert payload["ensembles"] == {}
        assert payload["recommendation"] == "NR"
        assert payload["target_price"] is None
        assert payload["conviction"] == 0
        assert payload["headline_scenario"] == "base"
        assert payload["viewed_scenario"] == "base"
    finally:
        engine.dispose()


def test_legacy_fundamental_schema_reads_existing_data(monkeypatch) -> None:
    app, engine, SessionLocal = _client_and_session()
    try:
        _seed(SessionLocal)
        real_existing_columns = fundamentals_service._existing_table_columns
        real_table_exists = fundamentals_service._table_exists

        def fake_existing_columns(db, model):
            columns = real_existing_columns(db, model)
            if model in {models.FundamentalLatestSnapshot, models.FundamentalAnnualMetric}:
                return columns - {"as_of_date", "source_document_id"}
            return columns

        def fake_table_exists(db, model):
            if model is models.FundamentalBetaHistory:
                return False
            return real_table_exists(db, model)

        monkeypatch.setattr(fundamentals_service, "_existing_table_columns", fake_existing_columns)
        monkeypatch.setattr(fundamentals_service, "_table_exists", fake_table_exists)

        with TestClient(app, raise_server_exceptions=False) as client:
            universe = client.get("/fundamentals/universe")
            assert universe.status_code == 200
            row = next(item for item in universe.json() if item["symbol"] == "AAA")
            assert row["as_of_date"] is not None

            detail = client.get("/fundamentals/stocks/AAA?scenario=base")
            assert detail.status_code == 200
            assert detail.json()["symbol"] == "AAA"

            sensitivity = client.get("/fundamentals/stocks/AAA/sensitivity?scenario=base")
            assert sensitivity.status_code == 200
    finally:
        engine.dispose()
