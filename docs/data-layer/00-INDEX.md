# Data Layer — Architecture Documentation

This folder contains the complete architecture, system design, and step-by-step documentation for the **Data Layer** of the Moroccan market backtesting platform.

## Documents

| # | File | Scope |
|---|------|-------|
| 01 | [overview.md](./01-overview.md) | High-level architecture, services, data flows |
| 02 | [database-models.md](./02-database-models.md) | All tables, columns, constraints, relationships |
| 03 | [backend-endpoints.md](./03-backend-endpoints.md) | Every `/market-data/*` endpoint — request/response/logic |
| 04 | [worker-tasks.md](./04-worker-tasks.md) | Excel ingestion + market refresh worker pipelines |
| 05 | [core-data-module.md](./05-core-data-module.md) | `core/quant_core/data.py` — adapters, normalization, column rename |
| 06 | [storage-and-keys.md](./06-storage-and-keys.md) | S3/MinIO bucket layout, key construction, parquet format |
| 07 | [frontend-architecture.md](./07-frontend-architecture.md) | Data page, components, hooks, API client, proxy |
| 08 | [data-flows.md](./08-data-flows.md) | End-to-end flows: Excel upload, Bourse refresh, catalog, technical study |
| 09 | [config-and-infra.md](./09-config-and-infra.md) | Environment variables, Docker Compose, queue config |
| 10 | [prompt-context.md](./10-prompt-context.md) | Condensed context blocks for LLM-assisted development |
| 11 | [daily-update-and-data-page.md](./11-daily-update-and-data-page.md) | Daily scheduled refresh, data page as control center, freshness monitoring |

## The Data Page Is the Heart of This Layer

The `/data` page is not a secondary view — it is the **control center** for the entire data pipeline. Every backtest depends on data managed here. Without fresh, complete data, backtests produce stale or wrong results.

Key responsibilities:
- **Visibility**: what data exists, how fresh it is, what's missing
- **Ingestion**: upload Excel files (BMCE format) → automatic parsing + parquet creation
- **Refresh**: trigger Bourse de Casablanca / Yahoo Finance updates (manual today, daily scheduled planned)
- **Registry**: track which symbols are active, their metadata, provider mappings
- **Monitoring**: freshness badges, health summary, refresh progress

## How to use these docs for LLM-assisted development

Each document is written to be **self-contained enough to paste into an LLM context window**. The [prompt-context.md](./10-prompt-context.md) file contains pre-built context blocks you can copy-paste to:

- Add a new endpoint to the market data router
- Add a new frontend component to the data page
- Add a new data source adapter
- Add a new worker task
- Modify the ingestion pipeline
- Add a new database migration
- Implement daily scheduled refresh (see doc 11 for full context)
