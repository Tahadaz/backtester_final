# Cumulative-YTD Audit (Phase 2)

Systematic check: for every (symbol, fiscal_year) with all four `Q1/Q2/Q3/Q4` rows present AND an independently-ingested FY figure in `fundamental_annual_metric`, computed `sum(Q1..Q4) / FY`. If quarters were cumulative YTD (Q4 alone ≈ FY), this ratio would be far above 1 (roughly 2.5x, since Q1+H1+9M+FY-style cumulative summing quadruple/quintuple-counts). If quarters are standalone, the ratio should be ≈1.0.

| Field | N symbol-years (all 4 quarters + FY) | Median sum(Q1-4)/FY | Mean |
|---|---|---|---|
| Revenue | 29 | **1.000** | 0.979 |
| NetIncome | 29 | **1.000** | 0.988 |
| EBITDA | 4 | **1.001** | 1.001 |
| Operating_Cash_Flow | 0 | — (no symbol-year has all 4 quarters) | — |

**Verdict: Revenue, NetIncome, and EBITDA quarterly rows are genuine standalone quarters, not cumulative YTD.** No `Q2 = H1 - Q1`-style reconstruction is needed or safe to force where it isn't already the native semantics — summing them directly is correct. Confirmed independently for ATW 2023 (Q1 6.63B + Q2 5.646B + Q3 7.059B + Q4 6.626B = 25.961B vs FY 25.962B, effectively exact).

## Operating_Cash_Flow: no complete standalone-quarter symbol-year exists

Zero symbol-years have all four `Q1-Q4` CFO rows simultaneously. Cash-flow statements in this market/dataset are predominantly reported **semiannually** (H1/H2), not quarterly — this is a genuine reporting-frequency characteristic of the underlying filings, not a pipeline defect. See `ttm_cfp_construction.md` for the direct consequence.

## H2 = FY − H1 reconstruction already exists in the pipeline

Found 122 `fundamental_source_document` rows titled `"StockAnalysis H2 derived from FY minus H1"` — the ingestion pipeline **already performs** exactly the kind of standalone-period reconstruction the brief describes, for stockanalysis-sourced semiannual data specifically. This was not built this session; it pre-exists and was discovered during the audit. Its PIT-dating is compromised, however — see `quarterly_pit_audit.md`.

## Duplicate/carry-forward rate (distinct from cumulative-YTD)

Checking consecutive same-fiscal-year period pairs (quarterly + semiannual combined) for exact-duplicate values (a sign of stale carry-forward rather than genuine new-period data): Revenue 7/346 (2.0%), EBITDA 7/257 (2.7%), NetIncome 7/370 (1.9%), Operating_Cash_Flow 6/207 (2.9%), Capitaux_propres 20/538 (3.7%), Total_Equity 6/355 (1.7%). All low (under 4%) — not a systemic duplication problem once semiannual rows are included (an earlier, narrower check restricted to `period_type='quarterly'` only found CFO 100% duplicated, but that was an artifact of looking at an unrepresentative 13-row/3-symbol slice — the correction is documented here for transparency).
