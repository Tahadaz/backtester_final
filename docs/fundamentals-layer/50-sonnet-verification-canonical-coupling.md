# Brief 50 — Couple data-tie-out verification into recompute (fix the silent-rating / absurd-cible hole)

**Owner:** Sonnet (implements). **Priority:** P0 — correctness/integrity. **Type:** engine + pipeline + small frontend gate.
**Supersedes nothing.** Complements brief 38 (verification logic), brief 41 (verification coverage), brief 44 (valuation bias). This brief fixes the *plumbing* that lets unverified data reach a published cible; brief 44 fixes the *math* on the names that survive verification.

---

## §0 Read-gate (open every anchor and confirm current line numbers before editing)

- `services/api/app/services/fundamentals.py`
  - `derive_recommendation` NR gates — `:359` (NR triggers at `:371` data_unverified_nr warning, `:373` no_usable, `:386-395` thresholds)
  - `recompute_symbol_valuations` — `:4327`; **the bug**: verification is *looked up*, not computed — `:4351-4357`
  - `_persist_data_unverified_nr` — `:4183` (the NR persistence path already exists; it is only reached when a row pre-exists)
  - `latest_data_verification` — `:4113` (read-only lookup keyed on import_id+symbol+statement_year)
  - `_data_unverified_reason` — `:4133`
  - `derive_research_overlay` request-time gate (`:589-591`) — sets `recommendation="NR"`, `target_price=None`
- `core/quant_core/fundamentals/integrity.py`
  - `build_data_tieout_report(symbol, statement_year, rows_by_metric, *, previous_rows_by_metric, snapshot_year, metric_years, period_type, assumptions, provenance)` — `:461`; returns `DataTieOutReport(status in {"verified","data_unverified"}, failed_checks, reason, warnings, offending_metrics, ...)` — `:528`
- `services/api/scripts/remediate_fundamentals.py`
  - `_upsert_verification` — `:524` (the canonical persistence shape for a `FundamentalDataVerification` row; **reuse this pattern**, do not invent a new one)
  - how `rows_by_metric` / `previous_rows_by_metric` / `metric_years` are assembled before calling `build_data_tieout_report` (search upward from `:641` and `:751`) — **reuse the same assembly helper**, do not re-derive it
- `frontend/components/strategy/signal-fundamental-view.tsx`
  - `officialTargetPrice` fallback leak — `:1931`
  - thesis `fairValue` fallback leak — `:2176`

---

## §1 Evidence (live canonical DB, scenario=base, resolved via `is_canonical=true`)

**The headline number: of 73 canonical names, 53 have NO data-verification row on their canonical import+year. 52 of those carry a published cible anyway** — i.e. they are rated on annual data that was never confirmed to tie out.

### MNG walkthrough (the reported case)
- Canonical import `17fa82d2`: `fair_value_base = 4129.7`, `current_price = 14800`, `usable_model_count = 3`, `confidence = 0.71`, **verification rows for this import+year = 0**, warnings = `["justified_multiples_excluded_cross_model_outlier"]`.
- A *different*, non-canonical MNG import `46bd54cb` **was** verified → `t7_plausibility` → `data_unverified_nr` → `fair_value_base = NULL` → correctly **NR**.
- Because the canonical import has no verification row, `recompute_symbol_valuations` skips the gate, computes a normal ensemble, and `derive_recommendation` rates MNG **SELL at 4129 (≈ −72% vs price)**. The page then shows that 4k cible.
- Compounding (brief 44, not this brief): the only sane model `justified_multiples = 10329` (BKGR target ≈ 10800) was discarded as a `cross_model_outlier`, leaving three midcycle-suppressed models (ddm 2668 / RI 3754 / relative 5048). So even if it *should* be rated, 4129 is wrong. With verification coupled, MNG correctly becomes **NR** (its data genuinely fails T7), so the cible disappears — which is the right outcome regardless of brief 44.

### The 52 unverified-but-rated canonical names (by |implied upside|)
17 of them carry an implausible |upside| ≥ ~48%:

| symbol | cible | price | upside% | umc |
|---|---|---|---|---|
| MLE | 744.7 | 370.0 | +101.3 | 3 |
| SNA | 16.3 | 78.0 | −79.1 | 2 |
| RDS | 41.8 | 178.0 | −76.5 | 2 |
| MNG | 4129.7 | 14800 | −72.1 | 3 |
| STR | 60.6 | 200.0 | −69.7 | 2 |
| MSA | 284.6 | 868.0 | −67.2 | 5 |
| ARD | 743.2 | 446.5 | +66.4 | 3 |
| M2M | 142.2 | 400.0 | −64.4 | 2 |
| TQM | 684.2 | 1839 | −62.8 | 6 |
| CFG | 83.5 | 204.9 | −59.2 | 3 |
| SAH | 4898.5 | 3080 | +59.0 | 4 |
| WAA | 9473.6 | 6000 | +57.9 | 3 |
| GTM | 322.5 | 760.0 | −57.6 | 4 |
| SID | 916.4 | 2000 | −54.2 | 3 |
| AKT | 568.6 | 1215 | −53.2 | 4 |
| CMT | 2479.3 | 5101 | −51.4 | 5 |
| EQD | 684.3 | 1334 | −48.7 | 3 |

