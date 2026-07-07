# Quarterly Data Semantics (Phase 1)

Inspected `fundamental_period_metric` directly (142,458 rows, 73 symbols, `period_type` in `annual`/`semiannual`/`quarterly`, `period_label` in `FY/H1/H2/S1/S2/Q1/Q2/Q3/Q4`). Nothing inferred from column names alone — every claim below is a traced, computed check against actual values.

## Coverage by field (distinct symbols with any quarterly/semiannual observation)

| Field | Distinct symbols | Rows |
|---|---|---|
| Capitaux_propres (book equity) | 72 | 905 |
| Total_Equity | 70 | 684 |
| Shares_Outstanding | 70 | 704 |
| NetIncome | 70 | 704 |
| Revenue | 64 | 652 |
| Operating_Cash_Flow | 56 | 426 |
| EBITDA | 62 | 527 |

Broad nominal coverage (56-72 of 73 symbols have *some* quarterly-or-semiannual row for these fields) — but nominal row presence is not the same as usable, standalone-period, PIT-safe data; see `cumulative_ytd_audit.md` and `information_refresh_analysis.md`.

## Is book equity (B/M's numerator) cumulative or standalone?

**Neither concept applies** — book equity is a balance-sheet snapshot (a stock, not a flow), so every quarterly `Capitaux_propres` observation is, by construction, the correct point-in-time balance as of that quarter-end. There is no "cumulative YTD" risk for balance-sheet items at all. This substantially simplifies Phase 4.

## Is CFO/Revenue/NetIncome (flow items) cumulative or standalone?

See `cumulative_ytd_audit.md` for the systematic check — **standalone**, not cumulative, confirmed by summing Q1-Q4 against the independently-ingested FY figure.

## Publication-date availability

67,349 of 142,458 rows (47%) have a linked `fundamental_source_document.publication_date`. Of those, a large fraction are not genuine filing dates — see `quarterly_pit_audit.md`.
