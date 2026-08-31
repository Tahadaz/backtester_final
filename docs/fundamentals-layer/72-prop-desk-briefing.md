# Prop-desk briefing: fundamental value strategy

**Recommendation for 2026-08-31:** do not allocate live or paper capital to the current model. Approve a controlled rebuild of one deterministic B/M candidate.

## The 60-second statement

“The app contains promising value research, but it is not production-ready. I found and repaired a critical formula defect: the old B/M denominator could keep a filing-era market cap fixed while price moved; v2 now uses only decision-date close times verified PIT shares. I also made filing availability strict, exactly linked 194 StockAnalysis metric rows to official Bourse evidence, and recovered six missing document dates from the official publication archive without overwriting conflicts. The old performance remains withdrawn because the effective-share/corporate-action history, PIT universe, total returns, executable fills, liquidity rules, and calibrated costs are still incomplete. Authorization therefore remains fail closed. I am asking for a controlled rebuild and shadow-validation programme, not capital.”

## What survives

- The economic B/M hypothesis is well established and worth testing locally.
- The candidate is explainable and deterministic: positive as-published group-share book equity divided by price times effective shares outstanding, ranked within the genuinely investable PIT universe.
- The old SFC composite does not survive as a production candidate.
- CF/P remains research only until cash-flow mappings and issuer applicability are resolved.
- No random input, fitted blend, forecast, or opaque score is needed in the production candidate.

## Why the answer is no-go

| Blocker | Desk impact |
|---|---|
| Withdrawn v1 market-cap denominator | The code is fixed in v2, but every old performance result must be rerun. |
| Incomplete observed publication history | V2 rejects fallback rows; unmatched history does not receive an assumed date. |
| Corrected extracts instead of immutable vintages | Restatements and later corrections can leak into historical decisions. |
| Unverified historical universe | Survivorship and missing-security bias are unresolved. |
| Uncertified `Close` and price-only MASI | Strategy and benchmark are not verified total-return series. |
| Execution lag configured but unused | Backtest prices are not demonstrated attainable fills. |
| No ADV/capacity rule and material name/sector concentration | The portfolio may not be executable or diversified. |
| Unsupported 33 bps cost convention | Net returns are not desk-calibrated. |
| Short, reused, dependent sample | The reported confidence is overstated and not independent. |
| No reconciled shadow trading or OMS controls | There is no safe research-to-orders boundary. |

## What changed in the app

- A versioned readiness policy lists explicit evidence and remediation for every gate.
- `live_trading_authorized` is `false` unless all gates pass.
- The snapshot API returns the readiness report and blocker identifiers.
- The dashboard displays **LIVE INTERDIT** alongside the research label.
- Tests verify that one failed or missing gate prevents authorization.
- Structural Value v2 ignores stored workbook market cap and exposes close, shares, book equity, and source-document provenance per signal row.
- The Bourse archive parser preserves only observed dates; an invalid or missing date is not replaced with today.
- The archive crawl is bounded by new official document identities, requires verified TLS for writes, and records the archive URL/match method. It filled six missing dates; four conflicts and six ambiguous filenames remain quarantined.
- Exact reconciliation applied 194 links across 38 issuers; a repeat audit made zero changes.
- The strict 2026-05-31 cross-section now has 20 B/M-eligible issuers out of 66 rows, not fabricated full-universe coverage.
- Fundamental IC inference now uses deterministic Newey-West HAC rather than a random bootstrap.
- Undated Bourse price rows are rejected, and raw close is no longer mislabeled as adjusted close.
- V2 snapshot recomputation rejects the old 33 bps convention unless the desk supplies both an explicit cost and its approved source.

This is a formula, lineage, and control repair; it is not a claim that the missing historical data or model validation has been completed.

## The desk ask

Approve scope and ownership for:

1. official filing/publication-vintage capture;
2. effective-dated shares, corporate actions, listings, suspensions, and delistings;
3. verified security and benchmark total returns;
4. desk execution, liquidity, capacity, concentration, and cost rules;
5. a frozen B/M rerun with trial accounting, HAC/non-overlapping inference, and one locked holdout;
6. independent model-risk review followed by reconciled shadow trading.

Do not approve capital, a Sharpe claim, or a production date tomorrow.

## Likely questions

**“But the reported Sharpe is strong—why not start small?”**

Because the denominator defect changes the historical signal itself. Position size does not cure invalid evidence.

**“Did you replace stored market cap with price times shares?”**

Yes, in Structural Value v2, and the system fails closed when verified PIT shares are unavailable. What remains is certifying the historical effective-share and corporate-action ledger before rerunning performance.

**“Is the model random?”**

The proposed production signal is deterministic. The fundamental IC study's primary inference is now deterministic Newey-West HAC; random resampling is not part of the signal or release decision.

**“Is value investing rejected?”**

No. The B/M hypothesis survives as the only first reconstruction candidate. The current implementation and evidence are rejected for deployment.

**“When is it ready?”**

When all evidence gates pass and independent owners sign the exact code/data/model versions—not on a date chosen in advance.

Full audit: [Fundamental factor model: prop-desk production-readiness review](71-prop-desk-production-readiness.md).