(Full 52-name set reproduced by the §5 SQL.) Note heavy overlap with the brief-44 bias names (TQM, SID, WAA, AKT, CMT) — but they are *also* unverified, so verification must be fixed first or brief 44 will be validated against ungated noise.

---

## §2 Root cause

1. **`recompute_symbol_valuations` reads verification, never computes it** (`:4351`). It calls `latest_data_verification(...)`, and only persists NR (`_persist_data_unverified_nr`) when a row already exists with `status=data_unverified`. If the canonical import has no row, the gate is silently skipped.
2. **Verification is produced by a separate, selective step** (`remediate_fundamentals.py::_upsert_verification`, `:524`) that targets specific imports/symbols. It was never run against most canonical imports.
3. **Canonical promotion (`is_canonical`) is not coupled to verification.** The promoted vintage can be (and for MNG is) one that was never verified, while the verified vintage stays non-canonical. Result: the tie-out gate built in brief 38 is dormant for ~73% of the live universe.

This is a plumbing gap, not a math error. The verdict function `build_data_tieout_report` already exists and works; it just isn't invoked on the recompute path.

---

## §3 Fix — verification must be computed at recompute time, not looked up

In `recompute_symbol_valuations` (`fundamentals.py:4327`), replace the read-only lookup at `:4351-4357` with a **compute-then-persist-then-gate** flow:

1. Keep reading the existing row first (so a curated/forced `remediate_fundamentals` verdict is never overwritten):
   - If a `FundamentalDataVerification` row already exists for `(import_id, symbol, target_snapshot.latest_statement_year)`, use it as today.
2. **If none exists, compute it.** Assemble `rows_by_metric` / `previous_rows_by_metric` / `metric_years` from the already-loaded `history` (`context["history"]`, `:4320/4347`) for the target statement year and the prior year, using **the same assembly helper `remediate_fundamentals.py` uses** (do not re-derive line-item mapping — extract/reuse it so the two paths can never diverge). Then call:
   ```python
   report = build_data_tieout_report(
       symbol, target_snapshot.latest_statement_year, rows_by_metric,
       previous_rows_by_metric=prev_rows_by_metric,
       snapshot_year=target_snapshot.latest_statement_year,
       metric_years=metric_years, period_type="annual",
   )
   ```
3. **Persist the computed verdict** as a `FundamentalDataVerification` row using the same field shape as `_upsert_verification` (`status`, `reason`, `failed_checks_json`, `warnings_json`, `offending_metrics_json`, `tieout_report_json`, and the `snapshot.coverage_json["data_verification"]` mirror). Factor `_upsert_verification` into a shared helper importable by both the script and the service, rather than copying it.
4. **Then gate** exactly as the existing branch does: if `report.status == "data_unverified"`, fall through to `_persist_data_unverified_nr(...)` (`:4362`) with `reason=report.reason`. Otherwise continue to the normal ensemble.

Net effect: every canonical recompute produces and stores a verdict; an unverified vintage can no longer be silently rated. MNG (and any other T-failing canonical vintage) flips to NR with `fair_value_base=NULL`, `target_price=None`.

### §3a — Close the promotion window (read-path safety net) — REQUIRED
Recompute alone is not sufficient, because **canonical promotion is fully decoupled from recompute**. `refresh_canonical_snapshot_flags` (`fundamentals.py:1804`) flips `is_canonical` to whichever vintage `_resolve_canonical_snapshot_rows` prefers, and **does not recompute or verify**. So the pointer can move to an old vintage whose ensemble was computed days earlier and never gated — the cible is then served from a stale, unverified ensemble with no fresh compute (observed live: 72/73 canonical ensembles carry a 2-day-old `computed_at` while the canonical set has churned). This is exactly why the silently-rated set grew over time.

Add a **read-path gate** so a missing verdict can never be rated, independent of recompute timing. In `derive_recommendation` / `derive_research_overlay` (`fundamentals.py:359` / `:557`): when the canonical import+year has **no** `FundamentalDataVerification` row, treat the name as **not-yet-verified → NR** (do not fall through to a rating). Concretely, `derive_research_overlay` already computes `verification` for the canonical import; extend `_data_unverified_reason` handling so `verification is None` ⇒ `recommendation="NR"`, `target_price=None` with a distinct reason token (e.g. `verification_pending`) so it's auditable and distinguishable from a real `data_unverified` failure.

