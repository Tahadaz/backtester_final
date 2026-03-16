# Data Layer — High-Level Overview

## Purpose

The data layer manages Moroccan stock market OHLCV data for the backtesting platform. It handles:

1. **Ingestion** — Excel uploads (BMCE/Casablanca format) parsed and stored as canonical parquet
2. **Live refresh** — Scraping Bourse de Casablanca and Yahoo Finance for incremental updates
3. **Stock registry** — Tracking which symbols are active, their metadata, and provider mappings
4. **Catalog** — Unified view merging ingested data + tracked stocks for the frontend
5. **Technical study** — SMA consensus signals computed on-demand from canonical data

---

## Service Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                    │
│  app/data/page.tsx  ←→  hooks/use-api.ts  ←→  lib/api.ts   │
│         │                                        │          │
│         └────── app/api/[...path]/route.ts ──────┘          │
│                    (reverse proxy)                           │
└──────────────────────┬──────────────────────────────────────┘
                       │  HTTP (/api/market-data/*)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI Backend                             │
│  routers/market_data.py                                      │
│    ├── Stock CRUD     (stock_master)                         │
│    ├── Catalog        (full-outer-join view)                 │
│    ├── Excel upload   → enqueue RQ job                       │
│    ├── Refresh trigger → enqueue RQ job                      │
│    ├── OHLCV preview  (read parquet from S3)                │
│    ├── Bourse lookup  (scrape casablanca-bourse.com)        │
│    ├── Health         (freshness summary)                    │
│    └── Technical study (SMA consensus)                       │
└──────────┬──────────────────────────┬───────────────────────┘
           │  SQL                     │  Enqueue
           ▼                          ▼
┌──────────────────┐     ┌──────────────────────────────────┐
│   PostgreSQL     │     │         Redis (RQ)                │
│                  │     │  Queues: "runs",                  │
│  Tables:         │     │    "defaults_discovery",          │
│  - dataset       │     │    "market_refresh"               │
│  - market_data   │     └──────────┬───────────────────────┘
│    _store        │                │  Dequeue
│  - stock_master  │                ▼
│  - provider_     │     ┌──────────────────────────────────┐
│    symbol_map    │     │       RQ Worker                   │
│  - market_       │     │                                   │
│    refresh_run   │     │  tasks/ingest_market_data.py      │
│  - market_       │     │    → parse Excel → parquet → S3   │
│    refresh_error │     │                                   │
└──────────────────┘     │  tasks/refresh_market_data.py     │
                         │    → fetch from Bourse/Yahoo      │
           ┌─────────────│    → merge → parquet → S3         │
           │             └──────────────────────────────────┘
           ▼
┌──────────────────┐
│  MinIO (S3)      │
│                  │
│  Bucket:         │
│  quant-artifacts │
│  ├── datasets/   │  ← raw Excel uploads
│  └── market_data/│  ← canonical parquets
└──────────────────┘
```

---

## Key File Map

### Backend
| File | Role |
|------|------|
| `services/api/app/routers/market_data.py` | All `/market-data/*` endpoints |
| `services/api/app/models.py` | SQLAlchemy ORM (MarketDataStore, StockMaster, etc.) |
| `services/api/app/schemas/market_data.py` | Pydantic request/response schemas |
| `services/api/app/queue.py` | `get_queue()` + `get_market_refresh_queue()` |
| `services/api/app/config.py` | All environment variables / settings |
| `services/worker/tasks/ingest_market_data.py` | Excel → parquet ingestion worker |
| `services/worker/tasks/refresh_market_data.py` | Bourse/Yahoo → parquet refresh worker |
| `services/worker/config.py` | Worker settings (queues, heartbeat, etc.) |
| `core/quant_core/data.py` | Data source adapters, normalization, validation |
| `core/quant_core/s3_keys.py` | Canonical S3 key builders |

### Frontend
| File | Role |
|------|------|
| `quant-backtesting-frontend/app/data/page.tsx` | Main data management page |
| `quant-backtesting-frontend/components/data/*.tsx` | 8 data-specific UI components |
| `quant-backtesting-frontend/hooks/use-api.ts` | SWR hooks (useMarketCatalog, useRefreshRun, etc.) |
| `quant-backtesting-frontend/lib/api.ts` | Zod schemas + API client functions |
| `quant-backtesting-frontend/app/api/[...path]/route.ts` | Next.js → FastAPI reverse proxy |

### Infrastructure
| File | Role |
|------|------|
| `infra/docker-compose.yml` | PostgreSQL, Redis, MinIO, workers |
| `services/api/alembic/versions/` | Database migrations |

---

## Data Lifecycle (Summary)

1. **User uploads Excel** → raw bytes stored in S3 → `Dataset` row created → worker parses sheets → canonical parquet saved → `market_data_store` upserted
2. **User triggers refresh** → `MarketRefreshRun` created → worker fetches from Bourse/Yahoo → merges with existing parquet → `market_data_store` updated
3. **Frontend displays** → `GET /catalog` returns full-outer-join of `market_data_store` + `stock_master` → table rendered with freshness badges
4. **Backtest reads data** → `BacktestEngine` loads parquet from `market_data_store.object_key` via `BMCEDataSource` or `ParquetDataSource`
