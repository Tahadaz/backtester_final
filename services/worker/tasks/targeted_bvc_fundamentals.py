# =============================================================================
# DORMANT — BVC/Gemini pipeline (Phase 2 gate, Brief 45)
#
# This module is intentionally disabled pending the canonical StockAnalysis
# re-ingest (Phase 4).  To re-enable, set the env var:
#   BVC_PIPELINE_ENABLED=1
# in both the API and worker environments.  The API endpoint
# (`enqueue_targeted_bvc_fundamental_import`) enforces the same gate and will
# return HTTP 503 until that flag is present.
#
# Do NOT delete this code — it is the only full-history BVC ingest path and
# will be needed again after Phase 4 validation.
# =============================================================================
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from services.api.app import models
from services.api.app.json_sanitize import sanitize_json_compatible
from services.api.app.services.fundamentals import (
    FUNDAMENTAL_COMPANY_SYMBOL_ALIASES,
    FUNDAMENTAL_SYMBOL_ALIASES,
    delete_fundamental_import_artifacts,
    execute_import_run,
    refresh_import_after_pit_sync,
    sync_bvc_period_metrics_to_annual_and_latest,
)
from services.api.app.services.fundamental_publication_reconciliation import reconcile_stockanalysis_publication_dates
from services.worker.config import settings
from services.worker.db import SessionLocal


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _normalize_company(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^A-Z0-9]+", " ", text.upper())
    return " ".join(text.strip().split())


def _stock_rows(db, symbols: list[str]) -> dict[str, models.StockMaster]:
    wanted = sorted({symbol.upper() for symbol in symbols if symbol and symbol.strip()})
    if not wanted:
        return {}
    rows = (
        db.query(models.StockMaster)
        .filter(models.StockMaster.symbol.in_(wanted))
        .all()
    )
    return {str(row.symbol).upper(): row for row in rows}


def _all_bvc_stock_rows(db) -> dict[str, models.StockMaster]:
    rows = (
        db.query(models.StockMaster)
        .filter(
            models.StockMaster.is_active.is_(True),
            ~models.StockMaster.symbol.in_(["INSTRUMENT", "MAJ"]),
            (
                (models.StockMaster.market_region == "masi")
                | (models.StockMaster.market_region.is_(None))
            ),
        )
        .all()
    )
    return {str(row.symbol).upper(): row for row in rows}


def _target_company_terms(stocks: dict[str, models.StockMaster]) -> dict[str, list[str]]:
    by_symbol: dict[str, list[str]] = {symbol: [symbol] for symbol in stocks}
    for symbol, stock in stocks.items():
        if stock.display_name:
            by_symbol[symbol].append(str(stock.display_name))

    for alias, canonical in FUNDAMENTAL_SYMBOL_ALIASES.items():
        if canonical in by_symbol:
            by_symbol[canonical].append(alias)

    for company, canonical in FUNDAMENTAL_COMPANY_SYMBOL_ALIASES.items():
        if canonical in by_symbol:
            by_symbol[canonical].append(company)

    manual = {
        "CAP": ["CASH PLUS S.A", "CASH PLUS"],
        "CMG": ["CMGP GROUP", "CMGP"],
        "TGC": ["TRAVAUX GENERAUX DE CONSTRUCTION DE CASABLANCA", "TGCC"],
        "BCI": ["BANQUE MAROCAINE POUR LE COMMERCE ET L'INDUSTRIE", "BMCI"],
        "AFI": ["AFRIC INDUSTRIES SA", "AFRIC INDUSTRIES"],
        "MLE": ["MAROC LEASING"],
        "SLF": ["SALAFIN"],
        "VCN": ["VICENNE"],
    }
    for symbol, terms in manual.items():
        if symbol in by_symbol:
            by_symbol[symbol].extend(terms)

    return {
        symbol: sorted({term.strip() for term in terms if term and term.strip()})
        for symbol, terms in by_symbol.items()
    }


def _python_executable(fama_dir: Path) -> str:
    if settings.FAMA_FRENCH_PYTHON:
        return settings.FAMA_FRENCH_PYTHON
    local = fama_dir / ".venv" / "Scripts" / "python.exe"
    if local.exists():
        return str(local)
    return sys.executable


