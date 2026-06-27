from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from curl_cffi import requests
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.api.app import models  # noqa: E402
from services.api.app.json_sanitize import sanitize_json_compatible  # noqa: E402
from services.api.app.services.fundamentals import (  # noqa: E402
    create_import_run,
    refresh_import_after_pit_sync,
    sync_bvc_period_metrics_to_annual_and_latest,
)
from services.worker.db import SessionLocal  # noqa: E402
from services.worker.tasks.targeted_bvc_fundamentals import (  # noqa: E402
    _all_bvc_stock_rows,
    _target_company_terms,
)


API_URL = "https://www.casablanca-bourse.com/api/proxy/fr/api/node/publication_societe_bourse"
ANALYSES_URL = "https://www.casablanca-bourse.com/fr/analyses-recherches"
BROKER_NAME = "Attijari Global Research"
DEFAULT_START_DATE = dt.date(2024, 1, 1)
CACHE_DIR = ROOT / ".cache" / "attijari_morning_briefs"


@dataclass(frozen=True)
class Publication:
    title: str
    publication_date: dt.date
    broker: str
    source_url: str
    node_id: str


@dataclass(frozen=True)
class ExtractedMetric:
    symbol: str
    company_name: str
    fiscal_year: int
    period_type: str
    period_label: str
    metric_name: str
    metric_value: float
    raw_metric_name: str
    unit: str | None = None


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.strip().upper().replace(".", " ").split())


def _date_or_none(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _client_get(url: str, *, timeout: int = 60):
    return requests.get(
        url,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Referer": ANALYSES_URL,
            "User-Agent": "Mozilla/5.0",
        },
        impersonate="chrome110",
        verify=False,
        timeout=timeout,
    )


def _included_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in payload.get("included", []) if item.get("id")}


def _extract_pdf_url(item: dict[str, Any], included: dict[str, dict[str, Any]]) -> str | None:
    media_ref = item.get("relationships", {}).get("field_vactory_media_document", {}).get("data") or {}
    media = included.get(str(media_ref.get("id")))
    if not media:
        return None
    file_ref = media.get("relationships", {}).get("field_media_file", {}).get("data") or {}
    file_item = included.get(str(file_ref.get("id")))
    if not file_item:
        return None
    uri = file_item.get("attributes", {}).get("uri", {}).get("value", {})
    return uri.get("_default")


def _extract_broker(item: dict[str, Any], included: dict[str, dict[str, Any]]) -> str:
    broker_ref = item.get("relationships", {}).get("field_societe", {}).get("data") or {}
    broker_item = included.get(str(broker_ref.get("id"))) or {}
    return str(broker_item.get("attributes", {}).get("name") or "")


def discover_publications(
    *,
    start_date: dt.date,
    end_date: dt.date,
    max_pages: int,
    page_size: int = 50,
) -> list[Publication]:
    include = "field_vactory_media_document,field_vactory_media_document.field_media_file,field_societe"
    out: list[Publication] = []
    seen_urls: set[str] = set()

    for page in range(max_pages):
        offset = page * page_size
        params = (
            f"include={include}"
            f"&page%5Blimit%5D={page_size}"
            f"&page%5Boffset%5D={offset}"
            "&filter%5Bstatus%5D%5Bvalue%5D=1"
            "&filter%5Blangcode%5D=fr"
            "&sort%5Bsort-vactory-date%5D%5Bpath%5D=field_vactory_date"
            "&sort%5Bsort-vactory-date%5D%5Bdirection%5D=DESC"
        )
        response = _client_get(f"{API_URL}?{params}", timeout=90)
        response.raise_for_status()
        payload = response.json()
        items = payload.get("data", [])
        if not items:
            break
        included = _included_by_id(payload)
        page_dates: list[dt.date] = []
        for item in items:
            attrs = item.get("attributes", {})
            publication_date = _date_or_none(attrs.get("field_vactory_date"))
            if publication_date is None:
                continue
            page_dates.append(publication_date)
            if publication_date < start_date or publication_date > end_date:
                continue
            title = str(attrs.get("title") or "")
            broker = _extract_broker(item, included)
            if broker != BROKER_NAME or "morning" not in title.lower():
                continue
            source_url = _extract_pdf_url(item, included)
            if not source_url or source_url in seen_urls:
                continue
            seen_urls.add(source_url)
            out.append(
                Publication(
                    title=title,
                    publication_date=publication_date,
                    broker=broker,
                    source_url=source_url,
                    node_id=str(item.get("id") or ""),
                )
            )
        if page_dates and max(page_dates) < start_date:
            break
    return sorted(out, key=lambda item: item.publication_date)


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    name = Path(url.split("?", 1)[0]).name or f"{digest}.pdf"
    return CACHE_DIR / f"{digest}_{name}"


