# 44 — Systematic downward-bias remediation (engine-side), implementer: Sonnet

> **Status.** Plan-only. No code changed by the author of this plan. **Supersedes the premise of brief 43.** Brief 43 assumed mid-cycle normalization "only feeds multiples, not intrinsic." That is no longer true in the live tree — the DB shows `midcycle_ebit_margin_applied` on `fcff_dcf/fcfe_dcf/ddm/residual_income` already. The real defect is different and bigger: a **one-directional ~−38pp downward bias** produced by several structural mechanisms that all push value down at once. This brief replaces 43's §3.1/§3.2 with the mechanism that the DB actually exhibits, keeps 43's insurer item (§3.3) as RC-F, and adds the terminal-value / thin-peer / combiner-weighting fixes that are the majority of the bias.
>
> **Priority: P0.** This is the dominant correctness problem in the fundamentals layer. Engine-only; no new data (the data-coverage gap is brief 45, runs in parallel).
>
> **Plugin rubric anchor.** `financial-analysis:dcf-model` (terminal value must not dominate; normalize the *starting* cash flow, not clip it to a trough median that then fades flat), `financial-analysis:comps-analysis` (a multiple built on <5 real peers or a market-wide fallback is not investment-grade and must not carry full weight), `equity-research:initiate` (regulated/contracted utilities and distributors are **not** cyclical commodity producers).

---

## 0. Files Sonnet MUST read first (gate — confirm current line numbers, the tree has shifted)

1. `docs/fundamentals-layer/21-codex-briefs-INDEX.md` — binding "anti-hallucination" rules. **This brief is a sanctioned exception to rule #5**, scoped to: cyclical classification + normalization, terminal-value handling, peer-reliability weighting, the ensemble combiner, and the insurer path. No fabricated numbers anywhere; observed medians or `unavailable`.
2. `core/quant_core/fundamentals/valuation.py`:
   - `CYCLICAL_COMMODITY_SECTOR_TOKENS` (`:560`) and `CYCLICAL_COMMODITY_SYMBOL_REGISTRY` (`:573`). **`TQM`, `TMA`, and the `energie/energy/electricite/electricity/petrole/oil/gaz/gas` tokens are the misclassification source.**
   - `_cyclical_commodity_source` (`:961`); `_midcycle_earnings_basis` (`:1057`, ≥4-year gate at `:1070`); `_midcycle_model_warning` (`:1139`).
   - DCF terminal-value warnings: `terminal_value_above_75pct_ev` (`:2262` in `_fcff_dcf` `:2200`), `terminal_value_above_75pct_equity_value` (`:2369` in `_fcfe_dcf` `:2317`; also `_ddm` `:2419`).
   - `SEVERE_TERMINAL_VALUE_WARNINGS` (`:625`), `SEVERE_FCF_DCF_WARNINGS`/`_PREFIXES` (`:623-624`), `_severe_valuation_exclusion_reason` (`:1684`).
   - `_relative_multiples` (`:2840`) — `relative_peers_thin_sector_market_fallback` (`:2939`), `relative_peers_count_below_5` (`:2942`).
   - `compute_valuation_ensemble` (`:3198`) — **equal-weight blend (`:3262`)**, headline = median of class medians (`:3249-3255`), review gate (`:3280-3296`), `_reject_cross_model_outliers` (`:3112`).
   - `DEFAULT_ASSUMPTIONS` review thresholds (`:69`, `:76-79`) and their `derivation`/`source` registry (`:397-429`).
3. `core/quant_core/fundamentals/projection.py` — `build_projection` (`:141`); the cyclical margin clip (`:264-277`) and capex `max(D&A, midcycle)` (`:310-327`).
4. `docs/fundamentals-layer/43-codex-sector-aware-valuation-correctness.md` — the insurer §3.3 carries over as RC-F here.

> If a cited line shifted, report the new line and proceed. Do not guess.

---

## 1. Evidence (live, `is_canonical=true` snapshots, base scenario, vs BKGR Jun-2026)

