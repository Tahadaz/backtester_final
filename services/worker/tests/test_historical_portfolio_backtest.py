from __future__ import annotations

from datetime import datetime, timezone
import uuid
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.quant_core.historical_portfolio import HistoricalOpportunity, METHODOLOGY_VERSION
from core.quant_core.historical_portfolio import PortfolioBacktestConfig, SelectionObservation
from core.quant_core.signal_ranking import AsOfDecision
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


def test_json_sanitizer_recurses_through_nested_payloads() -> None:
    payload = {
        "values": [float("nan"), float("inf"), (float("-inf"), 1.25)],
        "numpy": pd.Series([float("inf")], dtype="float32").iloc[0],
    }

    assert worker._sanitize_json(payload) == {
        "values": [None, None, [None, 1.25]],
        "numpy": None,
    }


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
        provenance={"edge_score": 60.0, "n": 40, "expected_return_net": 0.01},
    )
    from dataclasses import asdict
    db.add(models.HistoricalTradeOpportunity(
        methodology_version=METHODOLOGY_VERSION,
        decision_date=pd.Timestamp(opportunity.decision_date).date(), symbol="AAA", horizon="weekly",
        variant=opportunity.variant, accepted=False, status="evaluated", actionable=True,
        reconstructed_dashboard_winner=True, rank_json=[1.0], decision_json={
            "status": "evaluated", "signal_direction": "long", "actionable": True,
            "actionability_reasons": [], "evidence": opportunity.provenance,
        }, opportunity_json=asdict(opportunity),
        input_hash="x" * 64, materialization_run_id=materialization_id,
    ))
    run_id = uuid.uuid4()
    db.add(models.HistoricalPortfolioBacktestRun(
        id=run_id, status="queued", methodology_version=METHODOLOGY_VERSION,
        config_json={
            "start_date": "2024-02-01", "end_date": "2024-03-31", "symbols": [],
            "horizons": ["weekly"], "bootstrap_samples": 100,
        },
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
    monkeypatch.setattr(worker, "benchmark_curves", lambda *_args: {
        "available": False,
        "nonfinite_diagnostics": [float("nan"), float("inf"), {"negative": float("-inf")}],
    })

    worker.execute_historical_portfolio_backtest(str(run_id))

    verify = Session()
    completed = verify.query(models.HistoricalPortfolioBacktestRun).filter_by(id=run_id).one()
    assert completed.status == "succeeded"
    assert completed.diagnostics_json["stage"] == "completed"
    assert completed.provenance_json["opportunity_store_materialization_runs"] == [str(materialization_id)]
    assert completed.benchmark_curves_json["nonfinite_diagnostics"] == [None, None, {"negative": None}]
    assert set(completed.equity_curves_json["0.01"]["sleeves"]) == {"weekly"}
    curve_dates = [point["date"] for point in completed.equity_curves_json["0.01"]["combined"]["equity_curve"]]
    assert curve_dates
    assert min(curve_dates) >= "2024-02-01"
    assert max(curve_dates) <= "2024-03-31"
    assert all(trade["horizon"] == "weekly" for trade in completed.trades_json)
    verify.close()


def test_replay_emits_baseline_event_for_keys_without_a_winner(monkeypatch) -> None:
    """Replay loads winners only, but the event ledger must still carry one baseline event per
    (decision_date, symbol, horizon) key — including keys whose modes produced no winner."""

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
        provenance={"edge_score": 60.0, "n": 40, "expected_return_net": 0.01},
    )
    from dataclasses import asdict
    db.add(models.HistoricalTradeOpportunity(
        methodology_version=METHODOLOGY_VERSION,
        decision_date=pd.Timestamp("2024-03-01").date(), symbol="AAA", horizon="weekly",
        variant=opportunity.variant, accepted=False, status="evaluated", actionable=True,
        reconstructed_dashboard_winner=True, rank_json=[1.0], decision_json={
            "status": "evaluated", "signal_direction": "long", "actionable": True,
            "actionability_reasons": [], "evidence": opportunity.provenance,
        }, opportunity_json=asdict(opportunity),
        input_hash="x" * 64, materialization_run_id=materialization_id,
    ))
    # Second key: two evaluated-but-not-actionable modes, so it has no winner at all.
    for variant, reason in (("expanded_ta_simple", "neutral_bucket"), ("ta_simple", "non_positive_expectancy")):
        db.add(models.HistoricalTradeOpportunity(
            methodology_version=METHODOLOGY_VERSION,
            decision_date=pd.Timestamp("2024-03-08").date(), symbol="BBB", horizon="weekly",
            variant=variant, accepted=False, status="evaluated", actionable=False,
            reconstructed_dashboard_winner=False, rank_json=[], decision_json={
                "status": "evaluated", "signal_direction": "neutral", "actionable": False,
                "actionability_reasons": [reason], "evidence": {},
            }, opportunity_json=None,
            input_hash="y" * 64, materialization_run_id=materialization_id,
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
    monkeypatch.setattr(worker, "_load_prices", lambda _db, _symbols: {"AAA": prices, "BBB": prices})

    worker.execute_historical_portfolio_backtest(str(run_id))

    verify = Session()
    completed = verify.query(models.HistoricalPortfolioBacktestRun).filter_by(id=run_id).one()
    assert completed.status == "succeeded"
    events = completed.diagnostics_json["execution_events_v1"]
    baseline = {
        (event["decision_date"], event["symbol"], event["horizon"])
        for event in events if event["scenario"] == "baseline"
    }
    assert ("2024-03-01", "AAA", "weekly") in baseline
    # The no-winner key is the regression guard: filtering the load to winners would drop it.
    assert ("2024-03-08", "BBB", "weekly") in baseline
    no_winner = next(
        event for event in events
        if event["scenario"] == "baseline" and event["symbol"] == "BBB"
    )
    assert no_winner["winner_variant"] is None
    assert no_winner["actionable"] is False
    assert no_winner["execution_action"] == "no_action"
    # All three stored rows are counted even though only one was hydrated for replay.
    assert completed.diagnostics_json.get("stored_candidate_count", 3) == 3
    verify.close()


def test_materializer_persists_complete_grid_and_one_reconstructed_winner(monkeypatch) -> None:
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
        config_json={
            "start_date": "2024-03-01", "end_date": "2024-03-01",
            "symbols": ["AAA"], "resolved_universe": ["AAA"],
        },
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
            actionable = horizon == "weekly" and variant in {"legacy_ta_simple", "expanded_ta_simple"}
            rank = (2, 70.0 if variant == "expanded_ta_simple" else 60.0, 0.01, 0.02) if actionable else None
            evidence = {
                "decision_edge_cost_bps": 33.0, "n": 40,
                "edge_score": rank[1] if rank else None, "expected_return_net": 0.02,
                "action_expected_return_net": 0.02,
                "action_expected_return_net_ci_lower": 0.01, "hit_ci_lower": 0.55,
                "proven_edge_net": bool(actionable), "gates": {"n": True},
                "mc_luck_pvalue_net_adj": 0.01, "label_shuffle_pvalue_net_adj": 0.01,
                "freshness_status": "pass",
            }
            opportunity = HistoricalOpportunity(
                decision_date=as_of.date().isoformat(), symbol="AAA", horizon=horizon,
                variant=variant, direction="long", rank=rank or (), bucket="strong_buy",
                training_end="2024-02-29", selection_sample_end="2024-02-29", proof_sample_end="2024-02-29",
                provenance=evidence,
            ) if actionable else None
            result = AsOfDecision(
                status="evaluated", signal_direction="long" if actionable else "neutral",
                category_scores={key: 1.0 for key in ("tendance", "momentum", "oscillation", "volume")},
                aggregate_score=80.0 if actionable else 0.0, bucket="strong_buy" if actionable else "hold",
                actionable=actionable, actionability_reasons=[] if actionable else ["neutral_bucket"],
                rank=rank, evidence=evidence,
                selection_cutoff="2024-02-29", proof_cutoff="2024-02-29",
                selection_observations=(), opportunity=opportunity, computation_rejection_reasons=[],
            )
            return [("AAA", result)]
        return select

    monkeypatch.setattr("services.api.app.db._ensure_session_factory", lambda: Session)
    monkeypatch.setattr(worker, "_load_inputs", lambda _db, _config: ({"AAA": prices}, {}))
    monkeypatch.setattr(
        worker, "_load_weekly_masi_calendar",
        lambda _db, config: worker.weekly_decision_dates(prices.index, config["start_date"], config["end_date"]),
    )
    monkeypatch.setattr(worker, "_build_selector", fake_selector)
    worker.materialize_historical_opportunities(str(run_id))

    verify = Session()
    run = verify.query(models.HistoricalOpportunityMaterializationRun).filter_by(id=run_id).one()
    rows = verify.query(models.HistoricalTradeOpportunity).all()
    assert run.status == "succeeded", run.error_message
    assert len(rows) == 24
    assert not any(row.accepted for row in rows)
    assert [row.variant for row in rows if row.reconstructed_dashboard_winner] == ["expanded_ta_simple"]
    assert run.coverage_json["decision_date_count"] == 1
    verify.close()


def test_pit_selector_ranks_candidates_by_point_in_time_edge_score(monkeypatch) -> None:
    index = pd.bdate_range("2023-01-02", periods=90)
    frame = pd.DataFrame(
        {
            "Open": 100.0 + pd.Series(range(len(index)), index=index) * 0.2,
            "Close": 100.1 + pd.Series(range(len(index)), index=index) * 0.2,
            "Volume": 1_000_000.0,
        },
        index=index,
    )
    scores = pd.Series(80.0, index=index)
    captured: dict = {}

    def fake_edge_payload(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            n=40,
            expected_return_net=0.02,
            expected_return_net_ci_lower=0.01,
            action_expected_return_net=0.02,
            action_expected_return_net_ci_lower=0.01,
            edge_score=82.5,
            proven_edge_net=True,
            exit_lag_bars=5,
            entry_price_kind="open",
            exit_price_kind="open",
            proof_window_end=index[-10],
            selection_n=45,
            proof_n=40,
            hit_ci_lower=0.56,
            edge_score_components={"sample_n": 66.67, "freshness": 80.0},
            mc_luck_pvalue_net_adj=0.02,
            label_shuffle_pvalue_net_adj=0.03,
            freshness_status="passed",
            gates={"n": True},
            return_calc_method="open_to_exit_ladder",
            methodology_version="edge-v2",
            selection_window_end=index[-20],
            entry_lag_bars=1,
        )

    monkeypatch.setattr("core.quant_core.signal_ranking.build_edge_payload", fake_edge_payload)
    selector = worker._build_selector(
        {("AAA", "expanded_ta_simple"): {key: scores for key in ("tendance", "momentum", "oscillation", "volume")}},
        {"cost_bps_per_side": 33.0, "slippage_bps_per_side": 5.0, "edge_mc_iterations": 250},
    )

    opportunities = selector(index[-1], "weekly", "expanded_ta_simple", {"AAA": frame})

    assert len(opportunities) == 1
    _symbol, decision = opportunities[0]
    opportunity = decision.opportunity
    assert opportunity is not None
    assert opportunity.rank == (2.0, 82.5, 0.01, 0.02)
    assert opportunity.provenance["edge_score"] == 82.5
    assert opportunity.provenance["edge_methodology_version"] == "edge-v2"
    assert captured["selection_oos_sample"].dates.max() <= captured["oos_sample"].dates.max()
    assert captured["cost_bps_per_side"] == 33.0
    assert captured["multiple_testing_count"] == 8


def test_pit_selector_retains_low_edge_and_short_candidates(monkeypatch) -> None:
    index = pd.bdate_range("2023-01-02", periods=90)
    frame = pd.DataFrame(
        {"Open": 100.0, "Close": 100.0, "Volume": 1_000_000.0}, index=index,
    )
    metrics = SimpleNamespace(
        n=40, action_expected_return_net=0.02, action_expected_return_net_ci_lower=0.01,
        edge_score=49.99, proven_edge_net=True, exit_lag_bars=5,
        entry_price_kind="open", exit_price_kind="open", proof_window_end=index[-10],
        selection_n=45, proof_n=40, hit_ci_lower=0.56, edge_score_components={},
        mc_luck_pvalue_net_adj=0.02, label_shuffle_pvalue_net_adj=0.03,
        freshness_status="passed",
    )
    metrics.expected_return_net = 0.02
    metrics.expected_return_net_ci_lower = 0.01
    metrics.gates = {"n": True}
    metrics.return_calc_method = "open_to_exit_ladder"
    metrics.methodology_version = "edge-v2"
    metrics.selection_window_end = index[-20]
    metrics.entry_lag_bars = 1
    monkeypatch.setattr("core.quant_core.signal_ranking.build_edge_payload", lambda **_kwargs: metrics)
    selector = worker._build_selector(
        {
            ("LOW", "expanded_ta_simple"): {key: pd.Series(80.0, index=index) for key in ("tendance", "momentum", "oscillation", "volume")},
            ("SHORT", "expanded_ta_simple"): {key: pd.Series(-80.0, index=index) for key in ("tendance", "momentum", "oscillation", "volume")},
        },
        {},
    )

    opportunities = selector(index[-1], "weekly", "expanded_ta_simple", {"LOW": frame, "SHORT": frame})
    assert [item[0] for item in opportunities] == ["LOW", "SHORT"]
    assert opportunities[0][1].opportunity.provenance["edge_score"] == 49.99
    assert opportunities[1][1].opportunity.direction == "short"


def _winner_decision(opportunity, *, gate_pass=True):
    return {
        "decision_date": opportunity.decision_date,
        "symbol": opportunity.symbol,
        "horizon": opportunity.horizon,
        "winner_variant": opportunity.variant,
        "signal_direction": opportunity.direction,
        "actionable": True,
        "execution_eligible": opportunity.direction == "long",
        "input_hash": opportunity.direction * 8,
        "opportunity": opportunity,
        "gate_pass": gate_pass,
    }


def test_winning_short_liquidates_matching_long_gate_free_without_reversal() -> None:
    index = pd.bdate_range("2024-01-01", periods=45)
    prices = pd.DataFrame({
        "Open": 100.0, "High": 102.0, "Low": 98.0, "Close": 101.0, "Volume": 1_000_000.0,
    }, index=index)
    observations = tuple(
        SelectionObservation((index[i]).date().isoformat(), value)
        for i, value in zip((5, 8, 11), (0.02, 0.03, 0.01))
    )
    long = HistoricalOpportunity(
        decision_date=index[20].date().isoformat(), symbol="AAA", horizon="monthly",
        variant="expanded_ta_simple", direction="long", bucket="strong_buy", rank=(1,),
        training_end=index[19].date().isoformat(), selection_sample_end=index[19].date().isoformat(),
        proof_sample_end=index[19].date().isoformat(), exit_lag_bars=15,
        selection_observations=observations,
    )
    short = HistoricalOpportunity(
        decision_date=index[24].date().isoformat(), symbol="AAA", horizon="monthly",
        variant="legacy_ta_simple", direction="short", bucket="strong_sell", rank=(1,),
        training_end=index[23].date().isoformat(), selection_sample_end=index[23].date().isoformat(),
        proof_sample_end=index[23].date().isoformat(), exit_lag_bars=15,
        selection_observations=observations,
    )
    result = worker._simulate_winner_sleeve(
        [_winner_decision(long), _winner_decision(short, gate_pass=False)],
        {"AAA": prices}, PortfolioBacktestConfig(bootstrap_samples=100), horizon="monthly",
    )
    assert len(result["trades"]) == 1
    assert result["trades"][0]["kelly_fraction"] > 0
    assert result["trades"][0]["exit_reason"] == "short_signal_liquidation"
    assert result["trades"][0]["exit_date"] == index[25].date().isoformat()
    exits = [event for event in result["execution_events"] if event["execution_action"] == "exit_long"]
    assert len(exits) == 1
    assert exits[0]["reason"] == "short_signal_liquidation"
    assert exits[0]["position_after"] == "flat"
    assert result["liquidations"][0]["horizon"] == "monthly"
    assert result["liquidations"][0]["equity_at_fill"] > 0
    assert result["liquidations"][0]["exposure_reduction_pct_of_equity_at_fill"] > 0
    assert result["equity_curve"][-1]["equity"] == pytest.approx(
        100_000.0 + result["trades"][0]["realized_pnl"]
    )


def test_nonfinite_entry_open_is_rejected_without_poisoning_weekly_equity() -> None:
    index = pd.bdate_range("2024-01-01", periods=35)
    prices = pd.DataFrame({
        "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1_000_000.0,
    }, index=index)
    prices.loc[index[21], ["Open", "High", "Low"]] = float("nan")
    prices.loc[index[21], "Volume"] = 0.0
    observations = tuple(SelectionObservation(index[i].date().isoformat(), 0.02) for i in (3, 5, 7))
    opportunity = HistoricalOpportunity(
        decision_date=index[20].date().isoformat(), symbol="AAA", horizon="weekly",
        variant="expanded_ta_simple", direction="long", bucket="strong_buy",
        training_end=index[19].date().isoformat(), selection_sample_end=index[19].date().isoformat(),
        proof_sample_end=index[19].date().isoformat(), selection_observations=observations,
    )

    result = worker._simulate_winner_sleeve(
        [_winner_decision(opportunity)], {"AAA": prices},
        PortfolioBacktestConfig(bootstrap_samples=100), horizon="weekly",
    )

    assert result["trades"] == []
    assert result["rejected_trades"] == [{
        "decision_date": opportunity.decision_date, "symbol": "AAA", "reason": "invalid_entry_open",
    }]
    assert result["execution_events"][0]["fill_price"] is None
    assert result["statistics"]["absolute_return"] == pytest.approx(0.0)
    assert all(pd.notna(point["equity"]) for point in result["equity_curve"])


def test_scheduled_exit_waits_for_next_finite_open() -> None:
    index = pd.bdate_range("2024-01-01", periods=35)
    prices = pd.DataFrame({
        "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1_000_000.0,
    }, index=index)
    prices.loc[index[25], ["Open", "High", "Low"]] = float("nan")
    prices.loc[index[25], "Volume"] = 0.0
    observations = tuple(SelectionObservation(index[i].date().isoformat(), 0.02) for i in (3, 5, 7))
    opportunity = HistoricalOpportunity(
        decision_date=index[20].date().isoformat(), symbol="AAA", horizon="weekly",
        variant="expanded_ta_simple", direction="long", bucket="strong_buy", exit_lag_bars=5,
        training_end=index[19].date().isoformat(), selection_sample_end=index[19].date().isoformat(),
        proof_sample_end=index[19].date().isoformat(), selection_observations=observations,
    )

    result = worker._simulate_winner_sleeve(
        [_winner_decision(opportunity)], {"AAA": prices},
        PortfolioBacktestConfig(bootstrap_samples=100), horizon="weekly",
    )

    assert len(result["trades"]) == 1
    assert result["trades"][0]["exit_date"] == index[26].date().isoformat()
    assert result["trades"][0]["entry_price"] == pytest.approx(100.0)
    assert result["trades"][0]["kelly_fraction"] > 0


def test_flat_short_and_gate_veto_never_promote_or_open_position() -> None:
    index = pd.bdate_range("2024-01-01", periods=35)
    prices = pd.DataFrame({
        "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1_000_000.0,
    }, index=index)
    observations = tuple(SelectionObservation(index[i].date().isoformat(), 0.02) for i in (3, 5, 7))
    short = HistoricalOpportunity(
        decision_date=index[20].date().isoformat(), symbol="AAA", horizon="weekly",
        variant="expanded_ta_simple", direction="short", bucket="sell",
        training_end=index[19].date().isoformat(), selection_sample_end=index[19].date().isoformat(),
        proof_sample_end=index[19].date().isoformat(), selection_observations=observations,
    )
    result = worker._simulate_winner_sleeve(
        [_winner_decision(short, gate_pass=False)], {"AAA": prices},
        PortfolioBacktestConfig(bootstrap_samples=100), horizon="weekly",
    )
    assert result["trades"] == []
    assert result["execution_events"][0]["reason"] == "short_entry_not_supported_masi"
