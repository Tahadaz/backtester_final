"""Signal backtest and portfolio endpoints: backtest-mc, batch-status, portfolio-backtest."""
from __future__ import annotations

import json
import math
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
    initial_capital: float = 100_000.0
    # None = no cap/floor applied. Exit-policy research (docs/plans/exit_policy_wfo_treatment_plan.md,
    # results/exit_treatment_trial_all/report.md) found no TP/SL variant beats the plain signal-flip
    # exit OOS, so both default off; these are opt-in overrides for manual experimentation.
    take_profit_pct: _Optional[float] = None
    stop_loss_pct: _Optional[float] = None
    kelly_multiplier: float = 0.5
    long_only: bool = True
    start_date: _Optional[str] = None
    end_date: _Optional[str] = None


def _dashboard_best_signal_trades_by_symbol(db: Session, horizon: str) -> dict[str, list[dict]]:
    """Per-symbol trades for the portfolio backtest.

    Reuses the same stitched-OOS-WFO trade reconstruction shown on the signal
    evidence page (``stitched_oos_backtest``), for whichever method the
    dashboard currently ranks as each symbol's best WFO signal — not an
    arbitrary SignalBacktestRun row/scope. This mirrors "for each day in the
    backtest period, take the trade that method's rule would have fired."
    """
    from services.api.app.models import SignalBestEvidenceSnapshot

    rows = db.query(SignalBestEvidenceSnapshot).filter(
        SignalBestEvidenceSnapshot.horizon == horizon,
        SignalBestEvidenceSnapshot.source == "wfo",
        SignalBestEvidenceSnapshot.status == "succeeded",
        SignalBestEvidenceSnapshot.cooldown_bars == 0,
    ).all()

    trades_by_symbol: dict[str, list[dict]] = {}
    for row in rows:
        payload = row.evidence_payload_jsonb
        stitched = payload.get("stitched_oos_backtest") if isinstance(payload, dict) else None
        raw_trades = stitched.get("trades") if isinstance(stitched, dict) else None
        if not isinstance(raw_trades, list) or not raw_trades:
            continue

        mapped: list[dict] = []
        for t in raw_trades:
            direction_label = str(t.get("direction") or "").strip().lower()
            if direction_label not in {"long", "short"}:
                continue
            pnl_return = t.get("action_return_net")
            open_date = t.get("entry_date")
            close_date = t.get("exit_date")
            if pnl_return is None or not open_date or not close_date:
                continue
            mapped.append({
                "open_date": open_date,
                "close_date": close_date,
                "open_price": t.get("entry_price"),
                "close_price": t.get("exit_price"),
                "direction": 1 if direction_label == "long" else -1,
                "pnl_return": float(pnl_return),
                "bars_held": t.get("holding_period_bars"),
            })
        if mapped:
            trades_by_symbol[row.symbol] = mapped
    return trades_by_symbol


def _portfolio_kelly(
    trades: list[dict],
    long_only: bool,
    kelly_multiplier: float,
) -> _Optional[dict]:
    """Return Kelly sizing stats for a symbol's trades, or None if < 3 qualifying trades.

    Retained for the universe endpoint's eligibility check (>= 3 qualifying
    trades). The walk-forward portfolio simulation below no longer uses this
    for sizing — see ``_kelly_fraction_from_returns``.
    """
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


def _kelly_fraction_from_returns(closed_returns: list[float], kelly_multiplier: float) -> float:
    """Same Kelly formula as ``_portfolio_kelly``, applied to an arbitrary list
    of already-realized trade returns (used walk-forward, on trades closed
    strictly before the sizing decision)."""
    n = len(closed_returns)
    wins = [r for r in closed_returns if r > 0]
    losses = [abs(r) for r in closed_returns if r <= 0]
    wr = len(wins) / n
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    if avg_loss == 0.0:
        f = wr
    elif avg_win == 0.0:
        f = 0.0
    else:
        f = wr - (1.0 - wr) / (avg_win / avg_loss)
    f = max(0.0, min(1.0, f))
    return kelly_multiplier * f


_PORTFOLIO_STARTER_TRADE_COUNT = 3
_PORTFOLIO_LEDGER_CAP = 4000
_MASI_BENCHMARK_UNAVAILABLE_WARNING = "Indice MASI indisponible pour le benchmark"