def download_pdf(url: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(url)
    if path.exists() and path.stat().st_size > 1000:
        return path
    response = _client_get(url, timeout=120)
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise ValueError(f"Downloaded content is not a PDF for {url}")
    path.write_bytes(response.content)
    return path


def extract_pdf_text(path: Path) -> str:
    with path.open("rb") as handle:
        reader = PdfReader(handle)
        return "\n".join(page.extract_text() or "" for page in reader.pages)


HEADER_RE = re.compile(r"^\|\s*MAROC\s*\|\s*(?P<company>[^|]+?)\s*\|(?P<title>.*)$", re.IGNORECASE)
PERIOD_RE = re.compile(r"\b(?:(?P<tag>T[1-4]|Q[1-4]|S[12]|FY)\s*)?(?P<year>20\d{2})\b", re.IGNORECASE)
NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d{3})*(?:,\d+)?%?|[-+]?\d+(?:,\d+)?%?")
TABLE_OWNER_SIGNAL_RE = re.compile(
    r"\b(PNB|RBE|RNPG|RNPG|RESULTAT\s+NET|MARGE|COUT\s+DU\s+RISQUE|RISQUE)\b",
    re.IGNORECASE,
)


def _periods_from_header(header: str) -> list[tuple[int, str, str]]:
    periods: list[tuple[int, str, str]] = []
    for match in PERIOD_RE.finditer(header):
        tag = (match.group("tag") or "FY").upper().replace("T", "Q")
        year = int(match.group("year"))
        if tag.startswith("Q"):
            periods.append((year, "quarterly", tag))
        elif tag.startswith("S"):
            periods.append((year, "semiannual", tag))
        else:
            periods.append((year, "annual", "FY"))
    return periods


def _unit_from_header(header: str) -> str | None:
    normalized = _normalize_text(header)
    if "MMDH" in normalized or "MILLIARDS DE DH" in normalized or "MILLIARDS DE DIRHAMS" in normalized:
        return "MMDH"
    if "MDH" in normalized or "MILLIONS DE DH" in normalized or "MILLIONS DE DIRHAMS" in normalized:
        return "MDH"
    if "KDH" in normalized or "MILLIERS DE DH" in normalized or "MILLIERS DE DIRHAMS" in normalized:
        return "KDH"
    if "DH" in normalized:
        return "DH"
    return None


def _unit_scale(unit: str | None) -> float:
    if unit == "MMDH":
        return 1_000_000_000.0
    if unit == "MDH":
        return 1_000_000.0
    if unit == "KDH":
        return 1_000.0
    return 1.0


def _metric_name(raw: str) -> str:
    text = unicodedata.normalize("NFKD", raw)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("'", "").replace("’", "")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    return text or "Metric"


