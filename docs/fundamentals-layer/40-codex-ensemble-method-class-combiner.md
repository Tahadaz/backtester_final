# 40 — Method-class combiner: stop the comps model being rejected by the intrinsic cluster

> **Status.** Plan-only. Claude has not modified code. **Sanctioned exception** to INDEX rule #5: scoped to `compute_valuation_ensemble` and `_reject_cross_model_outliers` only. No new data, no fabricated numbers, no price-anchored clamp. Does not touch the model formulas, the data gate (38), the cost-of-capital wiring (39), or scenarios (35).
>
> **Priority: P1 — the residual under-valuation + the surviving tail.** After brief 39 fixed the cost of capital, the low-beta cohort de-biased (ARD −43→+18, COL −80→−15, GAZ −51→−8), but comps-excluded names stay short of BKGR (GAZ −8, LHM −37, COL −15 vs +22/+31/+27) and MIC's tail grew (+166→+295). Both are the same defect: **the peer-comps model is being statistically rejected, so the market reality-check is missing from the headline.**
>
> **Plugin rubric anchor.** `financial-analysis:comps-analysis` (relative valuation is a co-equal method, not an input to be outlier-filtered against intrinsic DCF), `financial-analysis:dcf-model` (intrinsic and relative are two independent cross-checks — present both, reconcile, don't let one suppress the other).

---

## 0. Files Codex MUST read first (gate — confirm line numbers)

1. `docs/fundamentals-layer/21-codex-briefs-INDEX.md` — binding rules.
2. `docs/fundamentals-layer/07-ensemble-and-confidence.md` — methodology to keep consistent (update in the same PR).
3. `core/quant_core/fundamentals/valuation.py`:
   - `_reject_cross_model_outliers` (`:3048`) — the single-pool MAD rejection that masks the comps model.
   - `compute_valuation_ensemble` (`:3116`) — equal-weight median of survivors; consumes the rejection output.
   - `RELATIVE_FAMILY_MODELS` (`:549`), and the model set `{fcff_dcf, fcfe_dcf, ddm, residual_income, justified_multiples, relative_multiples}`.
   - Registry knobs: `ensemble_outlier_mad_k` (3.0), `ensemble_small_sample_floor_to_median` (0.25), `ensemble_small_sample_ceiling_to_median` (4.0) — and their `_ASSUMPTION_META_OVERRIDES` entries (`:335`).
   - `_severe_valuation_exclusion_reason` (structural/availability gates — keep), `_ensemble_confidence_components`.

> If a cited line has shifted, report the new line and proceed.

---

## 1. Evidence (live, post-brief-39, 2026-06-06)

The combiner pools **all** models, takes the median + MAD, and rejects anything outside `median ± 3·1.4826·MAD`. Because the intrinsic models (`fcff/fcfe/ddm/residual_income/justified_multiples`) **share the same CoE/ROE/g inputs, they cluster tightly** → MAD is small → the radius is small → the single peer-comps model (`relative_multiples`) lands outside and is excluded:

| symbol | intrinsic cluster | `relative_multiples` (comps) | headline | BKGR |
|---|---|---|---|---|
| GAZ | ~1700–2500 (incl) | **3922 → EXCLUDED** | −8% | +22 |
| LHM | ~900–1100 (incl) | **1552 → EXCLUDED** | −37% | +31 |
| COL | 13–49 (incl) | **207 → EXCLUDED** | −15% | +27 |
| MIC | high (incl) | comps reality-check absent | **+295%** | — |

This is **MAD masking**: a coherent majority from *one method* (intrinsic) suppresses the correct minority from *another method* (relative). It is structural — the intrinsic family always clusters (shared inputs), so the comps model is *systematically* the casualty, in both directions:
- **Under-valued defensives** (GAZ/LHM/COL): comps is higher than the low intrinsic cluster → excluded → headline stays low.
- **Run-away intrinsic** (MIC): comps would anchor it to peer multiples → but there's no comps in the blend to cap it → headline runs to +295%.

The comps model is the **market reality check**. Excluding it breaks the valuation in both tails.

---

## 2. Root cause

| # | Cause | Fix |
|---|---|---|
| RC1 | `_reject_cross_model_outliers` pools intrinsic + relative models into one median/MAD. The tight intrinsic cluster shrinks MAD, so the lone comps model is rejected as an "outlier" purely for being a *different method*, not for being wrong. | §3.1 |
| RC2 | Because comps is dropped, the headline (median of survivors) is intrinsic-only — no market cross-check — so it under-values defensives and lets intrinsic blow-ups (MIC) run uncapped. | §3.2 |
| RC3 | The only remaining tail guard is the small-sample structural band; a high estimate where models agree (MIC) is never flagged. | §3.3 |

---

## 3. The fix (method-class aware, standard equity practice)

**3.1 — Outlier rejection is intra-class, not cross-method.**
Split the candidates into two method classes:
- **Intrinsic** — `fcff_dcf`, `fcfe_dcf`, `ddm`, `residual_income`, `justified_multiples` (all derive value from the firm's own fundamentals + discount rate).
- **Relative / market** — `relative_multiples` (peer multiples — the market reality check).

Apply MAD outlier rejection **within each class only** (and only when a class has ≥3 members; a class of 1–2 isn't outlier-filtered against itself). A model is excluded **only** if it's an outlier *relative to its own method class* (e.g., one DCF wildly off the other DCFs), or it fails a structural/availability gate (`_severe_valuation_exclusion_reason`, non-positive, g≥r — keep these). **A coherent comps value is never rejected for differing from the intrinsic cluster.**

**3.2 — Headline reconciles the two classes; comps always has a voice.**
Compute a robust representative per class (median of that class's survivors). The headline = the **median of the available class representatives** (intrinsic-rep and market-rep when both exist; the one that exists otherwise). Equivalent simple form: pool the survivors but guarantee the surviving comps value is included in the median. Keep equal-weight; document the exact rule in `07-ensemble-and-confidence.md`. This:
- lifts GAZ/LHM/COL (the comps-rep pulls the headline up toward the market view), and
- caps MIC (the comps-rep pulls the run-away intrinsic value down toward peer multiples).

Band (`fair_value_low/high`) = spread across the combined survivor set, as today.

**3.3 — Final headline sanity gate (catches what comps can't tame).**
After reconciliation, if the headline upside is beyond a documented sanity bound (registry, e.g. `headline_review_upside` = +150% / floor −95%) **and** coverage/agreement is weak, attach a diagnostic warning and route to **NR/review** rather than shipping the number — reuse brief-34's intent and the brief-38 NR path. A name where comps + intrinsic genuinely agree on an extreme value is allowed (it'll be rare and defensible); a thin-coverage extreme is flagged. This is the backstop for any residual MIC-type case.

**3.4 — Re-validate.**
Re-run an all-scenario revalue; re-pull the brief-38-verified names. Expect: comps no longer shows `*_excluded_cross_model_outlier` when it's a coherent value; GAZ/LHM/COL move up toward BKGR; MIC capped toward peer multiples or flagged; no headline > +150% / < −95% shipped without a flag. Produce the before/after table.

---

## 4. Acceptance criteria

1. `python -m pytest core/tests/ -q` + touched API tests pass from the worktree root.
2. A coherent `relative_multiples` value is **never** excluded merely for diverging from a tight intrinsic cluster (assert on GAZ/LHM/COL: comps now contributes; no `relative_multiples_excluded_cross_model_outlier` for these).
3. Intra-class rejection still removes a true within-class outlier (e.g. one DCF 100× the other DCFs) and still honors the structural gates.
4. GAZ/LHM/COL headline upside moves materially up vs the post-39 values; MIC is capped toward its peer multiple or flagged for review; **no headline > +150% or < −95% is shipped without a review/NR flag.**
5. New tests: `core/tests/test_method_class_combiner.py` (comps protected from intrinsic-cluster rejection; intra-class outlier still caught; two-class reconciliation median; extreme-headline sanity flag).
6. Docs `07-ensemble-and-confidence.md` updated: two method classes, intra-class rejection, class reconciliation, headline sanity gate.

---

## 5. What NOT to do

- **Do not** reintroduce any price-anchored clamp (brief 31's mistake) — discipline is cross-*model*/method, never anchored to market price.
- **Do not** fabricate or floor values; structural gates (non-positive, g≥r, severe quality) stay as availability checks (→ `unavailable`), not number-inventing.
- **Do not** over-weight comps into a single-model headline — it's one of two co-equal classes, not the answer; both classes must be represented when both exist.
- **Do not** touch the model formulas, the data gate (38), the cost-of-capital wiring (39), or scenario logic (35).
- **Do not** widen rejection so far that genuine garbage survives — intra-class rejection + structural gates + the headline sanity flag together must still kill true blow-ups.

---

## 6. Relationship to other briefs

- **39 precedes 40.** With the cost of capital fixed, the intrinsic models are no longer uniformly depressed, so reconciling them with comps gives a sane headline (rather than averaging two wrong things). 40 closes the residual gap 39 left on comps-excluded names and tames the intrinsic tail.
- **After 40**, the remaining gap to BKGR is mostly the *forward-estimate* question (BKGR uses 2026e/2027e + target multiple; our engine is trailing) — the deferred decision on magnitude. Re-judge it on the post-40 numbers.

## Open questions (Codex: confirm before coding)

- Class assignment: confirm `justified_multiples` belongs in the **intrinsic** class (it's derived from ROE/CoE/g, so it clusters with DCF/DDM — yes) vs the relative class. Report the chosen mapping.
- Exact reconciliation rule: median-of-class-representatives vs pooled-median-with-comps-guaranteed — pick the simpler that satisfies §4 and document it. Show both on GAZ/LHM/COL before choosing.
- MIC: pull its `relative_multiples` value; confirm whether re-including comps alone caps it, or whether the §3.3 sanity flag is also needed. Report.
- `headline_review_upside` bound + the coverage/agreement threshold for the §3.3 flag — propose values with `derivation`/`source` in the registry.