Scorecard over the 35 names that overlap `core/tests/fixtures/bkgr_jun2026.csv` (reproduce with §6):

- **Directional (sign) agreement: 10/27 = 37%.** **Mean(app − BKGR): −38.5pp; median −33.6pp.** Of 35 BKGR names, **8 are blank/NR**; across the full 73-name canonical book **24 produce zero usable models**.
- The bias is **one-directional** — almost every miss is the app *below* BKGR. Only WAA/ARD/DWY/COL read above. A one-sided miss = structural, not noise.

The mechanisms, each confirmed in `fundamental_valuation_result` / `fundamental_ensemble_result`:

**RC-A — cyclical normalization over-suppresses, and is applied to non-cyclicals.**
`build_projection:264-270`: for a cyclical with ≥4 years it sets `year1_margin = ebit_anchor = median(all-history EBIT margin)` and fades flat to that same median — it **clips the starting margin to a (often trough-dragged) full-history median with no recovery fade**. `:318` then sets `maintenance_capex = max(D&A%, midcycle_capex%)`, which **double-penalizes FCFF**. Result: every model for a normalized name craters together.
- **TQM** (TAQA Morocco — a *contracted IPP* selling under long-term PPA to ONEE; stable, not cyclical): every model −74…−79% after `midcycle_ebit_margin_applied`; headline −60% vs **BKGR +65%** — the single worst miss in the book (−125pp). It is in the registry (`:573 "TQM": "electricity producer"`) and caught by the `electricite/energy` tokens. **Misclassified.**
- **TMA** (TotalEnergies Marketing — regulated fuel *distribution*, stable margin): `:573 "TMA": "energy/oil distributor"`. **Misclassified.**
- **LHM** (Holcim, genuinely cyclical cement): all models −38…−43% vs BKGR +31% — even a *correct* cyclical is suppressed ~70pp, proving the normalization itself over-discounts, not just the classification.

**RC-B — terminal value dominates the DCF book-wide.**
`terminal_value_above_75pct_equity_value` fires on **32 names**, `..._ev` on 21. When the explicit-window FCF is depressed (capex/growth/normalization), ~all the DCF value rests on a terminal computed off a low base. A TV>75% DCF currently **still ships at full weight** unless it *also* has an FCF-reliability warning (`_severe_valuation_exclusion_reason:1684` requires both).

**RC-C — DCF on negative trailing FCF for growth/capex-heavy names.**
`fcf_model_unreliable_negative_trailing_fcf` (7 names) + `..._capex_heavy` (6). **AKT** (Akdital — building hospitals; negative trailing FCF *by design*): fcfe/fcff flagged and excluded, but DDM (−50) and thin-peer multiples (−65/−54) still blend to −52% vs **BKGR +59%**.

**RC-D — thin-peer comps fall back to a too-low multiple and keep full weight.**
`relative_peers_count_below_5` on **18 names**, `relative_peers_thin_sector_market_fallback` on 10. In a ~75-name market most sectors lack 5 real peers, so comps default to a market-wide multiple that doesn't fit, lands low, and is **equal-weighted** into the headline.

**RC-E — the combiner equal-weights everything and its quality gate is blind to shared bias.**
`compute_valuation_ensemble:3262` uses `equal_weight = 1/len(usable_rows)`; the headline (`:3255`) is the mean of the two class medians. The review gate (`:3290`) only fires when `|upside| > 150% / < −95%` **and** coverage<0.8 or class-agreement<0.4. TQM at −60% never reaches the −95% floor, and its class agreement is *high* precisely because every model consumed the same depressed midcycle base — **agreement masks the bias instead of catching it.**

**RC-F — insurer/financial simplified path overshoots.**
`insurer_simplified_roe_projection` / `financial_simplified_roe_projection` (4 each). **WAA** +68% vs BKGR −7% (+75pp, the lone wrong-way miss).

