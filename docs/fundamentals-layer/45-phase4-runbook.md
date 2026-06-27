# Brief 45 — Phase 4 runbook (live re-ingest + purge)

**Owner:** Sonnet executor · **DB target:** local/dev · **Branch:** `feature/fundamental-ui-consolidation`

This is the operational, irreversible phase. Run it **staged**, not as one shot. It's the first time
the full chain (archetype detection → price lookup → `compute_ratios` → scoring → signal rows) runs
end-to-end against a real DB; unit tests don't cover that integrated path. **Stop and report at each
🛑 gate.** All commands run from repo root with `.venv/Scripts/python.exe`.

> The purge (`--apply`, Step 5) is the only destructive step. Legacy data survives until then, so
> everything before Step 5 is reversible by simply not purging.

---

## Step 0 — preflight
Confirm the DB the worker will hit is the intended **local/dev** one (read `services/worker/db.py`
/ `.env` `DATABASE_URL`; print host only, do not echo secrets). Abort if it points anywhere remote.

## Step 1 — smoke test on 3 symbols
```bash
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'.'); \
from services.worker.tasks.refresh_stockanalysis_fundamentals import refresh_stockanalysis_universe; \
print(refresh_stockanalysis_universe(symbols=['ATW','AFI','IBC'], triggered_by='phase4_smoke'))"
```
- `ATW` = bank, `AFI` = industrial, `IBC` = known no-coverage.
- Expect `succeeded` to include ATW + AFI; IBC in `failed`.

## 🛑 Gate A — verify the smoke test before going wider
Write a short verification script (use `services.worker.db.SessionLocal` and
`services.api.app.services.fundamentals.latest_snapshot_rows_by_symbol`). Assert/print:
1. **Not N/R:** `models.SignalEngineGlobalResult` rows for ATW and AFI (fundamental variants) have
   `status == "succeeded"` and `aggregate_score_pct is not None`. And the latest
   `FundamentalLatestSnapshot.scores_json["overall"]` is non-null for both.
2. **Bank archetype + ratios (ATW):** snapshot `source_json`/`diagnostics_json` records
   `archetype == "bank"`; `metrics_json` contains `Net_Interest_Margin`, `Cost_to_Income`,
   `Cout_du_risque`, `Price_to_Book`; and contains **none** of `EV_to_EBITDA`, `Current_Ratio`,
   `Debt_to_Equity`, `FCF_Yield`, `Price_to_Sales`.
3. **Industrial (AFI):** has `Operating_Margin`, `Current_Ratio`, and (if a `market_data_store`
   1d row exists) `PER`/`Price_to_Book`.
4. **Graceful no-coverage (IBC):** a `FundamentalQualityIssue` with code `stockanalysis_symbol_failed`
   (or equivalent no-coverage code); no silent empty snapshot.

**Stop and report this output. Do not continue if ATW comes back N/R or carries industrial-only ratios.**

## Step 2 — full universe re-ingest
```bash
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'.'); \
from services.worker.tasks.refresh_stockanalysis_fundamentals import refresh_stockanalysis_universe; \
print(refresh_stockanalysis_universe(triggered_by='phase4_full'))"
```
Note: ~75 symbols with a 1s inter-symbol sleep + scoring/valuation → expect a few minutes. Report the
`succeeded`/`failed` counts.

## 🛑 Gate B — verify N/R across the universe
Count, over the active MASI universe, how many covered symbols are still N/R (proxy:
`SignalEngineGlobalResult.status != "succeeded"` for the fundamental variant, or
`FundamentalLatestSnapshot.scores_json["overall"] is None`). Print the offending symbols.
**Expected: only genuinely-uncovered names (IBC-class).** Banks must NOT appear.

**Stop and report. Do not purge if any bank or otherwise-covered symbol is still N/R.**

## Step 3 — purge dry-run (non-destructive)
```bash
.venv/Scripts/python.exe scripts/purge_legacy_fundamental_aliases.py
```
Report the counts it *would* delete (legacy `Clean_*`/scraped-ratio annual rows + alias keys stripped
from snapshots). Sanity-check the magnitude is plausible (it should target alias/ratio rows, not the
fresh canonical rows just written).

## 🛑 Gate C — confirm before the destructive step
Report dry-run counts and wait for explicit go-ahead before Step 4.

## Step 4 — purge apply (destructive, point of no return)
```bash
.venv/Scripts/python.exe scripts/purge_legacy_fundamental_aliases.py --apply
```

## Step 5 — final verification
1. Re-run the universe N/R count (Gate B query) — unchanged (still only IBC-class).
2. No snapshot `metrics_json` contains any `Clean_*` key; no `FundamentalAnnualMetric.metric_name`
   in `_ALIAS_TO_CANONICAL`.
3. Spot-check ATW still scored with bank ratios after purge.
4. Run the test slice: `.venv/Scripts/python.exe -m pytest core/tests/ -q` → 1188 pass expected.

Report the final N/R list, purge counts, and test result.

---

## Out of scope for Phase 4 (do NOT bundle into these commits)
- The pre-existing live-quote test failure (`test_fundamental_responses_render_fresh_live_current_price`)
  is unrelated to the cutover — leave it; it's tracked separately.
