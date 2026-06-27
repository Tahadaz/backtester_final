from __future__ import annotations

import datetime as dt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.quant_core.fundamentals import default_assumptions_for_scenario
from services.api.app import models
from services.api.app.db import get_db
from services.api.app.routers import fundamentals as fundamentals_router
from services.api.app.services.fundamentals import (
    _apply_live_cost_of_capital,
    make_bulk_overrides_loader,
    resolved_assumptions_with_provenance,
    upsert_assumptions,
)


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
        models.StockMaster.__table__,
        models.FundamentalImport.__table__,
        models.FundamentalSourceDocument.__table__,
        models.FundamentalAnnualMetric.__table__,
        models.FundamentalLatestSnapshot.__table__,
        models.FundamentalAssumptionSet.__table__,
        models.FundamentalAssumptionOverride.__table__,
        models.FundamentalMacroConfig.__table__,
        models.FundamentalBetaHistory.__table__,
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


def _seed_stock(SessionLocal) -> None:
    db = SessionLocal()
    try:
        db.add(models.StockMaster(symbol="AAA", display_name="Alpha", sector="Banks", market_region="masi"))
        db.commit()
    finally:
        db.close()


def _seed_snapshot_with_history(SessionLocal, *, symbol: str, sector: str, metrics: dict[str, float], annual: dict[str, float]) -> None:
    db = SessionLocal()
    try:
        db.add(models.StockMaster(symbol=symbol, display_name=symbol, sector=sector, market_region="masi"))
        run = models.FundamentalImport(
            filename=f"{symbol}.xlsx",
            source_hash=f"{symbol}-hash",
            status="succeeded",
            data_source="workbook",
            methodology_version="v3",
        )
        db.add(run)
        db.flush()
        db.add(
            models.FundamentalLatestSnapshot(
                import_id=run.id,
                symbol=symbol,
                company_name=symbol,
                latest_statement_year=2024,
                metrics_json=metrics,
                scores_json={},
                diagnostics_json={},
                coverage_json={},
                model_eligibility_json={},
                source_json={"currency": "MAD"},
                as_of_date=dt.date(2026, 5, 31),
            )
        )
        db.add_all(
            [
                models.FundamentalAnnualMetric(
                    import_id=run.id,
                    symbol=symbol,
                    company_name=symbol,
                    statement_year=2024,
                    metric_name=metric,
                    metric_value=value,
                )
                for metric, value in annual.items()
            ]
        )
        db.commit()
    finally:
        db.close()