**RC-G (out of scope here → brief 45) — data gate NRs 24 names.**
`data_unverified_nr:*` (t1/t3/t6/t7) blanks BCI, MNG, ADI, JET, LBV, MSA, VCN, CMG… — a data-coverage gap, not engine math.

---

## 2. Root cause → fix

| # | Mechanism | Fix | Section |
|---|---|---|---|
| A | Mid-cycle clips margin to trough-dragged median + `max(D&A,capex)`; applied to non-cyclicals | Reclassify; normalize *toward* mid-cycle without dragging a depressed current margin; stop double-penalizing capex; thin-history → no confident trough | §3.1–§3.3 |
| B | TV>75% DCFs ship at full weight | De-weight / exclude DCFs whose terminal share exceeds threshold; anchor terminal on comps-cross-checked exit multiple | §3.4 |
| C | DCF on negative trailing FCF for growth names | Already excluded for fcff/fcfe — confirm; ensure the *headline* isn't then built only on the remaining depressed models without a flag | §3.5 |
| D | Thin/fallback comps carry full weight | Reliability-weight comps; a market-fallback multiple cannot be a full-weight headline driver | §3.6 |
| E | Equal weighting + agreement-masking review gate | Confidence/reliability-weighted blend; review gate must fire on shared-flag bias, not be suppressed by it | §4 |
| F | Insurer simplified ROE overshoot | Equity-side P/B-vs-normalized-ROE + DDM; cap one-off ROE spikes | §3.7 |

---

## 3. The fixes

### 3.1 — Reclassify: regulated/contracted names are not cyclical commodities (`valuation.py:560,573`)
- Remove from `CYCLICAL_COMMODITY_SYMBOL_REGISTRY`: **`TQM`** (contracted IPP) and **`TMA`** (regulated distribution). Re-examine **`GAZ`** (Afriquia Gaz — fuel distribution/retail; margins regulated, not commodity-cyclical): if it has no genuine commodity-margin cycle, remove it too; if kept, justify with a `derivation`/`source` note in the registry comment.
- Narrow `CYCLICAL_COMMODITY_SECTOR_TOKENS`: drop the over-broad `energie/energy/electricite/electricity/petrole/oil/gaz/gas` tokens (they sweep regulated utilities and distributors). Keep genuine cyclical-commodity *producers* only — mining (`mine/mines/mining`) and building materials (cement/steel/aluminium, which you may key by registry symbol rather than a sector token if the sector strings are noisy). Document each retained token.
- The retained cyclical set should be the *producers* whose realized margin genuinely swings with a commodity/BTP cycle: CMT, MNG, SMI, REB, ZDJ (mining), SID, ALM, CMA, LHM (BTP materials). Confirm against `stock_master.sector` and report the final set before changing behavior.

### 3.2 — Normalize *toward* mid-cycle without clipping a depressed margin (`projection.py:264-277`, `valuation.py:1057-1131`)
The current logic forces `year1_margin = ebit_anchor = median(history)` and fades flat. Replace with a through-cycle normalization that does **not** suppress a healthy current level toward a trough-dragged median:
- Compute `median_margin` over the cycle window as today, **and** keep `latest_margin`. The normalized margin should converge to `median_margin` as a *terminal/mid-cycle* anchor but **start from a blend that does not sit below the current margin when the current margin is itself at/under the median** (i.e. never normalize a trough *down* further). Concretely: `year1_margin = max(latest_margin, blended)` is wrong in the other direction — instead, fade *from* `latest_margin` *to* `median_margin` over the horizon (standard mid-cycle mean-reversion), so a currently-elevated cyclical fades down to mid-cycle and a currently-depressed one **recovers up** to mid-cycle. Do not pin all years to the median.
- This is the core of RC-A: a miner in a trough year should be valued on *recovery to mid-cycle*, not held at trough; a regulated name (now declassified) shouldn't be touched at all.
- Capex (`:318`): drop the `max(D&A%, midcycle_capex%)` that inflates maintenance capex. Use mid-cycle maintenance capex = `median(capex%)` over the window (or D&A% as the maintenance proxy), **not the max of the two**. Document the chosen definition with `source`.
- Surface on each cyclical model output: `normalized_earnings_basis` = {window, median_margin, latest_margin, trailing_vs_midcycle_pct, recovery_or_fade}. The DB must show whether each cyclical is fading down or recovering up.

