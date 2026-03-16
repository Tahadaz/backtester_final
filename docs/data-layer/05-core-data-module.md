# Data Layer — Core Data Module

**File:** `core/quant_core/data.py`

This module provides data source adapters, normalization, validation, and caching for OHLCV market data. It is used by both the worker tasks (ingestion/refresh) and the backtest engine.

---

## MarketData Container

```python
@dataclass(frozen=True)
class MarketData:
    bars: Dict[str, pd.DataFrame]  # symbol → DataFrame (DatetimeIndex, OHLCV columns)
    source: str                     # e.g. "yahoo", "bmce", "synthetic"
    timezone: str = "GMT"
    interval: str = "1d"
    meta: Dict[str, object] = field(default_factory=dict)

    def symbols(self) -> List[str]           # list of available symbols
    def get(self, symbol: str) -> pd.DataFrame  # get bars for a symbol
```

---

## BaseDataSource (Abstract)

```python
class BaseDataSource:
    def __init__(timezone="GMT", cache_dir=None, use_cache=True)

    def load(symbols, start=None, end=None, interval="1d",
             align=False, align_how="inner", fill_method=None, **kwargs) -> MarketData:
        # 1. Check disk cache (if use_cache + cache_dir set)
        # 2. Call self._load_impl(symbols, start, end, interval, **kwargs)
        # 3. For each symbol's DataFrame:
        #    a. _standardize_ohlcv(df, tz) — ensure DatetimeIndex, rename columns, coerce numerics
        #    b. _validate_ohlcv(df, symbol) — integrity checks, drop bad rows
        #    c. slice_date_range(df, start, end) — filter by requested range
        # 4. Optionally align_symbols(bars, how, fill_method)
        # 5. Save to disk cache
        # 6. Return MarketData(bars, source, timezone, interval)

    def _load_impl(symbols, start, end, interval, **kwargs) -> Dict[str, pd.DataFrame]
        # Abstract — each adapter implements this
```

---

## Data Source Adapters

### BMCEDataSource
**Purpose:** Read BMCE/Casablanca-format CSV or Excel files from local disk or S3.

```python
class BMCEDataSource(BaseDataSource):
    def __init__(file_paths, timezone="GMT", cache_dir=None, use_cache=True,
                 dayfirst=False, date_format=None)

    def _load_impl(symbols, start, end, interval, **kwargs) -> Dict[str, pd.DataFrame]
        # Multi-file: each file = one symbol, OR one workbook = multi-sheet = multi-symbol
        # Sheet name matching: case-insensitive against requested symbols
```

**Column rename map (line ~713):**
```python
rename = {
    "Ouvt": "Open",      "'+Haut": "High",     "'+Bas": "Low",
    "Clôture": "Close",  "Volume": "Volume",
    "Ouverture": "Open",
}
```

**French numeric handling (line ~744):**
- Space thousands separator: `"1 052"` → `1052`
- Comma decimal: `"1052,00"` → `1052.0`
- Applied to Open, High, Low, Close, Volume columns

### YahooFinanceDataSource
**Purpose:** Fetch from Yahoo Finance via `yfinance` library.

```python
class YahooFinanceDataSource(BaseDataSource):
    def _load_impl(symbols, start, end, interval, **kwargs):
        # yfinance.download(tickers, start, end, interval, auto_adjust=False, progress=False, group_by="column")
        # Handles MultiIndex columns (field, ticker) → dict[symbol → DataFrame]
```

### YFinanceMoroccoAdapter
**Purpose:** Yahoo Finance with automatic `.CS` suffix for Casablanca tickers.

```python
class YFinanceMoroccoAdapter(YahooFinanceDataSource):
    def __init__(provider_map=None, **kwargs)
        # provider_map: optional {internal_symbol → yahoo_ticker} override

    def _load_impl(symbols, start, end, interval, **kwargs):
        # 1. Map symbols: ATW → ATW.CS (unless provider_map overrides)
        # 2. Call super()._load_impl with mapped tickers
        # 3. Reverse-map keys: ATW.CS → ATW
```

