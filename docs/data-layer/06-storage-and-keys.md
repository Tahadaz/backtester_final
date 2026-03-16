# Data Layer — Storage & Key Structure

**S3-compatible storage:** MinIO (local dev) or AWS S3 (production)
**Bucket:** `quant-artifacts` (env `S3_BUCKET`)

---

## S3 Bucket Layout

```
quant-artifacts/
├── datasets/
│   └── {sha256_hash}/
│       └── {original_filename}       ← raw uploaded Excel/CSV (preserved forever)
│
├── market_data/
│   ├── {SYMBOL}/
│   │   └── 1D.parquet               ← canonical daily OHLCV (updated by ingestion & refresh)
│   └── uploads/
│       └── {dataset_id}/
│           └── ingest_report.json    ← per-symbol ingestion results
│
└── runs/
    └── {run_id}/
        ├── artifacts/                ← backtest artifacts (plots, ledger, etc.)
        └── _debug/
            └── profile.txt           ← cProfile output (if enabled)
```

---

## Key Construction Functions

**File:** `core/quant_core/s3_keys.py`

### `build_dataset_object_key(data_hash, filename) -> str`
```python
# Returns: "datasets/{data_hash}/{filename}"
# Used: when dataset.object_key is NULL (legacy rows)
# New rows: object_key is set at upload time and stored in DB
```

### `build_market_store_object_key(symbol, timeframe) -> str`
```python
# Returns: "market_data/{symbol}/{timeframe}.parquet"
# Used: by worker tasks when creating/updating canonical parquet
# Example: "market_data/ATW/1D.parquet"
```

---

## Parquet File Format

Each `market_data/{SYMBOL}/1D.parquet` file:

- **Index:** `DatetimeIndex` (UTC-aware or naive, normalized by `_standardize_ohlcv`)
- **Columns:** `Open`, `High`, `Low`, `Close`, `Volume` (all float64, Volume may be int)
- **Sorted by:** date ascending
- **Deduplicated:** by index (keep='last' during merge)

---

## Key Invariants

1. **`dataset.object_key` is canonical** — never recomputed unless NULL (legacy row)
2. **Fallback:** `build_dataset_object_key(data_hash, filename)` — always identical to what `datasets.py` wrote at upload time
3. **`market_data_store.object_key`** always matches `build_market_store_object_key(symbol, timeframe)`
4. **Raw uploads are never modified** — `datasets/{hash}/{filename}` is immutable
5. **Canonical parquets are overwritten in-place** — `market_data/{symbol}/1D.parquet` is replaced on each merge

---

## S3 Client Configuration

**File:** `services/api/app/config.py`

| Env Variable | Default | Purpose |
|-------------|---------|---------|
| `S3_ENDPOINT_URL` / `S3_ENDPOINT` | `http://localhost:9000` | MinIO endpoint |
| `S3_ACCESS_KEY_ID` / `S3_ACCESS_KEY` | `minio` | MinIO root user |
| `S3_SECRET_ACCESS_KEY` / `S3_SECRET_KEY` | `minio12345` | MinIO root password |
| `S3_BUCKET` | `quant-artifacts` | Default bucket name |
| `S3_REGION` | `us-east-1` | AWS region (ignored by MinIO) |
| `S3_USE_SSL` | `false` | HTTPS for S3 connections |

---

## Presigned URLs

**Endpoint:** `GET /market-data/uploads/{dataset_id}/report-url`

- Generates a presigned GET URL for `market_data/uploads/{dataset_id}/ingest_report.json`
- Default expiry: 300 seconds (configurable via `expires_seconds` param, range 30–3600)
- Used by frontend to download ingestion report without exposing S3 credentials
