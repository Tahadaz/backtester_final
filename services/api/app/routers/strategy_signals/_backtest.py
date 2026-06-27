"""Signal backtest and portfolio endpoints: backtest-mc, batch-status, portfolio-backtest."""
from __future__ import annotations

import json
import time
from typing import Any

import numpy as np
import pandas as pd

from pydantic import BaseModel as _BaseModel
from typing import Optional as _Optional

from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...db import get_db
from core.quant_core.signal_engine.domain import (
    EnsemblePipelineDetail,
    HORIZON_PARAMS,
    VariantRobustnessSummary,
    label_to_signal_value,
    signal_type_label,
    variant_signal_label,
)
from core.quant_core.signal_engine.ensemble import (
    run_family_ensemble_full,
    compute_family_score_timeseries,
)
from core.quant_core.signal_engine.modes import (
    resolve_signal_mode,
    signal_mode_read_names,
    signal_mode_storage_name,
)
from core.quant_core.significance import sharpe_ratio
from core.quant_core.risk import monte_carlo_equity_paths
from core.quant_core.horizons import canonical_horizon, LEGACY_HORIZON_ALIASES
from ...market_data_loader import load_ohlcv_for_symbol
from ._shared import (
    logger,
    router,
    CanonicalHorizon,
    _require_canonical_signal_horizon,
    _truncate_for_horizon,
    _clean_ohlcv,
    _safe_float,
    _safe_float_list,
)
from ._support_resistance import (
    _sr_overlay_empty,
    _sr_overlay_for_position_series,
)
from ._evidence import (
    _read_best_evidence_snapshot,
    _signal_backtest_diagnostics_with_source_reps,
    _signal_backtest_direction_filter,
    _signal_backtest_scope_score_by_date,
    _signal_backtest_recomputed_payload,
    _signal_backtest_score_series,
    _signal_backtest_selected_position,
    _signal_backtest_trade_ledger,
)