def _portfolio_benchmark(
    db: Session,
    *,
    start_date: str | None,
    end_date: str | None,
    initial_capital: float,
) -> tuple[dict | None, str | None]:
    """Load MASI daily closes, rebase to ``initial_capital`` over [start_date, end_date].

    Returns ``(benchmark_payload, warning)``. On any failure (no MASI series,
    insufficient overlap with the backtest period, bad data), returns
    ``(None, _MASI_BENCHMARK_UNAVAILABLE_WARNING)`` so callers can degrade
    gracefully instead of failing the whole request.
    """
    if not start_date or not end_date or initial_capital <= 0:
        return None, _MASI_BENCHMARK_UNAVAILABLE_WARNING
    try:
        ohlcv = load_ohlcv_for_symbol(db, "MASI", "1D")
        ohlcv = _clean_ohlcv(ohlcv)
        if ohlcv is None or len(ohlcv) == 0 or "Close" not in ohlcv.columns:
            raise ValueError("empty or malformed MASI series")

        series = ohlcv["Close"].copy()
        idx = pd.to_datetime(series.index)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        series.index = idx.normalize()
        series = series[~series.index.duplicated(keep="last")].sort_index()

        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        windowed = series[(series.index >= start_ts) & (series.index <= end_ts)].dropna()
        if len(windowed) < 2:
            raise ValueError("insufficient MASI data in backtest period")

        close_first = float(windowed.iloc[0])
        if close_first <= 0:
            raise ValueError("invalid MASI first close")

        curve = [
            {
                "date": ts.strftime("%Y-%m-%d"),
                "equity": float(initial_capital * (float(close) / close_first)),
            }
            for ts, close in windowed.items()
        ]

        # Downsample long series to keep the payload light, always keeping the
        # final point so total_return matches the metrics below exactly.
        if len(curve) > 600:
            step = math.ceil(len(curve) / 600)
            sampled = curve[::step]
            if sampled[-1]["date"] != curve[-1]["date"]:
                sampled.append(curve[-1])
            curve = sampled

        final_equity = curve[-1]["equity"]
        bench_total_return = (final_equity - initial_capital) / initial_capital * 100.0

        peak = initial_capital
        max_dd = 0.0
        for point in curve:
            eq = point["equity"]
            peak = max(peak, eq)
            if peak > 0:
                max_dd = max(max_dd, (peak - eq) / peak * 100.0)

        years = (windowed.index[-1] - windowed.index[0]).days / 365.25
        cagr: float | None = None
        if years > 0:
            cagr = ((final_equity / initial_capital) ** (1.0 / years) - 1.0) * 100.0

        return {
            "curve": curve,
            "metrics": {
                "total_return": round(bench_total_return, 4),
                "cagr": round(cagr, 4) if cagr is not None else None,
                "max_drawdown": round(max_dd, 4),
            },
        }, None
    except Exception:
        logger.debug("portfolio backtest MASI benchmark unavailable", exc_info=True)
        return None, _MASI_BENCHMARK_UNAVAILABLE_WARNING


