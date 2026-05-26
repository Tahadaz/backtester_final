from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Any

from core.quant_core.fundamentals.domain import FundamentalWorkbook
from core.quant_core.fundamentals.providers import ProviderUnavailableError
from core.quant_core.fundamentals.providers.stockanalysis_provider import StockAnalysisFundamentalProvider

from services.api.app import models
from services.api.app.json_sanitize import sanitize_json_compatible
from services.api.app.services.fundamentals import (
    _build_integrity_reports,
    _persist_integrity_reports,
    create_import_run,
    latest_snapshot_rows_by_symbol,
    make_bulk_overrides_loader,
    persist_pillar_history_for_import,
    recompute_symbol_valuations_all_scenarios,
    rescore_universe,
)
from services.worker.db import SessionLocal


logger = logging.getLogger(__name__)

NON_STOCK_SYMBOLS = {"INSTRUMENT", "MAJ", "MAJJ", "WORKSHEET"}


def _utcnow():
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc)


def _selected_stocks(db, symbols: list[str] | None) -> list[models.StockMaster]:
    wanted = sorted({symbol.strip().upper() for symbol in symbols or [] if symbol and symbol.strip()} - NON_STOCK_SYMBOLS)
    query = db.query(models.StockMaster).filter(
        models.StockMaster.is_active.is_(True),
        models.StockMaster.market_region == "masi",
        ~models.StockMaster.symbol.in_(NON_STOCK_SYMBOLS),
    )
    if wanted:
        query = query.filter(models.StockMaster.symbol.in_(wanted))
    return query.order_by(models.StockMaster.symbol.asc()).all()


def _missing_coverage_symbols(
    db,
    *,
    symbols: list[str] | None = None,
    min_latest_metrics: int = 40,
    min_annual_nonnull: int = 180,
    min_years: int = 4,
) -> list[str]:
    stocks = _selected_stocks(db, symbols)
    stock_symbols = [str(row.symbol).upper() for row in stocks]
    latest = latest_snapshot_rows_by_symbol(db, symbols=stock_symbols, scope="masi")
    missing: list[str] = []
    for symbol in stock_symbols:
        snapshot = latest.get(symbol)
        if snapshot is None:
            missing.append(symbol)
            continue
        latest_count = sum(value is not None for value in (snapshot.metrics_json or {}).values())
        annual_nonnull = (
            db.query(models.FundamentalAnnualMetric)
            .filter(
                models.FundamentalAnnualMetric.import_id == snapshot.import_id,
                models.FundamentalAnnualMetric.symbol == symbol,
                models.FundamentalAnnualMetric.metric_value.isnot(None),
            )
            .count()
        )
        years = {
            int(row[0])
            for row in db.query(models.FundamentalAnnualMetric.statement_year)
            .filter(
                models.FundamentalAnnualMetric.import_id == snapshot.import_id,
                models.FundamentalAnnualMetric.symbol == symbol,
            )
            .all()
            if row[0] is not None
        }
        if latest_count < min_latest_metrics or annual_nonnull < min_annual_nonnull or len(years) < min_years:
            missing.append(symbol)
    return missing


def _persist_workbook(db, import_id: uuid.UUID, workbook: FundamentalWorkbook, *, data_source: str) -> None:
    db.add_all(
        [
            models.FundamentalCompanyMap(
                import_id=import_id,
                company_name=mapping.company_name,
                mapped_company_name=mapping.mapped_company_name,
                canonical_company_name=mapping.canonical_company_name,
                symbol=mapping.symbol,
                shares_outstanding=mapping.shares_outstanding,
                match_type=mapping.match_type,
                score_note=mapping.score_note,
                source=mapping.source,
                is_duplicate_symbol=mapping.is_duplicate_symbol,
            )
            for mapping in workbook.mappings
        ]
    )
    db.add_all(
        [
            models.FundamentalAnnualMetric(
                import_id=import_id,
                symbol=row.symbol,
                company_name=row.company_name,
                statement_year=row.statement_year,
                metric_name=row.metric_name,
                metric_value=row.metric_value,
                raw_metric_name=row.raw_metric_name,
                source_sheet=row.source_sheet,
                source_field=row.source_field,
                is_proxy=row.is_proxy,
            )
            for row in workbook.annual_metrics
        ]
    )
    db.add_all(
        [
            models.FundamentalQualityIssue(
                import_id=import_id,
                severity=issue.severity,
                code=issue.code,
                message=issue.message,
                symbol=issue.symbol,
                metric_name=issue.metric_name,
                statement_year=issue.statement_year,
                context_json=sanitize_json_compatible(issue.context),
            )
            for issue in workbook.quality_issues
        ]
    )
    db.add_all(
        [
            models.FundamentalLatestSnapshot(
                import_id=import_id,
                symbol=snapshot.symbol,
                company_name=snapshot.company_name,
                latest_statement_year=snapshot.latest_statement_year,
                data_source=data_source,
                metrics_json=sanitize_json_compatible(snapshot.metrics),
                scores_json={"status": "pending_rescore"},
                diagnostics_json=sanitize_json_compatible(snapshot.diagnostics),
                coverage_json=sanitize_json_compatible(snapshot.coverage),
                model_eligibility_json={},
                source_json=sanitize_json_compatible(snapshot.source),
            )
            for snapshot in workbook.latest_snapshots
        ]
    )
    _persist_integrity_reports(db, import_id=import_id, reports=_build_integrity_reports(workbook.annual_metrics))


