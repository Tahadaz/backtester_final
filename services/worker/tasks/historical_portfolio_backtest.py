"""Persisted background execution for the historical opportunity portfolio."""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
import math
from uuid import UUID
from typing import Any

import numpy as np
import pandas as pd

from core.quant_core.historical_portfolio import (
    CAPACITY_SCENARIOS,
    DECISION_HORIZONS,
    METHODOLOGY_VERSION,
    HistoricalOpportunity,
    PortfolioBacktestConfig,
    SelectionObservation,
    benchmark_curves,
    combine_sleeves_equal_risk,
    nested_capacity_frontier,
    provenance_hash,
    simulate_sleeve,
    snapshot_audit,
    stationary_bootstrap_drawdown_risk,
    weekly_decision_dates,
)
from core.quant_core.horizons import HORIZON_SPECS
from core.quant_core.research.score_history import _bucket_for
from core.quant_core.research.stats.hit_rate import wilson_ci
from core.quant_core.signal_engine.modes import TECHNICAL_SIGNAL_MODE_NAMES, signal_mode_read_names


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _price_col(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out.index = pd.DatetimeIndex(out.index)
    if out.index.tz is not None:
        out.index = out.index.tz_convert(None)
    out.index = out.index.normalize()
    return out[~out.index.duplicated(keep="last")].sort_index()


def _direction(bucket: str) -> str | None:
    if bucket in {"buy", "strong_buy"}:
        return "long"
    if bucket in {"sell", "strong_sell"}:
        return "short"
    return None


def _trade_observation(
    frame: pd.DataFrame, decision: pd.Timestamp, direction: str, exit_lag: int,
    cost_bps: float, slippage_bps: float,
) -> SelectionObservation | None:
    loc = int(frame.index.searchsorted(decision, side="right")) - 1
    entry_pos, exit_pos = loc + 1, loc + int(exit_lag)
    if loc < 0 or entry_pos >= len(frame) or exit_pos >= len(frame):
        return None
    open_col = _price_col(frame, ("Open", "open"))
    if open_col is None:
        return None
    entry = float(frame.iloc[entry_pos][open_col])
    exit_price = float(frame.iloc[exit_pos][open_col])
    if not np.isfinite(entry) or not np.isfinite(exit_price) or entry <= 0:
        return None
    gross = (exit_price / entry - 1.0) * (1.0 if direction == "long" else -1.0)
    net = gross - 2.0 * (float(cost_bps) + float(slippage_bps)) * 1e-4
    return SelectionObservation(frame.index[exit_pos].date().isoformat(), float(net))


def _bootstrap_lower(values: list[float], seed: int) -> float | None:
    if len(values) < 2:
        return None
    rng = np.random.default_rng(seed)
    array = np.asarray(values, dtype=float)
    means = np.mean(rng.choice(array, size=(500, len(array)), replace=True), axis=1)
    return float(np.quantile(means, 0.025))


def _build_selector(score_series: dict[tuple[str, str], dict[str, pd.Series]], config: dict[str, Any]):
    cost_bps = float(config.get("cost_bps_per_side", 33.0))
    slippage_bps = float(config.get("slippage_bps_per_side", 5.0))
    seed = int(config.get("bootstrap_seed", 5107))

    def selector(as_of: pd.Timestamp, horizon: str, variant: str, market: dict[str, pd.DataFrame]):
        candidates: list[HistoricalOpportunity] = []
        for symbol, frame in market.items():
            categories = score_series.get((symbol, variant), {})
            if not categories:
                continue
            historical = [series.loc[series.index <= as_of].rename(category) for category, series in categories.items()]
            if not historical:
                continue
            aggregate = pd.concat(historical, axis=1).mean(axis=1).dropna()
            if aggregate.empty or aggregate.index[-1] != as_of:
                # Weekly decisions are after that day's close; no stale carry-forward
                # is silently turned into an opportunity.
                continue
            bucket = _bucket_for(float(aggregate.iloc[-1]))
            direction = _direction(bucket)
            if direction is None:
                continue
            spec = HORIZON_SPECS[horizon]
            mode_rows: list[tuple[int, list[SelectionObservation], list[SelectionObservation]]] = []
            for exit_lag in spec.forward_grid_days:
                observations: list[SelectionObservation] = []
                for signal_date, score in aggregate.iloc[:-1].items():
                    past_bucket = _bucket_for(float(score))
                    if _direction(past_bucket) != direction or past_bucket != bucket:
                        continue
                    observation = _trade_observation(frame, signal_date, direction, exit_lag, cost_bps, slippage_bps)
                    if observation is not None and pd.Timestamp(observation.exit_date) < as_of:
                        observations.append(observation)
                split = max(1, len(observations) // 2)
                mode_rows.append((exit_lag, observations[:split], observations[split:]))
            viable = [row for row in mode_rows if len(row[1]) >= 3]
            if not viable:
                continue
            # Holding period is selected on the earlier sample only.
            exit_lag, selection, proof = max(
                viable, key=lambda row: (float(np.mean([x.net_return for x in row[1]])), -row[0])
            )
            proof_returns = [row.net_return for row in proof]
            n = len(proof_returns)
            if n < 30:
                continue
            expected = float(np.mean(proof_returns))
            if expected <= 0:
                continue
            lower = _bootstrap_lower(proof_returns, seed + exit_lag)
            hits = sum(value > 0 for value in proof_returns)
            hit_lower, _ = wilson_ci(hits, n)
            proven = bool(lower is not None and lower > 0 and hit_lower is not None and hit_lower > 0.5)
            training_end = aggregate.index[-2].date().isoformat() if len(aggregate) >= 2 else None
            known = tuple(selection + proof)
            sample_end = max((row.exit_date for row in known), default=None)
            candidates.append(HistoricalOpportunity(
                decision_date=as_of.date().isoformat(), symbol=symbol, horizon=horizon,
                variant=variant, direction=direction, bucket=bucket,
                rank=(2.0 if proven else 1.0, lower if lower is not None else expected * 0.5, expected),
                training_end=training_end, selection_sample_end=sample_end,
                proof_sample_end=max((row.exit_date for row in proof), default=None),
                entry_lag_bars=1, exit_lag_bars=int(exit_lag),
                entry_price_kind="open", exit_price_kind="open",
                selection_observations=known,
                provenance={
                    "source": "persisted_fold_scoped_wfo_oos_score_history", "is_oos_required": True,
                    "variant": variant, "all_mode_count": len(TECHNICAL_SIGNAL_MODE_NAMES),
                    "selection_n": len(selection), "proof_n": n,
                    "expected_return_net": expected, "ci_lower_net": lower,
                    "hit_ci_lower": hit_lower, "proven_edge_net": proven,
                    "score_history_end": as_of.date().isoformat(),
                    "ranking_contract": "dashboard _best_signal_rank tuple",
                },
            ))
        return candidates

    return selector


def _load_inputs(db, config: dict[str, Any]):
    from services.api.app import models
    from services.api.app.market_data_loader import load_ohlcv_for_symbol

    requested = list(config.get("symbols") or [])
    query = db.query(models.SignalScoreHistory.symbol).filter(models.SignalScoreHistory.is_oos.is_(True)).distinct()
    symbols = sorted({row[0].upper() for row in query.all()})
    if requested:
        symbols = [symbol for symbol in symbols if symbol in set(requested)]
    prices: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            frame = _clean_frame(load_ohlcv_for_symbol(db, symbol))
            if not frame.empty:
                prices[symbol] = frame
        except Exception:
            continue

    score_series: dict[tuple[str, str], dict[str, pd.Series]] = {}
    for symbol in prices:
        for variant in TECHNICAL_SIGNAL_MODE_NAMES:
            sources = tuple(f"wfo:{name}" for name in signal_mode_read_names(variant))
            if variant == "expanded_ta_simple":
                sources = (*sources, "wfo")
            rows = db.query(models.SignalScoreHistory).filter(
                models.SignalScoreHistory.symbol == symbol,
                models.SignalScoreHistory.source.in_(sources),
                models.SignalScoreHistory.is_oos.is_(True),
                models.SignalScoreHistory.horizon.in_(DECISION_HORIZONS),
            ).order_by(models.SignalScoreHistory.date.asc()).all()
            by_category: dict[str, dict[pd.Timestamp, float]] = {}
            for row in rows:
                # Horizon-specific rows are loaded later by the selector's closure
                # through distinct variant keys; preserve horizon in category key.
                by_category.setdefault(f"{row.horizon}:{row.category}", {})[pd.Timestamp(row.date)] = float(row.score_pct)
            # Split is done here to avoid mixing horizon series.
            for horizon in DECISION_HORIZONS:
                selected = {
                    key.split(":", 1)[1]: pd.Series(values).sort_index()
                    for key, values in by_category.items() if key.startswith(f"{horizon}:")
                }
                if selected:
                    score_series[(f"{symbol}|{horizon}", variant)] = selected
    return prices, score_series


def _load_prices(db, symbols: list[str]) -> dict[str, pd.DataFrame]:
    from services.api.app.market_data_loader import load_ohlcv_for_symbol

    prices: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            frame = _clean_frame(load_ohlcv_for_symbol(db, symbol))
            if not frame.empty:
                prices[symbol] = frame
        except Exception:
            continue
    return prices


def _opportunity_from_json(payload: dict[str, Any]) -> HistoricalOpportunity:
    raw = dict(payload)
    raw["rank"] = tuple(raw.get("rank") or ())
    raw["selection_observations"] = tuple(
        SelectionObservation(**item) for item in (raw.get("selection_observations") or [])
    )
    return HistoricalOpportunity(**raw)


def materialize_historical_opportunities(materialization_run_id: str) -> None:
    """Build PIT candidates once and replace only the requested date/symbol slice."""

    from services.api.app import models
    from services.api.app.db import _ensure_session_factory

    Session = _ensure_session_factory()
    db = Session()
    run = None
    try:
        run = db.query(models.HistoricalOpportunityMaterializationRun).filter_by(
            id=UUID(materialization_run_id)
        ).with_for_update().first()
        if run is None or run.status not in {"queued", "running"}:
            return
        run.status = "running"
        run.started_at = _utcnow()
        run.progress_json = {"stage": "loading_fold_scoped_oos_history", "progress_pct": 1}
        db.commit()

        config = dict(run.config_json or {})
        prices, raw_scores = _load_inputs(db, config)
        if not prices:
            raise ValueError("No market data with fold-scoped is_oos WFO history is available")
        dates = weekly_decision_dates(
            sorted({value for frame in prices.values() for value in frame.index}),
            config["start_date"], config["end_date"],
        )
        selectors = {}
        for horizon in DECISION_HORIZONS:
            keyed = {
                (symbol, mode): raw_scores.get((f"{symbol}|{horizon}", mode), {})
                for symbol in prices for mode in TECHNICAL_SIGNAL_MODE_NAMES
            }
            selectors[horizon] = _build_selector(keyed, config)

        candidates: list[HistoricalOpportunity] = []
        total = max(1, len(dates) * len(DECISION_HORIZONS) * len(TECHNICAL_SIGNAL_MODE_NAMES))
        completed = 0
        for decision in dates:
            sliced = {symbol: frame.loc[frame.index <= decision].copy() for symbol, frame in prices.items()}
            for horizon in DECISION_HORIZONS:
                for variant in TECHNICAL_SIGNAL_MODE_NAMES:
                    candidates.extend(selectors[horizon](decision, horizon, variant, sliced))
                    completed += 1
            if completed % 96 == 0:
                run.progress_json = {
                    "stage": "evaluating_point_in_time_candidates",
                    "progress_pct": min(90, round(completed / total * 90)),
                    "decision_dates_completed": int(completed / (len(DECISION_HORIZONS) * len(TECHNICAL_SIGNAL_MODE_NAMES))),
                    "decision_dates_total": len(dates),
                }
                db.commit()

        accepted_keys: set[tuple[str, str, str, str]] = set()
        best: dict[tuple[str, str, str], HistoricalOpportunity] = {}
        for item in candidates:
            key = (item.decision_date, item.symbol.upper(), item.horizon)
            previous = best.get(key)
            if previous is None or tuple(item.rank) > tuple(previous.rank):
                best[key] = item
        for item in best.values():
            accepted_keys.add((item.decision_date, item.symbol.upper(), item.horizon, item.variant))

        start = pd.Timestamp(config["start_date"]).date()
        end = pd.Timestamp(config["end_date"]).date()
        delete_query = db.query(models.HistoricalTradeOpportunity).filter(
            models.HistoricalTradeOpportunity.decision_date >= start,
            models.HistoricalTradeOpportunity.decision_date <= end,
        )
        requested_symbols = list(config.get("symbols") or [])
        if requested_symbols:
            delete_query = delete_query.filter(models.HistoricalTradeOpportunity.symbol.in_(requested_symbols))
        delete_query.delete(synchronize_session=False)
        db.flush()

        for item in candidates:
            payload = asdict(item)
            key = (item.decision_date, item.symbol.upper(), item.horizon, item.variant)
            db.add(models.HistoricalTradeOpportunity(
                decision_date=pd.Timestamp(item.decision_date).date(),
                symbol=item.symbol.upper(), horizon=item.horizon, variant=item.variant,
                accepted=key in accepted_keys, rank_json=list(item.rank), opportunity_json=payload,
                input_hash=provenance_hash(payload), materialization_run_id=run.id,
            ))
        run.status = "succeeded"
        run.completed_at = _utcnow()
        run.progress_json = {
            "stage": "completed", "progress_pct": 100,
            "candidate_count": len(candidates), "accepted_count": len(accepted_keys),
        }
        run.coverage_json = {
            "start": start.isoformat(), "end": end.isoformat(),
            "symbols": sorted(prices), "decision_date_count": len(dates),
            "horizons": list(DECISION_HORIZONS), "variants": list(TECHNICAL_SIGNAL_MODE_NAMES),
        }
        db.commit()
    except Exception as exc:
        db.rollback()
        if run is None:
            run = db.query(models.HistoricalOpportunityMaterializationRun).filter_by(
                id=UUID(materialization_run_id)
            ).first()
        if run is not None:
            run.status = "failed"
            run.error_message = str(exc)[:4000]
            run.completed_at = _utcnow()
            run.progress_json = {"stage": "failed", "progress_pct": (run.progress_json or {}).get("progress_pct", 0)}
            db.commit()
    finally:
        db.close()


def execute_historical_portfolio_backtest(run_id: str) -> None:
    from services.api.app import models
    from services.api.app.db import _ensure_session_factory
    from services.api.app.market_data_loader import load_ohlcv_for_symbol

    Session = _ensure_session_factory()
    db = Session()
    row = None
    try:
        row = db.query(models.HistoricalPortfolioBacktestRun).filter_by(id=UUID(run_id)).with_for_update().first()
        if row is None:
            return
        if row.status not in {"queued", "running"}:
            return
        row.status = "running"
        row.started_at = _utcnow()
        row.error_message = None
        row.diagnostics_json = {"stage": "loading_materialized_pit_opportunities", "progress_pct": 5}
        db.commit()

        config = dict(row.config_json or {})
        from services.api.app.services.historical_opportunity_store import opportunity_store_coverage
        coverage = opportunity_store_coverage(db, config)
        if not coverage["available"]:
            raise ValueError("PIT opportunity store does not cover the requested period; materialize it first")
        start = pd.Timestamp(config["start_date"]).date()
        end = pd.Timestamp(config["end_date"]).date()
        store_query = db.query(models.HistoricalTradeOpportunity).filter(
            models.HistoricalTradeOpportunity.decision_date >= start,
            models.HistoricalTradeOpportunity.decision_date <= end,
        )
        requested_symbols = list(config.get("symbols") or [])
        if requested_symbols:
            store_query = store_query.filter(models.HistoricalTradeOpportunity.symbol.in_(requested_symbols))
        stored_rows = store_query.all()
        opportunities = [
            _opportunity_from_json(item.opportunity_json)
            for item in stored_rows if item.accepted
        ]
        candidate_lookup = {
            (item.decision_date.isoformat(), item.horizon, item.symbol.upper(), item.variant):
                _opportunity_from_json(item.opportunity_json)
            for item in stored_rows
        }
        symbols = sorted({item.symbol.upper() for item in stored_rows})
        prices = _load_prices(db, symbols)
        if not prices:
            raise ValueError("Market data for materialized PIT opportunities is unavailable")
        row.diagnostics_json = {
            "stage": "simulating_stored_opportunities", "progress_pct": 15,
            "stored_candidate_count": len(stored_rows), "accepted_opportunity_count": len(opportunities),
        }
        db.commit()

        all_scenarios: dict[str, Any] = {}
        capacity_returns: dict[float, pd.Series] = {}
        for scenario_idx, cap in enumerate(CAPACITY_SCENARIOS):
            engine_config = PortfolioBacktestConfig(
                initial_capital=float(config.get("initial_capital", 100_000.0)),
                cost_bps_per_side=float(config.get("cost_bps_per_side", 33.0)),
                slippage_bps_per_side=float(config.get("slippage_bps_per_side", 5.0)),
                half_kelly_multiplier=float(config.get("half_kelly_multiplier", 0.5)),
                max_position_fraction=float(config.get("max_position_fraction", 0.25)),
                capacity_fraction=cap, allow_partial_fills=bool(config.get("allow_partial_fills", True)),
                bootstrap_seed=int(config.get("bootstrap_seed", 5107)),
                bootstrap_samples=int(config.get("bootstrap_samples", 1000)),
            )
            sleeves = {horizon: simulate_sleeve(opportunities, prices, engine_config, horizon=horizon) for horizon in DECISION_HORIZONS}
            combined = combine_sleeves_equal_risk(sleeves, engine_config.initial_capital)
            daily = pd.Series(dtype=float)
            if combined["equity_curve"]:
                combined_frame = pd.DataFrame(combined["equity_curve"])
                daily = combined_frame.set_index(pd.to_datetime(combined_frame["date"]))["equity"].pct_change().dropna()
                combined["risk_appetite"] = stationary_bootstrap_drawdown_risk(
                    daily, seed=engine_config.bootstrap_seed,
                    samples=engine_config.bootstrap_samples, mean_block=engine_config.bootstrap_mean_block,
                )
            capacity_returns[cap] = daily
            all_scenarios[str(cap)] = {"sleeves": sleeves, "combined": combined}
            row.diagnostics_json = {"stage": "simulating_capacity_scenarios", "progress_pct": 35 + scenario_idx * 10}
            db.commit()

        selected_key = str(float(config.get("capacity_fraction", 0.01)))
        selected = all_scenarios[selected_key]
        selected_config = replace(engine_config, capacity_fraction=float(config.get("capacity_fraction", 0.01)))
        masi = pd.Series(dtype=float)
        try:
            masi_frame = _clean_frame(load_ohlcv_for_symbol(db, "MASI", "1D"))
            close_col = _price_col(masi_frame, ("Close", "close", "Adj Close"))
            if close_col:
                masi = masi_frame[close_col]
        except Exception:
            pass
        benchmarks = benchmark_curves(selected["combined"]["equity_curve"], masi)
        combined_stats = dict(selected["combined"].get("statistics", {}))
        if benchmarks.get("available"):
            full_return = benchmarks["full_investment_masi"]["total_return"]
            matched_return = benchmarks["exposure_matched_masi"]["total_return"]
            strategy_return = combined_stats.get("absolute_return")
            combined_stats.update({
                "full_investment_masi_return": full_return,
                "exposure_matched_masi_return": matched_return,
                "excess_return_vs_full_investment_masi": (
                    float(strategy_return) - float(full_return) if strategy_return is not None else None
                ),
                "excess_return_vs_exposure_matched_masi": (
                    float(strategy_return) - float(matched_return) if strategy_return is not None else None
                ),
            })

        snapshots = db.query(models.DashboardSnapshot).filter(
            models.DashboardSnapshot.as_of_date >= pd.Timestamp(config["start_date"]).date(),
            models.DashboardSnapshot.as_of_date <= pd.Timestamp(config["end_date"]).date(),
        ).order_by(models.DashboardSnapshot.as_of_date.asc()).all()
        audit = snapshot_audit(opportunities, [{
            "as_of_date": item.as_of_date, "horizon": item.horizon, "payload_jsonb": item.payload_jsonb,
        } for item in snapshots])
        literal_opportunities: list[HistoricalOpportunity] = []
        literal_unavailable: list[dict[str, Any]] = []
        for snapshot in snapshots:
            payload = snapshot.payload_jsonb if isinstance(snapshot.payload_jsonb, dict) else {}
            stocks = payload.get("stocks") if isinstance(payload.get("stocks"), list) else []
            for stock in stocks:
                best = stock.get("best_signal") if isinstance(stock, dict) else None
                symbol = str(stock.get("symbol") or "").strip().upper() if isinstance(stock, dict) else ""
                variant = str(best.get("variant") or "").strip() if isinstance(best, dict) else ""
                if not symbol or variant not in TECHNICAL_SIGNAL_MODE_NAMES:
                    continue
                candidate = candidate_lookup.get((snapshot.as_of_date.isoformat(), snapshot.horizon, symbol, variant))
                if candidate is None:
                    literal_unavailable.append({
                        "as_of_date": snapshot.as_of_date.isoformat(), "horizon": snapshot.horizon,
                        "symbol": symbol, "variant": variant,
                        "reason": "point_in_time_selection_sample_unavailable",
                    })
                    continue
                direction = str(best.get("direction") or candidate.direction).strip().lower()
                if direction not in {"long", "short"}:
                    continue
                literal_opportunities.append(HistoricalOpportunity(
                    **{
                        **candidate.__dict__,
                        "direction": direction,
                        "bucket": str(best.get("bucket") or candidate.bucket),
                        "entry_lag_bars": int(best.get("entry_lag_bars") or candidate.entry_lag_bars),
                        "exit_lag_bars": int(best.get("exit_lag_bars") or candidate.exit_lag_bars),
                        "entry_price_kind": str(best.get("entry_price_kind") or candidate.entry_price_kind),
                        "exit_price_kind": str(best.get("exit_price_kind") or candidate.exit_price_kind),
                        "provenance": {
                            **dict(candidate.provenance),
                            "literal_dashboard_snapshot": True,
                            "snapshot_as_of_date": snapshot.as_of_date.isoformat(),
                            "snapshot_computed_at": snapshot.computed_at.isoformat() if snapshot.computed_at else None,
                        },
                    }
                ))
        literal_sleeves = {
            horizon: simulate_sleeve(literal_opportunities, prices, selected_config, horizon=horizon)
            for horizon in DECISION_HORIZONS
        }
        audit["portfolio"] = {
            "sleeves": literal_sleeves,
            "combined": combine_sleeves_equal_risk(literal_sleeves, selected_config.initial_capital),
            "opportunity_count": len(literal_opportunities),
            "unavailable_opportunities": literal_unavailable,
            "fills": "modeled_no_historical_fill_dataset",
        }

        risk_limit = 0.25
        frontier = nested_capacity_frontier(
            capacity_returns, risk_limit=risk_limit,
            seed=int(config.get("bootstrap_seed", 5107)),
        )
        opportunity_payload = [asdict(item) for item in opportunities]
        provenance = {
            "methodology_version": METHODOLOGY_VERSION,
            "signal_modes": list(TECHNICAL_SIGNAL_MODE_NAMES),
            "source": "persisted fold-scoped WFO out-of-sample score history; current WfoGlobalSignal and SignalBestEvidenceSnapshot rows are not read",
            "score_history_requires_is_oos": True,
            "data_symbols": sorted(prices),
            "coverage_start": coverage["requested_start"],
            "coverage_end": coverage["requested_end"],
            "opportunity_store_materialization_runs": coverage["materialization_run_ids"],
            "input_hash": provenance_hash({"config": config, "opportunities": opportunity_payload}),
        }
        validation = {
            "all_eight_variants_evaluated": list(TECHNICAL_SIGNAL_MODE_NAMES),
            "cutoffs_precede_decision": all(
                (item.training_end is None or item.training_end < item.decision_date)
                and (item.selection_sample_end is None or item.selection_sample_end < item.decision_date)
                for item in opportunities
            ),
            "modeled_fills": True,
            "capacity_scenarios": list(CAPACITY_SCENARIOS),
            "nested_oos_capacity_frontier": frontier,
        }
        trades = [trade for sleeve in selected["sleeves"].values() for trade in sleeve["trades"]]
        warnings = [
            "Fills are modeled because no historical fill dataset exists.",
            "DashboardSnapshot coverage is short and the literal audit is not statistically equivalent to the reconstruction.",
        ]
        if not audit["snapshot_dates"]:
            warnings.append("No DashboardSnapshot rows existed in the requested period; literal audit unavailable.")
        if not benchmarks.get("available"):
            warnings.append("MASI benchmark unavailable or has insufficient overlap.")

        row.provenance_json = provenance
        row.diagnostics_json = {"stage": "completed", "progress_pct": 100, "opportunity_count": len(opportunities), "trade_count": len(trades)}
        row.opportunities_json = opportunity_payload
        row.trades_json = trades
        row.equity_curves_json = all_scenarios
        row.benchmark_curves_json = benchmarks
        row.statistics_json = {
            "selected_capacity_fraction": float(config.get("capacity_fraction", 0.01)),
            "sleeves": {key: value["statistics"] for key, value in selected["sleeves"].items()},
            "combined": combined_stats,
            "risk_appetite": selected["combined"].get("risk_appetite", {}),
        }
        row.validation_json = validation
        row.snapshot_audit_json = audit
        row.warnings_json = warnings
        row.status = "succeeded"
        row.completed_at = _utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        if row is None:
            row = db.query(models.HistoricalPortfolioBacktestRun).filter_by(id=UUID(run_id)).first()
        if row is not None:
            row.status = "failed"
            row.error_message = str(exc)[:4000]
            row.completed_at = _utcnow()
            row.diagnostics_json = {"stage": "failed", "progress_pct": (row.diagnostics_json or {}).get("progress_pct", 0)}
            db.commit()
    finally:
        db.close()
