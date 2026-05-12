# 01 — Data Layer Overview

## Purpose

The data layer manages the complete lifecycle of Moroccan market OHLCV data: ingestion from Excel files or live sources, canonical storage in parquet format, provider symbol mapping, freshness tracking, and serving to both the frontend data page and the signal engine.

## Service Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Frontend (Next.js)                                       │
│  app/data/page.tsx → components/data/*                    │
│  SWR hooks (30s catalog, 2s refresh poll)                │
│  /api proxy → FastAPI                                    │
└──────────────────────┬───────────────────────────────────┘
                       │ HTTP
┌──────────────────────▼───────────────────────────────────┐
│  API (FastAPI)                                           │
│  routers/market_data.py        — 18 endpoints            │
│  market_data_loader.py         — shared OHLCV loaders    │
│  market_data_formats.py        — format detection/parse  │
│  market_holidays.py            — holiday calendar         │
│  masi_tickers.py               — 93 MASI tickers         │
│  scheduler.py                  — daily cron refresh       │
└──────────┬───────────────────────────────┬───────────────┘
           │ SQL                            │ RQ enqueue
┌──────────▼──────────┐    ┌───────────────▼───────────────┐
│  PostgreSQL          │    │  Worker (RQ)                  │
│  stock_master        │    │  ingest_market_data.py        │
│  market_data_store   │    │  refresh_market_data.py       │
│  provider_symbol_map │    │                               │
│  market_refresh_run  │    │  Adapters:                    │
│  market_refresh_error│    │  - YFinanceMoroccoAdapter     │
│  dataset             │    │  - BourseDirectAdapter        │
└──────────────────────┘    │  - BDCSessionAdapter          │
                            └──────────────┬───────────────┘
                                           │ S3
                            ┌──────────────▼───────────────┐
                            │  MinIO / S3                   │
                            │  datasets/{hash}/{filename}   │
                            │  market_data_store/{sym}/1D   │
                            │  market_data/uploads/{id}/... │
                            └──────────────────────────────┘
```

## Key Files

### API Layer (`services/api/app/`)
| File | Purpose |
|------|---------|
| `routers/market_data.py` | 18 endpoints: catalog, CRUD, upload, refresh, OHLCV, calendar, health, format reference, Bourse lookup |
| `schemas/market_data.py` | Pydantic input/output models: MarketCatalogRowOut, StockMasterOut, OhlcvBarOut, AvailabilityCalendarOut, etc. |
| `market_data_loader.py` | Shared OHLCV loaders — reads parquet from S3, falls back to uploaded datasets, handles column aliasing |
| `market_data_formats.py` | 3 format specs (BMCE new/old, Investing), header normalization (deaccent, casefold, mojibake), French numeric parsing, date disambiguation |
| `market_holidays.py` | Casablanca exchange holidays from JSON file. Mtime-cached. Confirmed + tentative certainty levels. Symbol-specific overrides. |
| `masi_tickers.py` | 93 MASI tickers with display_name + sector. Functions: `is_masi_ticker()`, `get_masi_info()`, `all_masi_tickers()` |
| `scheduler.py` | APScheduler BackgroundScheduler — CronTrigger at 18:00 Africa/Casablanca, Mon–Fri. Toggleable via `MARKET_REFRESH_CRON_ENABLED` env var. |

### Worker Layer (`services/worker/tasks/`)
| File | Purpose |
|------|---------|
| `ingest_market_data.py` | Excel → per-sheet symbol detection → format detection → normalize OHLCV → merge parquet → write ingest report |
| `refresh_market_data.py` | Per-symbol: resolve provider → pick adapter → incremental fetch → merge parquet → update DB → log errors |

### Frontend Layer (`frontend/`)
| File | Purpose |
|------|---------|
| `app/data/page.tsx` | Main data page (596 lines): catalog table, MASI/Autres tabs, action buttons, embedded dialogs |
| `components/data/excel-upload-dialog.tsx` | Step-by-step Excel import: format reference, upload, poll, per-symbol result report |
| `components/data/stock-detail-panel.tsx` | OHLCV candlestick chart (Plotly), availability calendar grid, year-strip overview, data quality diagnostics, last 10 bars preview |
| `components/data/freshness-badge.tsx` | Color-coded: ≤1 day green "À jour", ≤7 days yellow "{n}j", else red "{n}j — obsolète" |
| `components/data/refresh-status-bar.tsx` | Real-time progress bar with adaptive polling (2s while running, stop when done) |

## Data Lifecycle

```
1. REGISTER    Stock added to stock_master (via "Ajouter un titre" dialog or auto on Excel ingest)
                 ↓ Auto-fills display_name/sector from MASI registry
                 ↓ Auto-creates provider_symbol_map (yahoo .CS + bourse_direct)
2. INGEST      Excel upload → format detection → French numeric parsing → OHLCV normalization
       or      Bourse/Yahoo refresh → adapter fetch → incremental merge
                 ↓
3. STORE       Parquet at market_data_store/{symbol}/1D; metadata row in market_data_store
                 ↓
4. SERVE       API loads parquet → OhlcvBarOut, AvailabilityCalendarOut, OhlcvHistoryOut
                 ↓
5. MONITOR     Freshness badges (dual model), calendar grid, data quality report
                 ↓
6. REFRESH     Manual button or daily cron at 18:00 → incremental update → back to step 3
```

## Design Invariants

1. **One parquet per symbol** — `market_data_store/{symbol}/1D` is the single source of truth. No separate files per time range.

2. **Merge-on-write** — Every ingestion merges new data with existing parquet. Overwrite-if-different on timestamp collision. Status: "created" / "updated" / "unchanged".

3. **Canonical columns** — DatetimeIndex + Open, High, Low, Close, Volume. Any source format is normalized to this schema.

4. **UPPERCASE symbols** — All symbols stored and queried in uppercase. MASI tickers strip `.MA`/`.CS` suffixes.

5. **Provider abstraction** — `provider_symbol_map` decouples canonical symbol from provider-specific IDs. Yahoo uses `.CS` suffix. Bourse Direct uses raw symbol.

6. **Staleness = business days** — `data_as_of < 2 business days ago` = stale. Weekends/holidays don't count.

7. **Format auto-detection** — Three upload formats supported. Detection scores each format by matched canonical field count; requires ≥3 matches.

8. **Holiday-aware calendar** — Availability calendar distinguishes weekends, confirmed holidays, tentative holidays, missing expected days, and partial data. Backed by JSON holiday file with mtime caching.
