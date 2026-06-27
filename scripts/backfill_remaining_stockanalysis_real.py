from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy.orm.attributes import flag_modified

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.quant_core.fundamentals.domain import AnnualMetricRow
from core.quant_core.fundamentals.providers import ProviderUnavailableError
from services.api.app import models
from services.api.app.json_sanitize import sanitize_json_compatible
from services.api.app.services.fundamentals import (
    _build_integrity_reports,
    _load_history,
    _persist_integrity_reports,
    latest_snapshot_rows_by_symbol,
)
from services.worker.db import SessionLocal

from scripts.replace_top5_with_stockanalysis_real import (
    AUDIT_DIR,
    DEFAULT_SYMBOLS as CLEANED_TOP5_SYMBOLS,
    OLD_DETERMINISTIC_SHEETS,
    REQUIRED_GROUPS,
    SOURCE_SHEET,
    YEARS,
    _existing_rows,
    _fetch_source_rows,
    _missing_groups,
    _refresh_downstream,
    _refresh_snapshots_without_stale_metrics,
    _source_document,
)


ALREADY_CLEANED = set(CLEANED_TOP5_SYMBOLS) | {"MNG", "SMI", "CMT", "REB", "ZDJ"}
STALE_SOURCE_SHEETS = OLD_DETERMINISTIC_SHEETS | {"stockanalysis", "stockanalysis_supplement"}
STALE_TIE_OUT_ONLY_METRICS = {
    "BS_Cash_and_Equivalents",
    "Beginning_Cash",
    "CFS_Beginning_Cash",
    "CFS_Ending_Cash",
    "Ending_Cash",
}
SUPPLEMENT_AUDIT_DIR = ROOT / "data" / "stockanalysis_real_remaining_audits"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _active_remaining_symbols(db, requested: list[str] | None) -> list[str]:
    query = (
        db.query(models.StockMaster.symbol)
        .filter(models.StockMaster.market_region == "masi")
        .filter(models.StockMaster.is_active.is_(True))
        .filter(~models.StockMaster.symbol.in_(sorted(ALREADY_CLEANED)))
    )
    if requested:
        wanted = sorted({symbol.upper() for symbol in requested})
        query = query.filter(models.StockMaster.symbol.in_(wanted))
    return [str(row[0]).upper() for row in query.order_by(models.StockMaster.symbol.asc()).all()]


def _stock_rows(db, symbols: Iterable[str]) -> dict[str, models.StockMaster]:
    rows = db.query(models.StockMaster).filter(models.StockMaster.symbol.in_(sorted({s.upper() for s in symbols}))).all()
    return {str(row.symbol).upper(): row for row in rows}


def _delete_proxy_and_deterministic_rows(db, *, import_id: Any, symbol: str) -> tuple[int, set[str]]:
    rows = (
        db.query(models.FundamentalAnnualMetric)
        .filter(models.FundamentalAnnualMetric.import_id == import_id)
        .filter(models.FundamentalAnnualMetric.symbol == symbol)
        .filter(models.FundamentalAnnualMetric.statement_year.in_(YEARS))
        .all()
    )
    stale_rows = [
        row
        for row in rows
        if bool(row.is_proxy)
        or str(row.source_sheet or "") in OLD_DETERMINISTIC_SHEETS
        or (
            str(row.metric_name or "") in STALE_TIE_OUT_ONLY_METRICS
            and str(row.source_sheet or "") != SOURCE_SHEET
        )
    ]
    metric_names = {str(row.metric_name) for row in stale_rows}
    for row in stale_rows:
        db.delete(row)
    return len(stale_rows), metric_names


