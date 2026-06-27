# Data flow

End-to-end path of fundamental data from an Excel upload to the analyst's screen.

## Pipeline stages

```
   User                                                              Engine                              Storage
    │                                                                  │                                    │
    │   1. Upload workbook  ───POST /fundamentals/import──>            │                                    │
    │                                                                  │                                    │
    │                                                       2. Worker: execute_fundamental_import           │
    │                                                          │       │                                    │
    │                                                          ▼       │                                    │
    │                                            parse_fundamental_workbook                                 │
    │                                            (workbook.py)          │                                   │
    │                                                          │       │                                    │
    │                                                          ▼       │                                    │
    │                                            FundamentalWorkbook                                        │
    │                                            ├ CompanyMapping[]                                         │
    │                                            ├ AnnualMetricRow[]                                        │
    │                                            ├ FundamentalSnapshot[]                                    │
    │                                            └ FundamentalQualityIssue[]                                │
    │                                                          │       │                                    │
    │                                                          ▼       │                                    │
    │                                            3. score_fundamental_snapshots                             │
    │                                               (scoring.py)        │                                   │
    │                                                          │       │ writes scores into snapshot       │
    │                                                          ▼       │                                    │
    │                                            4. compute_symbol_valuations (per symbol)                  │
    │                                               (valuation.py:601)  │                                   │
    │                                                          │       │ writes 7 ValuationResult per sym  │
    │                                                          ▼       │                                    │
    │                                            5. compute_valuation_ensemble (per symbol)                 │
    │                                               (valuation.py:555)  │                                   │
    │                                                          │       │ writes 1 EnsembleResult per sym   │
    │                                                          ▼       │                                    │
    │                                            6. Persist                                                 │
    │                                                                  │     fundamental_import           ──┤
    │                                                                  │     fundamental_company_map      ──┤
    │                                                                  │     fundamental_annual_metric    ──┤
    │                                                                  │     fundamental_latest_snapshot  ──┤
    │                                                                  │     fundamental_valuation_result ──┤
    │                                                                  │     fundamental_ensemble_result  ──┤
    │                                                                  │     fundamental_quality_issue    ──┤
    │                                                                  │     fundamental_assumption_set    │ (read-side)
    │                                                                  │                                    │
    │   <───────────────────  API responses  ────────────────────────  │                                    │
    │                                                                  │                                    │
    │   7. UI fetch & render                                           │                                    │
    │      /fundamentals page                                          │                                    │
```

## Step-by-step trace

### 1. Upload (UI / API)

`POST /fundamentals/import` with multipart `file` (Excel workbook).

Router: `services/api/app/routers/fundamentals.py`.
- Persists the file to object storage (S3-compatible).
- Creates a `FundamentalImport` row with `status="queued"`.
- Enqueues `execute_fundamental_import(import_id)` on the worker.
- Returns `{upload_id, rq_job_id}`.

### 2. Worker parses the workbook

`services/worker/tasks/fundamentals.py:execute_fundamental_import`:
- Fetches the file bytes from S3 using `object_key`.
- Delegates to `services/api/app/services/fundamentals.py:execute_import_run`.

`execute_import_run`:
1. Calls `parse_fundamental_workbook(payload)` — the heavy parser in `core/quant_core/fundamentals/workbook.py`.
2. Receives a `FundamentalWorkbook` with mappings, annual metrics, snapshots, quality issues.
3. Sets `FundamentalImport.status="running"`.

### 3. Scoring

`score_fundamental_snapshots(snapshots, annual_metrics, sectors=...)`:
- Computes sector-bucketed percentile ranks with market fallback.

### Canonical snapshot pointer

After a successful ingest or valuation recompute, the API resolves one canonical
`fundamental_latest_snapshot` per symbol and persists it with
`is_canonical = true`. The resolver is shared by the universe, detail,
overlay, signal-sync, and recompute paths. It prefers succeeded/partial imports
with core statement coverage, source priority, metric breadth, and then import
recency; old databases without the flag fall back to the same ranking.
Verified/proof-backed FY2025 remediation snapshots outrank unverified partial
snapshots for the same symbol so a later generic import cannot mask a
source-read canonical record or an NR verification verdict.

Failed imports keep their `fundamental_import` audit row, but derived artifacts
are removed: latest snapshots, valuations, ensembles, projections, and imported
statement rows. Source-document provenance is preserved.

`services/api/scripts/prune_superseded_fundamentals.py` removes superseded
per-symbol valuation artifacts for non-canonical imports. It is a dry-run by
default and requires `--apply` to delete rows.

### Brief 38 source-data verification

Before source data is allowed to drive display-facing valuation, the remediation
path can persist a `fundamental_data_verification` row for the canonical import
and statement year. The verifier recomputes the following from raw lines rather
than trusting stored ratios: balance-sheet equality, group-basis BVPS, income
label consistency, group-basis ROE, annual-vintage consistency, existing
three-statement integrity checks, and plausibility bands.

Curated corrections live in
`core/quant_core/fundamentals/data/fundamental_corrections.json`. Each curated
figure records the official BVC document URL, page/line reference, and verbatim
filing label. `services/api/scripts/remediate_fundamentals.py` is dry-run by
default; `--apply` upserts the curated annual metrics and verification rows, and
`--revalue` then runs the existing all-scenario recompute path with live quote
fetching disabled.

If a canonical symbol/year is marked `data_unverified`, valuation recompute
persists all models as unavailable and the ensemble is NR. The API overlay also
forces NR for that import/year, so a stale cached fair value cannot leak through.

