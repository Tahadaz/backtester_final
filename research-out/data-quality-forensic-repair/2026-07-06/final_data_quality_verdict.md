# Final Data Quality Verdict (complete — Workstreams 1-3, 2026-07-06)

Supersedes the interim verdict written earlier in this audit (Phase 1-6 only). This version covers the full nine-task scope: pipeline reconstruction, REB/SAH/SBM forensics, the universe-wide EV bug, the full duplicate catalogue, the deterministic resolver, field mapping/sector applicability, canonical B/M and CF/P definitions, the PIT fallback audit, provenance/data-quality tests, and the downstream research rerun.

## 1. Is duplicate resolution now deterministic?

**Yes, for the cross-import panel resolver** (`panel.py:_latest_metric_map`), which is the consequential one — it resolves competing values across independently-sourced imports (workbook/stockanalysis/bvc), and this is exactly where the ATW/IAM demo_fixture contamination won by row-order accident. Fixed with an explicit sort key (`availability_date`, `statement_year`, source-document presence, source-document id) and proven order-independent by test (`test_resolution_is_independent_of_input_order`, 20 shuffles, identical winner every time). The narrower `workbook.py:_select_best_latest` (dedup within one Excel file) was already deterministic given fixed input order; left as-is with the tie-break-convention inconsistency documented, not fixed, since it never resolves cross-source conflicts.

## 2. How many material conflicts exist?

10,439 conflicting `(symbol, statement_year, metric_name)` groups (post-repair). 1,591 involve factor-critical metrics.

## 3. How many were resolved?

3,475 are harmless (values agree within 0.1%, any candidate is safe) — auto-resolved by construction. Three concrete, root-caused bugs were fully repaired in the live DB: REB document mis-mapping (260 rows deleted, 190 documents quarantined), the EnterpriseValue net-debt-only bug (2,168 of 2,273 flagged rows recomputed), and demo_fixture contamination (all rows from 2 synthetic imports deleted, affecting ATW/BOA/IAM/MNG/TQM).

## 4. How many remain unresolved?

6,964 conflicting groups remain unresolved at the generic level (Category I) — flagged, logged, not guessed. Of these, ~20 symbols have scale-mismatch or sign-flip conflicts specifically on factor-critical metrics (RIS, M2M, MDP, SRM, CAP, IMO, LES, SBM, SMI, SNP, WAA, and 10 others) that would need the same document-level forensic depth as REB/SAH/SBM to close — not performed this session. SAH's workbook-sourced market cap (~29.3x scale error) also remains unresolved/excluded-by-recommendation rather than repaired, since the exact bad source cell was never pinned down. 105 EnterpriseValue rows remain unresolved for lack of an available market cap (correctly left alone).

## 5. Are there additional systemic mapping bugs?

**Yes, one newly found this session, not in the original brief**: `net_income`'s alias list mixes consolidated total net income and group-share (RNPG) net income with no preference rule — affects ROE, ROA, earnings yield for any issuer with material minority interests. Documented in `field_mapping_audit.md`, **not repaired** this session (needs a scan of how many symbol-years are actually affected first).

## 6. Is B/M now defined consistently everywhere?

**Yes**, in the two places it's independently computed (`characteristic_study.py`, `methodology_bakeoff.py`) — the negative-book-equity inconsistency (the specific issue named in the original brief) is fixed: both now exclude negative book equity rather than one excluding and one signing it. `final_model_validation.py` inherits this automatically since it consumes `characteristic_study.py`'s output rather than recomputing. Regression test added and passing.

## 7. Is CF/P now defined consistently everywhere?

**Yes for where it's computed** — only `characteristic_study.py` computes a standalone CF/P signal; `methodology_bakeoff.py` never had one to reconcile against. Financial-sector exclusion implemented and tested.

## 8. Is CF/P economically valid for financial firms?

**No, and it is now excluded for them** (bank/insurance archetype) — confirmed 0 financial observations in the post-fix CF/P coverage (566 financial observations remain excluded that would otherwise have been included). **Known gap**: the exclusion uses the narrower bank/insurance-only `is_financial` flag, not the broader leasing/financing definition used elsewhere in the codebase — leasing/financing names (MAB, EQD, SLF, MLE) are not yet excluded. Flagged, not silently claimed complete.

## 9. How dependent are results on 90-day fallback?

