# Brief 47 — Valuation growth-input remediation (Sonnet)

**Owner:** Sonnet implementer · **Branch:** `feature/fundamental-ui-consolidation` · **Extends:** brief 44
**Goal:** Fix the systematic bearish bias and near-zero cross-sectional rank correlation between our
fundamental valuation ensemble and the BKGR Jun-2026 study. The data cutover (briefs 45/46) made
coverage complete; this brief fixes the **valuation methodology**, specifically the near-term growth
inputs to the intrinsic models.

> Methodology change with real blast radius. Backend-first, one lever at a time, and **re-run the
> BKGR validator after every change** (it is the pass/fail gate). Stop and report after each phase.

---

## 0. Diagnosis (already done — verify, don't re-investigate)

Measured against `core/tests/fixtures/bkgr_jun2026.csv` via `services/api/scripts/validate_vs_bkgr.py`
on current post-cutover data:

| Metric | Value | Read |
|---|---|---|
| overlap / quorum | 34 / 33 of 35 | coverage is fine (only BCI missing) |
| directional_agreement | **0.33** | worse than a coin flip |
| spearman (rank corr) | **0.09** | ~no cross-sectional correlation — the worst symptom |
| mean_diff_vs_bkgr_pct | **−44%** | systematically bearish |
| median_engine_upside_pct | **−24%** | engine says "overvalued" where BKGR says "buy" |

**Per-model median upside (canonical universe) — this is the key evidence:**
```
relative_multiples   -1.5%   ← peer-based, tracks the market (≈ correct anchor)
justified_multiples -25.6%
residual_income     -28.2%
fcff_dcf            -33.2%
ddm                 -39.5%
fcfe_dcf            -51.5%   ← all intrinsic models structurally too low
```
It is **not** the data, **not** the discount rate (CoE median 8.2%, WACC 7.1% — low/favorable),
**not** terminal growth (3.5%), and **not** mid-cycle normalization (only 12/69 symbols; normalized
vs non-normalized medians ≈ equal). The intrinsic models are low because their **near-term growth
inputs understate forward growth**:

- **DCF** (`core/quant_core/fundamentals/valuation.py:1600-1629`, `_fcf_growth_input`): stage-1 growth
  = a **single trailing year** of `NetIncome_Growth`/`Revenue_Growth`. One noisy YoY number, floored
  at −5%; a flat/down latest year anchors the whole DCF near zero growth.
- **DDM** (`valuation.py:2050-2080`, `_sustainable_dividend_growth`): growth = **`ROE × retention`**.
  MASI blue chips pay out most earnings (high payout → low retention), so sustainable growth is
  structurally tiny (often floored near −5% when payout ≥ 100%). Wrong for a high-dividend market.

Both symptoms follow: the **bias** because every intrinsic model discounts an understated profile;
the **rank scramble (spearman ≈ 0)** because single-year and retention-implied growth are noisy and
idiosyncratic per company, uncorrelated with forward-looking expectations.

**Anchor for "right":** `relative_multiples` at −1.5% means the market is *not* egregiously overvalued
on a peer basis, so the −40% is a model artifact, not a real signal. BKGR is optimistic sell-side —
we need **not** match its +30% levels. Target: rank like BKGR (Spearman up) and sit near
`relative_multiples` (~0%), not −40%.

---

## Phase A — fix intrinsic-model near-term growth (do first)

### A1. DCF stage-1 growth (`_fcf_growth_input`, valuation.py:1600)
- Replace the single-trailing-year growth with a **robust multi-year estimate**: a normalized
  historical CAGR (e.g. 3-5y, already partially present as the `*_series_cagr` fallbacks) or a damped
  blend of trailing-1y and multi-year CAGR. Prefer the multi-year signal; use 1y only to nudge.
- Keep sane bounds (floor/cap) but the current −5% floor + 1y noise is the defect — widen the
  information used, don't just re-floor.
- Preserve the existing source-priority + `is_proxy` tagging and warnings.

### A2. DDM growth (`_sustainable_dividend_growth`, valuation.py:2050)
- Stop relying solely on `ROE × retention`. Move to a **2-stage** shape where stage-1 uses actual /
  historical earnings growth (multi-year, same robust estimate as A1) and only the **terminal** leg
  uses the sustainable `ROE × retention` (or terminal_growth cap). Retention-implied growth alone is
  wrong for high-payout names.
- Keep the payout sanity guards already there.

### A3. Re-validate (mandatory gate after Phase A)
- Re-run valuations for the universe, then:
  `DATABASE_URL=<dev> python services/api/scripts/validate_vs_bkgr.py --json`
- Report before/after: directional_agreement, spearman, mean_diff_vs_bkgr_pct, median_engine_upside,
  overlap/quorum, and the **per-model median upside table** (relative_multiples should stay ~0%; the
  intrinsic medians should rise toward it).
- **Coverage must not regress** (overlap/quorum stay ≈ 34/33). Stop and report.

## Phase B — ensemble weighting (only if Phase A leaves a material gap)
- If intrinsic models are fixed, equal-weight is fine — prefer that. Only if a gap remains, consider
  modestly up-weighting market-anchored models (`relative_multiples`/`justified_multiples`) or
  damping chronically-divergent intrinsic models. Ensemble aggregation lives in the valuation
  pipeline that writes `fundamental_ensemble_result` (find via `model_weights_json` /
  `usable_model_count`). Do NOT hard-exclude the bullish model as an "outlier" when the rest are
  depressed (observed on MSA: `justified_multiples` +13% was the only realistic model and got w=0).
- Re-validate (A3 gate) after.

## Phase C — BCI (the one missing valuation)
- BCI (BMCI, a bank) has no usable ensemble. Diagnose (likely thin metric coverage / bank model
  eligibility) and either fix or leave an explicit no-coverage note. Low priority vs A/B.

---

## Acceptance criteria
1. **Spearman materially up** from 0.09 (target ≥ ~0.4 — rank correlation is the primary goal).
2. **directional_agreement** up from 0.33 (target ≥ ~0.6).
3. **Bias narrowed**: median_engine_upside and mean_diff move from −24%/−44% toward the
   `relative_multiples` anchor (~0%) — not necessarily to BKGR's +30%.
4. **No coverage regression**: overlap/quorum stay ≈ 34/33; per-model `relative_multiples` median
   stays ~0% (don't break the model that already works).
5. Full core suite green; valuation sanity tests (`core/tests/test_valuation_sanity.py`,
   `test_valuation_bias_*`) pass.

## Guardrails
- **Don't re-introduce the brief-31 over-valuation problem** (+200-500% upside). Keep existing caps /
  outlier guards; this brief widens the *growth information*, it doesn't remove sanity bounds.
- **Don't chase BKGR's optimism** — the goal is rank correlation + a sane level near peer multiples,
  not matching sell-side targets. Over-fitting to the 35-name fixture is failure.
- Re-run the BKGR validator after every lever; report the metric deltas each time. One lever per
  commit. Stop and report after Phase A before touching the ensemble.
- Backend-only; no frontend changes in this brief.
