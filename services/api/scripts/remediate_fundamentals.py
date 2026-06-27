"""Brief 38 fundamental data-integrity remediation.

Dry-run is the default. Use --apply to persist curated metric corrections and
verification rows. Use --revalue with --apply to recompute all scenario
valuations from the existing service path after remediation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from sqlalchemy.orm import Session  # noqa: E402

from core.quant_core.fundamentals.integrity import (  # noqa: E402
    apply_curated_corrections,
    build_data_tieout_report,
    curated_correction_entry,
    load_curated_corrections,
)
from core.quant_core.fundamentals.minority import resolve_minority_roe_basis  # noqa: E402
from core.quant_core.fundamentals.valuation import DEFAULT_ASSUMPTIONS  # noqa: E402
from app import models  # noqa: E402
from app.db import _ensure_session_factory  # noqa: E402
from app.json_sanitize import sanitize_json_compatible  # noqa: E402
from app.services.fundamentals import (  # noqa: E402
    VALUATION_SCENARIOS,
    latest_snapshot_rows_by_symbol,
    recompute_symbol_valuations_all_scenarios,
    refresh_canonical_snapshot_flags,
)


NAMED_DEFECT_SYMBOLS = ("LHM", "COL", "STR", "BCP", "CDM", "CMT", "JET", "LBV", "M2M", "MDP", "MSA", "SAH", "TQM")
FY2025_PROOF_DIR = REPO_ROOT / "data" / "corrections" / "fy2025"  # proof artifacts removed from git (repo-cleanup phase 1.2) — already applied to DB; --fy2025-reingestion flag is now inert
FY2025_REINGESTION_VERSION = "brief42-fy2025-proof-2026-06-07"


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def _metric_value(rows: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = _num(rows.get(name))
        if value is not None:
            return value
    return None


def _report_to_dict(report: Any) -> dict[str, Any]:
    return {
        "symbol": report.symbol,
        "statement_year": report.statement_year,
        "status": report.status,
        "failed_checks": list(report.failed_checks),
        "warnings": list(report.warnings),
        "offending_metrics": report.offending_metrics,
        "recomputed_metrics": report.recomputed_metrics,
        "reason": report.reason,
        "checks": [
            {
                "name": check.name,
                "status": check.status,
                "delta": check.delta,
                "rel_delta": check.rel_delta,
                "inputs": check.inputs,
                "message": check.message,
            }
            for check in report.checks
        ],
        "provenance": report.provenance,
    }


def _source_urls(entry: dict[str, Any] | None) -> list[str]:
    urls: list[str] = []
    if isinstance(entry, dict):
        official = entry.get("official_document")
        if isinstance(official, dict) and official.get("url"):
            urls.append(str(official["url"]))
        if entry.get("stockanalysis_url"):
            urls.append(str(entry["stockanalysis_url"]))
    return urls


def _artifact_source_urls(artifact: dict[str, Any] | None) -> list[str]:
    urls: list[str] = []
    if not isinstance(artifact, dict):
        return urls
    for item in artifact.get("source_documents") or []:
        if isinstance(item, dict) and item.get("source_url"):
            urls.append(str(item["source_url"]))
    for figure in (artifact.get("figures") or {}).values():
        if isinstance(figure, dict) and figure.get("source_url"):
            urls.append(str(figure["source_url"]))
    return sorted(set(urls))


def _stockanalysis_payload(db: Session, *, import_id: Any, symbol: str, entry: dict[str, Any] | None) -> dict[str, Any]:
    url = str((entry or {}).get("stockanalysis_url") or "")
    row = None
    if url:
        row = (
            db.query(models.FundamentalSourceDocument)
            .filter(
                models.FundamentalSourceDocument.import_id == import_id,
                models.FundamentalSourceDocument.symbol == symbol.upper(),
                models.FundamentalSourceDocument.source_url == url,
            )
            .one_or_none()
        )
    return {
        "url": url or None,
        "covered": row is not None,
        "source_document_id": row.id if row is not None else None,
        "status": row.status if row is not None else None,
    }


def _rows_for_year(
    db: Session,
    *,
    import_id: Any,
    symbol: str,
    statement_year: int,
    snapshot_metrics: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, int]]:
    rows = dict(snapshot_metrics or {})
    metric_years: dict[str, int] = {}
    annual_rows = (
        db.query(models.FundamentalAnnualMetric)
        .filter(
            models.FundamentalAnnualMetric.import_id == import_id,
            models.FundamentalAnnualMetric.symbol == symbol.upper(),
            models.FundamentalAnnualMetric.statement_year == int(statement_year),
        )
        .all()
    )
    for row in annual_rows:
        rows[str(row.metric_name)] = row.metric_value
        metric_years[str(row.metric_name)] = int(row.statement_year)
    return rows, metric_years


def _previous_rows_for_year(db: Session, *, import_id: Any, symbol: str, statement_year: int) -> dict[str, Any]:
    rows = (
        db.query(models.FundamentalAnnualMetric)
        .filter(
            models.FundamentalAnnualMetric.import_id == import_id,
            models.FundamentalAnnualMetric.symbol == symbol.upper(),
            models.FundamentalAnnualMetric.statement_year < int(statement_year),
        )
        .order_by(models.FundamentalAnnualMetric.statement_year.desc())
        .all()
    )
    previous_year = None
    out: dict[str, Any] = {}
    for row in rows:
        if previous_year is None:
            previous_year = int(row.statement_year)
        if int(row.statement_year) != previous_year:
            break
        out[str(row.metric_name)] = row.metric_value
    return out


def _apply_aliases_and_derived(rows: dict[str, Any], previous_rows: dict[str, Any] | None = None) -> dict[str, Any]:
    out = dict(rows or {})
    if _metric_value(out, "Resultat_net") is not None:
        out["NetIncome"] = _metric_value(out, "Resultat_net")
        out["Net_Income"] = _metric_value(out, "Resultat_net")
    if _metric_value(out, "Resultat_net_part_du_groupe") is not None:
        out["NetIncome_Group"] = _metric_value(out, "Resultat_net_part_du_groupe")
        out["Net_Income_Group"] = _metric_value(out, "Resultat_net_part_du_groupe")
    if _metric_value(out, "Equity_Group") is not None:
        out["Total_Equity_Group"] = _metric_value(out, "Equity_Group")
    total_passif = _metric_value(out, "Total_Liabilities_And_Equity")
    total_equity = _metric_value(out, "Total_Equity")
    if total_passif is not None and total_equity is not None:
        out["Total_Liabilities"] = total_passif - total_equity

    basis = resolve_minority_roe_basis(
        out,
        epsilon=float(DEFAULT_ASSUMPTIONS["minority_materiality_epsilon"]),
    )
    group_equity = basis.group_equity
    if not basis.is_material_minority and group_equity is not None:
        out["Total_Equity_Group"] = group_equity
    elif _metric_value(out, "Equity_Group") is not None:
        out["Total_Equity_Group"] = _metric_value(out, "Equity_Group")

    shares = _metric_value(out, "Shares_Outstanding", "Shares")
    if shares is not None and shares > 0 and group_equity is not None:
        out["BVPS"] = group_equity / shares
        out["Book_Value_Per_Share"] = out["BVPS"]
    rnpg = basis.rnpg
    if rnpg is not None and group_equity is not None and group_equity != 0:
        out["ROE"] = rnpg / group_equity
        out["Return_on_Equity"] = out["ROE"]
    current_price = _metric_value(out, "Current_Price", "Price")
    if current_price is not None and shares is not None and group_equity is not None and group_equity > 0:
        out["Price_to_Book"] = (current_price * shares) / group_equity
        out["P_B"] = out["Price_to_Book"]
    return out


def _source_document_for_entry(db: Session, *, import_id: Any, symbol: str, entry: dict[str, Any] | None) -> models.FundamentalSourceDocument | None:
    official = (entry or {}).get("official_document")
    url = official.get("url") if isinstance(official, dict) else None
    if not url:
        return None
    return (
        db.query(models.FundamentalSourceDocument)
        .filter(
            models.FundamentalSourceDocument.import_id == import_id,
            models.FundamentalSourceDocument.symbol == symbol.upper(),
            models.FundamentalSourceDocument.source_url == str(url),
        )
        .first()
    )


def _upsert_metric(
    db: Session,
    *,
    snapshot: models.FundamentalLatestSnapshot,
    statement_year: int,
    metric_name: str,
    metric_value: float | None,
    provenance: dict[str, Any],
    source_document_id: int | None,
    source_sheet: str = "brief38_curated",
) -> None:
    if metric_value is None:
        return
    row = (
        db.query(models.FundamentalAnnualMetric)
        .filter(
            models.FundamentalAnnualMetric.import_id == snapshot.import_id,
            models.FundamentalAnnualMetric.symbol == snapshot.symbol,
            models.FundamentalAnnualMetric.statement_year == int(statement_year),
            models.FundamentalAnnualMetric.metric_name == metric_name,
        )
        .one_or_none()
    )
    label = str(provenance.get("label") or "brief38_curated_correction")
    if row is None:
        row = models.FundamentalAnnualMetric(
            import_id=snapshot.import_id,
            symbol=snapshot.symbol,
            company_name=snapshot.company_name,
            statement_year=int(statement_year),
            metric_name=metric_name,
        )
        db.add(row)
    row.metric_value = float(metric_value)
    row.raw_metric_name = label
    row.source_sheet = source_sheet
    row.source_field = str(provenance.get("source") or "official_filing")
    row.is_proxy = False
    row.as_of_date = snapshot.as_of_date
    row.source_document_id = source_document_id


def _persist_metric_corrections(
    db: Session,
    *,
    snapshot: models.FundamentalLatestSnapshot,
    statement_year: int,
    corrected_rows: dict[str, Any],
    correction_provenance: dict[str, Any],
    entry: dict[str, Any] | None,
) -> None:
    source_doc = _source_document_for_entry(db, import_id=snapshot.import_id, symbol=snapshot.symbol, entry=entry)
    source_document_id = source_doc.id if source_doc is not None else snapshot.source_document_id
    correction_metrics = set(correction_provenance)
    derived_metrics = {
        "Total_Liabilities",
        "Total_Equity_Group",
        "NetIncome",
        "Net_Income",
        "NetIncome_Group",
        "Net_Income_Group",
        "BVPS",
        "Book_Value_Per_Share",
        "ROE",
        "Return_on_Equity",
        "Price_to_Book",
        "P_B",
    }
    for metric in sorted(correction_metrics | derived_metrics):
        if metric not in corrected_rows:
            continue
        provenance = correction_provenance.get(metric) or {
            "source": "derived",
            "label": f"Brief 38 derived {metric}",
            "formula": "standard remediation formula from official raw lines",
        }
        _upsert_metric(
            db,
            snapshot=snapshot,
            statement_year=statement_year,
            metric_name=metric,
            metric_value=_num(corrected_rows.get(metric)),
            provenance=provenance,
            source_document_id=source_document_id,
        )

    metrics = dict(snapshot.metrics_json or {})
    metrics.update({metric: corrected_rows.get(metric) for metric in sorted(correction_metrics | derived_metrics) if metric in corrected_rows})
    snapshot.metrics_json = sanitize_json_compatible(metrics)
    source = dict(snapshot.source_json or {})
    source["brief38_correction"] = {
        "version": "brief38-curated-2026-06-06",
        "official_document": (entry or {}).get("official_document"),
    }
    snapshot.source_json = sanitize_json_compatible(source)
    db.add(snapshot)


def load_fy2025_proof_artifacts(
    *,
    proof_dir: Path = FY2025_PROOF_DIR,
    symbols: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    wanted = {symbol.upper() for symbol in symbols or []}
    artifacts: dict[str, dict[str, Any]] = {}
    if not proof_dir.exists():
        return artifacts
    for path in sorted(proof_dir.glob("*.json")):
        symbol = path.stem.upper()
        if wanted and symbol not in wanted:
            continue
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        payload["symbol"] = str(payload.get("symbol") or symbol).upper()
        try:
            artifact_path = str(path.relative_to(REPO_ROOT))
        except ValueError:
            artifact_path = str(path)
        payload.setdefault("artifact_path", artifact_path)
        artifacts[payload["symbol"]] = payload
    return artifacts


def _artifact_entry(artifact: dict[str, Any]) -> dict[str, Any]:
    documents = [item for item in artifact.get("source_documents") or [] if isinstance(item, dict)]
    official = documents[0] if documents else {}
    return {
        "official_document": {
            "url": official.get("source_url"),
            "title": official.get("document_title") or official.get("title") or "Brief 42 FY2025 proof filing",
        },
        "stockanalysis_url": artifact.get("stockanalysis_url"),
    }


def _ensure_artifact_source_documents(
    db: Session,
    *,
    snapshot: models.FundamentalLatestSnapshot,
    artifact: dict[str, Any],
) -> dict[str, models.FundamentalSourceDocument]:
    docs: dict[str, models.FundamentalSourceDocument] = {}
    for item in artifact.get("source_documents") or []:
        if not isinstance(item, dict) or not item.get("source_url"):
            continue
        url = str(item["source_url"])
        row = (
            db.query(models.FundamentalSourceDocument)
            .filter(
                models.FundamentalSourceDocument.import_id == snapshot.import_id,
                models.FundamentalSourceDocument.symbol == snapshot.symbol,
                models.FundamentalSourceDocument.source_url == url,
            )
            .one_or_none()
        )
        if row is None:
            row = models.FundamentalSourceDocument(
                import_id=snapshot.import_id,
                symbol=snapshot.symbol,
                company_name=snapshot.company_name,
                document_title=str(item.get("document_title") or item.get("title") or "Brief 42 FY2025 proof filing"),
                source_url=url,
                document_kind="brief42_proof",
                fiscal_year=int(artifact.get("fiscal_year") or 2025),
                period_type="annual",
                period_label="FY",
                status="succeeded",
                extracted_field_count=0,
                raw_json=sanitize_json_compatible(
                    {
                        "brief42_artifact": artifact.get("artifact_path"),
                        "page_count": item.get("page_count"),
                        "tls_note": item.get("tls_note"),
                    }
                ),
            )
            db.add(row)
            db.flush()
        docs[url] = row
    return docs


def _proof_rows_and_provenance(artifact: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    rows: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    figure_map: dict[str, dict[str, Any]] = {}
    for key, figure in (artifact.get("figures") or {}).items():
        if not isinstance(figure, dict):
            continue
        metric_name = str(figure.get("metric_name") or key)
        status = str(figure.get("status") or "observed")
        value = _num(figure.get("value"))
        if status != "observed" or value is None:
            continue
        rows[metric_name] = value
        provenance[metric_name] = {
            "source": "official_filing",
            "page": figure.get("page"),
            "line": figure.get("line"),
            "label": figure.get("verbatim_label") or metric_name,
            "source_value": figure.get("reported_value"),
            "unit": figure.get("unit"),
            "source_url": figure.get("source_url"),
            "artifact": artifact.get("artifact_path"),
        }
        figure_map[metric_name] = figure
    return rows, provenance, figure_map


def _persist_fy2025_statement_set(
    db: Session,
    *,
    snapshot: models.FundamentalLatestSnapshot,
    statement_year: int,
    corrected_rows: dict[str, Any],
    correction_provenance: dict[str, Any],
    artifact: dict[str, Any],
    figure_map: dict[str, dict[str, Any]],
) -> None:
    source_docs = _ensure_artifact_source_documents(db, snapshot=snapshot, artifact=artifact)
    correction_metrics = set(correction_provenance)
    derived_metrics = {
        "Total_Liabilities",
        "Total_Equity_Group",
        "NetIncome",
        "Net_Income",
        "NetIncome_Group",
        "Net_Income_Group",
        "BVPS",
        "Book_Value_Per_Share",
        "ROE",
        "Return_on_Equity",
        "Price_to_Book",
        "P_B",
    }
    metrics_to_persist = {metric for metric in (correction_metrics | derived_metrics) if metric in corrected_rows}
    if metrics_to_persist:
        db.query(models.FundamentalAnnualMetric).filter(
            models.FundamentalAnnualMetric.import_id == snapshot.import_id,
            models.FundamentalAnnualMetric.symbol == snapshot.symbol,
            models.FundamentalAnnualMetric.statement_year == int(statement_year),
            models.FundamentalAnnualMetric.metric_name.notin_(metrics_to_persist),
        ).delete(synchronize_session=False)

    for metric in sorted(metrics_to_persist):
        if metric not in corrected_rows:
            continue
        provenance = correction_provenance.get(metric) or {
            "source": "derived",
            "label": f"Brief 42 derived {metric}",
            "formula": "standard remediation formula from official FY2025 raw lines",
            "artifact": artifact.get("artifact_path"),
        }
        figure = figure_map.get(metric) or {}
        source_url = str(figure.get("source_url") or provenance.get("source_url") or "")
        source_doc = source_docs.get(source_url)
        _upsert_metric(
            db,
            snapshot=snapshot,
            statement_year=statement_year,
            metric_name=metric,
            metric_value=_num(corrected_rows.get(metric)),
            provenance=provenance,
            source_document_id=source_doc.id if source_doc is not None else snapshot.source_document_id,
            source_sheet="brief42_fy2025_proof",
        )

    old_metrics = dict(snapshot.metrics_json or {})
    market_metrics = {"Current_Price", "Price", "Market_Cap", "MarketCapitalization"}
    metrics = {metric: old_metrics[metric] for metric in market_metrics if metric in old_metrics}
    metrics.update({metric: corrected_rows.get(metric) for metric in sorted(metrics_to_persist)})
    snapshot.metrics_json = sanitize_json_compatible(metrics)
    snapshot.latest_statement_year = int(statement_year)
    snapshot.is_canonical = True
    source = dict(snapshot.source_json or {})
    source["brief42_fy2025_reingestion"] = {
        "version": FY2025_REINGESTION_VERSION,
        "artifact": artifact.get("artifact_path"),
        "source_urls": _artifact_source_urls(artifact),
    }
    snapshot.source_json = sanitize_json_compatible(source)
    db.add(snapshot)


def _upsert_verification(
    db: Session,
    *,
    snapshot: models.FundamentalLatestSnapshot,
    statement_year: int,
    status: str,
    reason: str | None,
    report_before: Any,
    report_after: Any,
    correction_provenance: dict[str, Any],
    entry: dict[str, Any] | None,
) -> models.FundamentalDataVerification:
    row = (
        db.query(models.FundamentalDataVerification)
        .filter(
            models.FundamentalDataVerification.import_id == snapshot.import_id,
            models.FundamentalDataVerification.symbol == snapshot.symbol,
            models.FundamentalDataVerification.statement_year == int(statement_year),
        )
        .one_or_none()
    )
    if row is None:
        row = models.FundamentalDataVerification(
            import_id=snapshot.import_id,
            symbol=snapshot.symbol,
            statement_year=int(statement_year),
            status=status,
        )
        db.add(row)
    report_after_dict = _report_to_dict(report_after)
    row.status = status
    row.reason = reason
    row.failed_checks_json = sanitize_json_compatible(report_after.failed_checks)
    row.warnings_json = sanitize_json_compatible(report_after.warnings)
    row.offending_metrics_json = sanitize_json_compatible(report_after.offending_metrics)
    row.recomputed_metrics_json = sanitize_json_compatible(report_after.recomputed_metrics)
    row.corrections_json = sanitize_json_compatible(correction_provenance)
    row.provenance_json = sanitize_json_compatible((entry or {}).get("official_document") or {})
    row.source_urls_json = sanitize_json_compatible(_source_urls(entry))
    row.stockanalysis_json = sanitize_json_compatible(_stockanalysis_payload(db, import_id=snapshot.import_id, symbol=snapshot.symbol, entry=entry))
    row.tieout_report_json = sanitize_json_compatible({"before": _report_to_dict(report_before), "after": report_after_dict})
    row.updated_at = dt.datetime.now(dt.timezone.utc)
    coverage = dict(snapshot.coverage_json or {})
    coverage["data_verification"] = {"status": status, "reason": reason}
    snapshot.coverage_json = sanitize_json_compatible(coverage)
    db.add(snapshot)
    return row


def _status_from_entry_or_report(entry: dict[str, Any] | None, report: Any) -> tuple[str, str | None]:
    forced = str((entry or {}).get("force_status") or "").strip()
    if forced == "data_unverified":
        return "data_unverified", str((entry or {}).get("force_reason") or report.reason or "data_unverified")
    if report.status == "verified":
        return "verified", None
    return "data_unverified", report.reason or "data_unverified"


def remediate_fundamentals(
    db: Session,
    *,
    symbols: list[str] | None = None,
    apply: bool = False,
    revalue: bool = False,
) -> list[dict[str, Any]]:
    refresh_canonical_snapshot_flags(db, symbols=symbols)
    snapshots = latest_snapshot_rows_by_symbol(db, symbols=symbols)
    if symbols:
        wanted = {symbol.upper() for symbol in symbols}
        snapshots = {symbol: row for symbol, row in snapshots.items() if symbol in wanted}
    corrections = load_curated_corrections()
    report_rows: list[dict[str, Any]] = []
    for symbol, snapshot in sorted(snapshots.items()):
        if snapshot.latest_statement_year is None:
            continue
        year = int(snapshot.latest_statement_year)
        entry = curated_correction_entry(symbol, year, corrections=corrections)
        rows, metric_years = _rows_for_year(
            db,
            import_id=snapshot.import_id,
            symbol=symbol,
            statement_year=year,
            snapshot_metrics=dict(snapshot.metrics_json or {}),
        )
        previous_rows = _previous_rows_for_year(db, import_id=snapshot.import_id, symbol=symbol, statement_year=year)
        before = build_data_tieout_report(
            symbol,
            year,
            rows,
            previous_rows_by_metric=previous_rows,
            snapshot_year=snapshot.latest_statement_year,
            metric_years=metric_years,
            period_type="annual",
        )
        corrected, correction_provenance = apply_curated_corrections(rows, entry)
        corrected = _apply_aliases_and_derived(corrected, previous_rows)
        after = build_data_tieout_report(
            symbol,
            year,
            corrected,
            previous_rows_by_metric=previous_rows,
            snapshot_year=snapshot.latest_statement_year,
            metric_years={**metric_years, **{metric: year for metric in correction_provenance}},
            period_type="annual",
            provenance=correction_provenance,
        )
        status, reason = _status_from_entry_or_report(entry, after)
        if apply:
            if correction_provenance:
                _persist_metric_corrections(
                    db,
                    snapshot=snapshot,
                    statement_year=year,
                    corrected_rows=corrected,
                    correction_provenance=correction_provenance,
                    entry=entry,
                )
            _upsert_verification(
                db,
                snapshot=snapshot,
                statement_year=year,
                status=status,
                reason=reason,
                report_before=before,
                report_after=after,
                correction_provenance=correction_provenance,
                entry=entry,
            )
        report_rows.append(
            {
                "symbol": symbol,
                "year": year,
                "import_id": str(snapshot.import_id),
                "status": status,
                "reason": reason,
                "before": _report_to_dict(before),
                "after": _report_to_dict(after),
                "curated": entry is not None,
                "source_urls": _source_urls(entry),
                "cause": (entry or {}).get("cause"),
            }
        )
    if apply:
        db.flush()
        if revalue:
            os.environ["FUNDAMENTAL_DISABLE_LIVE_QUOTES"] = "1"
            for item in report_rows:
                recompute_symbol_valuations_all_scenarios(
                    db,
                    import_id=snapshots[item["symbol"]].import_id,
                    symbol=item["symbol"],
                    scenarios=VALUATION_SCENARIOS,
                )
        db.commit()
    else:
        db.rollback()
    return report_rows


def apply_fy2025_reingestion(
    db: Session,
    *,
    symbols: list[str] | None = None,
    apply: bool = False,
    revalue: bool = False,
    proof_dir: Path = FY2025_PROOF_DIR,
) -> list[dict[str, Any]]:
    refresh_canonical_snapshot_flags(db, symbols=symbols)
    artifacts = load_fy2025_proof_artifacts(proof_dir=proof_dir, symbols=symbols)
    snapshots = latest_snapshot_rows_by_symbol(db, symbols=list(artifacts) if not symbols else symbols)
    report_rows: list[dict[str, Any]] = []
    for symbol, artifact in sorted(artifacts.items()):
        snapshot = snapshots.get(symbol)
        if snapshot is None:
            report_rows.append(
                {
                    "symbol": symbol,
                    "year": int(artifact.get("fiscal_year") or 2025),
                    "status": "data_unverified",
                    "reason": "missing_canonical_snapshot",
                    "curated": True,
                    "source_urls": _artifact_source_urls(artifact),
                }
            )
            continue
        year = int(artifact.get("fiscal_year") or 2025)
        rows, metric_years = _rows_for_year(
            db,
            import_id=snapshot.import_id,
            symbol=symbol,
            statement_year=year,
            snapshot_metrics={},
        )
        previous_rows = _previous_rows_for_year(db, import_id=snapshot.import_id, symbol=symbol, statement_year=year)
        before = build_data_tieout_report(
            symbol,
            year,
            rows,
            previous_rows_by_metric=previous_rows,
            snapshot_year=year,
            metric_years=metric_years,
            period_type="annual",
        )
        proof_rows, correction_provenance, figure_map = _proof_rows_and_provenance(artifact)
        corrected = _apply_aliases_and_derived(proof_rows, previous_rows)
        observed_years = {metric: year for metric in correction_provenance}
        after = build_data_tieout_report(
            symbol,
            year,
            corrected,
            previous_rows_by_metric=previous_rows,
            snapshot_year=year,
            metric_years={**metric_years, **observed_years},
            period_type="annual",
            provenance=correction_provenance,
        )
        status, reason = _status_from_entry_or_report(None, after)
        if apply:
            _persist_fy2025_statement_set(
                db,
                snapshot=snapshot,
                statement_year=year,
                corrected_rows=corrected,
                correction_provenance=correction_provenance,
                artifact=artifact,
                figure_map=figure_map,
            )
            _upsert_verification(
                db,
                snapshot=snapshot,
                statement_year=year,
                status=status,
                reason=reason,
                report_before=before,
                report_after=after,
                correction_provenance=correction_provenance,
                entry=_artifact_entry(artifact),
            )
        report_rows.append(
            {
                "symbol": symbol,
                "year": year,
                "import_id": str(snapshot.import_id),
                "status": status,
                "reason": reason,
                "before": _report_to_dict(before),
                "after": _report_to_dict(after),
                "curated": True,
                "source_urls": _artifact_source_urls(artifact),
                "artifact": artifact.get("artifact_path"),
                "observed_metric_count": len(correction_provenance),
            }
        )
    if apply:
        db.flush()
        if revalue:
            os.environ["FUNDAMENTAL_DISABLE_LIVE_QUOTES"] = "1"
            for item in report_rows:
                snapshot = snapshots.get(item["symbol"])
                if snapshot is None:
                    continue
                recompute_symbol_valuations_all_scenarios(
                    db,
                    import_id=snapshot.import_id,
                    symbol=item["symbol"],
                    scenarios=VALUATION_SCENARIOS,
                )
        db.commit()
    else:
        db.rollback()
    return report_rows


def capability_check(db: Session) -> dict[str, Any]:
    total = int(db.query(models.FundamentalSourceDocument).count())
    with_source = int(
        db.query(models.FundamentalSourceDocument)
        .filter(models.FundamentalSourceDocument.source_url.isnot(None))
        .count()
    )
    symbol_count = len(
        {
            str(symbol).upper()
            for (symbol,) in db.query(models.FundamentalSourceDocument.symbol).filter(models.FundamentalSourceDocument.symbol.isnot(None)).distinct().all()
            if symbol
        }
    )
    sample = (
        db.query(models.FundamentalSourceDocument.source_url)
        .filter(models.FundamentalSourceDocument.source_url.like("https://media.casablanca-bourse.com/%"))
        .first()
    )
    result = {
        "source_document_count": total,
        "source_url_count": with_source,
        "symbol_count": symbol_count,
        "bvc_fetch": False,
        "pdf_parse": False,
        "sample_url": sample[0] if sample is not None else None,
        "tls_note": None,
        "error": None,
    }
    if sample is None:
        result["error"] = "no_bvc_media_source_url"
        return result
    try:
        import fitz  # type: ignore
        import requests

        try:
            response = requests.get(sample[0], timeout=30)
        except Exception as exc:
            result["tls_note"] = f"standard_tls_fetch_failed:{type(exc).__name__}"
            response = requests.get(sample[0], timeout=30, verify=False)
        result["bvc_fetch"] = response.status_code == 200 and response.content.startswith(b"%PDF")
        if result["bvc_fetch"]:
            doc = fitz.open(stream=response.content, filetype="pdf")
            text = doc.load_page(0).get_text("text") if doc.page_count else ""
            result["pdf_parse"] = doc.page_count > 0 and text is not None
            result["page_count"] = doc.page_count
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist corrections and verification rows")
    parser.add_argument("--revalue", action="store_true", help="Recompute all scenario valuations after --apply")
    parser.add_argument("--symbols", nargs="*", metavar="SYM", help="Restrict remediation to symbols")
    parser.add_argument("--named-defects", action="store_true", help="Only process the Brief 38 named defect set")
    parser.add_argument("--skip-capability-check", action="store_true", help="Do not fetch/parse a sample BVC PDF before running")
    parser.add_argument("--fy2025-reingestion", action="store_true", help="Apply Brief 42 FY2025 proof-of-read artifacts")
    parser.add_argument("--proof-dir", type=Path, default=FY2025_PROOF_DIR, help="Directory containing Brief 42 proof artifacts")
    args = parser.parse_args()

    symbols = [symbol.upper() for symbol in (args.symbols or [])]
    if args.named_defects:
        symbols = list(NAMED_DEFECT_SYMBOLS)
    session_factory = _ensure_session_factory()
    with session_factory() as db:
        if not args.skip_capability_check:
            print(json.dumps({"capability_check": capability_check(db)}, ensure_ascii=False, indent=2))
        if args.fy2025_reingestion:
            rows = apply_fy2025_reingestion(
                db,
                symbols=symbols or None,
                apply=args.apply,
                revalue=args.revalue,
                proof_dir=args.proof_dir,
            )
        else:
            rows = remediate_fundamentals(db, symbols=symbols or None, apply=args.apply, revalue=args.revalue)
        print(json.dumps({"mode": "apply" if args.apply else "dry_run", "rows": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