def test_assumption_override_lifecycle(monkeypatch) -> None:
    monkeypatch.setattr("services.api.app.auth.settings.ADMIN_API_KEY", "admin-secret")
    app, engine, SessionLocal = _client_and_session()
    user_headers = {"x-app-user-id": "analyst-1", "x-app-user-email": "analyst@example.com"}
    admin_user_headers = {**user_headers, "x-admin-api-key": "admin-secret"}
    try:
        _seed_stock(SessionLocal)
        with TestClient(app) as client:
            unauthenticated = client.put(
                "/fundamentals/AAA/assumptions/bull/override",
                headers={"x-admin-api-key": "admin-secret"},
                json={"overrides": {"equity_risk_premium": 0.07}},
            )
            assert unauthenticated.status_code == 401

            forbidden = client.put(
                "/fundamentals/AAA/assumptions/bull/override",
                headers=user_headers,
                json={"overrides": {"equity_risk_premium": 0.07}},
            )
            assert forbidden.status_code == 403

            created = client.put(
                "/fundamentals/AAA/assumptions/bull/override",
                headers=admin_user_headers,
                json={"overrides": {"stable_payout_ratio": "0.50"}, "note": "Payout", "created_by": "spoofed"},
            )
            assert created.status_code == 200
            payload = created.json()
            assert payload["overrides"] == {"stable_payout_ratio": 0.50}
            assert payload["note"] == "Payout"
            assert payload["created_by"] == "analyst@example.com"

            resolved = client.get("/fundamentals/AAA/assumptions/bull")
            assert resolved.status_code == 200
            resolved_payload = resolved.json()
            assert resolved_payload["assumptions"]["risk_free_rate"] == pytest.approx(0.035)
            assert resolved_payload["assumptions"]["equity_risk_premium"] == pytest.approx(0.060)
            assert resolved_payload["assumptions"]["stable_payout_ratio"] == pytest.approx(0.50)
            assert resolved_payload["assumptions"]["scenario_erp_addon"] == pytest.approx(-0.010)
            assert resolved_payload["assumptions"]["cost_of_equity"] == pytest.approx(0.035 + 0.050)
            assert resolved_payload["assumptions"]["wacc"] == pytest.approx(0.70 * 0.085 + 0.30 * 0.050 * 0.65)
            assert resolved_payload["provenance"]["risk_free_rate"] == "macro_config"
            assert resolved_payload["provenance"]["equity_risk_premium"] == "macro_config"
            assert resolved_payload["provenance"]["stable_payout_ratio"] == "user_override"
            assert resolved_payload["provenance"]["scenario_erp_addon"] == "scenario"
            assert resolved_payload["provenance"]["wacc"] == "computed"

            current = client.get("/fundamentals/AAA/assumptions/bull/override")
            assert current.status_code == 200
            assert current.json()["id"] == payload["id"]

            superseding = client.put(
                "/fundamentals/AAA/assumptions/bull/override",
                headers=admin_user_headers,
                json={"overrides": {"stable_payout_ratio": 0.60}, "note": "Superseded"},
            )
            assert superseding.status_code == 200
            assert superseding.json()["id"] != payload["id"]

            db = SessionLocal()
            try:
                current_rows = (
                    db.query(models.FundamentalAssumptionOverride)
                    .filter(
                        models.FundamentalAssumptionOverride.symbol == "AAA",
                        models.FundamentalAssumptionOverride.scenario == "bull",
                        models.FundamentalAssumptionOverride.is_current.is_(True),
                    )
                    .all()
                )
                assert len(current_rows) == 1
                assert current_rows[0].overrides == {"stable_payout_ratio": 0.60}
            finally:
                db.close()

            deleted = client.delete("/fundamentals/AAA/assumptions/bull/override", headers=admin_user_headers)
            assert deleted.status_code == 204
            assert client.get("/fundamentals/AAA/assumptions/bull/override").status_code == 404
            reverted = client.get("/fundamentals/AAA/assumptions/bull").json()
            assert reverted["assumptions"]["cost_of_equity"] == pytest.approx(0.035 + 0.050)
            assert reverted["assumptions"]["wacc"] == pytest.approx(0.70 * 0.085 + 0.30 * 0.050 * 0.65)
            assert reverted["provenance"]["wacc"] == "computed"
    finally:
        engine.dispose()


def test_assumption_override_validation(monkeypatch) -> None:
    monkeypatch.setattr("services.api.app.auth.settings.ADMIN_API_KEY", "admin-secret")
    app, engine, SessionLocal = _client_and_session()
    headers = {"x-app-user-id": "analyst-1", "x-admin-api-key": "admin-secret"}
    try:
        _seed_stock(SessionLocal)
        with TestClient(app) as client:
            unknown = client.put(
                "/fundamentals/AAA/assumptions/base/override",
                headers=headers,
                json={"overrides": {"foo": 1.0}},
            )
            assert unknown.status_code == 422
            assert "unknown assumption key" in unknown.text

            non_float = client.put(
                "/fundamentals/AAA/assumptions/base/override",
                headers=headers,
                json={"overrides": {"equity_risk_premium": "not-a-number"}},
            )
            assert non_float.status_code == 422
            assert "finite float" in non_float.text

            computed = client.put(
                "/fundamentals/AAA/assumptions/base/override",
                headers=headers,
                json={"overrides": {"wacc": 0.10}},
            )
            assert computed.status_code == 422
            assert "computed" in computed.text
    finally:
        engine.dispose()


