# 36 — Canonical snapshot per symbol + import hygiene

> **Status.** Plan-only. Claude has not modified code. Scope: the import lifecycle, the per-symbol canonical-snapshot resolution, and a cleanup of failed/superseded imports and their orphan valuation rows. No seven-model engine change.
>
> **Priority: P1.** The DB holds **127 fundamental imports** (16+ `failed`, plus a long tail of one-off failed uploads); a single symbol (Managem) carries ensemble rows under **23 distinct imports** with base fair values scattered from **0 to 7,336**. Reads mostly resolve a sane canonical snapshot today, but the clutter makes every "latest per symbol" query fragile and makes revalues recompute stale rows.
>
> **Plugin rubric anchor.** `equity-research:model-update` (one current model per name), `financial-analysis:audit-xls` (one source of truth, no orphan rows).

---

## 0. Files Codex MUST read first (gate — confirm line numbers)

1. `docs/fundamentals-layer/21-codex-briefs-INDEX.md` — binding rules.
2. `services/api/app/services/fundamentals.py`:
   - `latest_import` (`:1474`), `_latest_symbol_rank` (`:1509`), `latest_snapshot_rows_by_symbol` (`:1528`), `latest_imports_by_symbol` (`:1568`) — the current canonical resolution (a per-symbol ranking tuple: `has_core_statement, source_rank, core_metric_count, latest_key`).
   - `SUCCEEDED_IMPORT_STATUSES`, `NON_STOCK_SYMBOLS`, `MASI_FUNDAMENTAL_SOURCE_PRIORITY`.
   - The per-`import_id` ensemble read in `derive_research_overlay` (`:404-408`).
3. `services/api/app/models.py` — `FundamentalImport` (`:???` — find), `FundamentalLatestSnapshot`, `FundamentalEnsembleResult` (`:855`), `FundamentalValuationResult`. Note FK/cascade behaviour on `import_id`.
4. `services/api/scripts/` — the existing `dedup_fundamental_metrics.py` (commit `055de6f`) and any backfill scripts; build on these, don't fork their style.
5. The ingest workers under `services/worker/tasks/` (`targeted_bvc_fundamentals.py`, `ingest_market_data.py`, `refresh_yfinance_fundamentals.py`) — where imports are created and marked `failed`/`succeeded`.

> If a cited line has shifted, report the new line and proceed.

---

## 1. What is actually broken vs merely cluttered

**Working today:** `latest_snapshot_rows_by_symbol` already picks a *reasonable* canonical snapshot per symbol (prefers rows with core statements, better source, more metrics, then recency), and the overlay reads the ensemble for that snapshot's `import_id`. So the displayed value is usually coherent.

**Broken / fragile:**
1. **No explicit canonical pointer.** Canonicality is recomputed by a 4-tuple ranking on every query; different call sites (universe, overlay, revalue, leaderboard, signals sync) must each re-derive it identically or they drift. Evidence: the Managem trio mismatch (brief 35) plus 23 imports carrying live ensemble rows for one symbol.
2. **Failed/partial imports leave rows.** 16+ `failed` `targeted_three_statement_fill.xlsx` imports and many one-off failed uploads still have snapshot/annual/ensemble/valuation rows that the ranking must filter out every time. A failed import must not leave queryable valuation artifacts.
3. **Superseded imports are never retired.** Once a newer, better import lands for a symbol, the older import's ensemble/valuation rows persist forever, inflating the table and feeding the brief-34 revalue (which recomputed base across many stale imports — see the 23-import spread).

---

## 2. The fix (three parts, smallest first)