@router.get("/backtest-mc", summary="Get persisted signal backtest + MC results for one symbol/horizon")
def get_signal_backtest_results(
    symbol: str,
    horizon: CanonicalHorizon,
    variant: str = "expanded",
    source: _Optional[str] = None,
    scope: _Optional[str] = None,
    cooldown_bars: int = Query(0, ge=0, le=252),
    selected_direction: _Optional[str] = Query(
        None,
        description="Optional action filter for returned chart/ledger: long, short, or none.",
    ),
    db: Session = Depends(get_db),
):
    """Return all signal_backtest_run rows for (symbol, horizon).

    Optional filters:
      - source: "engine" | "wfo"
      - scope: "per_category" | "global" | "combination"

    Returns 404 when no results exist yet.
    Includes is_stale flag based on data_as_of vs market_data_store.data_as_of.
    """
    from services.api.app.models import SignalBacktestRun, MarketDataStore

    horizon = _require_canonical_signal_horizon(horizon)
    direction_filter = _signal_backtest_direction_filter(selected_direction)
    cooldown = min(252, max(0, int(cooldown_bars or 0)))
    q = db.query(SignalBacktestRun).filter_by(
        symbol=symbol,
        horizon=horizon,
        variant=variant,
        cooldown_bars=cooldown,
    )
    if source:
        q = q.filter(SignalBacktestRun.source == source)
    if scope:
        q = q.filter(SignalBacktestRun.scope == scope)

    rows = q.order_by(SignalBacktestRun.scope, SignalBacktestRun.scope_key, SignalBacktestRun.source).all()
    if not rows:
        try:
            from services.worker.tasks.signal_enqueue import enqueue_signal_backtest_for_symbol as _enqueue
            canonical_variant = signal_mode_storage_name(variant)
            _enqueue(symbol, horizon, variant=canonical_variant, triggered_by="api_read_miss")
        except Exception:
            logger.debug("could not enqueue signal backtest on cache miss", exc_info=True)
        raise HTTPException(
            status_code=404,
            detail=f"No backtest results for {symbol}/{horizon}/{variant}. Trigger /strategy/backtest-mc/trigger first.",
        )

    mds = db.query(MarketDataStore).filter_by(symbol=symbol, timeframe="1D").first()
    market_data_as_of = mds.data_as_of.isoformat() if (mds and mds.data_as_of) else None

    results = []
    representative_lookup_cache: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]] = {}
    for row in rows:
        row_data_as_of = row.data_as_of.isoformat() if row.data_as_of else None
        is_stale = (
            row_data_as_of is None
            or (market_data_as_of and row_data_as_of < market_data_as_of)
        )
        score_by_date, score_scope, score_scope_key = _signal_backtest_scope_score_by_date(db, row)
        base_position = row.position_series_json if isinstance(row.position_series_json, list) else []
        response_position = _signal_backtest_selected_position(base_position, direction_filter)
        score_series = _signal_backtest_score_series(row.dates_json, score_by_date)
        if direction_filter is None:
            response_equity = row.equity_json
            response_trades = row.trades_json
            response_metrics = {
                "total_return": row.total_return,
                "cagr": row.cagr,
                "sharpe": row.sharpe,
                "max_drawdown": row.max_drawdown,
                "win_rate": row.win_rate,
                "n_trades": row.n_trades,
            }
            response_mc = {
                "method": row.mc_method,
                "n_paths": row.n_paths,
                "envelope": row.mc_envelope_json,
                "stats": row.mc_stats_json,
            }
            trade_ledger = _signal_backtest_trade_ledger(row, score_by_date=score_by_date)
        else:
            recomputed = _signal_backtest_recomputed_payload(
                row,
                position=response_position,
                score_by_date=score_by_date,
            )
            response_equity = recomputed["equity"]
            response_trades = recomputed["trades"]
            response_metrics = recomputed["metrics"]
            selected_mc = recomputed.get("mc")
            response_mc = {
                "method": (selected_mc or {}).get("method") or "block_bootstrap",
                "n_paths": int((selected_mc or {}).get("n_paths") or row.n_paths or 0),
                "envelope": (selected_mc or {}).get("envelope") if selected_mc else None,
                "stats": (selected_mc or {}).get("stats") if selected_mc else None,
            }
            trade_ledger = _signal_backtest_trade_ledger(
                row,
                position_override=response_position,
                equity_override=response_equity,
                score_by_date=score_by_date,
            )

        response_metrics_dict = dict(response_metrics or {})
        sr_overlay = _sr_overlay_empty(
            "unavailable",
            "source_not_wfo",
            response_metrics_dict,
        )
        if str(row.source or "") == "wfo":
            sr_overlay = _sr_overlay_for_position_series(
                db,
                symbol=symbol,
                horizon=horizon,
                variant=variant,
                dates=row.dates_json if isinstance(row.dates_json, list) else [],
                baseline_position=response_position,
                baseline_metrics=response_metrics_dict,
                cost_bps=float(row.cost_bps or 0.0),
                slippage_bps=float(row.slippage_bps or 0.0),
                cooldown_bars=int(getattr(row, "cooldown_bars", 0) or 0),
                side_policy=(
                    "long_short"
                    if direction_filter == "short"
                    else str(row.side_policy or "long_only")
                ),
            )

        results.append({
            "source": row.source,
            "scope": row.scope,
            "scope_key": row.scope_key,
            "status": row.status,
            "warning_code": row.warning_code,
            "side_policy": row.side_policy or "long_only",
            "cooldown_bars": int(getattr(row, "cooldown_bars", 0) or 0),
            "selected_direction": direction_filter,
            "window_start": row.window_start.isoformat() if row.window_start else None,
            "window_end": row.window_end.isoformat() if row.window_end else None,
            "n_bars": row.n_bars,
            "n_trades": response_metrics.get("n_trades"),
            "equity": response_equity,
            "dates": row.dates_json,
            "trades": response_trades,
            "trade_ledger": trade_ledger,
            "close_series": row.close_series_json,
            "position_series": response_position,
            "global_score_series": score_series,
            "score_series": score_series,
            "score_scope": score_scope,
            "score_scope_key": score_scope_key,
            "signal_diagnostics": _signal_backtest_diagnostics_with_source_reps(
                db,
                row,
                cache=representative_lookup_cache,
            ),
            "metrics": response_metrics,
            "sr_overlay": sr_overlay,
            "mc": response_mc,
            "shuffle_stats": row.shuffle_stats_json,
            "computed_at": row.computed_at.isoformat() if row.computed_at else None,
            "data_as_of": row_data_as_of,
            "is_stale": is_stale,
        })

    return {
        "symbol": symbol,
        "horizon": horizon,
        "variant": variant,
        "market_data_as_of": market_data_as_of,
        "results": results,
    }


