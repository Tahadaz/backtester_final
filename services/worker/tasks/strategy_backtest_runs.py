from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from redis import Redis

from services.worker.db import SessionLocal
from services.api.app.config import settings
from services.api.app.market_data_loader import load_ohlcv_for_symbol
from services.api.app.json_sanitize import sanitize_json_compatible
from services.api.app import models
from services.api.app.strategy_v2 import (
    build_strategy_review,
    build_legacy_backtest_config_from_v2,
    migrate_strategy_config_v2,
)
from core.quant_core.data import drop_incomplete_ohlcv_rows
from core.quant_core.strategy_plan.backtest import BacktestCanceled, run_strategy_plan_backtest
from core.quant_core.strategy_plan.wfo import (
    aggregate_portfolio_test_results,
    compute_strategy_allocation_map,
    run_stock_walk_forward,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean_ohlcv(frame):
    return drop_incomplete_ohlcv_rows(frame)


def _single_stock_v2_config(config: dict[str, Any], symbol: str) -> dict[str, Any]:
    stock = dict((config.get("stocks") or {}).get(symbol) or {})
    return {
        "schema_version": 2,
        "app_domain": "four_pages",
        "legacy_snapshot": config.get("legacy_snapshot"),
        "portfolio": {
            "total_capital_mad": ((config.get("portfolio") or {}).get("total_capital_mad") or 0),
            "universe": {
                **dict(((config.get("portfolio") or {}).get("universe") or {})),
                "basket": [symbol],
            },
            "allocation": dict(((config.get("portfolio") or {}).get("allocation") or {})),
        },
        "stocks": {symbol: stock},
        "snapshot": config.get("snapshot"),
    }


def _stock_summary_from_result(symbol: str, result: dict[str, Any]) -> dict[str, Any]:
    metrics = dict(((result.get("general_results") or {}).get("metrics") or {}))
    assumptions = dict(result.get("assumptions") or {})
    return {
        "symbol": symbol,
        "net_pnl": metrics.get("net_pnl"),
        "total_return": metrics.get("total_return"),
        "cagr": metrics.get("cagr"),
        "sharpe": metrics.get("sharpe"),
        "max_drawdown": metrics.get("max_drawdown"),
        "number_of_trades": metrics.get("number_of_trades"),
        "missing_symbols": assumptions.get("missing_symbols") or [],
    }


def _stock_summary_from_direct_stock(stock: dict[str, Any]) -> dict[str, Any]:
    summary_metrics = dict(stock.get("summary_metrics") or {})
    allocation = dict(stock.get("allocation") or {})
    return {
        "symbol": str(stock.get("symbol") or ""),
        "net_pnl": summary_metrics.get("net_pnl"),
        "total_return": summary_metrics.get("total_return"),
        "cagr": summary_metrics.get("cagr"),
        "sharpe": summary_metrics.get("sharpe"),
        "max_drawdown": summary_metrics.get("max_drawdown"),
        "number_of_trades": summary_metrics.get("n_trades"),
        "capital_mad": allocation.get("capital_mad"),
        "weight_pct": allocation.get("weight_pct"),
    }


def _update_run_progress(run: models.StrategyBacktestRun, *, completed: int, total: int, active_symbol: str | None, message: str) -> None:
    run.progress_json = {
        "completed": completed,
        "total": total,
        "active_symbol": active_symbol,
        "message": message,
    }
    run.updated_at = _utcnow()


def _update_run_progress_detail(
    run: models.StrategyBacktestRun,
    *,
    phase: str,
    symbol: str | None,
    config_index: int,
    config_total: int,
    window_index: int,
    window_total: int,
    completed: int,
    total: int,
    message: str,
) -> None:
    run.progress_json = {
        "phase": phase,
        "symbol": symbol,
        "config_index": config_index,
        "config_total": config_total,
        "window_index": window_index,
        "window_total": window_total,
        "completed": completed,
        "total": total,
        "active_symbol": symbol,
        "message": message,
    }
    run.updated_at = _utcnow()


class StrategyBacktestRunCanceled(Exception):
    """Raised when a strategy backtest run is canceled by the user."""


def _get_cancel_redis() -> Redis | None:
    try:
        return Redis.from_url(settings.REDIS_URL, decode_responses=False)
    except Exception:
        return None


def _run_cancel_requested(
    db,
    *,
    run_key: UUID,
    rq_job_id: str | None,
    redis_client: Redis | None,
) -> bool:
    status = (
        db.query(models.StrategyBacktestRun.status)
        .filter(models.StrategyBacktestRun.id == run_key)
        .scalar()
    )
    status_text = str(status or "").strip().lower()
    if status_text in {"cancel_requested", "canceled"}:
        return True

    job_id = str(rq_job_id or "").strip()
    if not job_id or redis_client is None:
        return False
    try:
        return bool(redis_client.get(f"rq:cancel:{job_id}".encode()))
    except Exception:
        return False


def _mark_run_canceled(
    db,
    *,
    run_key: UUID,
    message: str,
) -> None:
    run = db.get(models.StrategyBacktestRun, run_key)
    if run is None:
        return
    run.status = "canceled"
    run.error_text = str(message or "Canceled by user.")[:8000]
    run.completed_at = _utcnow()
    run.updated_at = _utcnow()
    progress = dict(run.progress_json or {})
    progress["message"] = "Canceled by user"
    progress["active_symbol"] = None
    run.progress_json = progress

    for stock_row in (
        db.query(models.StrategyBacktestStock)
        .filter(models.StrategyBacktestStock.run_id == run_key)
        .all()
    ):
        if str(stock_row.status or "").strip().lower() in {"queued", "running", "cancel_requested"}:
            stock_row.status = "canceled"
            stock_row.error_text = "Canceled by user."
            stock_row.updated_at = _utcnow()
    db.commit()


def execute_strategy_backtest_run(run_id: str) -> None:
    db = SessionLocal()
    try:
        run_key = UUID(str(run_id))
        run = db.get(models.StrategyBacktestRun, run_key)
        if run is None:
            return
        cancel_redis = _get_cancel_redis()
        rq_job_id = str(run.rq_job_id or "").strip() or None

        def _raise_if_canceled(message: str = "Canceled by user.") -> None:
            if _run_cancel_requested(
                db,
                run_key=run_key,
                rq_job_id=rq_job_id,
                redis_client=cancel_redis,
            ):
                raise StrategyBacktestRunCanceled(message)

        _raise_if_canceled("Canceled before execution started.")

        strategy = db.get(models.SavedStrategy, run.strategy_id)
        if strategy is None:
            run.status = "failed"
            run.error_text = "Saved strategy not found."
            run.completed_at = _utcnow()
            db.commit()
            return

        try:
            from rq import get_current_job
        except Exception:
            get_current_job = lambda: None

        job = get_current_job()
        if job is not None:
            run.rq_job_id = str(job.id)
            rq_job_id = str(job.id)

        _raise_if_canceled("Canceled before execution started.")

        run.status = "running"
        run.started_at = _utcnow()
        db.commit()

        request = dict(run.request_json or {})
        config_v2 = migrate_strategy_config_v2(strategy.config_json or {}, horizon=strategy.horizon)
        basket = list(((config_v2.get("portfolio") or {}).get("universe") or {}).get("basket") or [])
        stock_rows = (
            db.query(models.StrategyBacktestStock)
            .filter(models.StrategyBacktestStock.run_id == run.id)
            .order_by(models.StrategyBacktestStock.symbol.asc())
            .all()
        )
        stock_map = {row.symbol: row for row in stock_rows}
        total = len(basket)
        succeeded = 0
        failed = 0
        not_viable = 0
        summaries: list[dict[str, Any]] = []
        portfolio_candidates: list[dict[str, Any]] = []
        run.result_json = {}

        if run.mode == "wfo":
            review = build_strategy_review(strategy.config_json or {}, horizon=strategy.horizon, for_wfo=True)
            if not review.get("ready"):
                run.status = "failed"
                run.error_text = "Strategy is not executable in four-page WFO mode."
                run.summary_json = {
                    "blocking_issues": list(review.get("blocking_issues") or []),
                }
                run.completed_at = _utcnow()
                db.commit()
                return

            bars_by_symbol: dict[str, Any] = {}
            for symbol in basket:
                _raise_if_canceled("Canceled while preparing WFO inputs.")
                symbol_key = str(symbol).strip().upper()
                bars = _clean_ohlcv(load_ohlcv_for_symbol(db, symbol_key, str(request.get("timeframe") or "1D")))
                bars_by_symbol[symbol_key] = bars
            allocation_by_symbol = compute_strategy_allocation_map(
                basket=[str(symbol).strip().upper() for symbol in basket],
                bars_by_symbol=bars_by_symbol,
                total_capital_mad=float(((config_v2.get("portfolio") or {}).get("total_capital_mad") or 0.0)),
                manual_overrides_by_symbol=dict((((config_v2.get("portfolio") or {}).get("allocation") or {}).get("manual_overrides_by_symbol") or {})),
                lookback_bars=int((((config_v2.get("portfolio") or {}).get("allocation") or {}).get("hrp_lookback_bars") or 252)),
            )

            for index, symbol in enumerate(basket):
                _raise_if_canceled("Canceled by user.")
                symbol_key = str(symbol).strip().upper()
                stock_row = stock_map.get(symbol_key)
                if stock_row is None:
                    stock_row = models.StrategyBacktestStock(run_id=run.id, symbol=symbol_key, status="queued")
                    db.add(stock_row)
                    db.flush()

                stock_row.status = "running"
                stock_row.error_text = None
                _update_run_progress(
                    run,
                    completed=index,
                    total=total,
                    active_symbol=symbol_key,
                    message=f"Running {run.mode} backtest for {symbol_key}",
                )
                db.commit()

                try:
                    bars = bars_by_symbol.get(symbol_key)
                    if bars is None or bars.empty:
                        raise ValueError(f"No usable OHLCV rows for {symbol_key}.")
                    stock_config = dict((config_v2.get("stocks") or {}).get(symbol_key) or {})
                    for row in (
                        db.query(models.StrategyBacktestWindow)
                        .filter(models.StrategyBacktestWindow.run_id == run.id)
                        .filter(models.StrategyBacktestWindow.symbol == symbol_key)
                        .all()
                    ):
                        db.delete(row)
                    db.flush()

                    def _wfo_progress_callback(**payload) -> None:
                        _raise_if_canceled(f"Canceled while processing {symbol_key}.")
                        _update_run_progress_detail(run, **payload)
                        db.commit()

                    result_bundle = run_stock_walk_forward(
                        symbol=symbol_key,
                        strategy_id=str(strategy.id),
                        strategy_name=str(strategy.name),
                        side_policy=str(strategy.side_policy),
                        horizon=str(strategy.horizon),
                        timeframe=str(request.get("timeframe") or "1D"),
                        stock_config=stock_config,
                        bars=bars,
                        start_date=str(request.get("start_date") or ""),
                        end_date=str(request.get("end_date") or ""),
                        allocated_capital=float(allocation_by_symbol.get(symbol_key, 0.0)),
                        cost_model_raw=dict(request.get("cost_model") or {}),
                        volume_gate=dict(request.get("volume_gate") or {}),
                        cooldown_bars=int(request.get("cooldown_bars") or 0),
                        wfo_config=dict(request.get("wfo_config") or {}),
                        progress_callback=_wfo_progress_callback,
                    )
                    result = sanitize_json_compatible(result_bundle["result"])
                    summary = sanitize_json_compatible(result_bundle["summary"])
                    stock_status = str(result_bundle.get("status") or "failed")
                    stock_row.status = stock_status
                    stock_row.summary_json = summary
                    stock_row.result_json = result
                    stock_row.updated_at = _utcnow()
                    for window in list(result_bundle.get("windows") or []):
                        db.add(
                            models.StrategyBacktestWindow(
                                run_id=run.id,
                                symbol=symbol_key,
                                window_index=int(window.get("window_index") or 0),
                                summary_json=sanitize_json_compatible(window.get("summary") or {}),
                                detail_json=sanitize_json_compatible(window.get("detail") or {}),
                            )
                        )
                    summaries.append(summary)
                    if stock_status == "succeeded":
                        succeeded += 1
                        portfolio_candidates.append({"symbol": symbol_key, "result": result})
                    elif stock_status == "not_viable":
                        not_viable += 1
                    else:
                        failed += 1
                except StrategyBacktestRunCanceled:
                    raise
                except Exception as exc:
                    stock_row.status = "failed"
                    stock_row.error_text = str(exc)[:8000]
                    stock_row.summary_json = {"symbol": symbol_key}
                    stock_row.result_json = {}
                    stock_row.updated_at = _utcnow()
                    failed += 1
                db.commit()
        else:
            timeframe = str(request.get("timeframe") or "1D")
            legacy_config = build_legacy_backtest_config_from_v2(config_v2, horizon=strategy.horizon)
            bars_by_symbol: dict[str, Any] = {}
            missing_symbols: list[str] = []
            for symbol in basket:
                _raise_if_canceled("Canceled while preparing direct backtest inputs.")
                symbol_key = str(symbol).strip().upper()
                stock_row = stock_map.get(symbol_key)
                if stock_row is None:
                    stock_row = models.StrategyBacktestStock(run_id=run.id, symbol=symbol_key, status="queued")
                    db.add(stock_row)
                    db.flush()
                    stock_map[symbol_key] = stock_row
                stock_row.status = "running"
                stock_row.error_text = None
                stock_row.summary_json = {"symbol": symbol_key}
                stock_row.result_json = {}
                stock_row.updated_at = _utcnow()
                try:
                    bars = _clean_ohlcv(load_ohlcv_for_symbol(db, symbol_key, timeframe))
                except Exception:
                    bars = None
                if bars is None or bars.empty:
                    missing_symbols.append(symbol_key)
                    continue
                bars_by_symbol[symbol_key] = bars
            _update_run_progress(
                run,
                completed=0,
                total=total,
                active_symbol=None,
                message="Running direct backtest",
            )
            db.commit()

            if not bars_by_symbol:
                raise ValueError("No basket symbols have usable market data for this backtest.")

            _raise_if_canceled("Canceled before direct backtest execution.")
            try:
                result = run_strategy_plan_backtest(
                    strategy_id=str(strategy.id),
                    strategy_name=str(strategy.name),
                    side_policy=str(strategy.side_policy),
                    horizon=strategy.horizon,
                    timeframe=timeframe,
                    config_json=legacy_config,
                    bars_by_symbol=bars_by_symbol,
                    start_date=str(request.get("start_date") or ""),
                    end_date=str(request.get("end_date") or ""),
                    cost_model_raw=dict(request.get("cost_model") or {}),
                    volume_gate=dict(request.get("volume_gate") or {}),
                    cooldown_bars=int(request.get("cooldown_bars") or 0),
                    family_history_mode=str(request.get("family_history_mode") or "static_current_reps"),
                    cancel_check=lambda: _run_cancel_requested(
                        db,
                        run_key=run_key,
                        rq_job_id=rq_job_id,
                        redis_client=cancel_redis,
                    ),
                )
            except BacktestCanceled as exc:
                raise StrategyBacktestRunCanceled(str(exc)) from exc
            result = sanitize_json_compatible(result)
            assumptions = dict(result.get("assumptions") or {})
            existing_missing = list(assumptions.get("missing_symbols") or assumptions.get("skipped_symbols") or [])
            assumptions["missing_symbols"] = sorted(set(existing_missing + missing_symbols))
            result["assumptions"] = assumptions
            run.result_json = result
            run_metrics = dict(((result.get("general_results") or {}).get("metrics") or {}))
            stock_results = {
                str(item.get("symbol") or "").strip().upper(): sanitize_json_compatible(item)
                for item in list(result.get("stocks") or [])
                if str(item.get("symbol") or "").strip()
            }

            for symbol in basket:
                _raise_if_canceled("Canceled while persisting direct backtest results.")
                symbol_key = str(symbol).strip().upper()
                stock_row = stock_map[symbol_key]
                stock_result = stock_results.get(symbol_key)
                if stock_result is not None:
                    summary = _stock_summary_from_direct_stock(stock_result)
                    stock_row.status = "succeeded"
                    stock_row.summary_json = summary
                    stock_row.result_json = stock_result
                    stock_row.error_text = None
                    stock_row.updated_at = _utcnow()
                    summaries.append(summary)
                    succeeded += 1
                else:
                    stock_row.status = "failed"
                    stock_row.summary_json = {"symbol": symbol_key}
                    stock_row.result_json = {}
                    stock_row.error_text = (
                        f"No usable OHLCV rows for {symbol_key}."
                        if symbol_key in missing_symbols
                        else "No persisted result for this symbol."
                    )
                    stock_row.updated_at = _utcnow()
                    failed += 1
                db.commit()

        _raise_if_canceled("Canceled before finalizing results.")
        run.status = "succeeded" if (succeeded > 0 or (not_viable > 0 and failed == 0)) else "failed"
        run_summary = {
            "succeeded": succeeded,
            "failed": failed,
            "not_viable": not_viable,
            "total": total,
            "stocks_with_results": [item.get("symbol") for item in summaries],
        }
        if run.mode == "wfo":
            wfo_request = dict(request.get("wfo_config") or {})
            run_summary["portfolio"] = sanitize_json_compatible(
                aggregate_portfolio_test_results(
                    portfolio_candidates,
                    n_monte_carlo_paths=int(wfo_request.get("n_monte_carlo_paths") or 1000),
                    monte_carlo_block_length=(
                        int(wfo_request.get("monte_carlo_block_length"))
                        if wfo_request.get("monte_carlo_block_length") is not None
                        else None
                    ),
                )
            )
            run_summary["stock_outcomes"] = {
                "succeeded": [item.get("symbol") for item in summaries if item.get("status") == "succeeded"],
                "not_viable": [item.get("symbol") for item in summaries if item.get("status") == "not_viable"],
            }
            strict_symbols: list[str] = []
            fallback_symbols: list[str] = []
            ratios_ignored_symbols: list[str] = []
            cap_applied_symbols: list[str] = []
            for stock_row in stock_map.values():
                result_json = dict(stock_row.result_json or {})
                diagnostics = dict(result_json.get("diagnostics") or {})
                policy = dict(diagnostics.get("policy") or {})
                policy_name = str(policy.get("window_policy_used") or diagnostics.get("window_policy") or "").strip().lower()
                if not policy_name:
                    continue
                if policy_name == "strict_fold_driven":
                    strict_symbols.append(stock_row.symbol)
                if bool(policy.get("fallback_applied")):
                    fallback_symbols.append(stock_row.symbol)
                ignored_inputs = [str(item) for item in list(policy.get("ignored_inputs") or [])]
                if "is_oos_ratios" in ignored_inputs:
                    ratios_ignored_symbols.append(stock_row.symbol)
                feasibility = dict(policy.get("feasibility") or {})
                if bool(feasibility.get("horizon_cap_applied")):
                    cap_applied_symbols.append(stock_row.symbol)
            run_summary["strict_window_policy"] = {
                "strict_symbols": sorted(set(strict_symbols)),
                "fallback_symbols": sorted(set(fallback_symbols)),
                "ratios_ignored_symbols": sorted(set(ratios_ignored_symbols)),
                "horizon_cap_applied_symbols": sorted(set(cap_applied_symbols)),
            }
        else:
            run_summary["general_metrics"] = dict((((run.result_json or {}).get("general_results") or {}).get("metrics") or {})
            )
            run_summary["missing_symbols"] = list((((run.result_json or {}).get("assumptions") or {}).get("missing_symbols") or [])
            )
        run.summary_json = run_summary
        _update_run_progress(
            run,
            completed=total,
            total=total,
            active_symbol=None,
            message="Completed" if (succeeded > 0 or not_viable > 0) else "Failed",
        )
        run.error_text = None if succeeded > 0 or (not_viable > 0 and failed == 0) else "All strategy backtest stocks failed."
        run.completed_at = _utcnow()
        db.commit()
    except StrategyBacktestRunCanceled as exc:
        try:
            db.rollback()
        except Exception:
            pass
        _mark_run_canceled(
            db,
            run_key=UUID(str(run_id)),
            message=str(exc) or "Canceled by user.",
        )
        return
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        run = db.get(models.StrategyBacktestRun, UUID(str(run_id)))
        if run is not None:
            run.status = "failed"
            run.error_text = str(exc)[:8000]
            run.completed_at = _utcnow()
            db.commit()
        raise
    finally:
        db.close()
