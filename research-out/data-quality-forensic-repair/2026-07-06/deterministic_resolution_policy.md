# Deterministic Duplicate Resolution Policy (Workstream 1)

## What was actually nondeterministic

`core/quant_core/fundamentals/cross_section/panel.py:_latest_metric_map` (the function that resolves competing metric rows across independently-sourced imports — workbook, stockanalysis, bvc — into the single value the PIT panel uses) tie-broke on `(availability_date, statement_year)` with `>=`. When two rows shared identical `availability_date` and `statement_year` (common — many rows across imports carry the same fallback-computed availability date), the winner was whichever row happened to come **last in the input list**, which reflected DB/SQL row order, not any source-quality judgment. This is exactly the mechanism that let the ATW/IAM demo_fixture contamination (see `duplicate_conflicts.md`) silently win in the live panel.

`core/quant_core/fundamentals/workbook.py:_select_best_latest` is a separate, narrower resolver (dedupes rows *within one Excel workbook*, not across imports) and was already deterministic given a fixed workbook row order — it just uses the opposite comparison operator (`>` vs panel.py's `>=`). Left as-is; documented as a style inconsistency, not a bug, since it never resolves cross-source conflicts.

## The fix (implemented, tested)

`panel.py:_metric_resolution_key` — an explicit, total-order sort key:

```
(availability_date, statement_year, has_linked_source_document, source_document_id)
```

`_latest_metric_map` now sorts the candidate rows by this key before resolving, so the winner is a pure function of the key values, never of input order. Priority, in order:
1. Later availability date wins (more current information).
2. Later statement year wins (as before).
3. **New**: a row traceable to a real filing (`source_document_id` set) beats an untraceable row with the same date/year.
4. **New**: among two traceable rows, the higher `source_document_id` wins (a deterministic, if arbitrary, final tie-break — since document ids are assigned serially at ingestion, this favors the most recently registered filing record).

This does **not** attempt a full accounting-context hierarchy (restated vs original, consolidated vs standalone, source-type ranking) — see "Not done" below. It solves the specific, confirmed problem: cross-import ties silently depending on row order.

## Tests

`core/tests/test_panel_deterministic_resolution.py` — 4 tests, all passing:
- `test_prefers_row_with_linked_source_document_on_exact_date_tie`
- `test_resolution_is_independent_of_input_order` (shuffles input 20x with a fixed seed, asserts identical winner every time)
- `test_later_availability_date_wins_over_source_document_presence`
- `test_does_not_leak_future_availability_rows` (regression guard on the existing PIT cutoff behavior)

Also ran the full existing `panel`/`sfc`/`bakeoff`/`characteristic`/`ic_study` test selection (34 tests) post-change — all pass, no regression.

Run: `python -m pytest core/tests/test_panel_deterministic_resolution.py core/tests/ -k "panel or sfc or bakeoff or characteristic or ic_study" -q`

## What this does NOT do (explicitly out of scope this session)

- **Source-type hierarchy** (bvc > workbook > stockanalysis, etc.): deliberately *not* encoded as a blanket rule, because the audit found source reliability is metric- and symbol-specific, not universal — `workbook` was wrong for SAH market cap and for the EnterpriseValue formula, but is fine for most other symbols/metrics; `bvc` was wrong for REB specifically due to mis-tagged documents (now fixed), not a generic bvc-source problem. A blanket hierarchy would have been the "one simplistic hierarchy that ignores accounting context" the audit brief explicitly warned against. The `source_document_id`-presence tie-break implemented here is a proxy for "traceable to a real filing," which is a safer signal than a source-type label.
- **Restated vs original, consolidated vs standalone**: the schema carries the fields to do this (`fundamental_source_document.period_type`, `document_kind`) but no restatement/consolidation-scope metadata is currently populated distinctly enough to build a reliable rule from it this session — flagged as unresolved, Category I.
- **Negative book equity / interim vs annual as a resolver concern**: these are handled in the canonical B/M definition (`bm_canonical_definition.md`), not the row-level resolver, since they are about which computed ratio to trust, not which raw row wins.
- **Full deterministic resolver for the 1,591 remaining factor-critical conflicts**: `_latest_metric_map`'s new tie-break makes the *panel construction* deterministic and demonstrably fixes the ATW/IAM case; it does not retroactively re-derive the economically correct value for the ~20 symbols flagged in `duplicate_conflicts.md` with scale-mismatch/sign-flip factor-critical conflicts (RIS, M2M, MDP, SRM, CAP, IMO, LES, SBM, SMI, SNP, WAA, and 10 others with 1 each) — those remain Category I / unresolved pending the same document-level tracing done for REB/SAH/SBM.