def build_stored_best_backtest_chart_payload(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str,
    cooldown_bars: int = 0,
    scope: str = "global",
    scope_key: str = "global",
) -> dict[str, Any] | None:
    """Assemble the WFO best-variant backtest chart payload for snapshot storage.

    Reuses the live ``/backtest-mc`` assembly and narrows it to the requested
    scope.  Returns ``None`` when no matching backtest rows exist so the caller
    can persist an evidence-only snapshot.
    """
    canonical_h = _require_canonical_signal_horizon(horizon)
    storage_variant = signal_mode_storage_name(variant) if variant else variant
    cooldown = min(252, max(0, int(cooldown_bars or 0)))
    try:
        payload = get_signal_backtest_results(
            symbol=symbol,
            horizon=canonical_h,
            variant=storage_variant,
            source="wfo",
            scope=scope,
            cooldown_bars=cooldown,
            selected_direction=None,
            db=db,
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise
    if not isinstance(payload, dict):
        return None
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return None
    if scope_key:
        narrowed = [row for row in results if str(row.get("scope_key") or "") == str(scope_key)]
        if narrowed:
            payload = {**payload, "results": narrowed}
    return payload


@router.get("/backtest-mc/best-chart", summary="Read the stored best-WFO backtest chart snapshot")
def get_signal_best_backtest_chart(
    symbol: str,
    horizon: CanonicalHorizon,
    cooldown_bars: int = Query(0, ge=0, le=252),
    db: Session = Depends(get_db),
):
    """Serve the weekly-materialized best backtest chart for the signal page.

    Mirrors ``/signal/best-evidence``: stored-only, 404 when unbuilt, 409 when
    stale relative to fresh market data.
    """
    symbol_upper = symbol.strip().upper()
    if not symbol_upper:
        raise HTTPException(status_code=422, detail="symbol is required")
    canonical_h = _require_canonical_signal_horizon(horizon)
    row = _read_best_evidence_snapshot(
        db,
        symbol=symbol_upper,
        horizon=canonical_h,
        cooldown_bars=cooldown_bars,
    )
    payload = row.chart_payload_jsonb
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=404,
            detail=f"Stored best backtest chart for {symbol_upper}/{canonical_h} is unavailable.",
        )
    return payload