### 3.3 — Graceful history degradation (no silent confident trough) — keep brief-43 §3.2
- ≥4 common years → normalize (as today). 3 years → normalize **with** `midcycle_normalization_thin_history`. <3 years → normalization genuinely unavailable: the cyclical's intrinsic models must **not** ship a confident trough-based rating — flag `cyclical_trough_unnormalized` and route the headline to review/NR (reuse the §4 review path), never a confident SELL on a single trough year. Thresholds in the registry with `derivation`/`source`.

### 3.4 — Terminal value must not dominate unchecked (`valuation.py:1684`, `:2261`, `:2369`, `:625`)
- A DCF whose terminal share exceeds a threshold is low-information. Today `_severe_valuation_exclusion_reason:1684` only excludes a TV>75% DCF if it *also* has an FCF-reliability warning. Change so that **TV share above a hard ceiling (propose 0.85, with `derivation`) excludes the DCF from the headline on its own**; between the warn level (0.75) and the ceiling it stays but is **reliability-down-weighted** in §4 (not equal-weighted).
- Where a terminal exit multiple is implied (`implied_exit_ev_to_ebitda`, `:2267`), sanity-check it against the comps exit multiple; if the implied exit multiple is wildly below the peer multiple, that is the over-discount signature — flag `terminal_exit_multiple_below_peer`.
- Do **not** fabricate a terminal multiple; use the observed comps multiple or mark the cross-check unavailable.

### 3.5 — Growth/capex-heavy DCF (`valuation.py:1636-1644`, `:1684`)
- Confirm `fcf_model_unreliable_negative_trailing_fcf` / `_capex_heavy` already exclude fcff/fcfe from the combiner (they do via `:1684`). The residual problem is that the **headline then rests on the remaining models** (DDM/RI/comps) which may themselves be depressed/thin, with no flag. When a name's *only* surviving intrinsic models are themselves flagged (proxy/thin) and the comps are market-fallback, the headline must carry `headline_low_information` and be reliability-weighted (§4), not shipped as a confident number. Do **not** invent forward FCF here — that forward-earnings decision stays deferred; the fix is to stop over-trusting the depressed survivors.

### 3.6 — Thin-peer comps cannot be full-weight headline drivers (`valuation.py:2840-2943`, §4)
- A `relative_multiples` result carrying `relative_peers_thin_sector_market_fallback` or `relative_peers_count_below_5` is low-reliability. It may stay in the candidate pool but must be **reliability-down-weighted** in the combiner (§4), and it must **not** be the deciding driver of a headline that disagrees with the intrinsic class by more than the review band.

### 3.7 — Insurer path (carry over brief-43 §3.3) (`valuation.py` financial routing)
- Insurers (`assurance/insurance/takaful`; WAA, ATL, SAH): equity-side only — justified P/B = (ROE − g)/(CoE − g) on **normalized** (median) ROE, P/E, DDM. **No** EV/EBITDA, EV/Sales, FCFF, net-debt bridge, or bank PNB/RBE chain. Normalize ROE so one spike year can't drive an overshoot; flag `insurer_no_embedded_value`. WAA's +68% must come down to a defensible level or be flagged. Confirm insurers are not inheriting brief-37's bank projection.

---

## 4. The combiner fix (RC-E) — `compute_valuation_ensemble:3198`

This is the keystone; without it the per-model fixes leak back in via equal weighting.