### BourseDirectAdapter
**Purpose:** HTTP adapter that fetches from Bourse de Casablanca download endpoint.

```python
class BourseDirectAdapter(BaseDataSource):
    def __init__(url_template=None, response_format="excel", delay=0.5, **kwargs)
        # url_template: env BOURSE_DIRECT_URL_TEMPLATE
        # delay: rate limiting between requests (seconds)

    def _load_impl(symbols, start, end, interval, **kwargs):
        # For each symbol:
        #   1. Build URL from template
        #   2. HTTP GET with timeout
        #   3. Parse response (Excel or CSV)
        #   4. Apply BMCE column rename
        #   5. Rate limit: sleep(delay)
```

### BDCSessionAdapter
**Purpose:** Scrape live session OHLCV from Bourse de Casablanca instrument page.

```python
class BDCSessionAdapter(BaseDataSource):
    def _load_impl(symbols, start, end, interval, **kwargs):
        # For each symbol:
        #   1. Fetch: https://www.casablanca-bourse.com/fr/live-market/instruments/{SYMBOL}?pwa=1
        #   2. Regex-parse server-rendered HTML:
        #      - "Cours (MAD)" → Close
        #      - "Ouverture" → Open
        #      - "Plus haut" → High
        #      - "Plus bas" → Low
        #      - "Volume en titre" → Volume
        #   3. Session date from page header ("vendredi 6 mars 2026")
        #   4. Returns single-row DataFrame (current session only)
```

### ParquetDataSource
**Purpose:** Read local or S3 parquet files.

```python
class ParquetDataSource(BaseDataSource):
    def _load_impl(symbols, start, end, interval, **kwargs):
        # Contract: parquet has DatetimeIndex OR 'timestamp' column
        # Columns: Open/High/Low/Close/Volume (case-insensitive via _standardize_ohlcv)
```

---

## Normalization & Validation

### `_standardize_ohlcv(df, tz="GMT", require_ohlc=True, fill_adj_close=True)`

1. Ensure DatetimeIndex (convert 'timestamp'/'date' column if needed)
2. Timezone localization/conversion to `tz`
3. Case-insensitive column rename: `close` → `Close`, `adjclose` → `Adj Close`
4. Validate required columns present (Open, High, Low, Close if require_ohlc=True)
5. Fill `Adj Close = Close` if missing and fill_adj_close=True
6. Coerce all OHLCV columns to numeric (errors='coerce')
7. Drop rows where Close is NaN
8. Drop duplicate index entries (keep='last')

### `_validate_ohlcv(df, symbol="")`

OHLC bar integrity checks:
- `High >= max(Open, Close)` — warns + drops violating rows
- `Low <= min(Open, Close)` — warns + drops violating rows
- `Low >= 0` — warns + drops negative rows

### `slice_date_range(df, start, end)`

Filter by timestamp range. Handles both string and datetime inputs.

### `align_symbols(bars, how="inner", fill_method=None)`

Multi-symbol index alignment:
- `how="inner"` — only dates present in ALL symbols
- `how="outer"` — all dates from ANY symbol
- `fill_method` — "ffill" or "bfill" for missing values after alignment

---

## Symbol Normalization

```python
def normalize_symbol(raw: str) -> str:
    # Uppercase + strip
    # Remove exchange suffixes: .CS, .MA, .BVC, :BVC, :MA
    # Remove parenthetical suffixes: "ATW (CASA)" → "ATW"
```

---

## Module-Level Caching

```python
_DATE_RANGE_CACHE: Dict[tuple, pd.DatetimeIndex] = {}
# Key: (start, end, freq, tz)
# Avoids redundant pd.date_range(freq="B") calls (~25ms each)
# Important for optimization loops that call make_synthetic_ohlcv per trial

_MARKET_DATA_CACHE: Dict[str, MarketData] = {}
# Per-process cache for loaded market data
# Used by execute_run to avoid re-loading data across optimization trials
```
