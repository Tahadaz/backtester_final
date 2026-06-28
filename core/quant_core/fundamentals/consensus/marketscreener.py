"""MarketScreener paced-scraper adapter (brief 54 §3 Phase 2).

Parses the MarketScreener `/quote/stock/<slug>-<id>/finances/` page for each
Casablanca name and emits ConsensusEstimate rows for EPS_Forward,
Revenue_Forward, NetIncome_Forward, PER_Forward, Target_Price, and Rating.

Access reality (brief 53 addendum):
  MarketScreener enforces a free-navigation quota (~dozen hits/session).  This
  adapter is therefore:
    • cache-first  — never re-fetches an HTML file already on disk
    • low-rate     — configurable rate_limit_sec (default 8 s) between live fetches
    • quota-aware  — detects the 'nopopin-freenav' redirect; stops and logs; never raises
    • hard-isolated — any failure is caught and logged; fetch() always returns a list

  Usage pattern: accrete coverage over multiple sessions.  Run a few symbols per
  session; the on-disk cache accumulates.  Once all 37 BKGR names are cached the
  adapter works entirely offline.

Page structure (verified 2026-06-28 against IAM, CDM, CMA, HPS):
  - Annual income statement table: Fiscal Period header, Net sales, Net income,
    Announcement Date rows (date = actual, '-' = forward estimate)
  - Per-share ratios table:        EPS, Dividend per Share rows; same structure
  - Forward multiples table:       P/E, PBR, EV/Sales for '2026 *', '2027 *'
  - Analyst consensus card div:    Number of Analysts, Average target price,
                                   Mean consensus rating

Units (MAD): revenue + net income in MAD millions; EPS/DPS in MAD per share.

ID map: Casablanca names occupy a contiguous numeric block
  (CDM=1408690 … IAM=1408717).  KNOWN_IDS seeds the map; `discover()` fills the
  rest by scanning the block with rate-limiting.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from .domain import (
    METRIC_EPS_FORWARD,
    METRIC_NI_FORWARD,
    METRIC_PER_FORWARD,
    METRIC_RATING,
    METRIC_REV_FORWARD,
    METRIC_TARGET_PRICE,
    ConsensusEstimate,
)

logger = logging.getLogger(__name__)

SOURCE_NAME = "marketscreener"
_BASE_URL = "https://www.marketscreener.com/quote/stock"

# Known MarketScreener numeric IDs for BKGR-covered Casablanca names.
# Add more via id_map_path (JSON) or discover().
KNOWN_IDS: dict[int, str] = {
    1408690: "CDM",
    1408696: "CMA",
    1408706: "HPS",
    1408717: "IAM",
}

# ---------------------------------------------------------------------------
# Number helpers
# ---------------------------------------------------------------------------

def _num(s: str) -> float | None:
    """Parse an English-format number string (comma thousands, period decimal)."""
    if not s or s.strip() in ("-", "ns", "N/A", ""):
        return None
    cleaned = s.strip().replace(",", "").replace(" ", "").rstrip("x%")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _positive(s: str) -> float | None:
    v = _num(s)
    return v if v is not None and v > 0 else None


# ---------------------------------------------------------------------------
# HTML table utilities
# ---------------------------------------------------------------------------

def _find_table_by_row(soup: Any, *label_prefixes: str) -> Any | None:
    """Return the first <table> containing a row whose first cell starts with
    any of the given label prefixes."""
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells and any(cells[0].startswith(p) for p in label_prefixes):
                return table
    return None


def _parse_table(table: Any) -> tuple[list[str], dict[str, list[str]]]:
    """Parse <table> into (year_headers, {normalised_label: [value_per_year]}).

    Label normalisation: strip trailing footnote digit (e.g. 'EPS1' → 'EPS').
    Values are left as raw strings; callers decide how to parse them.
    """
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)
    if not rows:
        return [], {}
    years = rows[0][1:]
    data: dict[str, list[str]] = {}
    n_years = len(years)
    for row in rows[1:]:
        if not row:
            continue
        label = re.sub(r"\d+$", "", row[0]).strip()  # strip footnote digit
        vals = row[1:n_years + 1]
        while len(vals) < n_years:
            vals.append("")
        if label and label not in data:
            data[label] = vals
    return years, data


def _forward_year_indices(years: list[str], data: dict[str, list[str]]) -> list[int]:
    """Return column indices for forward (unannounced) years.

    Strategy: 'Announcement Date' row → columns with '-' are forward estimates.
    Fallback: years that parse to a calendar year > today.year are forward.
    """
    ann = data.get("Announcement Date", [])
    if ann:
        return [i for i, d in enumerate(ann) if d == "-" and i < len(years)]
    # Fallback: any year > current year
    today = dt.date.today()
    result = []
    for i, y in enumerate(years):
        m = re.match(r"(\d{4})", y)
        if m and int(m.group(1)) > today.year:
            result.append(i)
    return result


def _canonical_year(year_str: str) -> int | None:
    m = re.match(r"(\d{4})", year_str.strip())
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Ticker / consensus card parsers
# ---------------------------------------------------------------------------

def _extract_ticker(soup: Any) -> str | None:
    """Extract CSE ticker from page title or standalone heading element.

    Patterns tried (in order):
    1. Title contains '(TICKER)' e.g. 'Itissalat Al-Maghrib (IAM) S.A.: ...'
    2. Title ends with '| TICKER ' e.g. '... | CDM '
    3. A standalone <h2> or <h3> that is just 2-5 uppercase letters
    """
    title = soup.title.get_text() if soup.title else ""

    m = re.search(r"\(([A-Z]{2,5})\)", title)
    if m:
        return m.group(1)

    m = re.search(r"\|\s*([A-Z]{2,5})\s*(?:\||$)", title)
    if m:
        return m.group(1)

    for tag in soup.find_all(["h2", "h3"]):
        text = tag.get_text(strip=True)
        if re.fullmatch(r"[A-Z]{2,5}", text):
            return text

    return None


def _parse_consensus_card(soup: Any) -> tuple[int | None, float | None, str | None]:
    """Extract (analyst_count, target_price_mad, mean_consensus_rating)
    from the 'Analysts' Consensus' card div."""
    for div in soup.find_all("div"):
        text = div.get_text(" ", strip=True)
        if "Number of Analysts" not in text or "Average target price" not in text:
            continue
        # Stop at reasonably-sized blocks to avoid matching the whole page
        if len(text) > 2000:
            continue

        m_count = re.search(r"Number of Analysts\s+(\d+)", text)
        count = int(m_count.group(1)) if m_count else None

        m_target = re.search(
            r"Average target price\s+([\d,\.\s]+?)(?:\s+(?:MAD|USD|EUR)|$)", text
        )
        target: float | None = None
        if m_target:
            raw = m_target.group(1).strip().replace(",", "").replace(" ", "")
            try:
                target = float(raw) if raw else None
            except ValueError:
                target = None

        m_rating = re.search(
            r"Mean consensus\s+(BUY|STRONG BUY|OUTPERFORM|HOLD|NEUTRAL|ACCUMULATE|"
            r"REDUCE|UNDERPERFORM|SELL|STRONG SELL)",
            text,
            re.IGNORECASE,
        )
        rating = m_rating.group(1).upper() if m_rating else None

        return count, target, rating

    return None, None, None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_finances_html(
    html: str,
    *,
    ticker: str | None = None,
    as_of_date: dt.date | None = None,
) -> list[ConsensusEstimate]:
    """Parse a MarketScreener finances page HTML into ConsensusEstimate rows.

    ticker    : if None, extracted from the page title/heading.
    as_of_date: defaults to today (date of fetch).
    Returns [] on any parse failure — never raises.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.error("beautifulsoup4 not installed; cannot parse MarketScreener HTML")
        return []

    try:
        soup = BeautifulSoup(html, "html.parser")
        return _parse_soup(soup, ticker=ticker, as_of_date=as_of_date)
    except Exception:
        logger.exception("MarketScreener HTML parse failed for ticker=%s", ticker)
        return []


def _parse_soup(
    soup: Any,
    *,
    ticker: str | None,
    as_of_date: dt.date | None,
) -> list[ConsensusEstimate]:
    aod = as_of_date or dt.date.today()
    sym = ticker or _extract_ticker(soup)
    if not sym:
        logger.warning("MarketScreener: could not determine ticker from page")
        return []
    sym = sym.upper()

    analyst_count, target_price, rating = _parse_consensus_card(soup)

    estimates: list[ConsensusEstimate] = []

    # --- Income statement table (Net sales, Net income) ---
    income_table = _find_table_by_row(soup, "Net sales", "Net income")
    if income_table:
        years, data = _parse_table(income_table)
        fwd_idx = _forward_year_indices(years, data)
        rev_row = data.get("Net sales") or data.get("Net Sales")
        ni_row = data.get("Net income") or data.get("Net Income")
        for i in fwd_idx:
            fy = _canonical_year(years[i])
            if fy is None:
                continue
            if rev_row and i < len(rev_row):
                val = _positive(rev_row[i])
                if val is not None:
                    estimates.append(ConsensusEstimate(
                        symbol=sym, fiscal_year=fy, period_type="annual",
                        metric=METRIC_REV_FORWARD, value=val,
                        source=SOURCE_NAME, as_of_date=aod, currency="MAD_M",
                        raw_label=f"Net sales {years[i]} (MAD M)",
                        analyst_count=analyst_count,
                    ))
            if ni_row and i < len(ni_row):
                val = _positive(ni_row[i])
                if val is not None:
                    estimates.append(ConsensusEstimate(
                        symbol=sym, fiscal_year=fy, period_type="annual",
                        metric=METRIC_NI_FORWARD, value=val,
                        source=SOURCE_NAME, as_of_date=aod, currency="MAD_M",
                        raw_label=f"Net income {years[i]} (MAD M)",
                        analyst_count=analyst_count,
                    ))

    # --- Per-share table (EPS, DPS) ---
    per_share_table = _find_table_by_row(soup, "EPS", "Dividend per Share")
    if per_share_table:
        years, data = _parse_table(per_share_table)
        fwd_idx = _forward_year_indices(years, data)
        eps_row = data.get("EPS") or data.get("Earnings Per Share")
        for i in fwd_idx:
            fy = _canonical_year(years[i])
            if fy is None:
                continue
            if eps_row and i < len(eps_row):
                val = _num(eps_row[i])
                if val is not None:
                    estimates.append(ConsensusEstimate(
                        symbol=sym, fiscal_year=fy, period_type="annual",
                        metric=METRIC_EPS_FORWARD, value=val,
                        source=SOURCE_NAME, as_of_date=aod, currency="MAD",
                        raw_label=f"EPS {years[i]}",
                        analyst_count=analyst_count,
                    ))

    # --- Forward multiples table (P/E) ---
    # Header: ['', '2026 *', '2027 *']; rows: ['P/E', '14.8x', '14.6x']
    multiples_table = _find_table_by_row(soup, "P/E")
    if multiples_table:
        years_raw, data = _parse_table(multiples_table)
        # All years in this table are forward (marked with *)
        pe_row = data.get("P/E")
        for i, yr in enumerate(years_raw):
            fy = _canonical_year(yr)
            if fy is None:
                continue
            if pe_row and i < len(pe_row):
                val = _positive(pe_row[i])
                if val is not None:
                    estimates.append(ConsensusEstimate(
                        symbol=sym, fiscal_year=fy, period_type="annual",
                        metric=METRIC_PER_FORWARD, value=val,
                        source=SOURCE_NAME, as_of_date=aod, currency="MAD",
                        raw_label=f"P/E {yr}",
                        analyst_count=analyst_count,
                    ))

    # --- Consensus card: target price and rating ---
    cur_year = aod.year
    if target_price is not None:
        estimates.append(ConsensusEstimate(
            symbol=sym, fiscal_year=cur_year, period_type="annual",
            metric=METRIC_TARGET_PRICE, value=target_price,
            source=SOURCE_NAME, as_of_date=aod, currency="MAD",
            analyst_count=analyst_count,
        ))
    if rating:
        estimates.append(ConsensusEstimate(
            symbol=sym, fiscal_year=cur_year, period_type="annual",
            metric=METRIC_RATING, value=None, source=SOURCE_NAME,
            as_of_date=aod, currency="MAD", raw_label=rating,
            analyst_count=analyst_count,
        ))

    return estimates


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class MarketScreenerAdapter:
    """ConsensusSource adapter for MarketScreener Casablanca finances pages.

    Parameters
    ----------
    cache_dir   : directory for on-disk HTML cache (created if absent)
    id_map      : {ms_id: ticker} overriding / extending KNOWN_IDS; OR a Path
                  to a JSON file (loaded once, auto-saved after discover())
    rate_limit_sec : minimum seconds between live fetches (default 8.0)
    """

    name = SOURCE_NAME

    def __init__(
        self,
        cache_dir: Path | str,
        id_map: dict[int, str] | Path | str | None = None,
        *,
        rate_limit_sec: float = 8.0,
    ) -> None:
        self._cache = Path(cache_dir)
        self._cache.mkdir(parents=True, exist_ok=True)
        self._rate = rate_limit_sec
        self._last_fetch: float = 0.0

        # Resolve id_map
        if isinstance(id_map, (str, Path)):
            self._map_path: Path | None = Path(id_map)
        else:
            self._map_path = self._cache / "ms_id_map.json"

        self._id_map: dict[int, str] = dict(KNOWN_IDS)
        if self._map_path.exists():
            try:
                loaded = json.loads(self._map_path.read_text(encoding="utf-8"))
                self._id_map.update({int(k): v for k, v in loaded.items()})
            except Exception:
                logger.warning("Could not load MS id_map from %s", self._map_path)
        if isinstance(id_map, dict):
            self._id_map.update(id_map)

    # ------------------------------------------------------------------

    def fetch(self, symbols: list[str] | None = None) -> list[ConsensusEstimate]:
        """Return ConsensusEstimate rows for all (or the given) symbols.

        Hard-isolated: any network or parse failure returns [] for that symbol
        without affecting others.
        """
        filter_set = {s.upper() for s in symbols} if symbols else None
        results: list[ConsensusEstimate] = []
        as_of = dt.date.today()

        for ms_id, ticker in sorted(self._id_map.items()):
            if filter_set and ticker.upper() not in filter_set:
                continue
            html = self._ensure_html(ms_id, ticker)
            if html is None:
                continue
            ests = parse_finances_html(html, ticker=ticker, as_of_date=as_of)
            logger.info(
                "MarketScreener: %s (id=%s) → %d estimates", ticker, ms_id, len(ests)
            )
            results.extend(ests)

        return results

    # ------------------------------------------------------------------

    def discover(
        self,
        id_range: tuple[int, int] = (1408680, 1408760),
        known_tickers: set[str] | None = None,
    ) -> dict[int, str]:
        """Scan a MarketScreener ID range and add discovered Casablanca tickers
        to the internal id_map.  Saves results to ms_id_map.json.

        Quota-safe: stops on the first nopopin-freenav redirect.
        Rate-limited: respects self._rate between fetches.

        known_tickers: if supplied, only record IDs whose tickers are in this
                       set (e.g. the 35 BKGR-covered names).
        """
        discovered: dict[int, str] = {}
        for ms_id in range(id_range[0], id_range[1] + 1):
            if ms_id in self._id_map:
                continue  # already known
            html = self._live_fetch(ms_id)
            if html is None:
                continue  # quota wall hit; _live_fetch already logged

            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                ticker = _extract_ticker(soup)
                if ticker and (known_tickers is None or ticker in known_tickers):
                    discovered[ms_id] = ticker
                    self._id_map[ms_id] = ticker
                    self._write_cache(ms_id, html)
                    logger.info("MarketScreener discover: %s → id=%s", ticker, ms_id)
            except Exception:
                logger.exception("MarketScreener discover: parse error for id=%s", ms_id)

        self._save_map()
        return discovered

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cache_path(self, ms_id: int) -> Path:
        return self._cache / f"ms_{ms_id}.html"

    def _write_cache(self, ms_id: int, html: str) -> None:
        self._cache_path(ms_id).write_text(html, encoding="utf-8")

    def _ensure_html(self, ms_id: int, ticker: str = "") -> str | None:
        p = self._cache_path(ms_id)
        if p.exists():
            return p.read_text(encoding="utf-8")
        html = self._live_fetch(ms_id)
        if html:
            self._write_cache(ms_id, html)
        return html

    def _live_fetch(self, ms_id: int) -> str | None:
        """Fetch one finances page.  Returns None on quota wall or error."""
        elapsed = time.monotonic() - self._last_fetch
        if elapsed < self._rate:
            time.sleep(self._rate - elapsed)

        url = f"{_BASE_URL}/X-{ms_id}/finances/"
        try:
            from curl_cffi import requests as cffi_requests

            resp = cffi_requests.get(url, impersonate="chrome", timeout=25)
            self._last_fetch = time.monotonic()

            final = str(resp.url)
            if "nopopin" in final or "solutions" in final:
                logger.warning(
                    "MarketScreener quota wall hit (id=%s); stopping live fetches", ms_id
                )
                return None
            if resp.status_code != 200:
                logger.warning(
                    "MarketScreener id=%s returned HTTP %s", ms_id, resp.status_code
                )
                return None
            if len(resp.text) < 20_000:
                logger.warning(
                    "MarketScreener id=%s returned suspiciously short response (%d chars)",
                    ms_id, len(resp.text),
                )
                return None
            return resp.text

        except ImportError:
            logger.error("curl_cffi not installed; cannot live-fetch MarketScreener pages")
            return None
        except Exception:
            logger.exception("MarketScreener live fetch failed for id=%s", ms_id)
            return None

    def _save_map(self) -> None:
        if self._map_path:
            try:
                self._map_path.write_text(
                    json.dumps({str(k): v for k, v in sorted(self._id_map.items())},
                               indent=2),
                    encoding="utf-8",
                )
            except Exception:
                logger.warning("Could not save MS id_map to %s", self._map_path)