def _batch_job_status_payload(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str,
    job_type: str,
):
    from services.api.app.models import SignalEngineBatchJob

    rows = (
        db.query(SignalEngineBatchJob)
        .filter_by(symbol=symbol, horizon=horizon, variant=variant, job_type=job_type)
        .order_by(
            SignalEngineBatchJob.created_at.desc(),
            SignalEngineBatchJob.started_at.desc().nullslast(),
        )
        .limit(5)
        .all()
    )
    return {
        "symbol": symbol,
        "horizon": horizon,
        "variant": variant,
        "job_type": job_type,
        "jobs": [
            {
                "id": str(row.id),
                "job_type": row.job_type,
                "status": row.status,
                "rq_job_id": row.rq_job_id,
                "triggered_by": row.triggered_by,
                "batch_id": row.batch_id,
                "total_units": row.total_units,
                "completed_units": row.completed_units,
                "failed_units": row.failed_units,
                "error_message": row.error_message,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }


@router.get("/engine/batch-status", summary="Get latest signal engine batch job status")
def get_signal_engine_batch_status(
    symbol: str,
    horizon: CanonicalHorizon,
    variant: str = "expanded",
    db: Session = Depends(get_db),
):
    """Return recent signal_engine batch jobs for this (symbol, horizon)."""
    horizon = _require_canonical_signal_horizon(horizon)
    return _batch_job_status_payload(
        db,
        symbol=symbol,
        horizon=horizon,
        variant=variant,
        job_type="signal_engine",
    )


@router.get("/engine/batch-status-global", summary="Get global signal engine batch status for manual global runs")
def get_signal_engine_batch_status_global(
    batch_id: _Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Aggregate latest status per tuple for one manual global launch batch."""
    from services.api.app.models import SignalEngineBatchJob

    query = db.query(SignalEngineBatchJob).filter_by(
        job_type="signal_engine",
        triggered_by="manual_global",
    )
    if batch_id:
        query = query.filter_by(batch_id=batch_id)
        effective_batch_id = batch_id
    else:
        seed_rows = query.all()
        latest_with_batch = None
        latest_ts = 0.0
        for row in seed_rows:
            current_batch = str(getattr(row, "batch_id", "") or "").strip()
            if not current_batch:
                continue
            created_ts = row.created_at.timestamp() if getattr(row, "created_at", None) else 0.0
            if created_ts >= latest_ts:
                latest_ts = created_ts
                latest_with_batch = current_batch
        effective_batch_id = latest_with_batch
        if effective_batch_id:
            query = query.filter_by(batch_id=effective_batch_id)

    rows = query.all()

    latest_by_key: dict[tuple[str, str, str], Any] = {}
    for row in rows:
        key = (str(row.symbol), str(row.horizon), str(row.variant))
        previous = latest_by_key.get(key)
        row_created = row.created_at.timestamp() if getattr(row, "created_at", None) else 0.0
        prev_created = previous.created_at.timestamp() if (previous and getattr(previous, "created_at", None)) else 0.0
        if previous is None or row_created >= prev_created:
            latest_by_key[key] = row

    counts = {
        "succeeded": 0,
        "running": 0,
        "failed": 0,
        "pending": 0,
        "partial": 0,
    }
    horizon_distribution: dict[str, int] = {}
    legacy_horizon_rows = 0
    first_error_sample: str | None = None
    for row in latest_by_key.values():
        status = str(getattr(row, "status", "") or "pending").strip().lower()
        horizon_name = str(getattr(row, "horizon", "") or "").strip().lower()
        if horizon_name:
            horizon_distribution[horizon_name] = horizon_distribution.get(horizon_name, 0) + 1
        if horizon_name in LEGACY_HORIZON_ALIASES:
            legacy_horizon_rows += 1
        if first_error_sample is None:
            err = str(getattr(row, "error_message", "") or "").strip()
            if err:
                first_error_sample = err
        if status in counts:
            counts[status] += 1
        elif status in ("queued",):
            counts["pending"] += 1
        elif status == "no_signal":
            # Computation completed normally — no tradeable signal found. Count as done.
            counts["succeeded"] += 1
        else:
            counts["failed"] += 1

    return {
        "batch_id": effective_batch_id,
        "total": len(latest_by_key),
        "succeeded": counts["succeeded"],
        "running": counts["running"],
        "failed": counts["failed"],
        "pending": counts["pending"],
        "partial": counts["partial"],
        "horizon_distribution": horizon_distribution,
        "legacy_horizon_rows": legacy_horizon_rows,
        "first_error_sample": first_error_sample,
    }


@router.get("/backtest-mc/batch-status", summary="Get latest signal backtest batch job status")
def get_signal_backtest_batch_status(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    db: Session = Depends(get_db),
):
    """Return recent signal_backtest batch jobs for this (symbol, horizon)."""
    return _batch_job_status_payload(
        db,
        symbol=symbol,
        horizon=horizon,
        variant=variant,
        job_type="signal_backtest",
    )


# ---------------------------------------------------------------------------
# Portfolio backtest (WFO OOS) — Portefeuille tab endpoints
# ---------------------------------------------------------------------------

class _PortfolioBacktestRequest(_BaseModel):
    symbols: list[str] = []
    horizon: str = "weekly"
    variant: str = "expanded"
    initial_capital: float = 100_000.0
    take_profit_pct: float = 0.05
    kelly_multiplier: float = 0.5
    long_only: bool = True
    start_date: _Optional[str] = None
    end_date: _Optional[str] = None


def _portfolio_dedupe(rows: list) -> list:
    """Keep one row per symbol — the one with the latest computed_at (None = oldest)."""
    best: dict[str, Any] = {}
    for row in rows:
        sym = row.symbol
        if sym not in best:
            best[sym] = row
        else:
            existing_at = best[sym].computed_at
            row_at = row.computed_at
            if existing_at is None:
                best[sym] = row
            elif row_at is not None and row_at > existing_at:
                best[sym] = row
    return list(best.values())


def _portfolio_kelly(
    trades: list[dict],
    long_only: bool,
    kelly_multiplier: float,
) -> _Optional[dict]:
    """Return Kelly sizing stats for a symbol's trades, or None if < 3 qualifying trades."""
    relevant = [t for t in trades if t.get("direction", 1) == 1] if long_only else list(trades)
    if len(relevant) < 3:
        return None
    wins = [t["pnl_return"] for t in relevant if t["pnl_return"] > 0]
    losses = [abs(t["pnl_return"]) for t in relevant if t["pnl_return"] <= 0]
    wr = len(wins) / len(relevant)
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    if avg_loss == 0.0:
        f = wr
    elif avg_win == 0.0:
        f = 0.0
    else:
        f = wr - (1.0 - wr) / (avg_win / avg_loss)
    f = max(0.0, min(1.0, f))
    kelly_size = kelly_multiplier * f
    n_long = sum(1 for t in trades if t.get("direction", 1) == 1)
    n_short = sum(1 for t in trades if t.get("direction", 1) != 1)
    return {
        "kelly_fraction": f,
        "kelly_pct": kelly_size * 100.0,
        "kelly_size": kelly_size,
        "win_rate": wr * 100.0,
        "avg_win_pct": avg_win * 100.0,
        "avg_loss_pct": avg_loss * 100.0,
        "n_trades": len(relevant),
        "n_long": n_long,
        "n_short": n_short,
    }


@router.get(
    "/signal/portfolio-backtest/universe",
    summary="Eligible WFO-trade universe for the portfolio backtest",
)
def get_portfolio_backtest_universe(
    horizon: str = "weekly",
    variant: str = "expanded",
    long_only: bool = True,
    db: Session = Depends(get_db),
):
    from services.api.app.models import SignalBacktestRun

    rows = db.query(SignalBacktestRun).filter(
        SignalBacktestRun.source == "wfo",
        SignalBacktestRun.horizon == horizon,
        SignalBacktestRun.variant == variant,
    ).all()

    deduped = _portfolio_dedupe(rows)

    symbols_out: list[dict] = []
    all_open_dates: list[str] = []
    all_close_dates: list[str] = []

    for row in deduped:
        trades = row.trades_json or []
        relevant = [t for t in trades if t.get("direction", 1) == 1] if long_only else trades
        if len(relevant) < 3:
            continue
        n_long = sum(1 for t in trades if t.get("direction", 1) == 1)
        n_short = sum(1 for t in trades if t.get("direction", 1) != 1)
        symbols_out.append({
            "symbol": row.symbol,
            "n_trades": len(relevant),
            "n_long": n_long,
            "n_short": n_short,
        })
        for t in trades:
            if t.get("open_date"):
                all_open_dates.append(t["open_date"])
            if t.get("close_date"):
                all_close_dates.append(t["close_date"])

    return {
        "symbols": symbols_out,
        "date_range": {
            "min": min(all_open_dates) if all_open_dates else None,
            "max": max(all_close_dates) if all_close_dates else None,
        },
    }


@router.post(
    "/signal/portfolio-backtest",
    summary="Run the portfolio WFO backtest across selected symbols",
)
def run_portfolio_backtest(
    body: _PortfolioBacktestRequest,
    db: Session = Depends(get_db),
):
    from datetime import date as _date
    from services.api.app.models import SignalBacktestRun

    rows = db.query(SignalBacktestRun).filter(
        SignalBacktestRun.source == "wfo",
        SignalBacktestRun.horizon == body.horizon,
        SignalBacktestRun.variant == body.variant,
    ).all()

    deduped = _portfolio_dedupe(rows)
    if body.symbols:
        sym_set = set(body.symbols)
        deduped = [r for r in deduped if r.symbol in sym_set]

    per_symbol_stats: list[dict] = []
    flat_trades: list[dict] = []
    warnings: list[str] = []

    for row in deduped:
        trades = row.trades_json or []
        ks = _portfolio_kelly(trades, body.long_only, body.kelly_multiplier)
        if ks is None:
            warnings.append(f"{row.symbol}: insufficient trades for Kelly sizing (< 3)")
            continue
        if ks["kelly_size"] <= 0:
            warnings.append(f"{row.symbol}: Kelly fraction ≤ 0, skipped")
            continue
        per_symbol_stats.append({"symbol": row.symbol, **ks})
        relevant = [t for t in trades if t.get("direction", 1) == 1] if body.long_only else trades
        for t in relevant:
            flat_trades.append({**t, "symbol": row.symbol, "_ks": ks["kelly_size"]})

    n_symbols_qualified = len(per_symbol_stats)
    if n_symbols_qualified == 0 and not warnings:
        warnings.append("No symbols qualified for the portfolio backtest.")

    if body.start_date:
        flat_trades = [t for t in flat_trades if t.get("open_date", "") >= body.start_date]
    if body.end_date:
        flat_trades = [t for t in flat_trades if t.get("open_date", "") <= body.end_date]

    flat_trades.sort(key=lambda t: t.get("open_date", ""))

    capital = body.initial_capital
    peak = capital
    max_dd = 0.0
    trade_results: list[dict] = []
    equity_curve: list[dict] = []

    if flat_trades:
        equity_curve.append({"date": flat_trades[0]["open_date"], "equity": capital})

    for t in flat_trades:
        pnl_ret = float(t.get("pnl_return", 0.0))
        kelly_size = float(t["_ks"])
        if pnl_ret >= body.take_profit_pct:
            eff_ret = body.take_profit_pct
            tp = True
        else:
            eff_ret = pnl_ret
            tp = False

        pos_size = round(kelly_size * capital)
        if pos_size <= 0:
            trade_results.append({
                "symbol": t["symbol"],
                "direction": int(t.get("direction", 1)),
                "open_date": t.get("open_date", ""),
                "close_date": t.get("close_date", ""),
                "open_price": float(t.get("open_price", 0.0)),
                "close_price": float(t.get("close_price", 0.0)),
                "pnl_return": pnl_ret,
                "effective_return": eff_ret,
                "tp_applied": tp,
                "position_size": 0,
                "pnl_mad": 0.0,
                "executed": False,
            })
            continue

        pnl_mad = pos_size * eff_ret
        capital += pnl_mad
        peak = max(peak, capital)
        if peak > 0:
            max_dd = max(max_dd, (peak - capital) / peak * 100.0)

        close_dt = t.get("close_date", "")
        if close_dt:
            equity_curve.append({"date": close_dt, "equity": capital})

        trade_results.append({
            "symbol": t["symbol"],
            "direction": int(t.get("direction", 1)),
            "open_date": t.get("open_date", ""),
            "close_date": close_dt,
            "open_price": float(t.get("open_price", 0.0)),
            "close_price": float(t.get("close_price", 0.0)),
            "pnl_return": pnl_ret,
            "effective_return": eff_ret,
            "tp_applied": tp,
            "position_size": pos_size,
            "pnl_mad": float(pnl_mad),
            "executed": True,
        })

    final_equity = capital
    executed = [t for t in trade_results if t["executed"]]
    n_trades_exec = len(executed)
    total_ret = (
        (final_equity - body.initial_capital) / body.initial_capital * 100.0
        if body.initial_capital else 0.0
    )
    tp_count = sum(1 for t in executed if t["tp_applied"])
    tp_pct = round(tp_count / n_trades_exec * 100.0, 1) if n_trades_exec else 0.0

    cagr: _Optional[float] = None
    sharpe: _Optional[float] = None
    if executed:
        try:
            d1 = _date.fromisoformat(min(t["open_date"] for t in executed))
            d2 = _date.fromisoformat(max(t["close_date"] for t in executed if t["close_date"]))
            yrs = (d2 - d1).days / 365.25
            if yrs > 0 and body.initial_capital > 0:
                cagr = ((final_equity / body.initial_capital) ** (1.0 / yrs) - 1.0) * 100.0
        except Exception:
            pass
        eff_rets = [t["effective_return"] for t in executed]
        if len(eff_rets) > 1:
            mu = float(np.mean(eff_rets))
            sigma = float(np.std(eff_rets, ddof=1))
            if sigma > 0:
                sharpe = mu / sigma * float(np.sqrt(len(eff_rets)))

    period = {
        "start": executed[0]["open_date"] if executed else None,
        "end": executed[-1]["close_date"] if executed else None,
        "requested_start": body.start_date,
        "requested_end": body.end_date,
    }

    trades_truncated = len(trade_results) > 2000
    trades_out = trade_results[:2000]

    per_symbol_out = [
        {k: v for k, v in s.items() if k != "kelly_size"}
        for s in per_symbol_stats
    ]

    return {
        "equity_curve": equity_curve,
        "metrics": {
            "total_return": round(total_ret, 4),
            "cagr": round(cagr, 4) if cagr is not None else None,
            "sharpe": round(sharpe, 4) if sharpe is not None else None,
            "max_drawdown": round(max_dd, 4),
            "final_equity": round(final_equity, 2),
            "n_symbols": n_symbols_qualified,
            "n_trades": n_trades_exec,
            "tp_applied_pct": tp_pct,
        },
        "per_symbol": per_symbol_out,
        "n_symbols_qualified": n_symbols_qualified,
        "warnings": warnings,
        "trades": trades_out,
        "trades_truncated": trades_truncated,
        "period": period,
    }
