# Brief: migrate Bourse de Casablanca scrapers to the new `boursenova` API + gap backfill

Status: approved by user 2026-11-17. Implementation brief (self-contained).

## Why

The Bourse de Casablanca website was rebuilt (plain Drupal theme `bn_institutional`, no `/fr/` prefix,
no Next.js `_next/data`, no `/api/proxy`). Every old URL the app uses now **302-redirects to the
homepage**, so the daily refresh silently gets nothing:

| Old URL (dead) | Used by |
|---|---|
| `https://www.casablanca-bourse.com/fr/live-market/instruments/{SYMBOL}?pwa=1` | `core/quant_core/data.py` `BDCSessionAdapter`; `services/worker/tasks/refresh_market_data.py:529` `_update_stock_metadata_from_bourse`; `services/api/app/services/bourse_live_quotes.py:23`; `services/api/app/routers/market_data.py:948` |
| `https://www.casablanca-bourse.com/fr/live-market/marche-cash/indices?pwa` | `core/quant_core/data.py` `CasablancaBourseIndicesAdapter` (used by `refresh_all_tracked_indices`) |
| `https://www.casablanca-bourse.com/fr/historique-des-indices` + `https://api.casablanca-bourse.com/fr/api/bourse_data/index_history` | `services/worker/tasks/ingest_casablanca_indices.py` |
| `https://www.casablanca-bourse.com/bourseweb/cours-historiques-download` | `BourseDirectAdapter` (only when `BOURSE_DIRECT_URL_TEMPLATE` is set) |

In addition, the app was down for ~1 month, so stored daily bars have a hole (possibly interior,
if a later bar was stored after the outage). The current refresh is tail-only
(`fetch_start = end_ts + 1 day`, `refresh_market_data.py:682-694`) and session-only adapters ignore
`start` entirely, so holes are never repaired.

## New endpoints (verified live 2026-11-17, public, plain GET, no cookies/WAF seed needed)

Base: `https://www.casablanca-bourse.com/api/boursenova` (the site reads it from
`drupalSettings.boursenova.apiBaseUrl`; hard-code with a constant).

TLS: the Windows/OS trust store accepts the chain; python `certifi` on the dev box failed with
`unable to get local issuer certificate`. Do **not** add new `verify=False`. Use `truststore`
(`truststore.inject_into_ssl()` or an `SSLContext`) if available, else default verification; if it
fails in the Linux containers, add the missing intermediate CA bundle explicitly. Existing
`verify=False` call sites may stay as they are (out of scope).

### 1. Stock daily history
```
GET /api/boursenova/stock-historical?instrument=IAM&market=comptant&type=actions
    &startDate=2023-11-18&endDate=2026-11-17&isCoursAjuste=false&target=tv
```
Response:
```json
{"totalCount": 736, "items": [
  {"seance": "13/11/2026", "timestamp": 1794528000000, "symbol": "IAM  ",
   "libelle": {"fr": "ITISSALAT AL-MAGHRIB", ...},
   "ouverture": 90.45, "dernierCours": 89, "coursReference": null,
   "plusHaut": 90.5, "plusBas": 89, "titresEchanges": 310977,
   "volumeEchanges": 27878393.29, "nbTransactions": 177,
   "capitalisation": 78239485260, "variation": null, ...}]}
```
- `instrument` = plain BVC ticker (IAM, ATW, ...). `symbol` comes back right-padded with spaces → `.strip()`.
- Mapping: `seance` (dd/mm/yyyy, authoritative session date) → index; `ouverture`→Open,
  `plusHaut`→High, `plusBas`→Low, `dernierCours`→Close, `titresEchanges`→Volume (shares — matches
  the old "Quantité échangée"→Volume convention). Keep `volumeEchanges`, `nbTransactions`,
  `capitalisation` only if the parquet schema already tolerates extra columns; otherwise drop.
  Share count = `round(capitalisation / dernierCours)` replaces the old "Nombre de titres" scrape
  (`NombreTitres` column + `_update_stock_share_count_from_frame`).
- Items are newest-first. A request whose `startDate` is older than ~3 years before today returns
  `{"totalCount":0,"items":[]}` (window ceiling, not an error) → clamp `startDate` to
  `today - 3y + 2d`. Full 3-year window is a single ~370 KB response; `pageNumber`/`pageSize`
  params exist (site uses pageSize=100) — implement paging defensively if `totalCount > len(items)`.
