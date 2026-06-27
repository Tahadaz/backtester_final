# 43 — Sector-aware valuation correctness: cyclical mid-cycle into intrinsic models + insurer model

> **Status.** Plan-only. Claude has not modified code. **Sanctioned exception** to INDEX rule #5: scoped to how cyclical/commodity normalization feeds the intrinsic models + projection, and to a proper insurer valuation path. No new data, no fabricated numbers.
>
> **Priority: P1 — two sector mis-fits, fixed together.** After 38–42 the data is real and blue-chips track BKGR (BCP +55 vs +69, CIH +36 vs +40). The residual under-valuation is concentrated in two sectors the engine mis-handles: **(A) cyclicals/miners** (SID −54, SMI −35, CMT −60 vs BKGR +38/+15/−7) and **(B) insurers** (WAA +68 vs BKGR −7 — overshoot the other way). Both are "the engine systematically mis-values a sector," not data corruption.
>
> **Plugin rubric anchor.** `financial-analysis:dcf-model` + `comps-analysis` (cyclicals valued on **mid-cycle / normalized** earnings power, applied to *all* methods, not just multiples), `equity-research:initiate` (insurers valued on P/B-vs-ROE + dividends / embedded value, never EV/EBITDA or generic FCF).

---

## 0. Files Codex MUST read first (gate — confirm line numbers)

1. `docs/fundamentals-layer/21-codex-briefs-INDEX.md` — binding rules.
2. `core/quant_core/fundamentals/valuation.py`:
   - `CYCLICAL_COMMODITY_SECTOR_TOKENS` (`:560`), `CYCLICAL_COMMODITY_SYMBOL_REGISTRY` (`:573` — SID/SMI/CMT/MNG/REB/ZDJ/CMA/LHM/ALM/GAZ/TMA/TQM already tagged), `_cyclical_commodity_source` (`:961`).
   - `_midcycle_earnings_basis` (`:1057`) — the ≥4-common-year gate (`:1070`); produces `normalized_ebit/net_income/ebitda`; `_midcycle_basis` (`:1134`), `_midcycle_model_warning` (`:1139`).
   - **Where midcycle is consumed today:** only the multiples path (`:1273-1280` `market_cap_over_midcycle_net_income`, `_justified_multiples`/`_relative_multiples` ~`:2421-2556`). Confirm the intrinsic models (`_fcff_dcf`, `_fcfe_dcf`, `_ddm`, `_residual_income`) and `build_projection` do **not** consume it.
   - `_is_financial` (`:813`), `FINANCIAL_SECTOR_TOKENS` (`:497`) — and how `_eligible_models` routes financials; brief-37's bank path.
3. `core/quant_core/fundamentals/projection.py` — `build_projection` starting revenue/margin (the trough entry point for cyclicals).
4. `docs/fundamentals-layer/37-codex-bank-insurer-model.md` — it explicitly left **insurers "simplified"**; this brief finishes them.

> If a cited line has shifted, report the new line and proceed.

---

## 1. Evidence (live, is_canonical, post-42)

**A — Cyclicals stay on trough earnings.** SID/SMI/CMT are tagged cyclical, so `_midcycle_earnings_basis` is *attempted*, but they still read −54/−35/−60 vs BKGR +38/+15/−7. Two structural causes:
- `_midcycle_earnings_basis` computes `normalized_ebit/net_income/ebitda` but those feed **only** justified/relative multiples. The **intrinsic** `_fcff_dcf/_fcfe_dcf/_ddm/_residual_income` and `build_projection` still start from **trailing/trough** earnings → low intrinsic values → the combiner (brief 40) reconciles a normalized market value against a trough intrinsic value and lands low.
- The ≥4-common-year gate (`:1070`): with much of the data only FY2024–25, miners get `status="unavailable"` → no normalization anywhere → pure trough.

**B — Insurers mis-fire.** WAA +68% (BKGR −7%); brief 37 left insurers on a "simplified" path. The generic equity model (and/or any residual EV/FCF leakage) over-values them; insurers need P/B-vs-normalized-ROE + dividends, embedded-value-flagged.

---

## 2. Root cause → fix

| # | Cause | Fix |
|---|---|---|
| RC1 | Mid-cycle normalized earnings feed only the multiples, not the intrinsic models/projection → intrinsic stays trough → drags the cyclical headline. | §3.1 |
| RC2 | ≥4-year gate silently falls back to trough for thin-history miners; a trough-based confident SELL is worse than an honest flag. | §3.2 |
| RC3 | Insurers run a generic/simplified path that over-values (WAA +68%). | §3.3 |

---

## 3. The fix

**3.1 — Mid-cycle normalization feeds the intrinsic models + projection for cyclicals.**
When `_cyclical_commodity_source` is set and `_midcycle_earnings_basis.status == "available"`, the **starting earnings power** used by `build_projection` and consumed by `_fcff_dcf/_fcfe_dcf/_ddm/_residual_income` must be the **normalized mid-cycle** figure, not the trailing/trough year:
- Projection start: revenue × `median_margin` (mid-cycle EBIT), and the equity models' starting net income = `normalized_net_income` (book × `median_roe`); D&A/EBITDA via `normalized_ebitda`.
- Growth then fades from the normalized base per the existing path (don't double-count a cyclical recovery on top of normalization).
- Surface `normalized_earnings_basis` in every cyclical model's outputs (it's currently only on the multiples) so the consumer sees trough-vs-mid-cycle. This is the core fix — it lifts SID/SMI/CMT toward through-cycle fair value the way `comps-analysis` and BKGR treat miners.

