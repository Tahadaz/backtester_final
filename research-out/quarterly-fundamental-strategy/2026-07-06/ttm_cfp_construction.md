# TTM CF/P Construction (Phase 5)

## Verdict: TTM CFO cannot be safely constructed — not enough standalone-quarter coverage to exist

Phase 2's audit found **zero symbol-years** with all four `Q1/Q2/Q3/Q4` Operating_Cash_Flow rows present simultaneously. The formula `TTM_CFO_t = Q_t + Q_{t-1} + Q_{t-2} + Q_{t-3}` requires four genuine, contiguous standalone quarters — this data simply does not exist at that granularity for any symbol in the current database. This is not a mapping bug to repair; cash-flow statements in this market/dataset are predominantly filed **semiannually** (H1/H2), a real reporting-frequency characteristic, not a pipeline defect.

## QC1 (current annual CF/P) vs QC2 (cumulative-CFO-annualized) vs QC3 (TTM)

- **QC3 (TTM CFO/market cap): not feasible.** Explicitly not forced, per the brief's instruction ("if TTM cannot be constructed safely for enough names, say so — do not force coverage").
- **QC2 (latest reported cumulative CFO annualized, e.g. `2 × H1_CFO` or `H2_CFO stated as already-annual-equivalent`)**: technically constructible given H1/H2 coverage exists for 56 symbols, but **not attempted this session** — it would require a fresh accounting-semantics decision (is doubling H1 a defensible full-year estimate given seasonality? Does a bank's or industrial's H1 cash flow generalize?) that wasn't validated, and given Phase 4/6 already show the *existing* CF/P signal is already benefiting from whatever quarterly/semiannual CFO blending the current resolver performs (same mechanism as B/M — the CFO alias resolution already picks up interim CFO rows when they're the latest PIT-available value), a bespoke QC2 annualization was judged not to add enough incremental value to justify the accounting-semantics risk in the time available.
- **QC1 (current annual CF/P)**: remains the canonical, already-validated definition from the prior session (`cfp_canonical_definition.md`) — retained as-is.

## Conclusion

CF/P is left as currently canonically defined (QC1). No new quarterly/TTM CF/P variant is introduced this session — this is a deliberate, evidence-based "say so, don't force it" outcome per the brief's own instruction, not an oversight.