def test_assumption_endpoint_exposes_normalized_scenario_probabilities(monkeypatch) -> None:
    monkeypatch.setattr("services.api.app.auth.settings.ADMIN_API_KEY", "admin-secret")
    app, engine, SessionLocal = _client_and_session()
    headers = {"x-app-user-id": "analyst-1", "x-admin-api-key": "admin-secret"}
    try:
        _seed_stock(SessionLocal)
        with TestClient(app) as client:
            created = client.put(
                "/fundamentals/AAA/assumptions/base/override",
                headers=headers,
                json={
                    "overrides": {
                        "scenario_probability_bear": 0.40,
                        "scenario_probability_base": 0.40,
                        "scenario_probability_bull": 0.40,
                    }
                },
            )
            assert created.status_code == 200

            resolved = client.get("/fundamentals/AAA/assumptions/base")
            assert resolved.status_code == 200
            payload = resolved.json()

        assert payload["scenario_probabilities"] == {
            "bear": pytest.approx(1 / 3),
            "base": pytest.approx(1 / 3),
            "bull": pytest.approx(1 / 3),
        }
        assert payload["assumptions"]["scenario_probability_bear"] == pytest.approx(1 / 3)
        assert payload["provenance"]["scenario_probability_base"] == "computed"
        assert payload["warnings"] == ["scenario_probabilities_renormalized"]
    finally:
        engine.dispose()


def test_methodology_endpoint_returns_assumption_registry() -> None:
    app, engine, _SessionLocal = _client_and_session()
    try:
        with TestClient(app) as client:
            response = client.get("/fundamentals/methodology")
            assert response.status_code == 200
            payload = response.json()
            assumptions = payload["assumptions"]
            assert {
                "risk_free_rate",
                "equity_risk_premium",
                "scenario_erp_addon",
                "scenario_cost_of_debt_addon",
                "cost_of_equity_floor",
                "mid_year_terminal",
                "beta_zero_return_threshold",
                "wacc",
            } <= set(assumptions)
            assert assumptions["risk_free_rate"]["source"]
            assert assumptions["wacc"]["editable"] is False
            assert "Ke = max" in payload["cost_of_capital"]["formula"]
    finally:
        engine.dispose()


def test_macro_erp_edit_moves_cost_of_equity_for_all_symbols() -> None:
    _app, engine, SessionLocal = _client_and_session()
    db = SessionLocal()
    try:
        db.add_all(
            [
                models.FundamentalBetaHistory(
                    symbol="AAA",
                    as_of=dt.date(2026, 5, 31),
                    beta=1.0,
                    method="ols",
                    r2=0.60,
                    n_obs=104,
                    zero_week_frac=0.05,
                    liquidity_flag=False,
                    proxy="MASI",
                    frequency="weekly",
                    window_years=2.0,
                    warnings_json=[],
                ),
                models.FundamentalBetaHistory(
                    symbol="BBB",
                    as_of=dt.date(2026, 5, 31),
                    beta=1.5,
                    method="ols",
                    r2=0.55,
                    n_obs=104,
                    zero_week_frac=0.08,
                    liquidity_flag=False,
                    proxy="MASI",
                    frequency="weekly",
                    window_years=2.0,
                    warnings_json=[],
                ),
            ]
        )
        db.commit()

        before_aaa, _ = resolved_assumptions_with_provenance(db, symbol="AAA", sector=None, scenario="base")
        before_bbb, _ = resolved_assumptions_with_provenance(db, symbol="BBB", sector=None, scenario="base")

        db.add(
            models.FundamentalMacroConfig(
                risk_free_mode="tenor",
                treasury_tenor="10Y",
                treasury_curve_json={"10Y": 0.035},
                erp_mode="manual",
                erp_index_symbol="MASI",
                erp_index_asset_class="index",
                manual_equity_risk_premium=0.07,
                country_risk_mode="auto",
                morocco_country_risk_premium=0.0,
                source="test_macro_config",
                is_active=True,
            )
        )
        db.commit()

        after_aaa, provenance_aaa = resolved_assumptions_with_provenance(db, symbol="AAA", sector=None, scenario="base")
        after_bbb, provenance_bbb = resolved_assumptions_with_provenance(db, symbol="BBB", sector=None, scenario="base")

        assert after_aaa["cost_of_equity"] > before_aaa["cost_of_equity"]
        assert after_bbb["cost_of_equity"] > before_bbb["cost_of_equity"]
        assert after_aaa["cost_of_equity"] == pytest.approx(0.035 + 1.0 * 0.07)
        assert after_bbb["cost_of_equity"] == pytest.approx(0.035 + 1.5 * 0.07)
        assert after_aaa["wacc"] > before_aaa["wacc"]
        assert provenance_aaa["equity_risk_premium"] == "macro_config"
        assert provenance_bbb["wacc"] == "computed"
    finally:
        db.close()
        engine.dispose()