**3.2 — Graceful degradation of the history gate (no silent trough).**
- Relax the gate from a hard `<4 → unavailable` to: use the available cycle years if **≥3**, flagged `midcycle_normalization_thin_history`; with `<3` years, normalization is genuinely unavailable → the cyclical's intrinsic models must **not** ship a trough-based confident rating: flag `cyclical_trough_unnormalized` and route the headline to **review/NR** (reuse brief-40's sanity-gate path) rather than a confident SELL on trough earnings.
- The thin-history threshold(s) live in the registry with `derivation`/`source`.

**3.3 — Proper insurer valuation (finish brief 37's deferred insurers).**
- Insurers (`assurance`/`insurance`/`takaful` in `FINANCIAL_SECTOR_TOKENS`; e.g. WAA, ATL, SAH): value **equity-side only** — justified P/B = (ROE − g)/(CoE − g) on **normalized** ROE (median over available years, not a one-off spike), P/E, and DDM; **no** EV/EBITDA, EV/Sales, FCFF, net-debt bridge, or PNB/RBE bank chain (those are bank-only).
- If embedded value / solvency (SCR) figures are not in the data, that's expected → use the P/B-ROE + DDM set, flag `insurer_no_embedded_value`, and **do not** let a single high-ROE year drive an overshoot (normalize ROE; the brief-40 sanity gate still caps the headline). WAA +68% must come down to a defensible level or be flagged.
- Confirm insurers are not accidentally inheriting the bank PNB/RBE projection path from brief 37.

**3.4 — Re-validate.** Re-run all-scenario revalue; re-pull the cyclical cohort (SID/SMI/CMT/MNG/SBM/ALM…) and insurers (WAA/ATL/SAH). Expect the miners to lift toward through-cycle (less deeply negative; CMT/SMI nearer BKGR), insurers' overshoot to resolve, and **no** new >+150%/<−95% unflagged tails. Report before/after + BKGR re-score.

---

## 4. Acceptance criteria

1. `python -m pytest core/tests/ -q` + touched API tests pass from the worktree root.
2. For a cyclical with available mid-cycle basis, the intrinsic models (DCF/DDM/RI) and the projection start from the **normalized** earnings (assert the DCF/DDM start ≠ trailing-trough; `normalized_earnings_basis` present on intrinsic-model outputs).
3. A cyclical with <3 years of history is **not** shipped as a confident trough rating — it's flagged/NR with `cyclical_trough_unnormalized`.
4. Insurers value on P/B-ROE + DDM (no EV/EBITDA/FCFF/PNB path); WAA's overshoot is resolved or flagged; insurers carry `insurer_no_embedded_value` where applicable.
5. Re-score: miners (SID/SMI/CMT) materially less negative / nearer BKGR; insurers sane; no new pathological tails (brief-40 gate holds). Before/after table in the report.
6. New tests: `core/tests/test_cyclical_intrinsic_normalization.py` (intrinsic models use mid-cycle when available; thin-history → flag/NR not trough) and `core/tests/test_insurer_valuation.py`.
7. Docs `06-valuation-models.md` + `13-methodology-and-sources.md` updated for the cyclical-intrinsic normalization and the insurer path.

---

## 5. What NOT to do

- **Do not** double-count recovery — when starting from normalized mid-cycle earnings, the growth fade must not *also* assume a cyclical rebound.
- **Do not** silently use trough earnings for a cyclical with thin history — flag or NR; never ship a confident SELL built on a single trough year.
- **Do not** value insurers (or banks) on EV/EBITDA, EV/Sales, FCFF, or a net-debt bridge.
- **Do not** fabricate embedded value / mid-cycle figures — use observed medians or mark unavailable.
- **Do not** touch the data gate (38), CoE wiring (39), the combiner mechanics (40 — only feed it better inputs), or scenario logic (35). **Do not** start the forward-estimate work (separate, deferred decision).

## 6. Relationship & what's left

- Independent of and complementary to 38–42 (those fixed data + generic engine). 43 fixes the two sector mis-fits.
- After 43, the remaining items are the **forward-earnings decision** (the trailing-vs-analyst magnitude gap on growth names — CDM/LHM/HPS) and **coverage** (the ~11 BKGR names still NR / outside the priority cohort, via another brief-42-style re-ingestion batch).

## 7. Open questions (Codex: confirm before coding)

- DB-confirm per cyclical (SID/SMI/CMT/MNG/SBM): is `_midcycle_earnings_basis.status` `available` or `unavailable_insufficient_history`? Report counts — this tells you how much of the miss is RC1 (feeding) vs RC2 (history).
- Insurers: pull WAA/ATL/SAH per-model to confirm what's driving the WAA +68% (spike ROE? a leaked EV/FCF model?) before choosing the cap/normalization.
- Thin-history thresholds (≥3 use-with-flag; <3 NR) — propose values with `derivation`/`source`.
- Confirm whether brief-37's bank projection is being wrongly applied to insurers (PNB/RBE on a non-bank financial).
