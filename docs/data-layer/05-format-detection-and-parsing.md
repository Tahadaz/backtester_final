# 05 — Format Detection & Parsing

**File**: `services/api/app/market_data_formats.py`

This module solves the fundamental problem of Moroccan market data heterogeneity: Excel files arrive in multiple formats with different column names, number conventions, and date orderings. The system auto-detects the format and normalizes to canonical OHLCV.

---

## The Three Upload Formats

### 1. BMCE New (`bmce_new`)

The current format exported from BMCE Capital (Bourse de Casablanca member).

| Canonical | Accepted Aliases |
|-----------|-----------------|
| Date | Séance |
| Open | Ouverture |
| High | +haut du jour |
| Low | +bas du jour |
| Close | Dernier Cours |
| Volume | Volume |

- **Number style**: French — space thousands separator, comma decimal (e.g., `1 052,00`)
- **Date order**: day-first (`dd/mm/yyyy`)

### 2. Investing / English (`investing`)

Format from Investing.com exports or English-locale tools.

| Canonical | Accepted Aliases |
|-----------|-----------------|
| Date | Date |
| Open | Open, Ouv. |
| High | High, Plus Haut |
| Low | Low, Plus Bas |
| Close | Close, Price |
| Volume | Volume, Vol. |

- **Number style**: English — comma thousands, period decimal (e.g., `1,052.00`)
- **Date order**: month-first (`mm/dd/yyyy`) — with dynamic disambiguation
- **Volume suffixes**: K, M, B (e.g., "1.5M" → 1,500,000)

### 3. BMCE Old (`bmce_old`)

Legacy BMCE export format with abbreviated column names.

| Canonical | Accepted Aliases |
|-----------|-----------------|
| Date | Date |
| Open | Ouvt |
| High | '+Haut |
| Low | '+Bas |
| Close | Clôture |
| Volume | Volume |

- **Number style**: French
- **Date order**: day-first

---

## Header Normalization

The `normalize_header_key(value)` function ensures robust matching regardless of encoding issues:

1. **Deaccent**: `é` → `e`, `ô` → `o`, etc. (via `unicodedata.normalize('NFD')`)
2. **Collapse whitespace**: multiple spaces/tabs → single space
3. **Casefold**: lowercase for comparison
4. **Mojibake handling**: detects and corrects UTF-8 encoding errors (e.g., `ClÃ´ture` → `Clôture` → `cloture`)

This is critical because Excel files from different sources may have inconsistent encoding.

---

## Format Detection Algorithm

`detect_upload_format(columns: list[str]) → UploadFormatSpec | None`

1. For each of the 3 format specs, count how many canonical fields (Date, Open, High, Low, Close, Volume) can be matched via the spec's aliases
2. Score = number of matched fields
3. Return best match if score ≥ 3; else None

The threshold of 3 ensures that at least half the fields match, preventing false positives from coincidental column names.

---

## Numeric Parsing

`parse_numeric_series(values, number_style, allow_suffixes) → pd.Series`

### French Style (`number_style="french"`)
- Input: `"1 052,00"` or `"1052,00"` or `"1 052"`
- Process: strip spaces used as thousands separators, replace comma with period
- Output: `1052.0`

### English Style (`number_style="english"`)
- Input: `"1,052.00"` or `"1052.00"`
- Process: strip commas used as thousands separators
- Output: `1052.0`

### Volume Suffixes (when `allow_suffixes=True`)
- `K` or `k` → ×1,000
- `M` or `m` → ×1,000,000
- `B` or `b` → ×1,000,000,000
- Example: `"1.5M"` → `1500000.0`

---

## Date Parsing

`parse_datetime_series(values, day_first, format_id) → pd.Series`

### Standard (BMCE new/old)
- Uses `pd.to_datetime(values, dayfirst=True)`
- Filters future-dated values (>= market_today_local)

### Investing Format (Ambiguous Dates)
The Investing.com format presents a challenge: dates like `03/05/2024` could be March 5th or May 3rd depending on locale.

**Resolution algorithm**:
1. Parse each date string as both day-first and month-first candidates
2. Build a dynamic programming resolution that maximizes chronological consistency
3. Prefer the interpretation that produces a monotonically increasing date series
4. Filter future-dated values

This is necessary because Investing.com exports don't consistently follow one convention.

---

## Column Renaming Pipeline

`rename_columns_for_upload(df) → (df_renamed, format_id, matched_aliases)`

1. Normalize all DataFrame column headers via `normalize_header_key()`
2. Call `detect_upload_format()` to find best format match
3. Build rename mapping: original column → canonical name
4. Rename DataFrame columns
5. Return renamed DataFrame + format_id + matched aliases (for diagnostic reporting)

---

## Format Reference Builder

`build_upload_format_reference() → dict`

Returns a structured reference used by the frontend's ExcelUploadDialog:

```python
{
    "canonical_fields": ["date", "open", "high", "low", "close", "volume"],
    "formats": [
        {
            "format_id": "bmce_new",
            "label": "BMCE Export (nouveau)",
            "aliases": {"date": ["Séance"], "open": ["Ouverture"], ...},
            "numeric_examples": ["1 052,00", "1052,00"],
            "volume_suffixes": [],
            "notes": ["Format français: espace comme séparateur de milliers, virgule décimale"]
        },
        ...
    ],
    "validation": {
        "required_fields": ["date", "close"],
        "note": "Au minimum les colonnes Date et Close (ou alias reconnu) sont requises."
    }
}
```

---

## Why This Matters

Without format detection, users would need to manually convert every Excel file to a standard format before uploading. Given that Moroccan market data comes from multiple sources (BMCE Capital, Investing.com, legacy archives), each with different conventions, automatic detection and normalization is essential for a usable data pipeline.

The French numeric parsing is particularly important: Moroccan financial institutions use French number formatting (`1 052,00`), which would be interpreted as text or as `1.0` by naive parsers.