def _upsert_real_supplement_rows(
    db,
    *,
    import_id: Any,
    symbol: str,
    rows: list[AnnualMetricRow],
    doc_id: int | None,
) -> dict[str, int]:
    existing = {
        (int(row.statement_year), str(row.metric_name)): row
        for row in (
            db.query(models.FundamentalAnnualMetric)
            .filter(models.FundamentalAnnualMetric.import_id == import_id)
            .filter(models.FundamentalAnnualMetric.symbol == symbol)
            .filter(models.FundamentalAnnualMetric.statement_year.in_(YEARS))
            .all()
        )
    }
    inserted = updated_existing = unchanged = preserved_existing = 0
    for row in rows:
        key = (int(row.statement_year), str(row.metric_name))
        current = existing.get(key)
        value = float(row.metric_value)
        if current is None:
            db.add(
                models.FundamentalAnnualMetric(
                    import_id=import_id,
                    symbol=symbol,
                    company_name=row.company_name or symbol,
                    statement_year=int(row.statement_year),
                    metric_name=row.metric_name,
                    metric_value=value,
                    raw_metric_name=row.raw_metric_name or row.metric_name,
                    source_sheet=SOURCE_SHEET,
                    source_field=row.source_field,
                    is_proxy=False,
                    as_of_date=row.as_of_date,
                    source_document_id=doc_id,
                )
            )
            inserted += 1
            continue
        source_sheet = str(current.source_sheet or "")
        if (
            current.metric_value is not None
            and not bool(current.is_proxy)
            and source_sheet not in STALE_SOURCE_SHEETS
        ):
            preserved_existing += 1
            continue
        current_value = None if current.metric_value is None else float(current.metric_value)
        if (
            current_value != value
            or bool(current.is_proxy)
            or str(current.source_sheet or "") != SOURCE_SHEET
            or str(current.raw_metric_name or "") != str(row.raw_metric_name or row.metric_name)
        ):
            current.metric_value = value
            current.raw_metric_name = row.raw_metric_name or row.metric_name
            current.source_sheet = SOURCE_SHEET
            current.source_field = row.source_field
            current.is_proxy = False
            current.as_of_date = row.as_of_date or current.as_of_date
            current.source_document_id = doc_id or current.source_document_id
            db.add(current)
            updated_existing += 1
            continue
        unchanged += 1
    db.flush()
    return {
        "inserted": inserted,
        "updated_existing": updated_existing,
        "unchanged": unchanged,
        "preserved_existing": preserved_existing,
    }


def _real_stockanalysis_count(db, *, import_id: Any, symbol: str) -> int:
    return (
        db.query(models.FundamentalAnnualMetric)
        .filter(models.FundamentalAnnualMetric.import_id == import_id)
        .filter(models.FundamentalAnnualMetric.symbol == symbol)
        .filter(models.FundamentalAnnualMetric.statement_year.in_(YEARS))
        .filter(models.FundamentalAnnualMetric.source_sheet == SOURCE_SHEET)
        .count()
    )


def _stale_count(db, *, import_id: Any, symbol: str) -> int:
    return (
        db.query(models.FundamentalAnnualMetric)
        .filter(models.FundamentalAnnualMetric.import_id == import_id)
        .filter(models.FundamentalAnnualMetric.symbol == symbol)
        .filter(models.FundamentalAnnualMetric.statement_year.in_(YEARS))
        .filter(
            (models.FundamentalAnnualMetric.is_proxy.is_(True))
            | (models.FundamentalAnnualMetric.source_sheet.in_(sorted(OLD_DETERMINISTIC_SHEETS)))
        )
        .count()
    )