Preferred: also have `refresh_canonical_snapshot_flags` enqueue/trigger `recompute_symbol_valuations_all_scenarios` for any symbol whose canonical import changed, so the verdict is produced at promotion time rather than relying on the read-path fallback. The read-path gate is the floor; the promotion-trigger is the fix.

**Idempotency / safety:**
- Do not overwrite a row whose provenance shows a curated correction or `force_status` (those come from `remediate_fundamentals`). Only auto-create when absent, or update only auto-generated rows. Guard on a provenance/source marker so a manual `data_unverified` verdict is never silently flipped to `verified` by an auto recompute.
- Use the same upsert key `(import_id, symbol, statement_year)` as `_upsert_verification` to avoid duplicate rows.

---

## §4 Frontend gate — NR must never display a leaked cible

Even after §3, the UI still resurrects a target for NR names via the fallback chain. Fix both leaks so an NR name shows no objectif:

- `signal-fundamental-view.tsx:1931` — `officialTargetPrice` must **not** fall back to `ensemble.fair_value_base` when `recommendation === "NR"`.
- `signal-fundamental-view.tsx:2176` — same: gate the `?? detail.ensemble?.fair_value_base` fallback on `recommendation !== "NR"`.

Concretely: compute `const ratable = (detail?.recommendation ?? row?.recommendation) !== "NR"` and only use the `fair_value_base` fallback when `ratable`. When not ratable, `targetPrice`/`fairValue` resolve to `null` and the existing "pas de recommandation valorisation exploitable" copy (`:2200`) renders. (Add a one-line caption near the per-model table: *« Objectif = médiane des classes de méthodes, pas moyenne des modèles. »* to remove the recurring "headline ≠ row average" confusion.)

---

## §5 Acceptance criteria + validation

**Run before/after the change (resolve via `is_canonical`).**

- **AC1 — no unverified canonical ratings.** After a full recompute, **0** canonical names have a non-null `fair_value_base` *and* no `FundamentalDataVerification` row for their canonical import+year. (Today: 52.)
- **AC2 — MNG is NR.** MNG canonical resolves to `recommendation = "NR"`, `target_price = NULL`, `fair_value_base = NULL` (it fails T7).
- **AC3 — no auto-overwrite of curated verdicts.** Any verification row carrying curated-correction/`force_status` provenance is unchanged after recompute (add a test).
- **AC4 — frontend.** For an NR detail payload, the rendered objectif is empty (unit/RTL test on `ResearchTicket`/thesis block).
- **AC5 — tests green.** `python -m pytest core/tests/ -q` and the touched `services/api/tests/` (extend `test_canonical_snapshot.py` / `test_remediation.py` with a "canonical import lacks verification → recompute computes it → NR" case).

**Validation SQL (the AC1 probe — must return 0 after):**
```sql
WITH canon AS (SELECT symbol, import_id, latest_statement_year y
               FROM fundamental_latest_snapshot WHERE is_canonical=true)
SELECT count(*)
FROM canon c
JOIN fundamental_ensemble_result e
  ON e.import_id=c.import_id AND e.symbol=c.symbol AND e.scenario='base'
LEFT JOIN fundamental_data_verification v
  ON v.import_id=c.import_id AND v.symbol=c.symbol AND v.statement_year=c.y
WHERE v.symbol IS NULL AND e.fair_value_base IS NOT NULL;
```
Report the before/after count and the per-name list of any name whose recommendation flips to NR (expected: the T-failing subset of the 52).

---

## §6 What NOT to do

- Do **not** fix this by editing the data of the 52 names — that is brief 45 (re-ingestion). This brief makes the *gate* fire; names with genuinely good data stay rated, names with bad data become NR.
- Do **not** loosen any tie-out check, threshold, or `BLOCKING_TIEOUT_CHECKS` to make more names pass. Verification logic (brief 38) is out of scope and must be unchanged.
- Do **not** touch the valuation math (midcycle, outlier rejection, combiner) — that is brief 44. If you run brief 44 and 50 together, land 50 first so brief 44's scorecard is measured on gated names only.
- Do **not** change `derive_recommendation` thresholds or `MIN_USABLE_MODELS_FOR_RATING`.
- Do **not** auto-flip an existing manual `data_unverified` verdict to `verified`.

---

## §7 Relationship to other briefs
- **Brief 38** built `build_data_tieout_report` and the NR gate. **This brief makes recompute actually call it** so the gate isn't bypassed by canonical-pointer desync.
- **Brief 41** expanded verification coverage via the remediation script. This brief removes the dependency on the script being run per-import by making recompute self-verifying.
- **Brief 44** fixes valuation bias on rated names. Order: **50 before 44.**
- **Brief 45** re-ingests official documents for names that fail tie-out. After 50, that failing set is the authoritative NR list to feed 45.
