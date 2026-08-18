from __future__ import annotations

from datetime import date
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.quant_core.historical_portfolio import METHODOLOGY_VERSION
from scripts.audit_pit_portfolio_windows import publish_audit
from services.api.app import models


def _db():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.HistoricalPortfolioBacktestRun.__table__.create(engine)
    models.HistoricalOpportunityMaterializationRun.__table__.create(engine)
    models.HistoricalTradeOpportunity.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_window_audit_publishes_three_deterministic_persisted_only_artifacts(tmp_path) -> None:
    db = _db()
    run_id = uuid.uuid4()
    run = models.HistoricalPortfolioBacktestRun(
        id=run_id, status="succeeded", methodology_version=METHODOLOGY_VERSION,
        config_json={"start_date": "2024-01-01", "end_date": "2024-05-31", "symbols": ["AAA"]},
        provenance_json={}, diagnostics_json={"execution_events_v1": [{
            "methodology_version": METHODOLOGY_VERSION, "scenario": "baseline",
            "decision_date": "2024-01-05", "action_date": "2024-01-08", "symbol": "AAA",
            "horizon": "weekly", "winner_variant": "expanded_ta_simple",
            "signal_direction": "long", "actionable": True, "execution_eligible": True,
            "execution_action": "enter_long", "reason": "long_entry", "position_before": "flat",
            "position_after": "long", "opportunity_input_hash": "a" * 64, "fill_price": 100.0,
            "quantity": 1.0, "notional": 100.0, "delay_sessions": 1,
        }]}, opportunities_json=[], trades_json=[], equity_curves_json={}, benchmark_curves_json={},
        statistics_json={}, validation_json={}, snapshot_audit_json={}, warnings_json=[],
    )
    materialization = models.HistoricalOpportunityMaterializationRun(
        status="succeeded", methodology_version=METHODOLOGY_VERSION,
        config_json={}, progress_json={}, coverage_json={},
    )
    db.add_all([run, materialization])
    db.flush()
    variants = (
        "legacy_ta_simple", "expanded_ta_simple", "legacy_factor_x_ta_simple",
        "expanded_factor_x_ta_simple", "legacy_ta_combo", "expanded_ta_combo",
        "legacy_factor_x_ta_combo", "expanded_factor_x_ta_combo",
    )
    for variant in variants:
        winner = variant == "expanded_ta_simple"
        db.add(models.HistoricalTradeOpportunity(
            methodology_version=METHODOLOGY_VERSION, decision_date=date(2024, 1, 5), symbol="AAA",
            horizon="weekly", variant=variant, accepted=False, status="evaluated",
            actionable=winner, reconstructed_dashboard_winner=winner, rank_json=[1] if winner else [],
            decision_json={
                "status": "evaluated", "signal_direction": "long" if winner else "neutral",
                "actionable": winner, "actionability_reasons": [] if winner else ["neutral_bucket"],
                "category_scores": {key: 1.0 for key in ("tendance", "momentum", "oscillation", "volume")},
                "evidence": {"n": 30},
            },
            opportunity_json={"direction": "long"} if winner else None,
            input_hash=variant.ljust(64, "x")[:64], materialization_run_id=materialization.id,
        ))
    db.commit()
    first = tmp_path / "first"
    second = tmp_path / "second"
    window = [(date(2024, 1, 1), date(2024, 5, 31))]
    publish_audit(db, run_id=run_id, windows=window, destination=first)
    publish_audit(db, run_id=run_id, windows=window, destination=second)
    names = {"summary.json", "weekly_attribution.csv", "decision_details.jsonl"}
    assert {item.name for item in first.iterdir()} == names
    assert {name: (first / name).read_bytes() for name in names} == {
        name: (second / name).read_bytes() for name in names
    }
    assert "long_entry" in (first / "weekly_attribution.csv").read_text()