1. **Replace equal weighting (`:3262`) with reliability weighting.** Each candidate gets a weight from its own confidence/quality, not `1/n`. Use the existing `confidence_score` and a reliability multiplier that **down-weights** results carrying low-information flags (`*_proxy`, `*_peer_median`, `*_fallback`, `*_assumption`, `relative_peers_*`, `terminal_value_above_75pct*` below the §3.4 exclusion ceiling, `earnings_growth_proxy`, `midcycle_normalization_thin_history`). The `NON_OBSERVED_INPUT_WARNING_TOKENS` set (`:629`) already enumerates most of these — reuse it. A fully observed, high-confidence model should outweigh a market-fallback comp several to one. Document the weight curve with `derivation`/`source`; no magic constants without a registry entry.
2. **Headline** stays the class-balanced blend but uses the reliability-weighted class representatives (weighted median/mean within class), so a thin comp can't swing the market-class representative.
3. **Fix the review gate (`:3280-3296`) so shared bias triggers review instead of hiding it.** Two changes:
   - The "weak class agreement" arm must not be *satisfied away* when all models agree because they share a flagged input. Add: if a **majority of usable models carry the same low-information flag** (e.g. `midcycle_*`, `*_fallback`, `earnings_growth_proxy`), treat the headline as low-information regardless of numeric agreement → `headline_review_shared_input_bias`.
   - The downside floor of −95% is too permissive for a confident SELL. A headline below a tighter confident-downside band (propose −60%, `derivation`) that is built on low-information models must route to review/NR rather than ship — this is what would have caught TQM at −60% and AKT at −52%. (A −60% headline on *fully observed, high-confidence* models may still ship — the gate is on information quality, not the number alone.)
4. Re-confirm `_reject_cross_model_outliers` (`:3112`) still runs *before* weighting and that weighting doesn't resurrect an excluded outlier.

---

## 5. Acceptance criteria