def _parse_number(raw: str) -> float | None:
    text = raw.strip().replace("%", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif re.search(r"\.\d{3}$", text):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _looks_like_split_thousands(left: str, right: str) -> bool:
    left_clean = left.strip().replace("%", "")
    right_clean = right.strip().replace("%", "")
    return (
        left_clean.lstrip("+-").isdigit()
        and right_clean.isdigit()
        and 1 <= len(left_clean.lstrip("+-")) <= 3
        and len(right_clean) == 3
    )


def _is_unscaled_metric(metric_name: str, raw_name: str) -> bool:
    normalized = _normalize_text(f"{metric_name} {raw_name}")
    tokens = set(normalized.split())
    if "MARGE" in tokens or metric_name.lower().startswith("marge_"):
        return True
    if normalized.startswith("DPA") or "DPA" in tokens:
        return True
    if "DH_ACTION" in metric_name.upper() or "PAR_ACTION" in metric_name.upper():
        return True
    if "TAUX" in tokens or "RATIO" in tokens or "ROE" in tokens or "ROA" in tokens:
        return True
    return False


def _apply_unit(value: float, *, unit: str | None, metric_name: str, raw_name: str) -> float:
    if _is_unscaled_metric(metric_name, raw_name):
        return value
    return value * _unit_scale(unit)


def _symbol_for_company(
    company: str,
    *,
    stocks: dict[str, models.StockMaster],
    company_terms: dict[str, list[str]],
) -> str | None:
    normalized = _normalize_text(company)
    if normalized in stocks:
        return normalized
    for symbol, terms in company_terms.items():
        if normalized == _normalize_text(symbol):
            return symbol
        normalized_terms = [_normalize_text(term) for term in terms if term]
        if any(term and term == normalized for term in normalized_terms):
            return symbol
        if any(term and len(term) >= 4 and term in normalized for term in normalized_terms):
            return symbol
        if any(len(normalized) >= 4 and normalized in term for term in normalized_terms):
            return symbol
    return None


def _parse_table_line(line: str, periods: list[tuple[int, str, str]]) -> tuple[str, list[float]] | None:
    matches = list(NUMBER_RE.finditer(line))
    if len(matches) < len(periods) or not matches:
        return None
    raw_name = line[: matches[0].start()].strip(" :-")
    normalized_name = _normalize_text(raw_name)
    if not raw_name or normalized_name in {"INDICATEURS", "VARIATION", "CASABLANCA", "MAROC"}:
        return None
    first_alpha = next((char for char in raw_name if char.isalpha()), "")
    if first_alpha and first_alpha != first_alpha.upper():
        return None
    if len(raw_name.split()) > 5:
        return None
    if normalized_name.split(" ", 1)[0] in {"A", "AU", "AUX", "DE", "DES", "DU", "LE", "LA", "LES"}:
        return None
    if len(raw_name) > 60 or any(token in normalized_name for token in ("ACTUALITES", "INFLATION", "CONSOMMATION")):
        return None
    tokens = [match.group(0) for match in matches]
    value_tokens: list[str] = []
    cursor = 0
    merge_split_thousands = len(tokens) >= 2 * len(periods)
    while len(value_tokens) < len(periods) and cursor < len(tokens):
        if (
            merge_split_thousands
            and cursor + 1 < len(tokens)
            and _looks_like_split_thousands(tokens[cursor], tokens[cursor + 1])
        ):
            value_tokens.append(f"{tokens[cursor]}{tokens[cursor + 1]}")
            cursor += 2
            continue
        value_tokens.append(tokens[cursor])
        cursor += 1
    if len(value_tokens) < len(periods):
        return None

    values: list[float] = []
    for token in value_tokens:
        value = _parse_number(token)
        if value is None:
            return None
        values.append(value)
    return raw_name, values


def extract_metrics_from_text(
    text: str,
    *,
    stocks: dict[str, models.StockMaster],
    company_terms: dict[str, list[str]],
) -> list[ExtractedMetric]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    out: list[ExtractedMetric] = []
    current_company: str | None = None
    current_symbol: str | None = None
    current_title = ""
    signal_company: str | None = None
    signal_symbol: str | None = None
    signal_line_idx = -10_000

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        header = HEADER_RE.match(line)
        if header:
            current_company = header.group("company").strip()
            current_symbol = _symbol_for_company(current_company, stocks=stocks, company_terms=company_terms)
            current_title = header.group("title").strip()
            if current_symbol and TABLE_OWNER_SIGNAL_RE.search(_normalize_text(f"{current_company} {current_title}")):
                signal_company = current_company
                signal_symbol = current_symbol
                signal_line_idx = idx
            idx += 1
            continue

        if "indicateurs" in _normalize_text(line).lower():
            periods = _periods_from_header(line)
            unit = _unit_from_header(line)
            owner_company = current_company
            owner_symbol = current_symbol
            current_has_signal = TABLE_OWNER_SIGNAL_RE.search(_normalize_text(f"{current_company or ''} {current_title}"))
            if signal_symbol and not current_has_signal and idx - signal_line_idx <= 20:
                owner_company = signal_company
                owner_symbol = signal_symbol
            if periods and owner_symbol and owner_company:
                idx += 1
                while idx < len(lines):
                    candidate = lines[idx]
                    normalized_candidate = _normalize_text(candidate)
                    if (
                        candidate.startswith("|")
                        or HEADER_RE.match(candidate)
                        or "indicateurs" in normalized_candidate.lower()
                        or normalized_candidate.startswith("ACTUALITES")
                    ):
                        break
                    parsed = _parse_table_line(candidate, periods)
                    if parsed is not None:
                        raw_name, values = parsed
                        metric_name = _metric_name(raw_name)
                        for (year, period_type, period_label), value in zip(periods, values):
                            out.append(
                                ExtractedMetric(
                                    symbol=owner_symbol,
                                    company_name=owner_company,
                                    fiscal_year=year,
                                    period_type=period_type,
                                    period_label=period_label,
                                    metric_name=metric_name,
                                    metric_value=_apply_unit(value, unit=unit, metric_name=metric_name, raw_name=raw_name),
                                    raw_metric_name=raw_name,
                                    unit=unit,
                                )
                            )
                    idx += 1
                continue
        idx += 1

    deduped: dict[tuple[str, int, str, str, str], ExtractedMetric] = {}
    for metric in out:
        key = (metric.symbol, metric.fiscal_year, metric.period_type, metric.period_label, metric.metric_name)
        deduped.setdefault(key, metric)
    return list(deduped.values())


def persist_metrics(
    *,
    publications: list[Publication],
    metrics_by_url: dict[str, list[ExtractedMetric]],
    dry_run: bool,
) -> dict[str, Any]:
    publications_by_url = {publication.source_url: publication for publication in publications}
    selected: dict[tuple[str, int, str, str, str], tuple[dt.date, str, ExtractedMetric]] = {}
    for source_url, metrics in metrics_by_url.items():
        publication = publications_by_url[source_url]
        for metric in metrics:
            key = (metric.symbol, metric.fiscal_year, metric.period_type, metric.period_label, metric.metric_name)
            rank = (publication.publication_date, source_url)
            if key not in selected or rank > (selected[key][0], selected[key][1]):
                selected[key] = (publication.publication_date, source_url, metric)
    deduped_by_url: dict[str, list[ExtractedMetric]] = {}
    for _date, source_url, metric in selected.values():
        deduped_by_url.setdefault(source_url, []).append(metric)
    metrics_by_url = deduped_by_url

    total_metrics = sum(len(metrics) for metrics in metrics_by_url.values())
    symbols = sorted({metric.symbol for metrics in metrics_by_url.values() for metric in metrics})
    if dry_run:
        return {"dry_run": True, "source_documents": len(metrics_by_url), "period_metrics": total_metrics, "symbols": symbols}

    db = SessionLocal()
    try:
        digest = hashlib.sha256(
            json.dumps(
                {
                    "kind": "attijari_morning_brief_backfill",
                    "urls": sorted(metrics_by_url),
                    "metric_count": total_metrics,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        run = create_import_run(
            db,
            data_source="bvc",
            source_universe="masi",
            filename=f"attijari_morning_brief_backfill_{_utcnow().date().isoformat()}.json",
            source_hash=digest,
            summary={
                "triggered_by": "backfill_attijari_morning_brief_fundamentals",
                "source": ANALYSES_URL,
                "broker": BROKER_NAME,
                "publication_count": len(publications),
                "source_document_count": len(metrics_by_url),
                "period_metric_count": total_metrics,
                "symbols": symbols,
            },
        )
        run.status = "running"
        run.imported_at = _utcnow()
        db.add(run)
        db.flush()

        document_count = 0
        metric_count = 0
        for source_url, metrics in sorted(metrics_by_url.items()):
            if not metrics:
                continue
            publication = publications_by_url[source_url]
            fiscal_years = sorted({metric.fiscal_year for metric in metrics})
            period_types = sorted({metric.period_type for metric in metrics})
            period_labels = sorted({metric.period_label for metric in metrics})
            document = models.FundamentalSourceDocument(
                import_id=run.id,
                symbol=metrics[0].symbol if len({metric.symbol for metric in metrics}) == 1 else None,
                company_name=", ".join(sorted({metric.company_name for metric in metrics}))[:255],
                document_title=publication.title,
                source_url=source_url,
                document_kind="research_note",
                publication_date=publication.publication_date,
                fiscal_year=max(fiscal_years) if fiscal_years else None,
                period_type=period_types[0] if len(period_types) == 1 else "mixed",
                period_label=period_labels[0] if len(period_labels) == 1 else "mixed",
                status="succeeded",
                extracted_field_count=len(metrics),
                raw_json=sanitize_json_compatible(
                    {
                        "node_id": publication.node_id,
                        "broker": publication.broker,
                        "source": ANALYSES_URL,
                        "symbols": sorted({metric.symbol for metric in metrics}),
                        "units": sorted({metric.unit for metric in metrics if metric.unit}),
                    }
                ),
            )
            db.add(document)
            db.flush()
            document_count += 1
            rows = [
                models.FundamentalPeriodMetric(
                    import_id=run.id,
                    source_document_id=int(document.id),
                    symbol=metric.symbol,
                    company_name=metric.company_name,
                    fiscal_year=metric.fiscal_year,
                    period_type=metric.period_type,
                    period_label=metric.period_label,
                    metric_name=metric.metric_name,
                    metric_value=metric.metric_value,
                    raw_metric_name=metric.raw_metric_name,
                    source_url=source_url,
                    document_title=publication.title,
                    is_proxy=False,
                )
                for metric in metrics
            ]
            db.bulk_save_objects(rows)
            metric_count += len(rows)

        pit_sync = sync_bvc_period_metrics_to_annual_and_latest(db, import_id=run.id, symbols=set(symbols))
        refreshed = refresh_import_after_pit_sync(db, import_id=run.id)
        run.status = "succeeded"
        run.completed_at = _utcnow()
        run.company_count = len(symbols)
        run.symbol_count = len(symbols)
        run.annual_metric_count = int(pit_sync.get("mapped_annual_metric_count", 0))
        run.latest_snapshot_count = int(refreshed.get("snapshot_count", 0))
        run.quality_issue_count = 0
        run.summary_json = sanitize_json_compatible(
            {
                **dict(run.summary_json or {}),
                "source_document_count": document_count,
                "period_metric_count": metric_count,
                "pit_sync": pit_sync,
                "pit_refresh": refreshed,
            }
        )
        db.add(run)
        db.commit()
        return {
            "import_id": str(run.id),
            "status": run.status,
            "source_documents": document_count,
            "period_metrics": metric_count,
            "annual_metrics": run.annual_metric_count,
            "latest_snapshots": run.latest_snapshot_count,
            "symbols": symbols,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run_backfill(args: argparse.Namespace) -> dict[str, Any]:
    db = SessionLocal()
    try:
        stocks = _all_bvc_stock_rows(db)
        company_terms = _target_company_terms(stocks)
    finally:
        db.close()

    publications = discover_publications(
        start_date=args.start_date,
        end_date=args.end_date,
        max_pages=args.max_pages,
    )
    metrics_by_url: dict[str, list[ExtractedMetric]] = {}
    errors: dict[str, str] = {}
    for publication in publications:
        try:
            pdf_path = download_pdf(publication.source_url)
            metrics = extract_metrics_from_text(
                extract_pdf_text(pdf_path),
                stocks=stocks,
                company_terms=company_terms,
            )
            if metrics:
                metrics_by_url[publication.source_url] = metrics
        except Exception as exc:
            errors[publication.source_url] = str(exc)

    result = persist_metrics(publications=publications, metrics_by_url=metrics_by_url, dry_run=args.dry_run)
    result["discovered_publications"] = len(publications)
    result["parsed_publications"] = len(metrics_by_url)
    result["download_or_parse_errors"] = errors
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill BVC fundamentals from Attijari Global Research Morning Brief tables.")
    parser.add_argument("--start-date", type=_date_or_none, default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", type=_date_or_none, default=dt.date.today())
    parser.add_argument("--max-pages", type=int, default=40, help="50-row BVC API pages to scan.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.start_date is None or args.end_date is None:
        parser.error("start-date and end-date must be ISO dates")
    return args


def main() -> None:
    result = run_backfill(_parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