**Very high reliance on the fallback mechanism itself** (88% of all metric-values in the panel use the 90-day fallback date, not a confirmed publication date) but **low sensitivity to the specific 90-vs-120-day choice** (only 3 of 3,104 panel rows changed between the two configs). 90 days is kept as-is per the governance rule against choosing a fallback based on which produces better results.

## 10. What changes under 120-day fallback?

Panel size: 3,104 → 3,101 rows (-0.1%), same 71 symbols. B/M and CF/P IC were not separately recomputed under 120-day (not done this session, logged as a limitation).

## 11. Did B/M survive the repaired dataset?

**Yes.** 6m primary horizon: mean IC 0.170, HAC t-stat 3.45, FDR-significant, Tier 1. The isolated effect of the REB/ATW/IAM repairs on aggregate B/M IC was negligible (0.180 → 0.170 at 6m, actually a slight decrease; 12m rose slightly) — the repairs were necessary for correctness, not because they were propping up the headline result.

## 12. Did CF/P survive the repaired dataset?

**Yes.** 6m: mean IC 0.135, HAC t-stat 4.94 (higher than B/M's), FDR q=0.00002. Classified Tier 2 only because it fails a monotonicity gate, not because the IC/t-stat is weak.

## 13. Is CF/P still incremental beyond B/M?

**Yes.** Orthogonalized to B/M: 6m residual IC 0.109, t=3.57, p=0.0004. Orthogonalized to B/M+size+liquidity: 6m residual IC 0.079, t=3.69, p=0.0002. Both significant at every horizon from 3m-12m. Pairwise rank correlation with B/M is only 0.25 — they are not redundant.

## 14. Which previous research conclusions are invalidated?

None of the headline B/M or CF/P conclusions from prior work are invalidated by this repair — both survive with materially similar magnitude and significance. What *is* invalidated: any prior claim that treated REB's B/M, SBM's/ATW's/BCP's/BOA's/IAM's/MNG's/CFG's EBITDA/EV, or SAH's market cap as individually trustworthy — those specific stock-level numbers were wrong and are now either fixed (REB, EV-affected symbols) or flagged unreliable (SAH).

## 15. Which conclusions survive?

B/M as a Tier 1 factor; CF/P as a statistically significant, incrementally informative factor despite its Tier 2 classification; the overall finding that neither factor's aggregate significance was an artifact of the specific bugs found and fixed this session.

## 16. Is the data layer now trustworthy enough for a proper live-like strategy backtest?

**Not yet, for a full live-like backtest** — see classification below. It is trustworthy enough for continued factor-research (IC/HAC-style analysis), which is what was actually rerun and validated here.

## 17. What unresolved data risk remains?

- ~6,964 unresolved generic conflicts, ~20 symbols with unresolved factor-critical scale/sign conflicts, SAH's market cap unrepaired, the net_income consolidated-vs-group-share ambiguity unrepaired, the leasing/financing CF/P exclusion gap, no non-overlapping/bootstrap/leave-one-out robustness checks, no 120-day IC rerun, and — most importantly — this entire audit covered depth on 3 named symbols plus 2 systemic bugs found along the way; the other ~68 symbols were not given the same forensic depth. A single-session audit cannot certify a 73-symbol, 10-year panel free of all REB/SAH/SBM-style issues; it can only certify that the specific issues found were real, fixed, and did not appear to be propping up the headline factor results.

## Production-status classification

**B. DATA LAYER USABLE WITH EXPLICIT EXCLUSIONS**

Justification: the two most consequential, universe-wide bugs found this session (demo_fixture contamination of ATW/BOA/IAM/MNG/TQM, and the EnterpriseValue net-debt-only bug affecting 150 symbol-years) are fixed and verified. The three originally-named cases (REB, SAH, SBM) are two-thirds repaired and confirmed via real recomputation (REB, SBM) with the third (SAH) explicitly documented as unreliable and excluded-by-recommendation rather than silently trusted. B/M and CF/P both survive the repair with real, computed IC/HAC significance and CF/P's incrementality over B/M is confirmed. This falls short of (A) READY because ~6,964 conflicts remain unresolved, ~20 symbols have known unresolved factor-critical conflicts, non-overlapping/bootstrap robustness checks were not run, and only a narrow slice of the universe received full forensic depth — a live-like strategy backtest should explicitly exclude or flag SAH and the ~20 unresolved-conflict symbols until they receive the same depth of review as REB/SAH/SBM did here.
