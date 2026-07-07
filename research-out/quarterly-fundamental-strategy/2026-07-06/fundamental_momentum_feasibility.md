# Fundamental Momentum Feasibility Audit ONLY (Phase 13)

No new factor built or backtested this session, per instruction — feasibility classification only, based on the semantics established in Phases 1-2.

| Candidate signal | Classification | Reasoning |
|---|---|---|
| ΔRevenue (quarter-over-quarter or YoY) | **Feasible now**, for a subset | Revenue is confirmed standalone-quarter (`cumulative_ytd_audit.md`), with 29 symbol-years of complete Q1-Q4 coverage — enough for a real, if not universal, feasibility test in a future study. |
| ΔNetIncome / earnings acceleration | **Feasible now**, for a subset | Same standalone-quarter confirmation, same 29 symbol-year coverage as Revenue. |
| ΔMargin (operating or net) | **Feasible after mapping repair** | Depends on both Revenue (clean) and Operating_Income/EBIT, which the prior session's `field_mapping_audit.md` already flagged as having a sector-specific caveat (EBIT vs "Resultat_Exploitation" not strictly identical) — usable but inherits that unresolved ambiguity. |
| ΔROA | **Feasible after mapping repair** | Depends on NetIncome (clean) and Total_Assets — Total_Assets' quarterly standalone-vs-point-in-time status was not separately audited this session (it's a balance-sheet item like book equity, so likely fine as a snapshot, but not independently confirmed the way Capitaux_propres was). |
| ΔLeverage (debt/assets change) | **Feasible after mapping repair** | Both Debt and Assets are balance-sheet snapshots (no cumulative-YTD risk), but neither's quarterly coverage breadth was independently verified this session — flagged, not confirmed. |
| ΔCFO / cash-flow acceleration | **Not feasible / too sparse** | Per `ttm_cfp_construction.md`, no symbol-year has complete standalone Q1-Q4 CFO; the underlying filings are semiannual, not quarterly, for cash flow specifically. A ΔCFO signal would need to be built on H1-vs-H1 (YoY) or H1-vs-H2 (sequential) comparisons instead of a quarterly cadence — feasible in principle at that coarser frequency, not attempted here. |

## Conclusion

A **future, properly-scoped fundamental-momentum study is feasible** for Revenue- and NetIncome-based deltas at quarterly frequency (subject to the same ~29-symbol-year coverage constraint that limits sample size), and for CFO-based deltas only at semiannual frequency. Margin/ROA/leverage deltas are feasible in principle but inherit existing, unresolved field-mapping ambiguities that should be resolved first. This audit does not itself constitute evidence that any of these signals predict returns — that is explicitly out of scope for this task.