**2.1 — One canonical-resolution function, reused everywhere.**
- Make `latest_snapshot_rows_by_symbol` (and a scalar `canonical_snapshot_for_symbol(db, symbol)`) the **single** source of truth. Audit every place that resolves "current import/snapshot for a symbol" (universe, overlay, leaderboard, signals sync, both revalue endpoints, weekly policy) and route them all through it. No call site may re-implement the ranking inline.
- Persist the result so it is not recomputed on every request: add a nullable `is_canonical boolean` (or `canonical_import_id` on a small per-symbol table) maintained at ingest-completion and revalue time. Migration `down_revision` = current head (Codex confirms). Reads filter `is_canonical = true`; the ranking function becomes the *writer* of that flag, run once per ingest, not per query.

**2.2 — Failed imports leave no valuation artifacts.**
- In the ingest workers: a `failed` import must not have committed snapshot/annual/ensemble/valuation rows. Wrap the per-import write so that on failure the partial rows are rolled back or deleted, and the import row is marked `failed` with no children. Add a guard test.
- Confirm `SUCCEEDED_IMPORT_STATUSES` is the only status any read path trusts (it already is in the cited functions — verify no read path queries by `created_at` without the status filter).

**2.3 — Retire superseded imports (cleanup script, idempotent).**
- New `services/api/scripts/prune_superseded_fundamentals.py` (same CLI style as `dedup_fundamental_metrics.py`): for each symbol, keep the canonical import's rows; **archive or delete** ensemble/valuation/snapshot rows belonging to non-canonical, superseded imports older than the canonical one. Dry-run by default (`--apply` to execute); print a per-symbol before/after row count. Never touch `fundamental_source_document` (provenance) or the import audit row itself — only the derived valuation artifacts.
- This is the script that collapses Managem's 23 ensemble-bearing imports down to one.

---

## 3. Tests

`services/api/tests/test_canonical_snapshot.py`:
- Two succeeded imports for one symbol (older richer, newer thinner) → canonical resolution is deterministic and identical across `latest_snapshot_rows_by_symbol`, the overlay, and the revalue path (assert same `import_id`).
- A `failed` import commits **no** ensemble/valuation/snapshot rows (guard for 2.2).
- `prune_superseded_fundamentals.py --apply` on a fixture with 3 stale + 1 canonical import for a symbol leaves exactly the canonical import's valuation rows; dry-run changes nothing.
- Regression: after pruning, `latest_snapshot_rows_by_symbol` returns the same symbol set and the overlay value for a spot-check symbol is unchanged (pruning removes clutter, not the answer).

---

## 4. Acceptance criteria

1. `python -m pytest core/tests/ -q` + new API tests pass from the worktree root.
2. Every "current snapshot/import per symbol" call site routes through the one canonical function/flag; grep proves no inline re-implementation of the ranking remains.
3. A `failed` import has zero ensemble/valuation/snapshot children.
4. After `prune_superseded_fundamentals.py --apply`, no symbol has live ensemble rows under more than one import (Managem drops from 23 → 1).
5. The displayed overlay value for a sample of symbols is unchanged by the cleanup (verified before/after).
6. Docs `02-data-flow.md` + `09-api-data-flow-and-frontend-contracts.md` document the canonical pointer and the prune script.

---

## 5. What NOT to do

- Do not delete `fundamental_import` audit rows or `fundamental_source_document` provenance — only derived valuation artifacts of superseded imports.
- Do not change the seven-model engine or the scenario logic (briefs 34/35).
- Do not make pruning destructive by default — dry-run unless `--apply`.
- Do not change ingestion sources or add new ones.

## Open questions (Codex: fill in, do not improvise)

- Confirm the FK/cascade between `fundamental_import` and its children — does deleting valuation rows require cascade config or explicit deletes? Report before writing the prune script.
- Confirm whether a per-symbol `canonical_import_id` table or an `is_canonical` flag on `fundamental_latest_snapshot` fits the existing schema better; choose the lower-migration option and note it.
- Confirm why 16 `targeted_three_statement_fill.xlsx` imports failed (data issue vs transient) — if it is a recurring data bug, note it as a follow-up; this brief only stops failures from leaving rows, it does not fix the upstream parse.