Brief 42 extends this with FY2025 proof-of-read artifacts under
`data/corrections/fy2025/<SYMBOL>.json`. Each artifact is a single fiscal
vintage and records, per observed figure, the filing URL, page/line reference,
verbatim label, reported value, normalized value, and unit. The remediation CLI
loads them with `--fy2025-reingestion`; dry-run prints the tie-out result, while
`--apply` replaces that symbol's canonical FY2025 annual rows with only the
cited proof set plus standard derived formulas. Unavailable filing lines are
recorded in the artifact but are not persisted as values. If a missing or
contradictory line is required by T1-T7, the symbol/year is persisted as
`data_unverified` and valuation remains NR.

- Calls Piotroski, DuPont, accrual diagnostics per symbol.
- Writes per-pillar scores back into `snapshot.scores`.
- Writes diagnostics into `snapshot.diagnostics`.

Important: after persistence, `rescore_universe` recomputes the latest per-symbol cohort for MASI or non-MASI, so incremental imports do not keep isolated one-symbol scores.

### 4. Per-symbol valuation

For each symbol in the import, `compute_symbol_valuations` (`valuation.py:601`):
1. Looks up the symbol's sector from `stock_master`.
2. Builds peer stats from same-sector snapshots (with market fallback).
3. Computes eligibility for each of the 7 models.
4. Runs each eligible model.
5. Computes the ensemble.

### 5. Persistence

Each entity gets its own table (all in `services/api/app/models.py`):
- `FundamentalImport` — one row per upload, tracks status + counts.
- `FundamentalCompanyMap` — symbol ↔ company name disambiguation.
- `FundamentalAnnualMetric` — long-form per (symbol, fiscal_year, metric_name).
- `FundamentalLatestSnapshot` — latest-period snapshot per symbol (with `metrics_json`, `scores_json`, `diagnostics_json`, `coverage_json` JSONBs).
- `FundamentalQualityIssue` — per-issue rows with severity / code / message.
- `FundamentalValuationResult` — one row per (symbol, scenario, model).
- `FundamentalEnsembleResult` — one row per (symbol, scenario).
- `FundamentalDataVerification` - one tie-out verdict per canonical
  (import_id, symbol, statement_year), with corrections and filing provenance.
- `FundamentalAssumptionSet` — per (scope_type, scope_key, scenario), independent of imports.

Migration: `services/api/alembic/versions/a0b1c2d3e4f6_add_fundamental_research_tables.py`.

### 6. API responses

The frontend reads via:
- `GET /fundamentals/universe` — list view (one row per symbol with headline scores).
- `GET /fundamentals/stocks/{symbol}` — detail view (snapshot + annuals + valuations + diagnostics).
- `GET /fundamentals/stocks/{symbol}/valuation` — per-model valuation detail.
- `GET /fundamentals/imports/latest` — for the workbook-upload page (shows last successful upload).

See [09-api-data-flow-and-frontend-contracts.md](09-api-data-flow-and-frontend-contracts.md) for full endpoint detail.

### 7. UI render

The `/fundamentals` page (`frontend/app/fundamentals/page.tsx`) has:
- Left column: symbol picker (universe table with filters).
- Center: pillar score gauges.
- Right: valuation summary (fair value triangle, upside, confidence).
- Bottom tabs: Summary / Valuation / Quality / Financials / Assumptions / Lineage.

## Re-computation triggers

Beyond a new workbook upload, the engine re-runs when:
- **Assumption set update** via `PUT /fundamentals/stocks/{symbol}/assumptions/{scenario}`. Calls `recompute_symbol_valuations` (in `services/api/app/services/fundamentals.py`) — runs valuation only, not scoring.

Pillar scoring is NOT re-run on assumption update because scores depend on the cohort, not on assumptions.

## Read paths

For UI rendering, every read goes through the API:

```
Frontend                  API                              DB
   │                       │                                │
   │ GET .../universe ────>│                                │
   │                       │  query latest_imports +        │
   │                       │  FundamentalLatestSnapshot  ──>│
   │                       │  + FundamentalEnsembleResult   │
   │ <─────────────────────│  + technical_context           │
   │                       │                                │
   │ GET .../stocks/X ────>│                                │
   │                       │  query snapshot, annuals,      │
   │                       │  valuations, ensemble,         │
   │                       │  quality_issues, assumptions ─>│
   │ <─────────────────────│                                │
```

The `technical_context` adapter joins to the signal layer (`row.technical?.signal_label` in `frontend/app/fundamentals/page.tsx:456`) — that's the one cross-layer dependency.

## Failure modes

| Failure | Where | Recovery |
|---|---|---|
| Workbook parse fails | `parse_fundamental_workbook` | `FundamentalImport.status="failed"`, `error_message` populated. Re-upload after fix. |
| Single symbol fails during valuation | `compute_symbol_valuations` (inside loop) | Currently raises; need to confirm whether the import as a whole fails or skips. **Test this.** |
| Single model fails for a symbol | `_fcff_dcf`, `_ddm`, etc. | Returns `_unavailable(...)` — graceful skip; doesn't break the symbol. |
| Persist fails (e.g. DB connection) | `execute_import_run` | `FundamentalImport.status="failed"`. Re-run after recovery. |

## See also

- [03-workbook-spec.md](03-workbook-spec.md) — the expected Excel layout.
- [04-pillars-and-scoring.md](04-pillars-and-scoring.md) — what scoring does.
- [06-valuation-models.md](06-valuation-models.md) — what valuation does.
- [09-api-data-flow-and-frontend-contracts.md](09-api-data-flow-and-frontend-contracts.md) — REST surface in detail.