- Today's row appears intraday (in-progress session). Same overwrite semantics as today: the post-close
  refresh overwrites it.
- `isCoursAjuste=true` returned identical numbers for IAM on the sampled window. Store **raw**
  (`false`), matching current store semantics.
- Holidays are simply absent (e.g. 2026-11-06 Green March) — correct.

### 2. Index daily history
```
GET /api/boursenova/indices/historical?code=MASI&startDate=2023-11-18&endDate=2026-11-17
GET /api/boursenova/indices/historical?code=MASI,MSI20&period=5D     (multi-code, period form)
```
Response: `{"totalCount":736,"items":[{"seance":"17/11/2026","timestamp":...,
"indices":{"MASI":{"code":"MASI","valeur":17234.7994,"plusHaut":17282.9779,"plusBas":17185.7386,
"variation":-0.027,"variationYTD":-8.55}},"volume":0,"transactions":0}]}`
- Close = `valeur`, High/Low = `plusHaut`/`plusBas`; there is no open → keep the existing
  `_standardize_ohlcv_index` convention (Open synthesized from previous close).
- New codes (from `drupalSettings.boursenova.indices` on `/market-data/indices`): AGRO, ASSUR,
  BANK, BOISS, CHIM, DISTR, ELEC, ESGI, IAG, IMMOB, MASI, MASID, MASIE, MASIMS, MASIR, MASRN,
  MINES, MS20R, MS20RN, MSI20, PHARM, SANTE, SDT, SPI, TCOM, TRANS (each has `label.fr`).
- App index symbols live in `index_master` / `CASABLANCA_INDEX_CODES`
  (`ingest_casablanca_indices.py:26`: MASI, MASI_20, MASI_ESG, MASI_USD, MASI_EUR,
  MASI_RENTABILITE_BRUT, ...). Build an explicit, tested `APP_SYMBOL -> boursenova code` map
  (match on `label.fr`; e.g. MASI_20→MSI20, MASI_ESG→ESGI, MASI_MID_AND_SMALL_CAP→MASIMS,
  MASI_USD→MASID?, MASI_EUR→MASIE?, MASI_RENTABILITE_BRUT→MASIR, MASI_RENTABILITE_NET→MASRN —
  **verify every pair against the live labels and against overlapping stored closes**, do not guess).
  App symbols with no new code: log once and skip (no failure).

## What to build

### A. Core adapters (`core/quant_core/data.py`)
1. `BoursenovaHistoryAdapter(BaseDataSource)` — honours `start`/`end` (clamped to the 3-year
   ceiling), one HTTP session, timeout 30s, 2 retries with backoff, browser User-Agent,
   empty DataFrame on failure (existing convention). Rejects rows without a parseable `seance`.
2. `BoursenovaIndicesAdapter` — `fetch(codes, start, end) -> dict[app_symbol, DataFrame]` with the
   same output shape as `CasablancaBourseIndicesAdapter.fetch()` (incl. `display_name`) so
   `refresh_all_tracked_indices` changes minimally.
3. Keep the old classes but stop routing to them (mark deprecated in docstring). Do not delete.

### B. Daily refresh (`services/worker/tasks/refresh_market_data.py`)
1. Route `bourse_direct` **and** `bmce_excel` sources (all Moroccan equities) to
   `BoursenovaHistoryAdapter`. If it returns empty for a symbol, fall back to the previous adapter
   (BMCE Capital live for `bmce_excel`) so nothing regresses. Yahoo path unchanged.
2. **Self-healing window**: fetch from `min(end_ts, today) - REFRESH_LOOKBACK_DAYS` (env, default 45
   calendar days) to today instead of `end_ts + 1`. `_merge_overwrite_if_different` already inserts
   missing dates and overwrites differing ones — confirm and test that it inserts interior missing
   dates (not only appends after the tail).
3. `is_before_bourse_refresh_cutoff`/`needs_bourse_refresh` short-circuit (lines ~640-654) must not
   skip a symbol that has a hole: only skip when the store is current **and** has no missing
   sessions inside the lookback window (cheap check against the exchange calendar described in D).
4. `_update_stock_metadata_from_bourse`: replace the dead page scrape with data from the same
   history response (share count from capitalisation/close). Must never raise.
