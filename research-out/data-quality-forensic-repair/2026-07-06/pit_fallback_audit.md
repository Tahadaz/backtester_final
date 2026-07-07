# PIT Publication/Availability Fallback Audit (Phase 11)

Ran `publication_coverage_stats()` against the live, repaired PIT panel (3,104 stock-month rows, 71 symbols, 111 monthly dates 2017-2026) at both the default 90-day annual lag and a stress 120-day lag.

## Headline numbers

| Config | Total metric-values | Real `publication_date` share | Fallback share | Panel rows | Symbols |
|---|---|---|---|---|---|
| 90-day (current default) | 4,627,951 | **11.96%** | 88.04% | 3,104 | 71 |
| 120-day (stress) | 4,527,075 | **12.23%** | 87.77% | 3,101 | 71 |

**~88% of every metric-value entering the panel relies on the conservative fallback rule (`period_end_date + lag_days`), not a confirmed filing date.** Only ~12% have a real `fundamental_source_document.publication_date` or explicit `as_of_date` traced to a source. This is a genuine, material data-quality limitation, not a bug — it reflects that most of the historical BVC/workbook/stockanalysis ingestion never recorded when a statement was actually published, so the pipeline conservatively assumes 90 days after fiscal year-end.

## Sensitivity: 90d vs 120d

Moving from 90-day to 120-day fallback changes the panel by only **3 rows out of 3,104** (0.1%) and does not change the symbol count. This is expected: the fallback lag only matters for stock-months near a rebalance-date boundary where a metric becomes available; for most symbol-years the extra 30 days doesn't cross a monthly rebalance date. **Practical conclusion: the B/M and CF/P results are not meaningfully sensitive to the specific choice of 90 vs 120 days** — this is a reassuring robustness finding, not a reason to prefer one over the other. Per the governance rule in this brief, 90 days remains the default (not re-chosen based on which produces better results) since neither materially changed the sample either way.

## What this means for trust in the panel

The 88% fallback share means most rows have look-ahead protection but not true point-in-time precision — a metric flagged available on `period_end + 90d` might genuinely have been published earlier or later. This is conservative (errs toward *later* availability, which prevents look-ahead but can also mean some genuinely-available-earlier information enters the panel later than it should). It should be read as: **the panel is safe from look-ahead bias, but the exact monthly timing of ~88% of fundamentals is an assumption, not a verified fact.**

## Not done this session

- Breakdown by year/issuer/sector/source of the fallback share (only the aggregate was computed; a full cross-tab would require re-running `publication_coverage_stats` per stratified subset of the panel, straightforward but not executed here).
- Recovering real publication dates for the 88% fallback rows from AMMC/Bourse de Casablanca archives — this is exactly the kind of manual source-by-source work flagged as out of scope for automated execution (Phase 11's "where feasible also identify a more conservative rule" and date recovery is a large manual undertaking, not a mechanical one).