def _command_output_tail(value: str, limit: int = 4000) -> str:
    value = value or ""
    return value[-limit:] if len(value) > limit else value


def _split_secret_list(raw: str | None) -> list[str]:
    return [item.strip() for item in (raw or "").replace(";", ",").split(",") if item.strip()]


def _run_scraper(
    *,
    symbols: list[str],
    company_terms: dict[str, list[str]],
    years: list[int],
    period_types: list[str],
    only_unseen: bool,
    force: bool,
    output_path: Path,
) -> subprocess.CompletedProcess[str]:
    fama_dir = Path(settings.FAMA_FRENCH_DIR)
    script = fama_dir / "run_full_pipeline.py"
    if not script.exists():
        raise FileNotFoundError(f"BVC scraper not found: {script}")

    all_terms = sorted({term for terms in company_terms.values() for term in terms})
    cmd = [
        _python_executable(fama_dir),
        str(script),
        "--symbols",
        ",".join(symbols),
        "--companies",
        ";".join(all_terms),
        "--max-pages",
        str(settings.FAMA_FRENCH_TARGET_MAX_PAGES),
        "--model",
        settings.FUNDAMENTAL_LLM_MODEL,
        "--factor-output",
        str(output_path),
        "--structured-output-dir",
        str(output_path.parent / "structured"),
        "--skip-structured-workbooks",
        "--market-reference-workbook",
        settings.FAMA_FRENCH_MARKET_REFERENCE_WORKBOOK,
        "--historical-workbook",
        settings.FAMA_FRENCH_HISTORICAL_WORKBOOK,
        "--reference-workbook",
        settings.FAMA_FRENCH_HISTORICAL_WORKBOOK,
    ]
    if settings.FUNDAMENTAL_LLM_FALLBACK_MODELS:
        cmd.extend(["--fallback-models", settings.FUNDAMENTAL_LLM_FALLBACK_MODELS])
    if years:
        cmd.extend(["--start-year", str(min(years)), "--end-year", str(max(years))])
    if period_types:
        cmd.extend(["--period-types", ",".join(period_types)])
    if only_unseen:
        cmd.append("--only-unseen")
    if not force:
        cmd.append("--skip-covered-periods")

    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    keys = _split_secret_list(settings.FUNDAMENTAL_LLM_API_KEYS)
    if keys:
        env["GEMINI_API_KEYS"] = ",".join(keys)
        env.setdefault("GEMINI_API_KEY", keys[0])
    return subprocess.run(
        cmd,
        cwd=str(fama_dir),
        env=env,
        text=True,
        capture_output=True,
        timeout=settings.FAMA_FRENCH_TARGET_TIMEOUT_SECONDS,
        check=False,
    )


def _row_matches_terms(company: str, ticker: str, terms: list[str]) -> bool:
    haystack = _normalize_company(f"{company} {ticker}")
    tokens = set(haystack.split())
    for term in terms:
        needle = _normalize_company(term)
        if not needle:
            continue
        if len(needle) <= 3 and needle.isalnum():
            if needle in tokens:
                return True
            continue
        if needle in haystack or haystack in needle:
            return True
    return False


