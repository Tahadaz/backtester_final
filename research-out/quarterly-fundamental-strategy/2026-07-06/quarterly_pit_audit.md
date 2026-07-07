# Quarterly PIT Availability Audit (Phase 3) — attempted falsification

## Finding: `publication_date` is not always a genuine filing date

402 of 3,183 `fundamental_source_document` rows (12.6%) have `publication_date == created_at::date` — the tell-tale sign of a default-to-ingestion-timestamp fallback when no real per-statement date was extracted. Concentrated in `"StockAnalysis interim financial tables - Balance/Income/Cash Flow"` (70 rows each) and `"StockAnalysis H2 derived from FY minus H1"` (122 rows). A cluster of 196 of these rows share the **exact identical timestamp** `2026-06-04 21:15:30.640734Z` across unrelated symbols (TMA, DYT, MOX, BCP, CTM, OUL, MDP, GTM, ...) and fiscal years spanning 2021-2024 — conclusively a single bulk-ingestion batch, not 196 companies coincidentally publishing interim statements on the same calendar date years apart.

## Is this a look-ahead violation?

**No, not in the direction that matters.** `panel.py:availability_date()` uses `publication_date` when present; for these rows the fake date (~2026) is far *later* than the true availability (the periods are mostly 2020-2024), so the panel treats this data as available later than it truly was — conservative, not dangerous. Attempted falsification of PIT safety: could not produce a case where this pattern causes a metric to appear in the panel before its true real-world availability.

## What it does corrupt: information-refresh / genuine-event timing

If a burst of years-old CFO/EBITDA/Revenue figures all get stamped with an identical mid-2026 "publication_date," any analysis asking "when did genuinely new information arrive" would misread this as a cluster of fresh filings landing on one day — a spurious information event, not a real one. This directly matters for `information_refresh_analysis.md` (Phase 6).

## Fix implemented (opt-in, not retroactively applied to prior reported results)

`core/quant_core/fundamentals/cross_section/quarterly_pit_audit.py::is_trustworthy_publication_date()` — flags a publication date as untrustworthy if the document title matches the known scrape patterns, or if `publication_date == created_at` date. 5 tests pass (`core/tests/test_quarterly_pit_audit.py`).

**Deliberately not wired into `panel.py`'s shared `availability_date()` this session** — doing so would silently change the PIT panel that all of this session's and the prior sessions' IC/strategy numbers depend on, without a full rerun and re-report of those numbers, which is out of scope ("do not restart the data audit," "do not reopen broad factor discovery"). This is flagged as the top concrete repository follow-up: wire the detector into `panel.py`, rerun the characteristic study, and re-verify whether any previously-reported IC/strategy number changes materially.

## Quantified real-vs-fake publication-date coverage

Of 67,349 period-metric rows with any linked publication_date, 52,671 (78.2%) share the single suspicious date `2026-06-04` alone. The previously-reported "12% real publication date coverage" figure from the prior session's `pit_fallback_audit.md` (which covered annual data only) is a different, separately-computed number and not directly restated here, but this finding suggests genuine per-filing publication-date coverage for the *quarterly/interim* layer specifically is meaningfully lower than the raw non-null count implies.