def test_static_terminal_growth_and_growth_cap_are_ignored_for_symbol_rows() -> None:
    _app, engine, SessionLocal = _client_and_session()
    db = SessionLocal()
    try:
        _seed_snapshot_with_history(
            SessionLocal,
            symbol="STAT",
            sector="Industrie",
            metrics={
                "Revenue": 120.0,
                "Revenue_Growth": 0.08,
                "ROE": 0.12,
                "Dividend_Payout": 0.40,
                "MarketCap_Calc": 1000.0,
            },
            annual={
                "Revenue": 120.0,
                "EBIT": 18.0,
                "Total_Debt": 100.0,
                "Total_Equity": 300.0,
            },
        )
        db.add(
            models.FundamentalAssumptionSet(
                scope_type="symbol",
                scope_key="STAT",
                scenario="base",
                version_label="old-static-growth-placeholders",
                assumptions_json={"terminal_growth": 0.011, "terminal_growth_firm": 0.012, "growth_cap": 0.01},
                is_active=True,
            )
        )
        db.commit()

        assumptions, provenance = resolved_assumptions_with_provenance(
            db,
            symbol="STAT",
            sector="Industrie",
            scenario="base",
        )

        assert "growth_cap" not in assumptions
        assert assumptions["terminal_growth_firm"] != pytest.approx(0.012)
        assert assumptions["terminal_growth_equity"] != pytest.approx(0.011)
        assert provenance["terminal_growth_firm"] == "computed_from_fundamentals"
        assert provenance["terminal_growth_equity"] == "computed_from_fundamentals"
    finally:
        db.close()
        engine.dispose()


def test_desk_cost_of_equity_floor_bounds_low_beta_symbols() -> None:
    _app, engine, SessionLocal = _client_and_session()
    db = SessionLocal()
    try:
        db.add(
            models.FundamentalBetaHistory(
                symbol="LOW",
                as_of=dt.date(2026, 5, 31),
                beta=0.10,
                method="ols",
                r2=0.20,
                n_obs=104,
                zero_week_frac=0.05,
                liquidity_flag=False,
                proxy="MASI",
                frequency="weekly",
                window_years=2.0,
                warnings_json=[],
            )
        )
        upsert_assumptions(
            db,
            scenario="base",
            assumptions={"risk_free_rate": 0.035, "cost_of_equity_floor": 0.095},
            scope_type="desk",
            scope_key="GLOBAL",
            version_label="desk-ke-floor-test",
        )
        db.commit()

        assumptions, provenance = resolved_assumptions_with_provenance(db, symbol="LOW", sector=None, scenario="base")
        build = assumptions["cost_of_capital_build_up"]

        assert build["cost_of_equity_unfloored"] == pytest.approx(0.035 + 0.10 * 0.060)
        assert assumptions["cost_of_equity"] == pytest.approx(0.095)
        assert build["cost_of_equity_floor"] == pytest.approx(0.095)
        assert build["cost_of_equity_floor_bound"] is True
        assert provenance["cost_of_equity_floor"] == "scenario"
        assert provenance["cost_of_equity"] == "computed"
    finally:
        db.close()
        engine.dispose()