def _patch_market_map(workbook_path: Path, stocks: dict[str, models.StockMaster], company_terms: dict[str, list[str]]) -> None:
    wb = load_workbook(workbook_path)
    if "Market_Map" not in wb.sheetnames:
        wb.save(workbook_path)
        return

    ws = wb["Market_Map"]
    headers = {str(cell.value or "").strip(): cell.column for cell in ws[1]}
    company_col = headers.get("Company in Long_Data") or headers.get("Company") or 1
    mapped_col = headers.get("Mapped market company")
    ticker_col = headers.get("Ticker")
    shares_col = headers.get("Shares outstanding")
    match_col = headers.get("Match type")
    note_col = headers.get("Score / Note")
    if ticker_col is None:
        ticker_col = ws.max_column + 1
        ws.cell(row=1, column=ticker_col, value="Ticker")
    if shares_col is None:
        shares_col = ws.max_column + 1
        ws.cell(row=1, column=shares_col, value="Shares outstanding")

    patched: set[str] = set()
    for row_idx in range(2, ws.max_row + 1):
        company = str(ws.cell(row=row_idx, column=company_col).value or "")
        mapped = str(ws.cell(row=row_idx, column=mapped_col).value or "") if mapped_col else ""
        ticker = str(ws.cell(row=row_idx, column=ticker_col).value or "")
        for symbol, terms in company_terms.items():
            if symbol not in stocks:
                continue
            if _row_matches_terms(f"{company} {mapped}", ticker, terms):
                stock = stocks[symbol]
                ws.cell(row=row_idx, column=ticker_col, value=symbol)
                if stock.shares_outstanding:
                    ws.cell(row=row_idx, column=shares_col, value=int(stock.shares_outstanding))
                if match_col:
                    ws.cell(row=row_idx, column=match_col, value="targeted_bvc")
                if note_col:
                    ws.cell(row=row_idx, column=note_col, value="Canonicalized by targeted BVC backfill")
                patched.add(symbol)
                break

    for symbol in sorted(set(stocks) - patched):
        stock = stocks[symbol]
        row_idx = ws.max_row + 1
        ws.cell(row=row_idx, column=company_col, value=stock.display_name or symbol)
        if mapped_col:
            ws.cell(row=row_idx, column=mapped_col, value=stock.display_name or symbol)
        ws.cell(row=row_idx, column=ticker_col, value=symbol)
        if stock.shares_outstanding:
            ws.cell(row=row_idx, column=shares_col, value=int(stock.shares_outstanding))
        if match_col:
            ws.cell(row=row_idx, column=match_col, value="targeted_bvc_fallback")
        if note_col:
            ws.cell(row=row_idx, column=note_col, value="Added by targeted BVC backfill")

    wb.save(workbook_path)


YEAR_FIELD_RE = re.compile(r"^(?P<metric>.+)_(?P<year>20\d{2}|19\d{2})$")
BVC_OPERATING_CF_METRICS = (
    "Flux_de_tresorerie_lies_a_lactivite",
    "Flux_tresorerie_activites_operationnelles",
    "Operating_Cash_Flow",
    "CF_Operating",
)
BVC_INVESTING_CF_METRICS = (
    "Flux_de_tresorerie_lies_aux_investissements",
    "CF_Investing",
)
BVC_CAPEX_METRICS = (
    "Flux_tresorerie_investissement_CAPEX",
    "Capex",
    "Capital_Expenditures",
)


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _date_or_none(value: Any) -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _load_bvc_jsonl_rows(fama_dir: Path) -> list[dict[str, Any]]:
    path = fama_dir / "data" / "raw" / "all_results.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def _matches_source_urls(row: dict[str, Any], source_urls: list[str]) -> bool:
    if not source_urls:
        return True
    raw_url = str(row.get("Source_URL") or row.get("pdf_url") or "")
    normalized = raw_url.lower()
    return any(url.lower() in normalized or normalized in url.lower() for url in source_urls)


BVC_DEFAULT_PERIOD_TYPES = ["annual", "semiannual", "quarterly"]
BVC_PERIOD_TYPE_ALIASES = {
    "yearly": ["annual"],
    "annuel": ["annual"],
    "annual": ["annual"],
    "semester": ["semiannual"],
    "semestriel": ["semiannual"],
    "semestre": ["semiannual"],
    "semiannual": ["semiannual"],
    "quarter": ["quarterly"],
    "quarterly": ["quarterly"],
    "trimestriel": ["quarterly"],
    "trimestre": ["quarterly"],
    "interim": ["semiannual", "quarterly"],
    "interimaire": ["semiannual", "quarterly"],
}