def backfill_remaining_stockanalysis_real(
    symbols: list[str] | None,
    *,
    dry_run: bool,
    skip_downstream: bool = False,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        selected = _active_remaining_symbols(db, symbols)
        snapshots = latest_snapshot_rows_by_symbol(db, symbols=selected, scope="masi")
        stocks = _stock_rows(db, selected)
        missing_active = sorted(set(selected) - set(snapshots))
        import_ids = {symbol: snapshots[symbol].import_id for symbol in selected if symbol in snapshots}

        fetched_rows: dict[str, list[AnnualMetricRow]] = {}
        fetch_summaries: dict[str, dict[str, Any]] = {}
        fetch_errors: dict[str, str] = {}
        for symbol in selected:
            try:
                rows, summary = _fetch_source_rows(symbol, stocks.get(symbol))
            except ProviderUnavailableError as exc:
                fetch_errors[symbol] = str(exc)
                continue
            fetched_rows[symbol] = rows
            fetch_summaries[symbol] = summary

        before_rows: list[AnnualMetricRow] = []
        for import_id in sorted(set(import_ids.values()), key=str):
            import_symbols = [symbol for symbol, item_import_id in import_ids.items() if item_import_id == import_id]
            before_rows.extend(_existing_rows(db, import_id=import_id, symbols=import_symbols))

        removed_metrics_by_import_symbol: dict[Any, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        write_summary: dict[str, Any] = {}
        if not dry_run:
            for symbol in selected:
                snapshot = snapshots.get(symbol)
                if snapshot is None:
                    continue
                rows = fetched_rows.get(symbol, [])
                doc_id = None
                if rows:
                    doc_id = _source_document(
                        db,
                        import_id=snapshot.import_id,
                        symbol=symbol,
                        summary=fetch_summaries.get(symbol, {}),
                    )
                deleted_stale, removed_names = _delete_proxy_and_deterministic_rows(
                    db,
                    import_id=snapshot.import_id,
                    symbol=symbol,
                )
                removed_metrics_by_import_symbol[snapshot.import_id][symbol].update(removed_names)
                counts = {"inserted": 0, "updated": 0, "unchanged": 0}
                if rows:
                    counts = _upsert_real_supplement_rows(
                        db,
                        import_id=snapshot.import_id,
                        symbol=symbol,
                        rows=rows,
                        doc_id=doc_id,
                    )
                write_summary[symbol] = {
                    "import_id": str(snapshot.import_id),
                    "fetched_rows": len(rows),
                    "deleted_proxy_or_deterministic_rows": deleted_stale,
                    **counts,
                }

            for import_id, symbol_metrics in removed_metrics_by_import_symbol.items():
                import_symbols = set(symbol_metrics)
                _refresh_snapshots_without_stale_metrics(
                    db,
                    import_id=import_id,
                    symbols=import_symbols,
                    removed_metrics_by_symbol=symbol_metrics,
                )
                history = [
                    row
                    for row in _load_history(db, import_id)
                    if row.symbol.upper() in import_symbols and row.statement_year in YEARS
                ]
                _persist_integrity_reports(db, import_id=import_id, reports=_build_integrity_reports(history))
                run = db.get(models.FundamentalImport, import_id)
                if run is not None:
                    run.annual_metric_count = (
                        db.query(models.FundamentalAnnualMetric)
                        .filter(models.FundamentalAnnualMetric.import_id == import_id)
                        .count()
                    )
                    summary = dict(run.summary_json or {})
                    fills = dict(summary.get("stockanalysis_real_remaining_backfill") or {})
                    fills[_utcnow().isoformat()] = {
                        "symbols": sorted(import_symbols),
                        "years": list(YEARS),
                    }
                    summary["stockanalysis_real_remaining_backfill"] = fills
                    run.summary_json = sanitize_json_compatible(summary)
                    flag_modified(run, "summary_json")
                    db.add(run)
            db.commit()
            if skip_downstream:
                downstream = {"skipped": True}
            else:
                downstream = _refresh_downstream(db, [s for s in selected if s in snapshots], import_ids)
                db.commit()
        else:
            downstream = {"dry_run": True}

        after_rows: list[AnnualMetricRow] = []
        for import_id in sorted(set(import_ids.values()), key=str):
            import_symbols = [symbol for symbol, item_import_id in import_ids.items() if item_import_id == import_id]
            after_rows.extend(_existing_rows(db, import_id=import_id, symbols=import_symbols))

        stale_remaining: dict[str, int] = {}
        stockanalysis_real_counts: dict[str, int] = {}
        for symbol, snapshot in snapshots.items():
            stale_remaining[symbol] = _stale_count(db, import_id=snapshot.import_id, symbol=symbol)
            stockanalysis_real_counts[symbol] = _real_stockanalysis_count(db, import_id=snapshot.import_id, symbol=symbol)

        result = {
            "dry_run": dry_run,
            "selected_symbols": selected,
            "symbol_count": len(selected),
            "years": list(YEARS),
            "missing_active": missing_active,
            "fetch_errors": fetch_errors,
            "source_missing": _missing_groups([row for rows in fetched_rows.values() for row in rows], selected, YEARS),
            "before_missing": _missing_groups(before_rows, selected, YEARS),
            "after_missing": _missing_groups(after_rows, selected, YEARS),
            "stale_proxy_or_deterministic_rows_remaining": stale_remaining,
            "stockanalysis_real_counts": stockanalysis_real_counts,
            "write_summary": write_summary,
            "downstream": downstream,
            "source_urls": {
                symbol: fetch_summaries.get(symbol, {}).get("source_urls", [])
                for symbol in selected
            },
        }
        SUPPLEMENT_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        audit_path = SUPPLEMENT_AUDIT_DIR / f"stockanalysis_real_remaining_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        audit_path.write_text(json.dumps(sanitize_json_compatible(result), indent=2, sort_keys=True), encoding="utf-8")
        result["audit_path"] = str(audit_path)
        return result
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill remaining active MASI fundamental gaps with real StockAnalysis rows only.")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols. Default: active MASI not already cleaned.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-downstream", action="store_true", help="Only write source rows and audit; skip score/valuation/signal refresh.")
    args = parser.parse_args()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()] or None
    result = backfill_remaining_stockanalysis_real(
        symbols,
        dry_run=bool(args.dry_run),
        skip_downstream=bool(args.skip_downstream),
    )
    print(json.dumps(sanitize_json_compatible(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
