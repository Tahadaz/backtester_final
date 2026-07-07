# Pipeline Reconstruction (Phase 1)

Grounded in the actual repo and live Postgres DB (`postgresql://app:app@127.0.0.1:5555/quant`, container `infra-quant_postgres-1`). No behavior inferred from names — all claims below verified by reading code or querying the DB directly.

## 1. Ingestion entry points

| Path | Role |
|---|---|
| `services/api/app/routers/fundamentals.py` `POST /fundamentals/import` | Excel upload → object storage → `fundamental_import(status="queued")` row → worker job |
| `services/worker/tasks/fundamentals.py:execute_fundamental_import` | Worker orchestration |
| `core/quant_core/fundamentals/workbook.py:parse_fundamental_workbook` | Parses analyst-curated Excel (`data_source='workbook'`) |
| `core/quant_core/fundamentals/providers/stockanalysis_provider.py` | Scrapes stockanalysis.com (`data_source='stockanalysis'`) |
| BVC targeted ingestion (`data_source='bvc'`, filename pattern `targeted_bvc_fundamentals_manual-*.jsonl`) | Per-symbol filing pull from Casablanca Bourse document pages, tagged with `fundamental_source_document` rows |
| `core/quant_core/fundamentals/providers/yfinance_provider.py` + `normalize_yfinance.py` | yfinance ingestion; **no unit-scale defenses** (see finding below) |
| `core/quant_core/fundamentals/consensus/{bkgr.py, marketscreener.py, reconcile.py}` | Consensus/forward-estimate ingestion |

## 2. Storage

- **Engine**: PostgreSQL 16 (Docker container `infra-quant_postgres-1`, port 5555), SQLAlchemy ORM in `services/api/app/models.py`, Alembic migrations under `services/api/alembic/versions/`.
- Key tables (confirmed via `information_schema` + direct query):
  - `fundamental_annual_metric` — long-form panel: `(import_id, symbol, statement_year, metric_name, metric_value, raw_metric_name, is_proxy, as_of_date, source_document_id)`. Unique on `(import_id, symbol, statement_year, metric_name)` — **dedup is scoped per import, not globally**, so the same symbol/year/metric legitimately has multiple conflicting rows across imports.
  - `fundamental_source_document` — filing provenance: `(id, symbol, company_name, document_title, source_url, publication_date, fiscal_year, period_type, status)`.
  - `fundamental_latest_snapshot` — one row per symbol with `is_canonical=true`, JSONB `metrics_json`. This is what production (valuation/scoring) actually reads.
  - `fundamental_import` — one row per ingestion run: `(id, status, filename, data_source, source_universe, created_at, annual_metric_count)`.
  - `stock_master.shares_outstanding` — single latest scraped share count (not a time series).
  - `market_data_store` — OHLCV pointer table (prices live in object storage, not Postgres rows directly).

Confirmed live counts as of 2026-07-06: `fundamental_annual_metric` holds 178 rows for REB, 207 for SAH across 12 distinct import batches spanning 2026-05-25 to 2026-06-19.

## 3. Duplicate handling — two independently-coded routines with opposite tie-breaks

- `workbook.py:_select_best_latest` (line 150) — tie-break operator `>` (last-iteration-wins on exact ties).
- `panel.py:_latest_metric_map` (line 176) — tie-break operator `>=` (opposite convention).
- DB constraint dedups only *within* one `import_id`; cross-import conflicts are resolved only at the `fundamental_latest_snapshot.is_canonical` layer, which is a separate resolver (`services/api/app/services/fundamentals.py`) not yet audited line-by-line.

## 4. PIT panel / "90-day fallback"

`core/quant_core/fundamentals/cross_section/panel.py`:
- `PanelConfig.annual_lag_days = 90` (semiannual 60, quarterly 45).
- `availability_date()` (line 59): `publication_date` if known, else `as_of_date`, else `period_end_date + lag_days`.
- `availability_kind()` tags each row `"publication_date" | "as_of_date" | "fallback_annual_90d"` — the pipeline **does** track what fraction of the panel is fallback-dated (`publication_coverage_stats()`, line 337); this has not yet been run/reported (Phase 11, pending).
- Hard runtime guards against look-ahead: `_assert_no_lookahead()`, `assert_metric_rows_no_lookahead()`.

## 5. Historical market cap

`price × shares`, computed fresh at read time (`pit_ic_backtest.py:174`, `characteristic_study.py:212`) — **not** a stored historical series. Share count is whichever value happens to be in the `AnnualMetricRow` history as of the as-of date (`_SHARES_NAMES = ("Shares_Outstanding",)`), with a static present-dated fallback table (`masi_float_shares.py`, dated 2026-05-25) used for benchmark-weight approximations. Confirmed live: SAH, REB, SBM shares outstanding are in fact stable/consistent across all import batches — the market-cap conflicts found below are **not** a shares-outstanding problem.

## 6. B/M and CF/P computation — three parallel implementations

`core/quant_core/fundamentals/cross_section/{characteristic_study.py, methodology_bakeoff.py, final_model_validation.py}` each independently pull `MarketCap_Calc`/`Market_Cap` and book equity/CFO via alias lists and compute the ratio locally. No single canonical function. This is a duplication risk flagged for Phase 9/10 consolidation, not yet fixed.

## Existing prior-work docs (already in repo, read but not re-litigated here)

`docs/fundamentals-layer/VERIFICATION_codex_briefs.md` already contains a prior root-cause writeup of the SAH P/E/P/B issue (yfinance `trailingPE`/`priceToBook` trusted verbatim, SAH.CS vs SAH.MA ticker-suffix ambiguity hypothesis) — this predates and is consistent with, but does not fully explain, the market-cap conflict found independently below in Phase 4.