def test_scenario_risk_addons_move_live_wacc_in_order() -> None:
    _app, engine, SessionLocal = _client_and_session()
    db = SessionLocal()
    try:
        bear, bear_provenance = resolved_assumptions_with_provenance(db, symbol="AAA", sector=None, scenario="bear")
        base, base_provenance = resolved_assumptions_with_provenance(db, symbol="AAA", sector=None, scenario="base")
        bull, bull_provenance = resolved_assumptions_with_provenance(db, symbol="AAA", sector=None, scenario="bull")

        assert bear["scenario_erp_addon"] == pytest.approx(0.015)
        assert bull["scenario_cost_of_debt_addon"] == pytest.approx(-0.005)
        assert bear["cost_of_equity"] > base["cost_of_equity"] > bull["cost_of_equity"]
        assert bear["wacc"] > base["wacc"] > bull["wacc"]
        assert bear["cost_of_capital_build_up"]["effective_equity_risk_premium"] == pytest.approx(0.075)
        assert bull["cost_of_capital_build_up"]["effective_cost_of_debt"] == pytest.approx(0.050)
        assert bear_provenance["scenario_erp_addon"] == "scenario"
        assert base_provenance["wacc"] == "computed"
        assert bull_provenance["scenario_cost_of_debt_addon"] == "scenario"
    finally:
        db.close()
        engine.dispose()


def test_live_cost_of_capital_uses_market_weights_and_synthetic_spread() -> None:
    _app, engine, SessionLocal = _client_and_session()
    try:
        _seed_snapshot_with_history(
            SessionLocal,
            symbol="IND",
            sector="Industrie",
            metrics={"MarketCap_Calc": 900.0, "Current_Price": 90.0, "Shares_Outstanding": 10.0},
            annual={"Total_Debt": 100.0, "Interest_Expense": 10.0, "EBIT": 50.0},
        )
        db = SessionLocal()
        try:
            assumptions, provenance = resolved_assumptions_with_provenance(db, symbol="IND", sector="Industrie", scenario="base")
            build = assumptions["cost_of_capital_build_up"]

            assert build["weight_source"] == "market_cap_plus_debt"
            assert build["equity_weight"] == pytest.approx(0.90)
            assert build["debt_weight"] == pytest.approx(0.10)
            assert build["interest_coverage"] == pytest.approx(5.0)
            assert build["synthetic_bucket"] == "A"
            assert build["kd_synthetic"] == pytest.approx(0.035 + 0.018)
            assert build["cost_of_debt_source"] == "synthetic_interest_coverage_spread"
            assert assumptions["cost_of_debt"] == pytest.approx(0.053)
            assert assumptions["wacc"] == pytest.approx(0.90 * 0.095 + 0.10 * 0.053 * 0.65)
            assert provenance["cost_of_debt"] == "computed"
            assert provenance["wacc"] == "computed"
        finally:
            db.close()
    finally:
        engine.dispose()


def test_financial_sector_keeps_registry_cost_of_debt() -> None:
    _app, engine, SessionLocal = _client_and_session()
    try:
        _seed_snapshot_with_history(
            SessionLocal,
            symbol="BNK",
            sector="Banks",
            metrics={"MarketCap_Calc": 900.0, "Current_Price": 90.0, "Shares_Outstanding": 10.0},
            annual={"Total_Debt": 100.0, "Interest_Expense": 10.0, "EBIT": 50.0},
        )
        db = SessionLocal()
        try:
            assumptions, _provenance = resolved_assumptions_with_provenance(db, symbol="BNK", sector="Banks", scenario="base")
            build = assumptions["cost_of_capital_build_up"]

            assert build["cost_of_debt_source"] == "registry_default_financial_sector"
            assert build["interest_coverage"] is None
            assert assumptions["cost_of_debt"] == pytest.approx(0.055)
            bull_once, _ = resolved_assumptions_with_provenance(db, symbol="BNK", sector="Banks", scenario="bull")
            bull_twice, _ = _apply_live_cost_of_capital(db, symbol="BNK", assumptions=bull_once, sector="Banks", scenario="bull")
            assert bull_once["cost_of_debt"] == pytest.approx(0.050)
            assert bull_twice["cost_of_debt"] == pytest.approx(0.050)
        finally:
            db.close()
    finally:
        engine.dispose()