def _enqueue_dashboard_snapshot(import_id: uuid.UUID, symbols: list[str]) -> str | None:
    try:
        from redis import Redis
        from rq import Queue

        from services.worker.config import settings

        queue = Queue(settings.MARKET_REFRESH_QUEUE_NAME, connection=Redis.from_url(settings.REDIS_URL))
        job = queue.enqueue(
            "services.worker.tasks.dashboard_snapshot.refresh_dashboard_snapshot",
            None,
            job_timeout=3600,
            meta={
                "triggered_by": "stockanalysis_fundamentals",
                "fundamental_import_id": str(import_id),
                "updated_symbols_count": len(symbols),
            },
        )
        return str(job.id)
    except Exception:
        logger.debug("dashboard snapshot enqueue after stockanalysis fundamentals failed", exc_info=True)
        return None


def refresh_stockanalysis_universe(
    symbols: list[str] | None = None,
    *,
    missing_only: bool = False,
    triggered_by: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    db = SessionLocal()
    batch_id = batch_id or str(uuid.uuid4())
    started = time.perf_counter()
    try:
        selected_symbols = _missing_coverage_symbols(db, symbols=symbols) if missing_only else symbols
        if missing_only and not selected_symbols:
            return {
                "batch_id": batch_id,
                "import_id": None,
                "status": "skipped",
                "succeeded": 0,
                "failed": 0,
                "reason": "no_missing_masi_fundamental_coverage",
            }
        stocks = _selected_stocks(db, selected_symbols)
        if not stocks:
            return {
                "batch_id": batch_id,
                "import_id": None,
                "status": "skipped",
                "succeeded": 0,
                "failed": 0,
                "reason": "no_active_masi_symbols",
            }

        digest = hashlib.sha256(("stockanalysis:" + batch_id + ":" + ",".join(stock.symbol for stock in stocks)).encode("utf-8")).hexdigest()
        run = create_import_run(
            db,
            data_source="stockanalysis",
            source_universe="masi",
            filename=f"stockanalysis_fundamentals_{batch_id}",
            source_hash=digest,
            summary={
                "batch_id": batch_id,
                "triggered_by": triggered_by,
                "symbols": [stock.symbol for stock in stocks],
                "missing_only": missing_only,
            },
        )
        run.status = "running"
        run.imported_at = _utcnow()
        db.add(run)
        db.commit()

        provider = StockAnalysisFundamentalProvider()
        succeeded: list[str] = []
        failed: dict[str, str] = {}
        for index, stock in enumerate(stocks):
            if index > 0:
                time.sleep(1.0)
            try:
                workbook = provider.fetch(
                    stock.symbol,
                    display_name=stock.display_name,
                    market_region=stock.market_region,
                    shares_outstanding=stock.shares_outstanding,
                )
                _persist_workbook(db, run.id, workbook, data_source="stockanalysis")
                succeeded.append(stock.symbol)
                db.flush()
            except ProviderUnavailableError as exc:
                failed[stock.symbol] = str(exc)
                db.add(
                    models.FundamentalQualityIssue(
                        import_id=run.id,
                        severity="error",
                        code="stockanalysis_symbol_failed",
                        message=str(exc),
                        symbol=stock.symbol,
                        context_json={"batch_id": batch_id, "market_region": stock.market_region},
                    )
                )
                db.flush()
            except Exception as exc:
                failed[stock.symbol] = str(exc)
                db.add(
                    models.FundamentalQualityIssue(
                        import_id=run.id,
                        severity="error",
                        code="stockanalysis_symbol_failed",
                        message=str(exc),
                        symbol=stock.symbol,
                        context_json={"batch_id": batch_id, "market_region": stock.market_region},
                    )
                )
                db.flush()

        run.symbol_count = len(succeeded)
        run.company_count = len(succeeded)
        run.annual_metric_count = (
            db.query(models.FundamentalAnnualMetric)
            .filter(models.FundamentalAnnualMetric.import_id == run.id)
            .count()
        )
        run.latest_snapshot_count = len(succeeded)
        run.quality_issue_count = (
            db.query(models.FundamentalQualityIssue)
            .filter(models.FundamentalQualityIssue.import_id == run.id)
            .count()
        )
        run.summary_json = sanitize_json_compatible(
            {
                **dict(run.summary_json or {}),
                "succeeded": succeeded,
                "failed": failed,
                "elapsed_seconds": round(time.perf_counter() - started, 2),
            }
        )
        run.completed_at = _utcnow()
        if succeeded and failed:
            run.status = "partial"
        elif succeeded:
            run.status = "succeeded"
        else:
            run.status = "failed"
            run.error_message = "All StockAnalysis symbols failed"
        db.add(run)
        db.commit()

        if succeeded:
            rescore_universe(db, scope="masi")
            persist_pillar_history_for_import(db, import_id=run.id)
            db.commit()
            overrides_loader = make_bulk_overrides_loader(db, succeeded)
            for symbol in succeeded:
                recompute_symbol_valuations_all_scenarios(
                    db,
                    import_id=run.id,
                    symbol=symbol,
                    overrides_loader=overrides_loader,
                )
            db.commit()
            try:
                from services.api.app.services.fundamental_signal_engine import upsert_fundamental_signal_rows

                upsert_fundamental_signal_rows(db, symbols=succeeded)
                db.commit()
            except Exception:
                logger.debug("fundamental signal row sync failed", exc_info=True)
                db.rollback()

        dashboard_snapshot_job_id = _enqueue_dashboard_snapshot(run.id, succeeded) if succeeded else None
        return {
            "batch_id": batch_id,
            "import_id": str(run.id),
            "status": run.status,
            "succeeded": len(succeeded),
            "failed": len(failed),
            "dashboard_snapshot_job_id": dashboard_snapshot_job_id,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
        }
    finally:
        db.close()


def refresh_stockanalysis_for_symbol(symbol: str, triggered_by: str | None = None) -> dict[str, Any]:
    return refresh_stockanalysis_universe(symbols=[symbol], triggered_by=triggered_by or "manual")