5. `refresh_all_tracked_indices`: use `BoursenovaIndicesAdapter` with the same lookback window;
   for multi-bar responses synthesize Open per bar from the previous close **within the merged
   series** (the current code sets one scalar `prev_close` for all rows — wrong for >1 bar).

### C. Live quotes (`services/api/app/services/bourse_live_quotes.py`, `routers/market_data.py:948`)
Replace the dead instrument-page scrape with `stock-historical` for `startDate=endDate=today`
(fallback: last 5 days, take the newest row). Keep the public response shape of these services.

### D. Gap audit + backfill (new)
1. Exchange calendar = the set of `seance` dates of MASI from `indices/historical` (3-year window).
   A stock's **expected sessions** = calendar dates between its first stored bar (or listing date)
   and today. Missing = expected − stored (exclude dates where the exchange returns no row for that
   stock — suspended/untraded names are legitimately absent; record them as `exchange_absent`, not
   as gaps).
2. `scripts/backfill_bourse_history.py` (host-side, same env/bootstrap pattern as other scripts in
   `scripts/`, plus an RQ task wrapper `services/worker/tasks/backfill_bourse_history.py` so it can
   run inside the prod worker container):
   - `--dry-run` (default): print per-symbol gap report (missing count, first/last missing date,
     stored-vs-exchange close mismatches in the overlap) as a table + JSON to
     `output/bourse-backfill/<timestamp>.json`.
   - `--apply`: for every tracked stock and active index, fetch the full 3-year window, **insert
     missing dates only** for dates older than `REFRESH_LOOKBACK_DAYS`; inside the lookback window
     use normal overwrite-if-different. Never overwrite older stored bars (they may come from a
     different provider/adjustment); report mismatches instead.
   - Persist through the existing helpers (`_save_parquet`, `_upsert_market_data_store`,
     `_upsert_market_data_store_index`) so `market_data_store.end_ts/data_as_of/close_last` stay
     consistent.
   - Idempotent; re-running `--dry-run` after `--apply` must report 0 gaps (except `exchange_absent`).
   - `--symbols IAM,ATW` and `--indices-only` / `--stocks-only` filters.
   - After `--apply`, optional `--enqueue-downstream`: enqueue the existing post-refresh chain
     (`_enqueue_signal_layers_after_refresh` / dashboard snapshot) and dispatch the weekly chain via
     `services/worker/tasks/scheduler_dispatch.dispatch_schedule(...)` for: weekly_fundamental_beta_refresh,
     weekly_fundamental_cross_section, weekly_value_strategy_refresh, weekly_wfo_dispatch,
     weekly_signal_backtest_dispatch, weekly_signal_history_dispatch,
     weekly_signal_best_evidence_snapshot, weekly_pit_opportunity_materialization,
     daily_dashboard_snapshot (respect their existing dependency ordering; read
     `services/api/app/services/scheduler_registry.py`).
3. Also expose it in the ops router if one already exists for manual refresh triggers
   (`services/api/app/routers/ops.py`) — admin-only, same auth as existing ops endpoints. Skip if
   it requires new auth plumbing.

### E. Index ingester (`ingest_casablanca_indices.py`)
Point it at `BoursenovaIndicesAdapter` (it becomes a thin wrapper over the backfill for indices).
Remove the WAF cookie seeding for the new path.

## Tests (required)
- Recorded JSON fixtures (small: ~5 rows per endpoint, include the padded `"IAM  "` symbol, a
  holiday gap, newest-first order) under the existing test-fixture convention. No network in tests.
- Adapter parsing, date clamping, empty/zero-count response, HTTP failure → empty frame.
- Merge inserts an **interior** missing date; backfill insert-only mode does not overwrite an old
  differing bar but does report it; lookback window does overwrite.
- Index multi-bar Open synthesis.
- Gap audit: `exchange_absent` vs real gap classification.
- Run the relevant existing suites: `core/tests`, `services/api/tests`, worker tests touching
  refresh/ingest. Report exact pass/fail counts.

## Live verification (required, read-only against the real site)
Run `scripts/backfill_bourse_history.py --dry-run` against the **local** dev stack DB if it is up
(see README for ports); if not up, run the adapters alone against the live site for IAM, ATW, BCP,
MASI, MSI20 and print row counts + first/last dates. Do not write to any production system.

## Out of scope
Fundamentals scrapers (`bvc_publications.py` — check its URL still works and just report), Yahoo,
removing old `verify=False` sites, pre-2023 history.
