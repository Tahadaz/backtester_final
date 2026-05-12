# Data Layer — Architecture Documentation

This folder contains the complete architecture, system design, and step-by-step documentation for the **Data Layer** of the Moroccan market backtesting platform. Every document reflects the current state of the codebase as of March 2026.

## Documents

| # | File | Scope |
|---|------|-------|
| 01 | [overview.md](./01-overview.md) | High-level architecture, services, key files, data lifecycle |
| 02 | [database-models.md](./02-database-models.md) | All tables: stock_master, market_data_store, provider_symbol_map, market_refresh_run, market_refresh_error, dataset |
| 03 | [backend-endpoints.md](./03-backend-endpoints.md) | Every `/market-data/*` endpoint — request/response/logic (18 endpoints) |
| 04 | [worker-tasks.md](./04-worker-tasks.md) | Excel ingestion + market refresh worker pipelines |
| 05 | [format-detection-and-parsing.md](./05-format-detection-and-parsing.md) | Upload format specs (BMCE new/old, Investing), header normalization, French numeric parsing, date disambiguation |
| 06 | [storage-and-keys.md](./06-storage-and-keys.md) | S3/MinIO bucket layout, key construction, parquet format |
| 07 | [frontend-architecture.md](./07-frontend-architecture.md) | Data page components, hooks, SWR polling, OHLCV chart, availability calendar, upload dialog |
| 08 | [data-flows.md](./08-data-flows.md) | End-to-end flows: Excel upload, Bourse refresh, catalog, availability calendar, data quality |
| 09 | [holidays-and-scheduling.md](./09-holidays-and-scheduling.md) | Casablanca exchange holiday calendar, APScheduler daily refresh, MASI ticker registry |
| 10 | [config-and-infra.md](./10-config-and-infra.md) | Environment variables, Docker Compose, queue config |
| 11 | [daily-update-and-data-page.md](./11-daily-update-and-data-page.md) | Data page as control center, freshness model, dual staleness, monitoring |
| 12 | [ui-goals-and-design.md](./12-ui-goals-and-design.md) | Data page product/UI contract, design reference, current ownership, states, and known gaps |

## The Data Page Is the Control Center

The `/data` page is not a secondary view — it is the **control center** for the entire data pipeline. Every backtest and every signal computation depends on data managed here. Without fresh, complete data, the signal engine produces stale or invalid results.

Key responsibilities:

- **Visibility**: what data exists, how fresh it is, what's missing — via catalog table, freshness badges, and availability calendar
- **Ingestion**: upload Excel files → automatic format detection (BMCE new/old, Investing) → French numeric parsing → incremental parquet merge
- **Refresh**: trigger Bourse de Casablanca scraping or Yahoo Finance updates — manual or scheduled daily at 18:00 Casablanca time
- **Registry**: track MASI symbols (93 tickers), manage provider mappings (Yahoo `.CS` suffix, Bourse Direct), display names and sectors
- **Monitoring**: data quality diagnostics (partial days, missing fields), year-strip overview, per-day calendar with holiday awareness
- **Data quality**: availability calendar classifying each trading day as present / missing / holiday / tentative / weekend / partial

## Key Architectural Decisions

1. **Canonical parquet store** — All OHLCV data normalized into a single parquet file per symbol at `market_data_store/{symbol}/1D`. Incremental merge-on-write (overwrite-if-different) rather than append-only, ensuring no duplicate timestamps.

2. **Format auto-detection** — Three upload formats supported (BMCE new, BMCE old, Investing/English) with normalized header matching. French numeric parsing handles `1 052,00` notation and volume suffixes (K/M/B).

3. **Moroccan holiday calendar** — JSON-based with confirmed/tentative certainty levels, symbol-specific holidays, mtime-aware caching. Used by the availability calendar and chart range-break removal.

4. **Dual freshness model** — Backend uses business days (≥2 = stale) for correctness. Frontend uses calendar days (≤1 green, ≤7 amber, else red) for quick visual scanning. Both are valid for their context.

5. **MASI ticker registry** — 93 hardcoded tickers with display names and sectors. Used for autocomplete when adding stocks, auto-filling metadata on stock creation, and filtering the catalog into MASI vs Other tabs.

## How to use these docs

Each document is self-contained enough to serve as context for an LLM development session. The documents are ordered from high-level architecture (01) through database models (02), API endpoints (03), worker tasks (04), down to frontend (07) and operational concerns (09–11).