def test_current_live_cost_uses_latest_beta_while_pit_lookup_stays_strict() -> None:
    _app, engine, SessionLocal = _client_and_session()
    try:
        _seed_snapshot_with_history(
            SessionLocal,
            symbol="LAG",
            sector="Industrie",
            metrics={"MarketCap_Calc": 900.0, "Current_Price": 90.0, "Shares_Outstanding": 10.0},
            annual={"Total_Debt": 100.0, "Interest_Expense": 10.0, "EBIT": 50.0},
        )
        db = SessionLocal()
        try:
            db.add(
                models.FundamentalBetaHistory(
                    symbol="LAG",
                    as_of=dt.date(2026, 6, 1),
                    beta=1.42,
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
            db.commit()

            current, current_provenance = resolved_assumptions_with_provenance(
                db,
                symbol="LAG",
                sector="Industrie",
                scenario="base",
            )
            current_build = current["cost_of_capital_build_up"]
            assert current_build["beta_source"] == "beta_history"
            assert current_build["beta"] == pytest.approx(1.42)
            assert current_build["beta_lookup_as_of"] == "latest"
            assert current_provenance["beta"] == "beta_history"

            snapshot = db.query(models.FundamentalLatestSnapshot).filter_by(symbol="LAG").one()
            strict, _ = _apply_live_cost_of_capital(
                db,
                symbol="LAG",
                assumptions={**default_assumptions_for_scenario("base"), "currency": "MAD"},
                sector="Industrie",
                scenario="base",
                snapshot_row=snapshot,
                use_snapshot_beta_as_of=True,
            )
            strict_build = strict["cost_of_capital_build_up"]
            assert strict_build["beta_source"] == "default_beta"
            assert strict_build["beta_lookup_as_of"] == "2026-05-31"
        finally:
            db.close()
    finally:
        engine.dispose()


def test_ensemble_weight_override_accepted_by_put_endpoint(monkeypatch) -> None:
    """Phase A / Phase B gate: ensemble_weight_relative_multiples is now registered in
    DEFAULT_ASSUMPTIONS, so the override PUT endpoint must accept it instead of
    returning 422 'unknown assumption key'."""
    monkeypatch.setattr("services.api.app.auth.settings.ADMIN_API_KEY", "admin-secret")
    app, engine, SessionLocal = _client_and_session()
    headers = {"x-app-user-id": "analyst-1", "x-app-user-email": "analyst@example.com", "x-admin-api-key": "admin-secret"}
    try:
        _seed_stock(SessionLocal)
        with TestClient(app) as client:
            # Setting relative_multiples weight to 1.0 means the ensemble will be driven
            # entirely by the comp model (assuming it survives quality gates).
            resp = client.put(
                "/fundamentals/AAA/assumptions/base/override",
                headers=headers,
                json={"overrides": {"ensemble_weight_relative_multiples": 1.0}},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["overrides"] == {"ensemble_weight_relative_multiples": 1.0}

            # Clearing the override reverts to auto weighting.
            delete_resp = client.delete("/fundamentals/AAA/assumptions/base/override", headers=headers)
            assert delete_resp.status_code == 204
            assert client.get("/fundamentals/AAA/assumptions/base/override").status_code == 404
    finally:
        engine.dispose()


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
                overrides={"equity_risk_premium": 0.07},
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
        assert loader("SYM001", "bull") == {"equity_risk_premium": 0.07}
    finally:
        db.close()
        engine.dispose()
