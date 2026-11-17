"""
backfill_bourse_history.py - gap audit + backfill of Casablanca stock/index daily bars
from the boursenova API.

Exchange calendar = MASI session dates (3-year window). For every tracked stock / active
index the stored series is compared with the exchange series:

* missing      : a calendar session between the first stored bar and today that is absent
                 from the store AND present on the exchange  -> real gap
* exchange_absent : absent from the store and the exchange feed has no row for that
                 instrument (suspended / untraded)             -> not a gap
* mismatches   : stored close differs from the exchange close on a shared date

``apply`` inserts missing dates older than REFRESH_LOOKBACK_DAYS (never overwrites an old
stored bar - it may come from another provider/adjustment; mismatches are only reported)
and applies normal overwrite-if-different inside the lookback window.

Entry points: ``run_backfill`` (library / CLI via scripts/backfill_bourse_history.py) and
``run_backfill_job`` (RQ task, market_refresh queue).
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Iterable

import pandas as pd
from sqlalchemy import text

from core.quant_core.data import (
    BOURSENOVA_APP_SYMBOL_TO_CODE,
    BoursenovaHistoryAdapter,
    BoursenovaIndicesAdapter,
    _standardize_ohlcv_index,
    clamp_boursenova_window,
    boursenova_today,
)
from core.quant_core.s3_keys import build_market_store_object_key
from services.worker.db import SessionLocal
from services.worker.tasks.ingest_market_data import (
    _merge_overwrite_if_different,
    _save_parquet,
    _try_load_existing_parquet,
)
from services.worker.tasks.refresh_market_data import (
    _align_tz,
    _persist_stock_frame,
    _upsert_market_data_store_index,
    refresh_lookback_days,
    synthesize_index_open,
)

logger = logging.getLogger(__name__)

STOCK_KEEP_COLS = ["Open", "High", "Low", "Close", "Volume", "NombreTitres"]
MAX_LISTED_DATES = 200

# Weekly chain dispatched after a backfill, in dependency order (see scheduler_registry).
DOWNSTREAM_SCHEDULES = (
    "weekly_fundamental_beta_refresh",
    "weekly_fundamental_cross_section",
    "weekly_value_strategy_refresh",
    "weekly_wfo_dispatch",
    "weekly_signal_backtest_dispatch",
    "weekly_signal_history_dispatch",
    "weekly_signal_best_evidence_snapshot",
    "weekly_pit_opportunity_materialization",
    "daily_dashboard_snapshot",
)


def _dates(frame: pd.DataFrame | None) -> set[datetime.date]:
    if frame is None or frame.empty:
        return set()
    return {ts.date() for ts in frame.index}


def audit_series(
    old: pd.DataFrame | None,
    exchange: pd.DataFrame | None,
    calendar: set[datetime.date],
    *,
    today: datetime.date,
    lookback_days: int,
) -> dict[str, Any]:
    """Compare a stored series with the exchange series; pure (no I/O)."""
    stored = _dates(old)
    exch = _dates(exchange)
    floor, _ = clamp_boursenova_window(None, None, today=today)
    cutoff = today - datetime.timedelta(days=lookback_days)

    first = max(min(stored), floor) if stored else (min(exch) if exch else None)
    expected = {d for d in calendar if first is not None and first <= d <= today}
    missing_all = expected - stored
    real = sorted(missing_all & exch)
    absent = sorted(missing_all - exch)

    mismatches: list[dict[str, Any]] = []
    if old is not None and exchange is not None and not old.empty and not exchange.empty:
        o = old["Close"].copy()
        o.index = [ts.date() for ts in o.index]
        e = exchange["Close"].copy()
        e.index = [ts.date() for ts in e.index]
        o = o[~o.index.duplicated(keep="last")]
        e = e[~e.index.duplicated(keep="last")]
        common = o.index.intersection(e.index)
        for d in common:
            sv, ev = float(o[d]), float(e[d])
            if abs(sv - ev) > max(0.01, 1e-6 * abs(ev)):
                mismatches.append({"date": d.isoformat(), "stored": sv, "exchange": ev})

    old_mm = [m for m in mismatches if datetime.date.fromisoformat(m["date"]) < cutoff]
    return {
        "stored_rows": len(stored),
        "exchange_rows": len(exch),
        "first_stored": min(stored).isoformat() if stored else None,
        "last_stored": max(stored).isoformat() if stored else None,
        "missing_count": len(real),
        "first_missing": real[0].isoformat() if real else None,
        "last_missing": real[-1].isoformat() if real else None,
        "missing_dates": [d.isoformat() for d in real[:MAX_LISTED_DATES]],
        "exchange_absent_count": len(absent),
        "exchange_absent_dates": [d.isoformat() for d in absent[:MAX_LISTED_DATES]],
        "mismatch_count": len(mismatches),
        "mismatch_older_than_lookback": len(old_mm),
        "mismatch_sample": mismatches[:10],
    }


def plan_incoming(
    old: pd.DataFrame | None,
    exchange: pd.DataFrame,
    *,
    today: datetime.date,
    lookback_days: int,
) -> pd.DataFrame:
    """Rows to merge: everything inside the lookback window (overwrite-if-different) plus
    exchange rows for dates older than the window that the store lacks (insert-only).
    Dates before the first stored bar are not prepended."""
    cutoff = today - datetime.timedelta(days=lookback_days)
    day = pd.Series([ts.date() for ts in exchange.index], index=exchange.index)
    recent = day >= cutoff
    if old is None or old.empty:
        return exchange
    stored = _dates(old)
    first = min(stored)
    older_missing = (~recent) & (~day.isin(stored)) & (day >= first)
    return exchange[recent | older_missing]


def _stock_exchange_frame(adapter: BoursenovaHistoryAdapter, symbol: str) -> pd.DataFrame:
    frame = adapter.load([symbol], start=None, end=None, interval="1d").bars.get(symbol)
    if frame is None or frame.empty:
        return pd.DataFrame()
    return frame[[c for c in STOCK_KEEP_COLS if c in frame.columns]]


def _index_exchange_frame(
    adapter: BoursenovaIndicesAdapter, symbol: str, old: pd.DataFrame | None
) -> pd.DataFrame:
    raw = adapter.fetch([symbol]).get(symbol)
    if raw is None or raw.empty:
        return pd.DataFrame()
    return synthesize_index_open(old, _standardize_ohlcv_index(raw.drop(columns=["display_name"], errors="ignore")))


def _existing_provider(db, symbol: str, default: str) -> str:
    try:
        row = db.execute(
            text("SELECT source_provider FROM market_data_store WHERE symbol = :s AND timeframe = '1D'"),
            {"s": symbol},
        ).first()
        return str(row[0]) if row and row[0] else default
    except Exception:
        db.rollback()
        return default


def _process(
    db,
    *,
    symbol: str,
    kind: str,
    exchange_loader,
    calendar: set[datetime.date],
    today: datetime.date,
    lookback: int,
    apply: bool,
) -> dict[str, Any]:
    object_key = build_market_store_object_key(symbol, "1D")
    old = _try_load_existing_parquet(object_key)
    exchange = exchange_loader(old)
    entry: dict[str, Any] = {"kind": kind, **audit_series(old, exchange, calendar, today=today, lookback_days=lookback)}
    entry["inserted"] = entry["overwritten"] = 0
    if not apply or exchange is None or exchange.empty:
        return entry

    incoming = plan_incoming(old, exchange, today=today, lookback_days=lookback)
    merged, summary = _merge_overwrite_if_different(old, _align_tz(incoming, old))
    entry["inserted"] = summary["inserted_count"]
    entry["overwritten"] = summary["overwritten_overlap_count"]
    if summary["status"] != "unchanged":
        _save_parquet(object_key, merged)
        if kind == "stock":
            _persist_stock_frame(db, symbol, "1D", object_key, merged, _existing_provider(db, symbol, "bourse_direct"))
        else:
            _upsert_market_data_store_index(
                db=db,
                symbol=symbol,
                object_key=object_key,
                start_ts=merged.index.min().to_pydatetime(),
                end_ts=merged.index.max().to_pydatetime(),
                row_count=int(len(merged)),
                source_provider=_existing_provider(db, symbol, "casablanca_bourse"),
                data_as_of=merged.index.max().date(),
            )
        db.commit()
    return entry


def enqueue_downstream(db, updated_stocks: list[str]) -> dict[str, Any]:
    """Enqueue the post-refresh signal chain for changed stocks, then dispatch the weekly chain."""
    from services.worker.tasks import refresh_market_data as rmd
    from services.worker.tasks.scheduler_dispatch import dispatch_schedule

    out: dict[str, Any] = {"signal_jobs": 0, "schedules": {}}
    signal_jobs: list[str] = []
    for sym in updated_stocks:
        signal_jobs.extend(rmd._enqueue_signal_layers_after_refresh(sym, db=db))
    out["signal_jobs"] = len(signal_jobs)
    if updated_stocks:
        out["dashboard_snapshot_job"] = rmd._enqueue_dashboard_snapshot_after_signal_jobs(
            signal_jobs, symbols=updated_stocks, triggered_by="bourse_backfill"
        )
        out["best_evidence_job"] = rmd._enqueue_best_evidence_snapshot_after_signal_jobs(
            signal_jobs, symbols=updated_stocks, triggered_by="bourse_backfill"
        )
    for schedule_id in DOWNSTREAM_SCHEDULES:
        try:
            res = dispatch_schedule(schedule_id, trigger_source="bourse_backfill")
            out["schedules"][schedule_id] = {"status": res.get("status"), "enqueued_jobs": res.get("enqueued_jobs")}
        except Exception as exc:
            out["schedules"][schedule_id] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    return out


def run_backfill(
    *,
    apply: bool = False,
    symbols: Iterable[str] | None = None,
    stocks: bool = True,
    indices: bool = True,
    downstream: bool = False,
    db=None,
) -> dict[str, Any]:
    """Audit (default) or repair stored daily bars. Returns the JSON-serialisable report."""
    own_db = db is None
    db = db or SessionLocal()
    today = boursenova_today()
    lookback = refresh_lookback_days()
    wanted = {s.strip().upper() for s in symbols} if symbols else None
    report: dict[str, Any] = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mode": "apply" if apply else "dry-run",
        "today": today.isoformat(),
        "lookback_days": lookback,
        "symbols": {},
        "errors": {},
    }
    try:
        idx_adapter = BoursenovaIndicesAdapter()
        floor, _ = clamp_boursenova_window(None, None, today=today)
        masi = idx_adapter.fetch(["MASI"], start=floor, end=today).get("MASI")
        calendar = _dates(masi)
        report["calendar_sessions"] = len(calendar)
        if not calendar:
            raise RuntimeError("exchange calendar (MASI) unavailable; refusing to audit")

        jobs: list[tuple[str, str]] = []
        if stocks:
            rows = db.execute(
                text(
                    "SELECT symbol FROM stock_master WHERE is_active = true "
                    "AND track_source IN ('bourse_direct', 'bmce_excel') ORDER BY symbol"
                )
            ).all()
            jobs += [("stock", str(r[0])) for r in rows]
        if indices:
            rows = db.execute(text("SELECT symbol FROM index_master WHERE is_active = true ORDER BY symbol")).all()
            jobs += [("index", str(r[0])) for r in rows]

        stock_adapter = BoursenovaHistoryAdapter(timezone="UTC", use_cache=False)
        for kind, sym in jobs:
            if wanted is not None and sym.upper() not in wanted:
                continue
            try:
                if kind == "stock":
                    loader = lambda old, s=sym: _stock_exchange_frame(stock_adapter, s)  # noqa: E731
                else:
                    if sym not in BOURSENOVA_APP_SYMBOL_TO_CODE:
                        report["symbols"][sym] = {"kind": kind, "status": "no_boursenova_code"}
                        continue
                    loader = lambda old, s=sym: _index_exchange_frame(idx_adapter, s, old)  # noqa: E731
                report["symbols"][sym] = _process(
                    db, symbol=sym, kind=kind, exchange_loader=loader, calendar=calendar,
                    today=today, lookback=lookback, apply=apply,
                )
            except Exception as exc:
                db.rollback()
                report["errors"][sym] = f"{type(exc).__name__}: {exc}"
                logger.exception("bourse backfill failed for %s", sym)

        entries = [e for e in report["symbols"].values() if "missing_count" in e]
        report["summary"] = {
            "instruments": len(entries),
            "with_gaps": sum(1 for e in entries if e["missing_count"]),
            "missing_total": sum(e["missing_count"] for e in entries),
            "exchange_absent_total": sum(e["exchange_absent_count"] for e in entries),
            "mismatch_total": sum(e["mismatch_count"] for e in entries),
            "inserted_total": sum(e["inserted"] for e in entries),
            "overwritten_total": sum(e["overwritten"] for e in entries),
            "errors": len(report["errors"]),
        }
        if apply and downstream:
            changed = [s for s, e in report["symbols"].items()
                       if e.get("kind") == "stock" and (e.get("inserted") or e.get("overwritten"))]
            report["downstream"] = enqueue_downstream(db, changed)
        return report
    finally:
        if own_db:
            db.close()


def run_backfill_job(
    apply: bool = False,
    symbols: list[str] | None = None,
    stocks: bool = True,
    indices: bool = True,
    downstream: bool = False,
) -> dict[str, Any]:
    """RQ entry point (market_refresh queue): same as ``run_backfill`` with a trimmed result."""
    report = run_backfill(apply=apply, symbols=symbols, stocks=stocks, indices=indices, downstream=downstream)
    for entry in report["symbols"].values():  # keep the RQ result small; full detail via the CLI
        for key in ("missing_dates", "exchange_absent_dates", "mismatch_sample"):
            entry.pop(key, None)
    return report


def render_table(report: dict[str, Any]) -> str:
    """Per-symbol text table of the gap report."""
    head = f"{'symbol':<14}{'kind':<6}{'stored':>7}{'exch':>6}{'missing':>8}{'first_missing':>15}{'last_missing':>14}{'absent':>7}{'mism':>6}{'ins':>5}{'ovw':>5}"
    lines = [head, "-" * len(head)]
    for sym, e in sorted(report["symbols"].items()):
        if "missing_count" not in e:
            lines.append(f"{sym:<14}{e.get('kind', ''):<6}{e.get('status', '')}")
            continue
        lines.append(
            f"{sym:<14}{e['kind']:<6}{e['stored_rows']:>7}{e['exchange_rows']:>6}{e['missing_count']:>8}"
            f"{(e['first_missing'] or '-'):>15}{(e['last_missing'] or '-'):>14}{e['exchange_absent_count']:>7}"
            f"{e['mismatch_count']:>6}{e['inserted']:>5}{e['overwritten']:>5}"
        )
    for sym, err in report.get("errors", {}).items():
        lines.append(f"{sym:<14}ERROR {err}")
    lines.append("summary: " + ", ".join(f"{k}={v}" for k, v in report.get("summary", {}).items()))
    return "\n".join(lines)