def _normalize_period_types(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for value in values or BVC_DEFAULT_PERIOD_TYPES:
        normalized = str(value or "").strip().lower()
        for period_type in BVC_PERIOD_TYPE_ALIASES.get(normalized, [normalized]):
            if period_type in {"annual", "semiannual", "quarterly"} and period_type not in out:
                out.append(period_type)
    return out or list(BVC_DEFAULT_PERIOD_TYPES)


def _period_title(row: dict[str, Any]) -> str:
    return _normalize_company(f"{row.get('Document_Title') or row.get('title') or ''} {row.get('Source_URL') or row.get('pdf_url') or ''}").lower()


def _period_label_from_title(row: dict[str, Any], period_type: str) -> str | None:
    title = _period_title(row)
    if period_type == "quarterly":
        if any(token in title for token in ("t1", "q1", "1er trimestre", "1ere trimestre", "1eme trimestre", "premier trimestre")):
            return "Q1"
        if any(token in title for token in ("t2", "q2", "2eme trimestre", "deuxieme trimestre")):
            return "Q2"
        if any(token in title for token in ("t3", "q3", "3eme trimestre", "troisieme trimestre")):
            return "Q3"
        if any(token in title for token in ("t4", "q4", "4eme trimestre", "quatrieme trimestre")):
            return "Q4"
    if period_type == "semiannual":
        if any(token in title for token in ("s1", "h1", "1er semestre", "1ere semestre", "1eme semestre", "premier semestre")):
            return "S1"
        if any(token in title for token in ("s2", "h2", "2eme semestre", "deuxieme semestre")):
            return "S2"
    if period_type == "annual":
        return "FY"
    return None


def _normalized_period_type(row: dict[str, Any]) -> str:
    raw = str(row.get("Period_Type") or "").strip().lower()
    if raw in {"annual", "semiannual", "quarterly"}:
        return raw
    title = _period_title(row)
    if any(token in title for token in ("trimestre", "t1", "t2", "t3", "t4", "q1", "q2", "q3", "q4")):
        return "quarterly"
    if any(token in title for token in ("semestre", "s1", "s2", "h1", "h2")):
        return "semiannual"
    if any(token in title for token in ("rapport financier annuel", "rapport annuel", "resultats financiers", "rfa")):
        return "annual"
    return raw or "unknown"


def _normalized_period_label(row: dict[str, Any], period_type: str) -> str:
    inferred = _period_label_from_title(row, period_type)
    if inferred:
        return inferred
    raw = str(row.get("Period_Label") or "").strip().upper()
    if raw:
        return raw
    return "FY" if period_type == "annual" else ""


def _matches_period(row: dict[str, Any], period_types: list[str], years: list[int]) -> bool:
    period_type = _normalized_period_type(row)
    fiscal_year = _safe_int(row.get("Fiscal_Year"))
    if period_types and period_type not in set(period_types):
        return False
    if years and fiscal_year not in set(years):
        return False
    return True


def _symbol_for_result_row(
    row: dict[str, Any],
    *,
    stocks: dict[str, models.StockMaster],
    company_terms: dict[str, list[str]],
) -> str | None:
    ticker = str(row.get("Ticker") or row.get("Symbol") or "").strip().upper()
    company = str(row.get("Company") or row.get("company_name") or "")
    title = str(row.get("Document_Title") or row.get("title") or "")
    source_url = str(row.get("Source_URL") or row.get("pdf_url") or "")
    evidence = _normalize_company(f"{company} {title} {source_url}")
    evidence_matches: list[str] = []
    for symbol, terms in company_terms.items():
        if _row_matches_terms(company, "", terms) or _row_matches_terms(title, source_url, terms):
            evidence_matches.append(symbol)
    if ticker in stocks:
        if not evidence:
            return ticker
        if ticker in evidence_matches:
            return ticker
        if evidence_matches:
            return evidence_matches[0]
        return None
    if evidence_matches:
        return evidence_matches[0]
    return None


def _period_metric_models_from_result_row(
    row: dict[str, Any],
    *,
    import_id: uuid.UUID,
    source_document_id: int | None,
    symbol: str,
) -> list[models.FundamentalPeriodMetric]:
    company = str(row.get("Company") or row.get("company_name") or symbol)
    period_type = _normalized_period_type(row)
    period_label = _normalized_period_label(row, period_type)
    source_url = str(row.get("Source_URL") or row.get("pdf_url") or "") or None
    title = str(row.get("Document_Title") or row.get("title") or "") or None
    period_end = _date_or_none(row.get("Period_End_Date"))
    out: list[models.FundamentalPeriodMetric] = []
    seen: set[tuple[int, str]] = set()
    values_by_year: dict[int, dict[str, float]] = {}
    for key, value in row.items():
        match = YEAR_FIELD_RE.match(str(key))
        if not match:
            continue
        metric_value = _safe_float(value)
        if metric_value is None:
            continue
        year = int(match.group("year"))
        metric_name = match.group("metric")
        values_by_year.setdefault(year, {})[metric_name] = metric_value
        dedupe_key = (year, metric_name)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(
            models.FundamentalPeriodMetric(
                import_id=import_id,
                source_document_id=source_document_id,
                symbol=symbol,
                company_name=company,
                fiscal_year=year,
                period_type=period_type,
                period_label=period_label,
                period_end_date=period_end,
                metric_name=metric_name,
                metric_value=metric_value,
                raw_metric_name=key,
                source_url=source_url,
                document_title=title,
                is_proxy=False,
            )
        )
    for year, values in values_by_year.items():
        if (year, "Free_Cash_Flow") in seen:
            continue
        cfo = _first_metric_value(values, BVC_OPERATING_CF_METRICS)
        investing = _first_metric_value(values, BVC_INVESTING_CF_METRICS)
        capex = _first_metric_value(values, BVC_CAPEX_METRICS)
        if cfo is None:
            continue
        if investing is not None:
            fcf = cfo + investing
            raw_metric_name = f"derived:cfo_plus_investing_cf:{year}"
        elif capex is not None:
            fcf = cfo - abs(capex)
            raw_metric_name = f"derived:cfo_minus_capex:{year}"
        else:
            continue
        seen.add((year, "Free_Cash_Flow"))
        out.append(
            models.FundamentalPeriodMetric(
                import_id=import_id,
                source_document_id=source_document_id,
                symbol=symbol,
                company_name=company,
                fiscal_year=year,
                period_type=period_type,
                period_label=period_label,
                period_end_date=period_end,
                metric_name="Free_Cash_Flow",
                metric_value=fcf,
                raw_metric_name=raw_metric_name,
                source_url=source_url,
                document_title=title,
                is_proxy=True,
            )
        )
    return out


def _first_metric_value(values: dict[str, float], names: tuple[str, ...]) -> float | None:
    for name in names:
        value = values.get(name)
        if value is not None:
            return value
    return None


DOCUMENT_KIND_RANK = {"RFA": 3, "CP": 2, "NOTICE": 1}


def _document_kind(row: dict[str, Any]) -> str | None:
    kind = str(row.get("Document_Kind") or row.get("document_kind") or "").strip()
    if kind:
        return kind.upper() if kind.upper() in {"RFA", "CP"} else kind.lower()
    haystack = f"{row.get('Document_Title') or row.get('title') or ''} {row.get('Source_URL') or row.get('pdf_url') or ''}".lower()
    if "rapport financier annuel" in haystack or "rapport annuel" in haystack or "rfa" in haystack:
        return "RFA"
    if "communique" in haystack or "communiqu" in haystack or "/cp" in haystack:
        return "CP"
    if "notice" in haystack:
        return "notice"
    return None


def _result_row_priority(row: dict[str, Any]) -> tuple[int, int, dt.date, str]:
    kind = _document_kind(row)
    return (
        DOCUMENT_KIND_RANK.get(str(kind or "").upper(), 0),
        int(_safe_int(row.get("Extracted_Field_Count")) or 0),
        _date_or_none(row.get("Publication_Date") or row.get("date")) or dt.date.min,
        str(row.get("Source_URL") or row.get("pdf_url") or ""),
    )


def _persist_bvc_lineage(
    db,
    *,
    import_id: uuid.UUID,
    symbols: list[str],
    stocks: dict[str, models.StockMaster],
    company_terms: dict[str, list[str]],
    source_urls: list[str],
    period_types: list[str],
    years: list[int],
) -> tuple[int, int]:
    rows = sorted(
        _load_bvc_jsonl_rows(Path(settings.FAMA_FRENCH_DIR)),
        key=_result_row_priority,
        reverse=True,
    )
    wanted_symbols = {symbol.upper() for symbol in symbols}

    db.query(models.FundamentalPeriodMetric).filter(models.FundamentalPeriodMetric.import_id == import_id).delete(synchronize_session=False)
    db.query(models.FundamentalSourceDocument).filter(models.FundamentalSourceDocument.import_id == import_id).delete(synchronize_session=False)
    db.flush()

    document_count = 0
    metric_count = 0
    document_by_url_symbol: dict[tuple[str, str], models.FundamentalSourceDocument] = {}
    seen_metric_keys: set[tuple[str, int, str, str, str]] = set()
    for row in rows:
        if not _matches_source_urls(row, source_urls):
            continue
        if not _matches_period(row, period_types, years):
            continue
        symbol = _symbol_for_result_row(row, stocks=stocks, company_terms=company_terms)
        if wanted_symbols and symbol not in wanted_symbols:
            continue
        if not source_urls and not wanted_symbols and not symbol:
            continue

        source_url = str(row.get("Source_URL") or row.get("pdf_url") or "")
        if not source_url:
            continue
        status = str(row.get("Status") or "unknown").lower()
        document_key = (source_url, symbol or "")
        document = document_by_url_symbol.get(document_key)
        if document is None:
            document = models.FundamentalSourceDocument(
                import_id=import_id,
                symbol=symbol,
                company_name=str(row.get("Company") or row.get("company_name") or "") or None,
                document_title=str(row.get("Document_Title") or row.get("title") or "") or None,
                source_url=source_url,
                document_kind=_document_kind(row),
                publication_date=_date_or_none(row.get("Publication_Date") or row.get("date")),
                fiscal_year=_safe_int(row.get("Fiscal_Year")),
                period_type=_normalized_period_type(row),
                period_label=_normalized_period_label(row, _normalized_period_type(row)) or None,
                period_end_date=_date_or_none(row.get("Period_End_Date")),
                status="succeeded" if status == "success" else status,
                error_message=str(row.get("Error") or row.get("error") or "") or None,
                extracted_field_count=int(_safe_int(row.get("Extracted_Field_Count")) or 0),
                raw_json=sanitize_json_compatible(row),
            )
            db.add(document)
            db.flush()
            document_by_url_symbol[document_key] = document
            document_count += 1

        if symbol and status == "success":
            metrics = []
            for metric in _period_metric_models_from_result_row(
                row,
                import_id=import_id,
                source_document_id=int(document.id),
                symbol=symbol,
            ):
                key = (metric.symbol, metric.fiscal_year, metric.period_type, metric.period_label, metric.metric_name)
                if key in seen_metric_keys:
                    continue
                seen_metric_keys.add(key)
                metrics.append(metric)
            db.bulk_save_objects(metrics)
            metric_count += len(metrics)
    return document_count, metric_count


def _mark_failed(db, import_id: uuid.UUID, message: str, *, stdout: str = "", stderr: str = "") -> None:
    row = db.get(models.FundamentalImport, import_id)
    if row is None:
        return
    delete_fundamental_import_artifacts(db, import_id=import_id, include_statement_rows=True)
    summary = dict(row.summary_json or {})
    summary["targeted_bvc_error"] = message
    if stdout:
        summary["scraper_stdout_tail"] = _command_output_tail(stdout)
    if stderr:
        summary["scraper_stderr_tail"] = _command_output_tail(stderr)
    row.status = "failed"
    row.error_message = message
    row.summary_json = sanitize_json_compatible(summary)
    row.completed_at = _utcnow()
    db.add(row)
    db.commit()


def execute_bvc_fundamental_import(
    import_id: str,
    *,
    symbols: list[str],
    source_urls: list[str] | None = None,
    sectors: list[str] | None = None,
    period_types: list[str] | None = None,
    fields: list[str] | None = None,
    years: list[int] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    only_unseen: bool = True,
    force: bool = False,
    batch_id: str | None = None,
) -> dict[str, object]:
    db = SessionLocal()
    run_id = uuid.UUID(str(import_id))
    symbols = sorted({symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()})
    source_urls = sorted({url.strip() for url in source_urls or [] if url and url.strip()})
    sectors = sorted({sector.strip() for sector in sectors or [] if sector and sector.strip()})
    period_types = _normalize_period_types(period_types)
    years = [int(year) for year in (years or []) if int(year) > 1900]
    if not years and (start_year is not None or end_year is not None):
        start = int(start_year or end_year or 1900)
        end = int(end_year or start_year or dt.date.today().year)
        if start > end:
            start, end = end, start
        years = list(range(start, end + 1))
    fields = fields or []
    try:
        row = db.get(models.FundamentalImport, run_id)
        if row is None:
            raise ValueError(f"fundamental import {import_id} not found")
        row.status = "running"
        row.imported_at = _utcnow()
        row.summary_json = sanitize_json_compatible({
            **dict(row.summary_json or {}),
            "targeted_bvc": True,
            "symbols": symbols,
            "source_urls": source_urls,
            "source_url_count": len(source_urls),
            "sectors": sectors,
            "period_types": period_types,
            "fields": fields,
            "years": years,
            "broad_scan": not symbols and not source_urls,
            "only_unseen": only_unseen,
            "force": force,
        })
        db.add(row)
        db.commit()

        requested_stocks = _stock_rows(db, symbols)
        missing = sorted(set(symbols) - set(requested_stocks))
        if missing:
            raise ValueError(f"Unknown stock_master symbols: {', '.join(missing)}")
        mapping_stocks = requested_stocks if requested_stocks else _all_bvc_stock_rows(db)
        scraper_terms = _target_company_terms(requested_stocks)
        if source_urls:
            scraper_terms["__source_urls__"] = source_urls
        mapping_terms = _target_company_terms(mapping_stocks)
        if source_urls:
            mapping_terms["__source_urls__"] = source_urls

        with tempfile.TemporaryDirectory(prefix="targeted_bvc_") as tmp:
            output_path = Path(tmp) / f"targeted_bvc_{batch_id or run_id}.xlsx"
            result = _run_scraper(
                symbols=symbols,
                company_terms=scraper_terms,
                years=years,
                period_types=period_types,
                only_unseen=only_unseen,
                force=force,
                output_path=output_path,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"BVC scraper failed with exit code {result.returncode}: {_command_output_tail(result.stderr or result.stdout, 1200)}"
                )
            if not output_path.exists():
                raise FileNotFoundError(f"BVC scraper did not produce workbook: {output_path}")

            _patch_market_map(output_path, mapping_stocks, mapping_terms)
            payload = output_path.read_bytes()

        imported = execute_import_run(db, import_id=run_id, payload=payload)
        document_count, period_metric_count = _persist_bvc_lineage(
            db,
            import_id=run_id,
            symbols=symbols,
            stocks=mapping_stocks,
            company_terms=mapping_terms,
            source_urls=source_urls,
            period_types=period_types,
            years=years,
        )
        pit_sync = sync_bvc_period_metrics_to_annual_and_latest(
            db,
            import_id=run_id,
            symbols={symbol.upper() for symbol in symbols} if symbols else None,
        )
        stockanalysis_pit_reconciliation = reconcile_stockanalysis_publication_dates(
            db,
            apply=True,
            symbols={symbol.upper() for symbol in symbols} if symbols else None,
        )
        refreshed = refresh_import_after_pit_sync(db, import_id=run_id)
        summary = dict(imported.summary_json or {})
        summary["targeted_bvc"] = {
            "batch_id": batch_id,
            "symbols": symbols,
            "source_urls": source_urls,
            "source_url_count": len(source_urls),
            "sectors": sectors,
            "period_types": period_types,
            "fields": fields,
            "years": years,
            "only_unseen": only_unseen,
            "force": force,
            "broad_scan": not symbols and not source_urls,
            "company_terms": scraper_terms,
            "mapping_symbol_count": len(mapping_stocks),
            "source_document_count": document_count,
            "period_metric_count": period_metric_count,
            "pit_sync": pit_sync,
            "stockanalysis_pit_reconciliation": stockanalysis_pit_reconciliation,
            "pit_refresh": refreshed,
            "scraper_stdout_tail": _command_output_tail(result.stdout),
            "scraper_stderr_tail": _command_output_tail(result.stderr),
        }
        imported.summary_json = sanitize_json_compatible(summary)
        db.add(imported)
        db.commit()
        db.refresh(imported)
        return {
            "import_id": str(imported.id),
            "status": imported.status,
            "symbols": int(imported.latest_snapshot_count or 0),
            "quality_issues": int(imported.quality_issue_count or 0),
            "source_documents": document_count,
            "period_metrics": period_metric_count,
        }
    except Exception as exc:
        db.rollback()
        _mark_failed(db, run_id, str(exc))
        raise
    finally:
        db.close()


def execute_targeted_bvc_fundamental_import(
    import_id: str,
    *,
    symbols: list[str],
    fields: list[str] | None = None,
    years: list[int] | None = None,
    batch_id: str | None = None,
) -> dict[str, object]:
    return execute_bvc_fundamental_import(
        import_id,
        symbols=symbols,
        fields=fields,
        years=years,
        batch_id=batch_id,
    )
