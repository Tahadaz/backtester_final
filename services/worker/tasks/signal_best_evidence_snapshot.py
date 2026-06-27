"""Materialize stored best WFO signal evidence for the signal page."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from core.quant_core.horizons import canonical_horizon
from services.api.app.models import MarketDataStore, SignalBestEvidenceSnapshot
from services.api.app.services.dashboard_builder import _build_best_signal_payload
from services.api.app.services.market_universe import list_signal_universe_symbols
from services.worker.db import SessionLocal

logger = logging.getLogger(__name__)

HORIZONS = ("weekly", "monthly", "quarterly")


def _require_canonical_signal_horizon(horizon: str) -> str:
    return canonical_horizon(horizon, allow_legacy=False)


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _payload_data_as_of(evidence_payload: dict[str, Any], chart_payload: dict[str, Any] | None) -> date | None:
    if chart_payload:
        results = chart_payload.get("results")
        if isinstance(results, list) and results:
            row = results[0]
            if isinstance(row, dict):
                chart_date = _coerce_date(row.get("data_as_of"))
                if chart_date is not None:
                    return chart_date
    current = evidence_payload.get("current_signal")
    if isinstance(current, dict):
        signal_date = _coerce_date(current.get("data_as_of"))
        if signal_date is not None:
            return signal_date
    return None


def _market_data_as_of(db: Session, symbol: str) -> date | None:
    row = db.query(MarketDataStore).filter_by(symbol=symbol, timeframe="1D").first()
    return _coerce_date(getattr(row, "data_as_of", None)) if row is not None else None


def _select_wfo_best_variant(db: Session, symbol: str, horizon: str) -> str | None:
    best = _build_best_signal_payload(db, symbol, horizon)
    if isinstance(best, dict) and str(best.get("source") or "") == "wfo":
        variant = str(best.get("variant") or "").strip()
        return variant or None
    return None


def _upsert_snapshot(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    cooldown_bars: int,
    evidence_payload: dict[str, Any],
    chart_payload: dict[str, Any] | None,
) -> None:
    selected_variant = str(evidence_payload.get("variant") or "").strip() or "expanded_ta_simple"
    selected_source = str(evidence_payload.get("source") or "").strip() or "wfo"
    chart_row = None
    if chart_payload:
        results = chart_payload.get("results")
        if isinstance(results, list) and results:
            chart_row = results[0] if isinstance(results[0], dict) else None

    row = (
        db.query(SignalBestEvidenceSnapshot)
        .filter_by(symbol=symbol, horizon=horizon, cooldown_bars=cooldown_bars)
        .first()
    )
    if row is None:
        row = SignalBestEvidenceSnapshot(symbol=symbol, horizon=horizon, cooldown_bars=cooldown_bars)
        db.add(row)

    data_as_of = _payload_data_as_of(evidence_payload, chart_payload) or _market_data_as_of(db, symbol)
    market_data_as_of = _market_data_as_of(db, symbol)
    row.status = "succeeded"
    row.source = selected_source
    row.variant = selected_variant
    row.scope = str((chart_row or {}).get("scope") or "global")
    row.scope_key = str((chart_row or {}).get("scope_key") or "global")
    row.side_policy = str((chart_row or {}).get("side_policy") or "long_short")
    row.evidence_payload_jsonb = evidence_payload
    row.chart_payload_jsonb = chart_payload
    row.upstream_rev = {
        "symbol": symbol,
        "horizon": horizon,
        "variant": selected_variant,
        "data_as_of": data_as_of.isoformat() if data_as_of else None,
        "market_data_as_of": market_data_as_of.isoformat() if market_data_as_of else None,
    }
    row.data_as_of = data_as_of
    row.market_data_as_of = market_data_as_of
    row.error_message = None
    row.computed_at = datetime.now(timezone.utc)


def _mark_snapshot_failed(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    cooldown_bars: int,
    error_message: str,
) -> None:
    row = (
        db.query(SignalBestEvidenceSnapshot)
        .filter_by(symbol=symbol, horizon=horizon, cooldown_bars=cooldown_bars)
        .first()
    )
    if row is None:
        row = SignalBestEvidenceSnapshot(
            symbol=symbol,
            horizon=horizon,
            cooldown_bars=cooldown_bars,
            variant="expanded_ta_simple",
        )
        db.add(row)
    row.status = "failed"
    row.error_message = error_message[:4000]
    row.computed_at = datetime.now(timezone.utc)


def refresh_signal_best_evidence_for_symbol(
    symbol: str,
    horizon: str,
    cooldown_bars: int = 0,
    *,
    include_sr_overlay: bool = True,
) -> dict[str, Any]:
    from services.api.app.routers.strategy_signals import (
        _build_signal_evidence_payload,
        build_stored_best_backtest_chart_payload,
    )

    symbol_upper = symbol.strip().upper()
    canonical_h = _require_canonical_signal_horizon(horizon)
    cooldown = max(0, min(252, int(cooldown_bars or 0)))
    db: Session = SessionLocal()
    try:
        preferred_variant = _select_wfo_best_variant(db, symbol_upper, canonical_h)
        evidence_payload = _build_signal_evidence_payload(
            db,
            symbol=symbol_upper,
            horizon=canonical_h,
            source="wfo",
            variant=preferred_variant,
            cooldown_bars=cooldown,
            include_sr_overlay=include_sr_overlay,
        )
        selected_variant = str(evidence_payload.get("variant") or preferred_variant or "expanded_ta_simple")
        chart_payload = build_stored_best_backtest_chart_payload(
            db,
            symbol=symbol_upper,
            horizon=canonical_h,
            variant=selected_variant,
            cooldown_bars=cooldown,
            scope="global",
            scope_key="global",
        )
        _upsert_snapshot(
            db,
            symbol=symbol_upper,
            horizon=canonical_h,
            cooldown_bars=cooldown,
            evidence_payload=evidence_payload,
            chart_payload=chart_payload,
        )
        db.commit()
        return {
            "symbol": symbol_upper,
            "horizon": canonical_h,
            "variant": selected_variant,
            "status": "succeeded",
            "has_chart": chart_payload is not None,
        }
    except Exception as exc:
        logger.exception("best signal evidence snapshot failed", extra={"symbol": symbol_upper, "horizon": canonical_h})
        try:
            db.rollback()
            _mark_snapshot_failed(
                db,
                symbol=symbol_upper,
                horizon=canonical_h,
                cooldown_bars=cooldown,
                error_message=str(exc),
            )
            db.commit()
        except Exception:
            db.rollback()
        return {"symbol": symbol_upper, "horizon": canonical_h, "status": "failed", "error": str(exc)}
    finally:
        db.close()


def refresh_signal_best_evidence_snapshot(
    symbol: str | None = None,
    horizon: str | None = None,
    cooldown_bars: int = 0,
    *,
    include_sr_overlay: bool = True,
) -> dict[str, Any]:
    db: Session = SessionLocal()
    try:
        symbols = [symbol.strip().upper()] if symbol else list_signal_universe_symbols(db)
    finally:
        db.close()

    horizons = [_require_canonical_signal_horizon(horizon)] if horizon else list(HORIZONS)
    results = [
        refresh_signal_best_evidence_for_symbol(
            item,
            h,
            cooldown_bars,
            include_sr_overlay=include_sr_overlay,
        )
        for item in symbols
        for h in horizons
        if item
    ]
    succeeded = sum(1 for item in results if item.get("status") == "succeeded")
    failed = len(results) - succeeded
    return {
        "status": "succeeded" if failed == 0 else "partial" if succeeded else "failed",
        "symbols": len(symbols),
        "horizons": horizons,
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "results_sample": results[:20],
    }