@router.get(
    "/signal/portfolio-backtest/universe",
    summary="Eligible WFO-trade universe for the portfolio backtest",
)
def get_portfolio_backtest_universe(
    horizon: str = "weekly",
    long_only: bool = True,
    db: Session = Depends(get_db),
):
    trades_by_symbol = _dashboard_best_signal_trades_by_symbol(db, horizon)

    symbols_out: list[dict] = []
    all_open_dates: list[str] = []
    all_close_dates: list[str] = []

    for symbol, trades in trades_by_symbol.items():
        relevant = [t for t in trades if t.get("direction", 1) == 1] if long_only else trades
        if len(relevant) < 3:
            continue
        n_long = sum(1 for t in trades if t.get("direction", 1) == 1)
        n_short = sum(1 for t in trades if t.get("direction", 1) != 1)
        symbols_out.append({
            "symbol": symbol,
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
    """Event-driven chronological walk-forward replay of stitched WFO OOS trades.

    Trades are not pre-filtered by in-sample Kelly (no survivorship bias):
    every symbol's trades enter the replay, and each OPEN event is sized with
    a Kelly fraction estimated only from that symbol's trades already CLOSED
    strictly before that date (or a small starter fraction while history is
    thin). Equity-curve points are stamped at CLOSE events processed in
    chronological order, so the curve is monotonic in time and never credits
    profits from trades that haven't closed yet.
    """
    from datetime import date as _date

    trades_by_symbol = _dashboard_best_signal_trades_by_symbol(db, body.horizon)
    if body.symbols:
        sym_set = set(body.symbols)
        trades_by_symbol = {sym: t for sym, t in trades_by_symbol.items() if sym in sym_set}

    warnings: list[str] = []

    # Build per-symbol relevant-direction trade lists, date-filtered on open_date,
    # each trade tagged with a stable global index (for deterministic tie-break)
    # and TP/SL-clamped effective return (independent of portfolio state).
    symbol_trades: dict[str, list[dict]] = {}
    trade_idx = 0
    for symbol, trades in trades_by_symbol.items():
        relevant = [t for t in trades if t.get("direction", 1) == 1] if body.long_only else list(trades)
        filtered = []
        for t in relevant:
            open_date = t.get("open_date", "")
            if body.start_date and open_date < body.start_date:
                continue
            if body.end_date and open_date > body.end_date:
                continue
            filtered.append(t)
        if not filtered:
            continue
        filtered.sort(key=lambda t: (t.get("open_date", ""), t.get("close_date", "")))
        prepared = []
        for t in filtered:
            pnl_ret = float(t.get("pnl_return", 0.0))
            eff_ret = pnl_ret
            tp = False
            sl = False
            if body.take_profit_pct is not None and eff_ret >= body.take_profit_pct:
                eff_ret = body.take_profit_pct
                tp = True
            if body.stop_loss_pct is not None and eff_ret <= -body.stop_loss_pct:
                eff_ret = -body.stop_loss_pct
                sl = True
            prepared.append({
                **t,
                "symbol": symbol,
                "_idx": trade_idx,
                "pnl_return": pnl_ret,
                "effective_return": eff_ret,
                "tp_applied": tp,
                "sl_applied": sl,
            })
            trade_idx += 1
        symbol_trades[symbol] = prepared

    if not symbol_trades:
        warnings.append("No symbols qualified for the portfolio backtest.")

    # Event list: (date, type_rank, symbol, idx, event_type) — closes (rank 0)
    # before opens (rank 1) on the same date, then symbol/idx for determinism.
    # Exception: a trade whose close_date == open_date must have its own CLOSE
    # ranked after its own OPEN (rank 2), otherwise the close would be
    # processed before the position is even opened and the trade would never
    # execute (cash gets deducted on open but never returned). Trades with
    # close_date < open_date are corrupt and are dropped entirely.
    events: list[tuple[str, int, str, int, str]] = []
    for symbol, trades in list(symbol_trades.items()):
        kept_trades = []
        for t in trades:
            open_date = t.get("open_date", "")
            close_date = t.get("close_date", "")
            if close_date and open_date and close_date < open_date:
                warnings.append(f"{symbol}: trade with close_date before open_date dropped")
                continue
            kept_trades.append(t)
            same_day_close = bool(close_date) and close_date == open_date
            events.append((open_date, 1, symbol, t["_idx"], "open"))
            events.append((close_date, 2 if same_day_close else 0, symbol, t["_idx"], "close"))
        symbol_trades[symbol] = kept_trades
    events.sort(key=lambda e: (e[0], e[1], e[2], e[3]))

    trades_by_key: dict[tuple[str, int], dict] = {
        (symbol, t["_idx"]): t for symbol, trades in symbol_trades.items() for t in trades
    }

    cash = body.initial_capital
    open_positions: dict[tuple[str, int], float] = {}  # (symbol, idx) -> entry cost
    closed_history: dict[str, list[float]] = {sym: [] for sym in symbol_trades}
    last_kelly_pct: dict[str, float] = {}

    # Per-trade result records, seeded in open_date order for stable output ordering.
    trade_records: dict[tuple[str, int], dict] = {}
    for symbol, trades in symbol_trades.items():
        for t in trades:
            trade_records[(symbol, t["_idx"])] = {
                "symbol": symbol,
                "direction": int(t.get("direction", 1)),
                "open_date": t.get("open_date", ""),
                "close_date": t.get("close_date", ""),
                "open_price": float(t.get("open_price", 0.0)),
                "close_price": float(t.get("close_price", 0.0)),
                "pnl_return": float(t.get("pnl_return", 0.0)),
                "effective_return": float(t.get("effective_return", 0.0)),
                "tp_applied": bool(t.get("tp_applied", False)),
                "sl_applied": bool(t.get("sl_applied", False)),
                "position_size": 0,
                "pnl_mad": 0.0,
                "executed": False,
                "skip_reason": None,
            }

    equity_curve: list[dict] = []
    exposure_samples: list[float] = []
    all_event_dates: list[str] = []

    # Accounting-style ledger — two rows per executed trade (open + close),
    # built chronologically alongside the replay so capital/exposure are
    # captured at the exact moment of each event.
    ledger: list[dict] = []
    ledger_truncated = False
    cumulative_realized_pnl = 0.0
    trade_quantity: dict[tuple[str, int], _Optional[float]] = {}

    if events:
        equity_curve.append({"date": events[0][0], "equity": cash})

    for event_date, _rank, symbol, idx, event_type in events:
        key = (symbol, idx)
        t = trades_by_key[key]
        all_event_dates.append(event_date)

        if event_type == "open":
            prior_closed = closed_history[symbol]
            if len(prior_closed) < _PORTFOLIO_STARTER_TRADE_COUNT:
                fraction = 0.05 * body.kelly_multiplier
            else:
                fraction = _kelly_fraction_from_returns(prior_closed, body.kelly_multiplier)
            last_kelly_pct[symbol] = fraction * 100.0

            record = trade_records[key]
            if fraction <= 0:
                record["skip_reason"] = "kelly <= 0"
                continue

            equity = cash + sum(open_positions.values())
            desired_size = round(fraction * equity)
            if desired_size <= 0:
                record["skip_reason"] = "position size 0"
                continue
            if cash <= 0:
                record["skip_reason"] = "insufficient cash"
                continue

            actual_size = min(desired_size, cash)
            if actual_size <= 0:
                record["skip_reason"] = "position size 0"
                continue

            cash -= actual_size
            open_positions[key] = actual_size
            record["position_size"] = float(actual_size)
            record["executed"] = True

            open_price = float(t.get("open_price", 0.0))
            qty = (actual_size / open_price) if open_price > 0 else None
            trade_quantity[key] = qty
            exposure_now_open = sum(open_positions.values())
            capital_now_open = cash + exposure_now_open
            exposition_pct_open = (
                (exposure_now_open / capital_now_open * 100.0) if capital_now_open > 0 else 0.0
            )
            if len(ledger) < _PORTFOLIO_LEDGER_CAP:
                ledger.append({
                    "date": event_date,
                    "symbol": symbol,
                    "side": "Achat" if int(t.get("direction", 1)) == 1 else "Vente à découvert",
                    "quantity": qty,
                    "prix_execution": open_price,
                    "cmp": open_price,
                    "montant": float(actual_size),
                    "pnl_realise": None,
                    "pnl_realise_cumule": round(cumulative_realized_pnl, 2),
                    "capital": round(capital_now_open, 2),
                    "exposition_pct": round(exposition_pct_open, 4),
                })
            else:
                ledger_truncated = True

        else:  # close
            record = trade_records[key]
            # Every closed trade (executed or not) counts toward the symbol's
            # walk-forward realized-return history used for later sizing.
            closed_history[symbol].append(float(t.get("pnl_return", 0.0)))

            if record["executed"]:
                pos_size = open_positions.pop(key, 0.0)
                eff_ret = float(t.get("effective_return", 0.0))
                pnl_mad = pos_size * eff_ret
                cash += pos_size * (1.0 + eff_ret)
                record["pnl_mad"] = float(pnl_mad)
                equity_curve.append({"date": event_date, "equity": cash + sum(open_positions.values())})

                cumulative_realized_pnl += pnl_mad
                qty = trade_quantity.pop(key, None)
                exposure_now_close = sum(open_positions.values())
                capital_now_close = cash + exposure_now_close
                exposition_pct_close = (
                    (exposure_now_close / capital_now_close * 100.0) if capital_now_close > 0 else 0.0
                )
                if len(ledger) < _PORTFOLIO_LEDGER_CAP:
                    ledger.append({
                        "date": event_date,
                        "symbol": symbol,
                        "side": "Vente" if int(t.get("direction", 1)) == 1 else "Rachat",
                        "quantity": qty,
                        "prix_execution": float(t.get("close_price", 0.0)),
                        "cmp": record["open_price"],
                        "montant": float(pos_size * (1.0 + eff_ret)),
                        "pnl_realise": float(pnl_mad),
                        "pnl_realise_cumule": round(cumulative_realized_pnl, 2),
                        "capital": round(capital_now_close, 2),
                        "exposition_pct": round(exposition_pct_close, 4),
                    })
                else:
                    ledger_truncated = True

        exposure_now = sum(open_positions.values())
        equity_now = cash + exposure_now
        exposure_samples.append((exposure_now / equity_now * 100.0) if equity_now > 0 else 0.0)

    # Collapse equity curve to monotonically non-decreasing dates, keeping the
    # last value for any repeated date.
    collapsed_curve: list[dict] = []
    for point in equity_curve:
        if collapsed_curve and collapsed_curve[-1]["date"] == point["date"]:
            collapsed_curve[-1]["equity"] = point["equity"]
        else:
            collapsed_curve.append(dict(point))
    equity_curve = collapsed_curve

    trade_results = list(trade_records.values())
    trade_results.sort(key=lambda r: (r["open_date"], r["symbol"]))

    if open_positions:
        warnings.append(f"{len(open_positions)} position(s) never closed at end of replay")
    final_equity = cash + sum(open_positions.values())
    executed = [t for t in trade_results if t["executed"]]
    n_trades_exec = len(executed)
    total_ret = (
        (final_equity - body.initial_capital) / body.initial_capital * 100.0
        if body.initial_capital else 0.0
    )
    tp_count = sum(1 for t in executed if t["tp_applied"])
    tp_pct = round(tp_count / n_trades_exec * 100.0, 1) if n_trades_exec else 0.0
    sl_count = sum(1 for t in executed if t["sl_applied"])
    sl_pct = round(sl_count / n_trades_exec * 100.0, 1) if n_trades_exec else 0.0

    cagr: _Optional[float] = None
    if executed:
        try:
            d1 = _date.fromisoformat(events[0][0])
            d2 = _date.fromisoformat(max(t["close_date"] for t in executed if t["close_date"]))
            yrs = (d2 - d1).days / 365.25
            if yrs > 0 and body.initial_capital > 0:
                cagr = ((final_equity / body.initial_capital) ** (1.0 / yrs) - 1.0) * 100.0
        except Exception:
            pass

    sharpe: _Optional[float] = None
    if len(equity_curve) >= 2:
        try:
            curve_df = pd.DataFrame(equity_curve)
            curve_df["date"] = pd.to_datetime(curve_df["date"])
            series = curve_df.set_index("date")["equity"]
            series = series[~series.index.duplicated(keep="last")].sort_index()
            axis = pd.to_datetime(sorted(set(all_event_dates)))
            unioned = series.reindex(series.index.union(axis)).ffill()
            on_axis = unioned.reindex(axis)
            weekly = on_axis.groupby(on_axis.index.to_period("W")).last()
            weekly_rets = weekly.pct_change().dropna()
            if len(weekly_rets) >= 8:
                sigma = float(weekly_rets.std(ddof=1))
                if sigma > 0:
                    sharpe = float(weekly_rets.mean()) / sigma * float(np.sqrt(52))
        except Exception:
            logger.debug("portfolio backtest sharpe computation failed", exc_info=True)

    # Max drawdown on the chronological equity curve.
    max_dd = 0.0
    peak = body.initial_capital
    for point in equity_curve:
        eq = point["equity"]
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak * 100.0)

    avg_exposure_pct = float(np.mean(exposure_samples)) if exposure_samples else 0.0
    max_exposure_pct = float(np.max(exposure_samples)) if exposure_samples else 0.0

    per_symbol_out: list[dict] = []
    for symbol, trades in symbol_trades.items():
        sym_records = [trade_records[(symbol, t["_idx"])] for t in trades]
        sym_executed = [r for r in sym_records if r["executed"]]
        n_skipped = len(sym_records) - len(sym_executed)
        if not sym_executed:
            warnings.append(f"{symbol}: no executed trades (capital or Kelly constraints)")
        wins = [r["effective_return"] for r in sym_executed if r["effective_return"] > 0]
        losses = [abs(r["effective_return"]) for r in sym_executed if r["effective_return"] <= 0]
        win_rate = (len(wins) / len(sym_executed) * 100.0) if sym_executed else 0.0
        avg_win_pct = float(np.mean(wins)) * 100.0 if wins else 0.0
        avg_loss_pct = float(np.mean(losses)) * 100.0 if losses else 0.0
        total_pnl_mad = float(sum(r["pnl_mad"] for r in sym_executed))
        n_long = sum(1 for t in trades if t.get("direction", 1) == 1)
        n_short = sum(1 for t in trades if t.get("direction", 1) != 1)
        per_symbol_out.append({
            "symbol": symbol,
            "n_trades": len(sym_executed),
            "n_skipped": n_skipped,
            "n_long": n_long,
            "n_short": n_short,
            "win_rate": win_rate,
            "avg_win_pct": avg_win_pct,
            "avg_loss_pct": avg_loss_pct,
            "kelly_pct": last_kelly_pct.get(symbol, 0.0),
            "total_pnl_mad": total_pnl_mad,
        })

    n_symbols_qualified = sum(1 for s in per_symbol_out if s["n_trades"] > 0)

    period = {
        "start": events[0][0] if events else None,
        "end": max((t["close_date"] for t in executed if t["close_date"]), default=None),
        "requested_start": body.start_date,
        "requested_end": body.end_date,
    }

    trades_truncated = len(trade_results) > 2000
    trades_out = trade_results[:2000]

    # MASI benchmark, rebased to initial_capital over the realized equity-curve
    # window. Degrades to None + a warning when MASI data is unavailable.
    benchmark: _Optional[dict] = None
    if equity_curve:
        benchmark, bench_warning = _portfolio_benchmark(
            db,
            start_date=equity_curve[0]["date"],
            end_date=equity_curve[-1]["date"],
            initial_capital=body.initial_capital,
        )
        if bench_warning:
            warnings.append(bench_warning)
    else:
        warnings.append(_MASI_BENCHMARK_UNAVAILABLE_WARNING)

    # Alpha must compare like with like: MASI history may start after the
    # strategy's first trade, so the strategy return is re-measured over the
    # benchmark's own [first, last] curve window before subtracting.
    alpha_total_return: _Optional[float] = None
    if benchmark is not None:
        b_start = benchmark["curve"][0]["date"]
        b_end = benchmark["curve"][-1]["date"]

        def _equity_at(as_of: str) -> float:
            value = body.initial_capital
            for point in equity_curve:
                if point["date"] <= as_of:
                    value = point["equity"]
                else:
                    break
            return value

        eq_start = _equity_at(b_start)
        eq_end = _equity_at(b_end)
        strategy_window_return = (
            (eq_end / eq_start - 1.0) * 100.0 if eq_start > 0 else 0.0
        )
        alpha_total_return = round(
            strategy_window_return - benchmark["metrics"]["total_return"], 4
        )
        benchmark["window"] = {
            "start": b_start,
            "end": b_end,
            "strategy_total_return": round(strategy_window_return, 4),
        }

    ledger_out = ledger[:_PORTFOLIO_LEDGER_CAP]

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
            "sl_applied_pct": sl_pct,
            "avg_exposure_pct": round(avg_exposure_pct, 4),
            "max_exposure_pct": round(max_exposure_pct, 4),
            "alpha_total_return": alpha_total_return,
        },
        "per_symbol": per_symbol_out,
        "n_symbols_qualified": n_symbols_qualified,
        "warnings": warnings,
        "trades": trades_out,
        "trades_truncated": trades_truncated,
        "period": period,
        "benchmark": benchmark,
        "ledger": ledger_out,
        "ledger_truncated": ledger_truncated,
    }
