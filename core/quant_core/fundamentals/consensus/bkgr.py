"""BKGR stock-guide PDF adapter (brief 54 §3 Phase 1).

Parses bkgr-stock-guide-juin-2026.pdf (and future editions) into ConsensusEstimate
rows for EPS_Forward, PER_Forward, Target_Price, and Rating.

PDF structure (June 2026 edition):
  Page 1: Cover ("Juin 2026")
  Page 2: Abbreviations — two-column "TICKER COMPANY_NAME  TICKER COMPANY_NAME"
  Page 3: Synthesis table (not parsed by this adapter — company names here are
           informational; ratings come from the detail pages directly)
  Pages 4+: One page per company, each containing:
    Header:  "COMPANY_NAME  SECTOR  Maroc" (double-space separated)
    Target:  "Objectif de cours : MAD 42,3  Upside : +28,2%  Recommandation : Achat"
    Date:    "En date du 25/05/26"
    INDICATEURS BOURSIERS table:
      "En MAD  2024  2025 2026e 2027e"
      "BPA  0,7  1,1  0,9  0,9"       ← French commas for decimals
      "PER  57,7x  31,9x  38,2x  35,4x"
      "DPA  0    0    0    0"
      "D/Y  0,0%   0,0%   0,0%   0,0%"

Company→ticker join (brief 53 §4, brief 54 §3):
  1. Parse abbreviations page (page 2) → {company_name_upper: ticker} map.
     Line-by-line, split each line on 2+ spaces → "TICKER COMPANY_NAME" entries.
  2. For each detail page, extract company_name from the header line
     (first field before the first 2+ spaces).
  3. Resolve ticker via: exact map lookup → supplement dict (known gaps like
     COLORADO→COL) → longest-prefix match → fuzzy (alpha-only normalized) →
     ticker-direct heuristic (2-5 uppercase chars, e.g. RDS, HPS, IAM, CDM).
  4. No synthesis-table position dependency — resolution is purely by company name.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

from .domain import (
    METRIC_EPS_FORWARD,
    METRIC_PER_FORWARD,
    METRIC_RATING,
    METRIC_TARGET_PRICE,
    ConsensusEstimate,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOURCE_NAME = "bkgr"

# Companies absent from the abbreviations page; map detail-page company_name → ticker.
_COMPANY_TICKER_SUPPLEMENTS: dict[str, str] = {
    "COLORADO": "COL",
    "RESIDENCES DAR SAADA": "RDS",
}

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# "En MAD  2024  2025 2026e 2027e" (INDICATEURS BOURSIERS section in each company page)
_YEAR_HEADER_RE = re.compile(
    r"\bEn MAD\s+(20\d{2}[Ee]?)\s+(20\d{2}[Ee]?)\s+(20\d{2}[Ee]?)\s+(20\d{2}[Ee]?)",
    re.IGNORECASE,
)

# BPA / PER / DPA / D/Y rows.  Values use French commas; per-share → no thousands.
_NUM_PAT = r"[-+]?\d+(?:[,.]\d+)?(?:x)?"
_ROW_RE = re.compile(
    r"\b(BPA|PER|DPA|D/Y)\b\s+"
    r"(" + _NUM_PAT + r"|ns|-)\s+"
    r"(" + _NUM_PAT + r"|ns|-)\s+"
    r"(" + _NUM_PAT + r"|ns|-)\s+"
    r"(" + _NUM_PAT + r"|ns|-)",
    re.IGNORECASE,
)

# "Objectif de cours : MAD 42,3  ..." or "... MAD 4 626  ..."
_TARGET_RE = re.compile(
    r"Objectif de cours\s*[:\-]\s*MAD\s*([\d\s,\.]+?)(?:\s{2,}|\s+(?:Upside|Downside|Recommandation))",
    re.IGNORECASE,
)

# "Recommandation : Acheter" (or "Achat", "Accumuler", etc.)
_RATING_RE = re.compile(
    r"Recommandation\s*[:\-]\s*(Acheter|Achat|Accumuler|Conserver|Vendre)",
    re.IGNORECASE,
)

# Date: "En date du 25/05/26" or "Cours au 25.05.26"
_DATE_RE = re.compile(
    r"(?:En date du|Cours au|Prix au)\s+(\d{1,2})[/\.\-](\d{1,2})[/\.\-](\d{2,4})",
    re.IGNORECASE,
)

# Abbreviations page entry: leading 2-5 uppercase chars followed by a space and company name
_ABBREV_ENTRY_RE = re.compile(r"^([A-Z]{2,5})\s+(.+)$")


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------

@dataclass
class _CompanyPage:
    page_no: int
    company_name: str           # first field of header line (uppercase)
    years: list[str]            # ["2024","2025","2026e","2027e"]
    rows: dict[str, list[str]]  # metric -> [v1,v2,v3,v4]
    target: float | None
    rating: str | None


# ---------------------------------------------------------------------------
# Number/text helpers
# ---------------------------------------------------------------------------

def _clean_num(s: str) -> float | None:
    """Parse a French-format number (comma decimal, optional x suffix)."""
    if not s or s.strip() in ("-", "ns", ""):
        return None
    # Keep only digits, comma (French decimal), dot, minus sign; strip x suffix
    cleaned = re.sub(r"[^\d,.\-]", "", s).replace(",", ".")
    cleaned = cleaned.strip(".")
    if not cleaned or cleaned == "-":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _clean_target(raw: str) -> float | None:
    """Parse a target-price string that may contain space/ௗ thousand separators."""
    # Remove Tamil thousand separator (U+0BF4) and any non-numeric chars except comma/dot/minus
    raw = raw.replace("௴", "")
    raw = re.sub(r"[^\d,\.\s\-]", "", raw)
    raw = re.sub(r"\s+", "", raw)      # remove thousand-sep spaces
    raw = raw.replace(",", ".")
    raw = raw.strip(".")
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _normalize_rating(raw: str) -> str:
    """Normalize rating variants: 'Achat' → 'Acheter'."""
    r = raw.strip().capitalize()
    return "Acheter" if r == "Achat" else r


def _alphanum(s: str) -> str:
    """Return uppercase alphanumeric-only string for fuzzy matching."""
    return re.sub(r"[^A-Z0-9]", "", s.upper())


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def _parse_date(full_text: str) -> dt.date:
    """Extract the priced-as-of date from PDF text. Defaults to 25 May 2026."""
    for m in _DATE_RE.finditer(full_text):
        try:
            day = int(m.group(1))
            month = int(m.group(2))
            year = int(m.group(3))
            if year < 100:
                year += 2000
            return dt.date(year, month, day)
        except (ValueError, TypeError):
            continue
    return dt.date(2026, 5, 25)


# ---------------------------------------------------------------------------
# Abbreviations page (page 2) parser
# ---------------------------------------------------------------------------

def _parse_abbreviations(page_text: str) -> dict[str, str]:
    """Parse the abbreviations page into {company_name_upper: ticker}.

    Each line has the format:
      "TICKER COMPANY_NAME  TICKER COMPANY_NAME"
    where entries on the same line are separated by 2+ spaces.
    """
    result: dict[str, str] = {}
    for line in page_text.splitlines():
        # Split line into entries on 2+ spaces
        entries = re.split(r"\s{2,}", line.strip())
        for entry in entries:
            entry = entry.strip()
            m = _ABBREV_ENTRY_RE.match(entry)
            if m:
                ticker = m.group(1).strip().upper()
                company = m.group(2).strip().upper()
                if company:
                    result[company] = ticker
    return result


# ---------------------------------------------------------------------------
# Company detail page parser
# ---------------------------------------------------------------------------

def _parse_company_page(page_text: str, page_no: int) -> _CompanyPage | None:
    """Parse one company detail page."""
    lines = [ln for ln in page_text.splitlines() if ln.strip()]

    # Extract company name: first non-boilerplate line matching "NAME  SECTOR  Maroc"
    company_name: str | None = None
    _BOILER_RE = re.compile(
        r"^(Page\s*\|\s*\d|Juin\s+20\d{2}|INFORMATIONS|INDICATEURS|RECOMMANDATION|"
        r"SYNTHESE|ABREV|Analyste|Perf\.|Volatil|ACTIONNARIAT|Flottant|Cours\s*\(|"
        r"Nombre|Capitalis|FORCES|FAIBLESSES|OPPORTUNITES|MENACES|Siège)",
        re.IGNORECASE,
    )
    for line in lines:
        stripped = line.strip()
        if _BOILER_RE.match(stripped):
            continue
        if "Maroc" in stripped and re.match(r"^[A-Z]", stripped):
            # Company name = first field before 2+ spaces
            parts = re.split(r"\s{2,}", stripped)
            if parts:
                company_name = parts[0].strip().upper()
            break

    if not company_name:
        return None

    # Year header: "En MAD  2024  2025 2026e 2027e" in INDICATEURS BOURSIERS
    year_match = _YEAR_HEADER_RE.search(page_text)
    if not year_match:
        return None
    years = [year_match.group(i) for i in range(1, 5)]

    # BPA/PER/DPA/D/Y rows
    rows: dict[str, list[str]] = {}
    for m in _ROW_RE.finditer(page_text):
        metric = m.group(1).upper()
        vals = [m.group(2), m.group(3), m.group(4), m.group(5)]
        if metric not in rows:
            rows[metric] = vals

    # Target price
    target: float | None = None
    tm = _TARGET_RE.search(page_text)
    if tm:
        target = _clean_target(tm.group(1))

    # Rating
    rating: str | None = None
    rm = _RATING_RE.search(page_text)
    if rm:
        rating = _normalize_rating(rm.group(1))

    if not rows and target is None:
        return None

    return _CompanyPage(
        page_no=page_no,
        company_name=company_name,
        years=years,
        rows=rows,
        target=target,
        rating=rating,
    )


# ---------------------------------------------------------------------------
# Ticker resolution
# ---------------------------------------------------------------------------

def _resolve_ticker(company_name: str, abbrev_map: dict[str, str]) -> str | None:
    """Resolve a detail-page company name to a ticker.

    Resolution priority:
    1. Exact lookup in abbreviations map.
    2. Supplement dict (COLORADO → COL, etc.).
    3. Longest-key prefix match: any map key that is a prefix of company_name, or
       company_name is a prefix of a map key (handles trailing sector tokens and
       minor name differences like WAFA ASSURANCE vs WAFA ASSURANCES).
    4. Fuzzy alphanumeric match (handles apostrophes: LABEL'VIE vs LABEL VIE).
    5. Ticker-direct: company_name is 2-5 uppercase chars (e.g. RDS, HPS, IAM, CMT).
    """
    name = company_name.strip().upper()

    # 1. Exact
    if name in abbrev_map:
        return abbrev_map[name]

    # 2. Supplement
    if name in _COMPANY_TICKER_SUPPLEMENTS:
        return _COMPANY_TICKER_SUPPLEMENTS[name]

    # 3. Prefix match (longest key first to prefer more specific matches)
    best_key_len = 0
    best_ticker: str | None = None
    for key, ticker in abbrev_map.items():
        if name.startswith(key) or key.startswith(name):
            if len(key) > best_key_len:
                best_key_len = len(key)
                best_ticker = ticker
    if best_ticker is not None:
        return best_ticker

    # 4. Fuzzy: normalize to alphanumeric only
    norm_name = _alphanum(name)
    for key, ticker in abbrev_map.items():
        if _alphanum(key) == norm_name:
            return ticker

    # 5. Ticker-direct (2-5 all-uppercase chars, e.g. "RDS", "CMT", "IAM")
    if re.match(r"^[A-Z]{2,5}$", name):
        return name

    return None


# ---------------------------------------------------------------------------
# Estimate emission
# ---------------------------------------------------------------------------

def _year_is_estimate(year_label: str) -> bool:
    return bool(re.search(r"[Ee]", year_label))


def _canonical_year(year_label: str) -> int:
    return int(re.sub(r"[^0-9]", "", year_label)[:4])


def _emit_estimates(
    ticker: str,
    page: _CompanyPage,
    as_of_date: dt.date,
) -> list[ConsensusEstimate]:
    estimates: list[ConsensusEstimate] = []

    bpa_vals = page.rows.get("BPA", [])
    per_vals = page.rows.get("PER", [])

    for col_idx, year_label in enumerate(page.years):
        if not _year_is_estimate(year_label):
            continue
        fiscal_year = _canonical_year(year_label)

        bpa = _clean_num(bpa_vals[col_idx]) if col_idx < len(bpa_vals) else None
        per = _clean_num(per_vals[col_idx]) if col_idx < len(per_vals) else None

        if bpa is not None:
            estimates.append(ConsensusEstimate(
                symbol=ticker,
                fiscal_year=fiscal_year,
                period_type="annual",
                metric=METRIC_EPS_FORWARD,
                value=bpa,
                source=SOURCE_NAME,
                as_of_date=as_of_date,
                currency="MAD",
                raw_label=f"BPA {year_label}",
            ))
        if per is not None:
            estimates.append(ConsensusEstimate(
                symbol=ticker,
                fiscal_year=fiscal_year,
                period_type="annual",
                metric=METRIC_PER_FORWARD,
                value=per,
                source=SOURCE_NAME,
                as_of_date=as_of_date,
                currency="MAD",
                raw_label=f"PER {year_label}",
            ))

    # Target price
    if page.target is not None:
        estimates.append(ConsensusEstimate(
            symbol=ticker,
            fiscal_year=as_of_date.year,
            period_type="annual",
            metric=METRIC_TARGET_PRICE,
            value=page.target,
            source=SOURCE_NAME,
            as_of_date=as_of_date,
            currency="MAD",
        ))

    # Rating
    if page.rating:
        estimates.append(ConsensusEstimate(
            symbol=ticker,
            fiscal_year=as_of_date.year,
            period_type="annual",
            metric=METRIC_RATING,
            value=None,
            source=SOURCE_NAME,
            as_of_date=as_of_date,
            currency="MAD",
            raw_label=page.rating,
        ))

    return estimates


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class BkgrAdapter:
    """ConsensusSource adapter for the BKGR stock-guide PDF.

    Parameters
    ----------
    pdf_path    : path to the BKGR stock-guide PDF.
    abbrev_page : 0-based page index of the abbreviations table (default 1 = page 2).
    detail_start: 0-based page index of the first company detail page (default 3 = page 4).
    """

    name = SOURCE_NAME

    def __init__(
        self,
        pdf_path: Path | str,
        abbrev_page: int = 1,
        detail_start: int = 3,
    ) -> None:
        self._pdf_path = Path(pdf_path)
        self._abbrev_page = abbrev_page
        self._detail_start = detail_start

    def fetch(self, symbols: list[str] | None = None) -> list[ConsensusEstimate]:
        """Parse the PDF and return ConsensusEstimate rows."""
        from pypdf import PdfReader

        reader = PdfReader(str(self._pdf_path))
        pages = [page.extract_text() or "" for page in reader.pages]
        full_text = "\n".join(pages)

        as_of_date = _parse_date(full_text)

        abbrev_map: dict[str, str] = {}
        if self._abbrev_page < len(pages):
            abbrev_map = _parse_abbreviations(pages[self._abbrev_page])

        filter_set = {s.upper() for s in symbols} if symbols else None
        results: list[ConsensusEstimate] = []

        for page_no, page_text in enumerate(
            pages[self._detail_start:], start=self._detail_start + 1
        ):
            cp = _parse_company_page(page_text, page_no)
            if cp is None:
                continue

            ticker = _resolve_ticker(cp.company_name, abbrev_map)
            if ticker is None:
                continue
            if filter_set and ticker.upper() not in filter_set:
                continue

            results.extend(_emit_estimates(ticker, cp, as_of_date))

        return results

    @property
    def as_of_date(self) -> dt.date:
        """Extract the priced-as-of date without emitting all estimates."""
        from pypdf import PdfReader
        reader = PdfReader(str(self._pdf_path))
        text = "".join(page.extract_text() or "" for page in reader.pages[:4])
        return _parse_date(text)
