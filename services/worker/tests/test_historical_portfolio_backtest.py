from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pandas as pd
from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.quant_core.historical_portfolio import HistoricalOpportunity, METHODOLOGY_VERSION
from services.api.app import models
from services.worker.tasks import historical_portfolio_backtest as worker


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


def _create_tables(engine, selected) -> None:
    metadata = MetaData()
    for model in selected:
        model.__table__.to_metadata(metadata)
    for table in metadata.tables.values():
        for column in table.columns:
            if column.server_default is not None and "jsonb" in str(column.server_default.arg).lower():
                column.server_default = None
    metadata.create_all(engine)


def test_backtest_reuses_materialized_opportunities_without_reconstruction(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    _create_tables(engine, (
        models.HistoricalPortfolioBacktestRun,
        models.HistoricalOpportunityMaterializationRun,
        models.HistoricalTradeOpportunity,
        models.DashboardSnapshot,
    ))
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    materialization_id = uuid.uuid4()
    db.add(models.HistoricalOpportunityMaterializationRun(
        id=materialization_id, status="succeeded", methodology_version=METHODOLOGY_VERSION,
        config_json={"start_date": "2024-01-01", "end_date": "2024-12-31", "symbols": []},
        progress_json={"stage": "completed"}, coverage_json={}, completed_at=datetime.now(timezone.utc),
    ))
    opportunity = HistoricalOpportunity(
        decision_date="2024-03-01", symbol="AAA", horizon="weekly",
        variant="expanded_ta_simple", direction="long", training_end="2024-02-29",
        selection_sample_end="2024-02-29", proof_sample_end="2024-02-29",
    )
    from dataclasses import asdict
    db.add(models.HistoricalTradeOpportunity(
        decision_date=pd.Timestamp(opportunity.decision_date).date(), symbol="AAA", horizon="weekly",
        variant=opportunity.variant, accepted=True, rank_json=[1.0], opportunity_json=asdict(opportunity),
        input_hash="x" * 64, materialization_run_id=materialization_id,
    ))
    run_id = uuid.uuid4()
    db.add(models.HistoricalPortfolioBacktestRun(
        id=run_id, status="queued", methodology_version=METHODOLOGY_VERSION,
        config_json={"start_date": "2024-01-01", "end_date": "2024-12-31", "symbols": [], "bootstrap_samples": 100},
        provenance_json={}, diagnostics_json={}, opportunities_json=[], trades_json=[], equity_curves_json={},
        benchmark_curves_json={}, statistics_json={}, validation_json={}, snapshot_audit_json={}, warnings_json=[],
    ))
    db.commit()
    db.close()

    prices = pd.DataFrame(
        {"Open": [100.0] * 80, "Close": [100.0] * 80, "Volume": [1_000_000.0] * 80},
        index=pd.bdate_range("2024-01-01", periods=80),
    )
    monkeypatch.setattr("services.api.app.db._ensure_session_factory", lambda: Session)
    monkeypatch.setattr(worker, "_load_prices", lambda _db, _symbols: {"AAA": prices})
    monkeypatch.setattr(worker, "_load_inputs", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("slow reconstruction called")))

    worker.execute_historical_portfolio_backtest(str(run_id))

    verify = Session()
    completed = verify.query(models.HistoricalPortfolioBacktestRun).filter_by(id=run_id).one()
    assert completed.status == "succeeded"
    assert completed.diagnostics_json["stage"] == "completed"
    assert completed.provenance_json["opportunity_store_materialization_runs"] == [str(materialization_id)]
    verify.close()


def test_materializer_persists_candidates_and_one_accepted_winner(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    _create_tables(engine, (
        models.HistoricalOpportunityMaterializationRun,
        models.HistoricalTradeOpportunity,
    ))
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    run_id = uuid.uuid4()
    db.add(models.HistoricalOpportunityMaterializationRun(
        id=run_id, status="queued", methodology_version=METHODOLOGY_VERSION,
        config_json={"start_date": "2024-03-01", "end_date": "2024-03-01", "symbols": []},
        progress_json={}, coverage_json={},
    ))
    db.commit()
    db.close()
    prices = pd.DataFrame(
        {"Open": [100.0] * 50, "Close": [100.0] * 50, "Volume": [1_000_000.0] * 50},
        index=pd.bdate_range(end="2024-03-01", periods=50),
    )

    def fake_selector(_scores, _config):
        def select(as_of, horizon, variant, _market):
            if horizon != "weekly" or variant not in {"legacy_ta_simple", "expanded_ta_simple"}:
                return []
            return [HistoricalOpportunity(
                decision_date=as_of.date().isoformat(), symbol="AAA", horizon=horizon,
                variant=variant, direction="long", rank=(2.0 if variant == "expanded_ta_simple" else 1.0,),
                training_end="2024-02-29", selection_sample_end="2024-02-29", proof_sample_end="2024-02-29",
            )]
        return select

    monkeypatch.setattr("services.api.app.db._ensure_session_factory", lambda: Session)
    monkeypatch.setattr(worker, "_load_inputs", lambda _db, _config: ({"AAA": prices}, {}))
    monkeypatch.setattr(worker, "_build_selector", fake_selector)
    worker.materialize_historical_opportunities(str(run_id))

    verify = Session()
    run = verify.query(models.HistoricalOpportunityMaterializationRun).filter_by(id=run_id).one()
    rows = verify.query(models.HistoricalTradeOpportunity).all()
    assert run.status == "succeeded"
    assert len(rows) == 2
    assert [row.variant for row in rows if row.accepted] == ["expanded_ta_simple"]
    assert run.coverage_json["decision_date_count"] == 1
    verify.close()
