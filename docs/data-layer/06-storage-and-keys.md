# 06 — Storage & Key Structure

**S3-compatible storage**: MinIO (local dev) or AWS S3 (production)
**Bucket**: `quant-artifacts` (env `S3_BUCKET`)

---

## Object Key Patterns

### Market Data Store (canonical OHLCV)
```
market_data_store/{SYMBOL}/1D
```
Example: `market_data_store/ATW/1D`

One file per (symbol, timeframe). Contains the complete OHLCV history in parquet format. This is the **single source of truth** for all downstream consumers (signal engine, backtest engine, frontend charts).

### Uploaded Datasets
```
datasets/{sha256_hash}/{original_filename}
```
Example: `datasets/a1b2c3d4.../ATW_historique.xlsx`

The hash ensures deduplication: re-uploading the same file produces the same key. The original filename is preserved for diagnostic purposes.

### Ingest Reports
```
market_data/uploads/{dataset_id}/ingest_report.json
```
Written by the ingestion worker after processing an Excel upload. Contains per-symbol status, row counts, detected format, matched aliases, and error details. Polled by the frontend via `GET /market-data/uploads/{dataset_id}/status`.

---

## Parquet Format

All canonical OHLCV files use the following schema:

| Column | Type | Notes |
|--------|------|-------|
| (index) | DatetimeIndex | UTC timezone, sorted ascending, deduplicated by last |
| Open | float64 | Opening price |
| High | float64 | High price |
| Low | float64 | Low price |
| Close | float64 | Closing price |
| Volume | float64 | Trading volume (may be NaN for partial days) |

### Invariants

1. **DatetimeIndex**: Always sorted ascending, no duplicate timestamps
2. **Deduplication**: On timestamp collision during merge, last value wins
3. **No future dates**: Rows with dates >= market_today_local are dropped
4. **Column naming**: Always uppercase first letter (Open, not open)

---

## Key Construction

### Market Data Store Key
Built by the worker during ingestion/refresh:
```python
object_key = f"market_data_store/{symbol.upper()}/{timeframe}"
```

### Dataset Key
Built by the API during upload:
```python
data_hash = hashlib.sha256(file_content).hexdigest()
object_key = f"datasets/{data_hash}/{filename}"
```

### Key stored in DB
The `market_data_store.object_key` column stores the canonical key. This is the **only** reference used by loaders — no reconstruction from symbol/timeframe is needed.

---

## Loader Hierarchy

The `market_data_loader.py` module provides shared loading functions:

### load_ohlcv_for_symbol(db, symbol, timeframe="1D")
1. Query market_data_store for object_key
2. If found: `load_ohlcv_from_store(object_key)` — reads parquet from S3
3. If not found: fall back to latest dataset (parquet only; XLSX/CSV cannot provide full OHLCV via this path)

### load_close_for_symbol(db, symbol, timeframe="1D")
Same hierarchy but returns numpy float64 array of Close prices only. Falls back to dataset if no store entry, including XLSX/CSV parsing with column alias detection.

### Column Alias Detection (for dataset fallback)
Close column candidates: `Close`, `close`, `Clôture`, `Cloture`, `CLOTURE`, `ClÃ´ture`, `Adj Close`, `AdjClose`, `adj_close`
Date column candidates: `Date`, `date`, `timestamp`, `Timestamp`, `datetime`, `Datetime`
