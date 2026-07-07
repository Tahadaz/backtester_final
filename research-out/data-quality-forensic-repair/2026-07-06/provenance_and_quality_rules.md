# Provenance & Automated Data-Quality Rules (Phases 12-13)

## Provenance: what the schema already carries (confirmed, not built new)

`fundamental_annual_metric`: `import_id, symbol, statement_year, metric_name, metric_value, raw_metric_name, is_proxy, as_of_date, source_document_id`.
`fundamental_source_document`: `id, import_id, symbol, company_name, document_title, source_url, publication_date, fiscal_year, period_type, period_label, period_end_date, status, document_kind`.
`fundamental_import`: `id, data_source, status, filename, created_at, annual_metric_count`.

This is enough to trace almost every field the audit brief asks for: source type (`fundamental_import.data_source`), source document/URL/date (`fundamental_source_document`), original vs normalized value (`raw_metric_name` holds the original label; `metric_value` is post-normalization — but the original *unvormalized* numeric value before any unit conversion is generally not separately retained, since normalization mostly happens at parse time in `stockanalysis_provider.py`/`workbook.py` rather than being logged as a transform step). **Missing**: an explicit `confidence`/`trust_status` column and an explicit `conflict_status` column — conflicts are detectable by querying for duplicates (as this audit did) but not flagged in-place on the rows themselves.

## Repairs made this session are provenance-preserving, explicit, and reversible

- REB: mis-tagged documents marked `status='mismapped'` (not deleted) — preserves the record that they were once attributed to REB and why.
- EnterpriseValue: repaired rows tagged `raw_metric_name='REPAIR_2026-07-06_ev_recompute'` — anyone querying the table can see exactly which rows were touched and by which repair.
- demo_fixture: rows deleted outright (not preserved) — justified because they were never real data (synthetic test fixtures), so there is no "original economic value" to preserve provenance of; the deletion itself is documented in this audit trail and the repair script (`scripts/repair_2026_07_data_quality_forensic.py`) is the permanent, versioned record of what was removed and why.
- All three repairs are reproducible: `scripts/repair_2026_07_data_quality_forensic.py --dry-run` (default) shows exactly what would change before `--apply` commits it.

## Automated data-quality rules added (Phase 13)

`core/tests/test_data_quality_regressions.py` — 4 tests, all passing against the live repaired DB:

1. **Entity resolution**: no `fundamental_annual_metric` rows sourced from a `demo_fixture`/`test_fixture`/`synthetic` import.
2. **Substring-mismap guard**: no active (`status='succeeded'`) REB-tagged source document whose `company_name` doesn't contain "rebab" — a narrow, deterministic re-check of the confirmed instance, not a general fuzzy-alias validator (see "not done" below).
3. **EV construction guard**: no un-tagged `EnterpriseValue` row still matches the `Total_Debt - Cash` pattern where a `MarketCap_Calc` was actually available (i.e., no *new* instance of the same bug, and the 2,168 repaired rows are excluded via their repair tag so the test isn't vacuously trivial).
4. **Negative-book-equity bound check**: fails loudly if the set of negative-book-equity symbols grows past 10 (baseline is 4) without investigation — a sanity tripwire, not a strict invariant, since negative book equity is sometimes genuinely correct.

`core/tests/test_panel_deterministic_resolution.py` — 4 tests covering the resolver (see `deterministic_resolution_policy.md`).
`core/tests/test_characteristic_study.py` — 2 new tests (negative book equity exclusion, financial-sector CF/P exclusion) added to the existing suite.

Run all of them: `python -m pytest core/tests/test_data_quality_regressions.py core/tests/test_panel_deterministic_resolution.py core/tests/test_characteristic_study.py -v` — **10/10 passing**.

## Not done this session (explicitly out of scope)

- A general substring-collision scanner across every ticker/company-name pair (only REB's confirmed instance is guarded; the brief's request to check every 2-3 letter ticker for the same collision risk was not executed as an automated rule, only manually spot-checked for MIC/Microdata in the original audit).
- Market-cap price×shares reconciliation as an automated test (the SAH ~29.3x issue was found manually via P/B cross-check, not via a generic "detect implausible scale jumps" rule — building that generic rule would require picking a threshold that doesn't also flag genuine small-caps like REB, which was not attempted).
- Sector-applicability automated checks (e.g., asserting EBITDA/EV is null for banks) — not implemented since the sector-applicability work itself (Phase 8) is only partially complete (see `sector_accounting_applicability.md`).
