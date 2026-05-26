from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Any

from core.quant_core.fundamentals.domain import FundamentalWorkbook
from core.quant_core.fundamentals.providers import ProviderUnavailableError, UnmappedSymbolError
from core.quant_core.fundamentals.providers.yfinance_provider import YfinanceFundamentalProvider

from services.api.app import models
from services.api.app.json_sanitize import sanitize_json_compatible
from services.api.app.services.fundamentals import (
    _build_integrity_reports,
    _persist_integrity_reports,
    create_import_run,
    make_bulk_overrides_loader,
    persist_pillar_history_for_import,
    recompute_symbol_valuations_all_scenarios,
    rescore_universe,
)
from services.worker.db import SessionLocal


logger = logging.getLogger(__name__)


def _utcnow():
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc)


def _selected_stocks(db, *, symbols: list[str] | None, market_regions: list[str] | None) -> list[models.StockMaster]:
    query = db.query(models.StockMaster).filter(models.StockMaster.is_active.is_(True))
    if symbols:
        query = query.filter(models.StockMaster.symbol.in_([symbol.upper() for symbol in symbols]))
    else:
        regions = market_regions or ["us", "european", "asian"]
        query = query.filter(models.StockMaster.market_region.in_(regions))
    return query.order_by(models.StockMaster.symbol.asc()).all()


def _provider_symbol(db, stock: models.StockMaster) -> str:
    row = (
        db.query(models.ProviderSymbolMap)
        .filter(models.ProviderSymbolMap.symbol == stock.symbol, models.ProviderSymbolMap.provider == "yahoo")
        .first()
    )
    if row is not None and row.provider_symbol:
        return str(row.provider_symbol)
    if str(stock.market_region or "").lower() == "us":
        return stock.symbol
    raise UnmappedSymbolError(f"No yahoo provider mapping for {stock.symbol}")


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


def refresh_yfinance_universe(
    symbols: list[str] | None = None,
    market_regions: list[str] | None = None,
    triggered_by: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    db = SessionLocal()
    batch_id = batch_id or str(uuid.uuid4())
    started = time.perf_counter()
    try:
        stocks = _selected_stocks(db, symbols=symbols, market_regions=market_regions)
        digest = hashlib.sha256(("yfinance:" + batch_id + ":" + ",".join(stock.symbol for stock in stocks)).encode("utf-8")).hexdigest()
        run = create_import_run(
            db,
            data_source="yfinance",
            source_universe="non_masi",
            filename=f"yfinance_fundamentals_{batch_id}",
            source_hash=digest,
            summary={"batch_id": batch_id, "triggered_by": triggered_by, "market_regions": market_regions or []},
        )
        run.status = "running"
        run.imported_at = _utcnow()
        db.add(run)
        db.commit()
        provider = YfinanceFundamentalProvider()
        succeeded: list[str] = []
        failed: dict[str, str] = {}
        for index, stock in enumerate(stocks):
            if index > 0:
                time.sleep(1.5)
            try:
                ticker = _provider_symbol(db, stock)
                workbook = provider.fetch(
                    stock.symbol,
                    provider_symbol=ticker,
                    display_name=stock.display_name,
                    market_region=stock.market_region,
                )
                _persist_workbook(db, run.id, workbook, data_source="yfinance")
                succeeded.append(stock.symbol)
                db.flush()
            except (ProviderUnavailableError, UnmappedSymbolError, Exception) as exc:
                failed[stock.symbol] = str(exc)
                db.add(
                    models.FundamentalQualityIssue(
                        import_id=run.id,
                        severity="error",
                        code="yfinance_symbol_failed",
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
        run.summary_json = sanitize_json_compatible({
            **dict(run.summary_json or {}),
            "succeeded": succeeded,
            "failed": failed,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
        })
        run.completed_at = _utcnow()
        if succeeded and failed:
            run.status = "partial"
        elif succeeded:
            run.status = "succeeded"
        else:
            run.status = "failed"
            run.error_message = "All yfinance symbols failed"
        db.add(run)
        db.commit()
        if succeeded:
            rescore_universe(db, scope="non_masi")
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
        return {
            "batch_id": batch_id,
            "import_id": str(run.id),
            "status": run.status,
            "succeeded": len(succeeded),
            "failed": len(failed),
        }
    finally:
        db.close()


def refresh_yfinance_for_symbol(symbol: str, triggered_by: str | None = None) -> dict[str, Any]:
    return refresh_yfinance_universe(symbols=[symbol], triggered_by=triggered_by or "manual")