1. `python -m pytest core/tests/ -q` + touched API tests pass from the worktree root.
2. **Reclassification:** TQM and TMA no longer carry `midcycle_*` flags on any model; their DCF/DDM start from actual (not normalized) margins. Re-score: TQM moves from −60% toward BKGR +65% (or, if a model genuinely can't value it, NR with a specific reason — never a confident −60%).
3. **Normalization direction:** for a genuine cyclical in a trough year, the intrinsic models start below mid-cycle and **recover up** (assert `recovery_or_fade == "recovery"` and DCF start margin ≥ latest trough margin); for one above mid-cycle, they fade down. `normalized_earnings_basis` present on intrinsic-model outputs. LHM/SID/CMT materially less negative / nearer BKGR.
4. **Thin history:** a cyclical with <3 years is flagged `cyclical_trough_unnormalized` and routed to review/NR, not a confident trough rating.
5. **Terminal value:** no DCF with TV share > the §3.4 exclusion ceiling contributes to a headline; TV between warn and ceiling is down-weighted (assert its weight < a fully-observed model's).
6. **Combiner:** weights are not all equal when reliability differs (assert a market-fallback comp's weight < an observed DCF's). The review gate fires `headline_review_shared_input_bias` on a name whose usable models share a `midcycle_*`/`*_fallback` flag.
7. **Insurer:** WAA on P/B-ROE + DDM (no EV/EBITDA/FCFF/PNB); overshoot resolved or flagged; `insurer_no_embedded_value` where applicable.
8. **Book-wide:** re-run the §6 scorecard. Targets — directional agreement **≥ 60%** (from 37%), |mean bias| **≤ 15pp** (from −38.5pp), and **no new** unflagged headline outside [−60%, +150%]. Before/after table per name in the report.
9. New tests: `core/tests/test_cyclical_intrinsic_normalization.py` (recovery-up vs fade-down; thin-history → flag/NR; TQM/TMA not normalized), `core/tests/test_ensemble_reliability_weighting.py` (unequal weights; shared-bias review trigger; thin-comp can't swing headline), `core/tests/test_insurer_valuation.py`.
10. Docs updated: `06-valuation-models.md`, `13-methodology-and-sources.md` (normalization direction, terminal-value handling, reliability weighting, insurer path); append a note to brief 43 that 44 supersedes its §3.1/§3.2 premise.

---

## 6. Validation procedure (reproduce the scorecard — Sonnet runs this before and after)

The author's exact method (resolve via `is_canonical`, **not** latest-import):

```sql
-- export app upsides for canonical base-scenario ensembles
COPY (
  SELECT e.symbol,
         round((e.upside_pct*100)::numeric,1) AS app_upside,
         e.usable_model_count AS nmod,
         coalesce(e.warnings_json::text,'[]') AS warns
  FROM fundamental_ensemble_result e
  JOIN fundamental_latest_snapshot s
    ON s.import_id=e.import_id AND s.symbol=e.symbol AND s.is_canonical=true
  WHERE e.scenario='base'
) TO STDOUT WITH CSV HEADER;
```

Join to `core/tests/fixtures/bkgr_jun2026.csv` on `ticker`, compute: directional agreement (sign match where the app has a fair value), mean/median of `(app_upside − bkgr_upside_pct)`, and the NR count. There is an existing harness at `services/api/scripts/validate_vs_bkgr.py` — prefer extending it over an ad-hoc script, and have it print the per-name before/after diff table used in the report.

Per-model drill-down for any name (used to confirm the mechanism):

```sql
SELECT v.symbol, v.model, v.family, round(v.fair_value::numeric,1) fv,
       round((v.upside_pct*100)::numeric,0) up, round(v.weight::numeric,2) w,
       v.confidence, v.warnings_json::text
FROM fundamental_valuation_result v
JOIN fundamental_latest_snapshot s
  ON s.import_id=v.import_id AND s.symbol=v.symbol AND s.is_canonical=true
WHERE v.scenario='base' AND v.symbol = ANY(ARRAY['TQM','AKT','LHM','WAA'])
ORDER BY v.symbol, v.family, v.model;
```

Revalue all scenarios after the change (the recompute path defaults to `scenario="all"`); if Postgres write-locks, stop the scheduler container first.

---

## 7. What NOT to do

- **Do not** start the forward-earnings / analyst-estimate work — that is a separate deferred *methodology decision*, not a bug. RC-C is fixed by not over-trusting depressed survivors, not by inventing forward FCF.
- **Do not** fabricate mid-cycle margins, exit multiples, embedded value, or peers — observed medians or `unavailable`/NR.
- **Do not** normalize a regulated/contracted name as if it were cyclical (the whole point of §3.1).
- **Do not** normalize a trough *downward* — mean-revert toward mid-cycle, both directions.
- **Do not** widen the data-integrity tolerances (38), change CoE wiring (39), or alter scenario logic (35) to force a pass.
- **Do not** touch the 24 NR names' data here — that is brief 45. If a name is NR for data reasons, leave it NR.
- **Do not** let "all models agree" suppress review when the agreement comes from a shared flagged input.

---

## 8. Out of scope → brief 45 (parallel, data-acquisition)

The 24 zero-model names (BCI, MNG, ADI, JET, LBV, MSA, VCN, CMG, …) are NR because their data still fails the T1–T7 tie-out gate — a brief-42-style proof-of-read re-ingestion, **not** engine math. That is brief 45 and runs in a separate chat; it is low-conflict with 44 (different files). Do not attempt it here.

## 9. Open questions (Sonnet: confirm in the report before coding)

- Final retained cyclical set after §3.1 (with each symbol's `stock_master.sector`), and the GAZ decision with justification.
- Per cyclical (CMT/MNG/SMI/SID/LHM/CMA/ALM): current `latest_margin` vs `median_margin` — is each currently above or below mid-cycle? This tells you who fades down vs recovers up and lets you predict the sign of the move.
- WAA per-model drivers behind +68% (spike ROE? a leaked EV/FCF model? bank PNB path mis-applied?) before choosing the normalization/cap.
- Proposed numeric thresholds with `derivation`/`source`: TV exclusion ceiling (≈0.85), confident-downside review band (≈−60%), thin-history cutoffs (≥4 full / 3 flagged / <3 NR), and the reliability weight curve.
- Confirm `_reject_cross_model_outliers` ordering vs the new weighting.
