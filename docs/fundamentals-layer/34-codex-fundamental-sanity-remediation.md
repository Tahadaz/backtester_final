# 34 — Fundamental valuation sanity remediation (no fabricated numbers, defensible methodology)

> **Status.** Plan-only. Claude has not modified code. This brief is a **sanctioned exception** to INDEX rule #5 (do-not-touch the seven-model engine): it scopes edits to the model floors, the ensemble combiner, the projection driver defaults, the confidence/rating layer, and a new validation harness. It does **not** introduce new MCP integrations, new currencies, or UI-token changes.
>
> **Priority: P0 — engine correctness.** It supersedes the residual symptoms left by briefs 30/31, which over-corrected: the engine now systematically *under*-values (see Evidence) and still emits an unbounded positive tail. Pick this up before any P1/P2 wrapper work.
>
> **Plugin rubric anchor.** `financial-analysis:dcf-model`, `financial-analysis:comps-analysis` (median-not-average, mid-cycle normalization, exclude statistical outliers), `equity-research:model-update`. The fixes below are the *standard* versions of what those skills do — nothing bespoke.

---

## 0. Files Codex MUST read first (gate — confirm line numbers before editing)

1. `docs/fundamentals-layer/21-codex-briefs-INDEX.md` — the anti-hallucination contract (rules that bind every brief).
2. `docs/fundamentals-layer/06-valuation-models.md`, `07-ensemble-and-confidence.md`, `08-assumptions-and-defaults.md` — methodology these changes must keep consistent (update the docs in the same PR where behaviour changes).
3. `core/quant_core/fundamentals/valuation.py`:
   - `DEFAULT_ASSUMPTIONS` + `_ASSUMPTION_META_OVERRIDES` (lines ~25–367) — the registry; new policy values go **here**, with `derivation`/`source`/`plausible_range`, never as bare code constants.
   - `MODEL_BASE_WEIGHTS` (424), `IMPLIED_PRICE_FLOOR_MULT`/`CEIL_MULT` (434–435), `RELATIVE_FAMILY_WEIGHT_CAP` (436), `EXTREME_LOW_CONFIDENCE_MODEL_UPSIDE` (453), `HEADLINE_*` (449–450).
   - `_clamp_implied` (723), `_dispersion_stats` (749), `_weighted_median` (736), `_severe_valuation_exclusion_reason` (1063), `compute_valuation_ensemble` (2304).
   - `_fcff_dcf` (1542), `_fcfe_dcf` (1653), `_ddm` (1746), `_residual_income` (1854), `_justified_multiples` (1979), `_relative_multiples` (2071).
4. `core/quant_core/fundamentals/projection.py` lines ~184–305 and ~530–660 — the driver-default block (this is where the placeholder numbers live).
5. `services/api/app/services/fundamentals.py` — `MIN_USABLE_MODELS_FOR_RATING` (263), `derive_recommendation` (274), `derive_conviction` (301), `derive_research_overlay` (364).
6. `docs/fundamentals-layer/32-codex-scenario-governance.md` — G1 (base-anchored headline). Phase D below reuses, does not re-spec, that fix.

> If any cited line has shifted, **report the new line and proceed** — never assume.

---

## 1. The one principle this brief enforces

**Every number that reaches a fair value is exactly one of three things:**

| Class | Definition | Where it lives |
|---|---|---|
| **Observed** | Read from filings/market data for *this* symbol. | `AnnualMetricRow`, `FundamentalSnapshot` |
| **Derived** | Computed from Observed via a standard formula (CAPM, Gordon, DuPont, sustainable growth…). | the model functions |
| **Assumption** | A desk policy value with a written `derivation`, `source`, and `plausible_range`, editable in the registry. | `DEFAULT_ASSUMPTIONS` + `_ASSUMPTION_META_OVERRIDES` |

**Anything else is forbidden.** No `= 0.03`, `= 0.10`, `= 0.04`, `= 0.0` driver fallbacks baked into function bodies; no per-sector confidence floors asserted by fiat; no price-anchored clamp that quietly drags fair value toward the market.

**When a required input is none of the three, the dependent model returns `fair_value=None`, `confidence="unavailable"`, and a `warnings[]` reason. It is never back-filled with an invented number, and it is never floored to `0`.** Marking a model unavailable is *simpler* than maintaining a fallback ladder — that is the simplification, not a complication.

This single rule resolves "no placeholders" and "don't over-engineer" at once: the fix is mostly **deletion** (remove clamps, the magic weight table, the caps, the sector confidence boost, the driver defaults) plus **two** standard additions (cross-model outlier rejection; mid-cycle normalization for cyclicals).

---

## 2. Evidence (current live state — base scenario, 73-name BVC universe)

Pulled from `fundamental_ensemble_result` (latest succeeded import per symbol) on 2026-06-05 and scored against the BKGR Stock Guide (Jun 2026, `bkgr-stock-guide-juin-2026.pdf`):

| Metric | BKGR | Engine today |
|---|---|---|
| Mean 12m upside (35 overlapping names) | **+24.9%** | **−42.6%** |
| Directional agreement | — | **7/35 = 20%** |
| Spearman rank correlation | — | **0.21** (no ordering skill) |
| BUY ratings across full 73 names | ~32 buy/accumulate | **0** |
| Rating mix | — | 64 HOLD · 8 SELL · 1 NR |
| Names at ≤ −95% (fabricated floor) | 0 | **9** |
| Names at > +120% (unbounded tail) | 0 | **4** (incl. **MLE +4,949%**) |

Representative failures, traced to the model level:

- **IAM (Maroc Telecom):** headline target **0**, −100%. `ddm`, `fcff_dcf`, `fcfe_dcf`, `residual_income` all return **0** (84% of ensemble weight). Cause: `max(0.0, equity_value)` floor (`_fcff_dcf:1592`, `:1622`; `_residual_income:1910`, `:1955`; `_ddm` analog). A non-positive equity value means the inputs are broken → must be **unavailable**, not 0.
- **MLE:** `residual_income` **+8,805%** at "medium" confidence, weight 0.46 → headline +4,949%. Cause: intrinsic family is unbounded (only `_relative_multiples`/`_justified_multiples` pass through `_clamp_implied`), and `_severe_valuation_exclusion_reason` only catches `> 1000% AND conf < 0.45`.
- **ATW (Attijariwafa, bank):** SELL, −39% (BKGR +30% Buy). `residual_income` = **0** at "high" confidence (weight 0.30) — `is_financial → "high"` (`_residual_income:1911`, `:1956`) asserts reliability the data didn't earn.
- **SMI / TAQA / Sonasid / Managem** (commodity/cyclical): −47% / −51% / −60% / −60% while BKGR has +15% / +65% / +38% / −27%. FCF models trip `fcf_model_unreliable_negative_trailing_fcf` at the bottom of the capex cycle; the relative multiple (the one model near BKGR — SMI relative = 19,189 vs BKGR 10,454) is capped to ≤25% family weight and out-voted by trough-earnings intrinsic models. **No mid-cycle normalization.**

The fix target is **sanity, not curve-fitting to BKGR.** BKGR uses forward consensus, guidance and analyst judgment; our engine is mechanical from historical filings. We will *not* tune to match BKGR name-by-name. We require: no fabricated floors/tails, no systematic directional bias, and directional agreement on the *unambiguous* cases.

---

## 3. Root-cause → fix map

| # | Root cause (file:line) | Fix (phase) |
|---|---|---|
| RC1 | Fabricated floor `max(0.0, equity_value)` ships 0 → −100% (`valuation.py:1592, 1622, 1910, 1955`, `_ddm` analog, `_fcfe_dcf` analog) | **A** |
| RC2 | Asymmetric bounds: relative/justified clamped to `[0.40×, 2.50×]` of price (a market-anchoring heuristic); intrinsic family unbounded; backstop only at `>1000% & conf<0.45` (`_clamp_implied`, `EXTREME_LOW_CONFIDENCE_MODEL_UPSIDE`, `_severe_valuation_exclusion_reason`) | **B** |
| RC3 | Comps suppressed: hand-tuned `MODEL_BASE_WEIGHTS` + `RELATIVE_FAMILY_WEIGHT_CAP=0.25` + capex multipliers — all undocumented constants — let fragile intrinsic models dominate (`compute_valuation_ensemble:2304`) | **B** |
| RC4 | `is_financial → "high"` confidence by fiat (`_residual_income:1911, 1956`; check `_ddm`) | **A** |
| RC5 | No mid-cycle normalization for cyclicals/commodities → trough/peak earnings drive RI/DDM/multiples | **C** |
| RC6 | Placeholder driver defaults: `year1_growth=0.03` (`projection.py:191, 543`), EBIT-margin `default=0.10` (`:214`), D&A `default=0.0` (`:226`), capex/maintenance `0.04` (`:231-232`), WC `default=0.0` (`:239`), payout `0.55` (`:244`) | **A** |
| RC7 | Confidence double-penalized (`base × dispersion_factor`, `_dispersion_stats:749` floors at 0.25) → ≥0.45 BUY gate unreachable → 0 BUYs | **D** |
| RC8 | `MIN_USABLE_MODELS_FOR_RATING=1` (`fundamentals.py:263`) — one model publishes a target | **D** |
| RC9 | Headline follows *selected* scenario, not base (`derive_research_overlay:364`) | **D** (reuse brief 32 G1) |
| RC10 | No external sanity guardrail — over/under-shoot regressions are silent | **E** |

---

## Phase A — Eliminate fabricated numbers (pure correctness, no new methodology)

**A1. Non-positive intrinsic value → `unavailable`, never 0.**
In `_fcff_dcf`, `_fcfe_dcf`, `_ddm`, `_residual_income`: replace every `fair = max(0.0, <value>)` with:
```
if <value> is None or <value> <= 0:
    fair = None
    model_unavailable = True
    warnings.append("<model>_nonpositive_value_unavailable")
else:
    fair = <value>
```
Already partially done for FCF when `reliability_warnings` is present (`:1587-1590`); make it **unconditional** (a non-positive per-share equity value is structurally impossible for a going concern and means the inputs are unusable regardless of other warnings). An `unavailable` model contributes nothing to the ensemble (it is already excluded at `compute_valuation_ensemble:2316`).

**A2. Remove the `is_financial → "high"` confidence assertion (RC4).**
In `_residual_income` (`:1911`, `:1956`) and `_ddm` (find the analog): confidence is earned from data quality + warnings via `_confidence(...)`, identically for all sectors. Sector affects *eligibility* (Phase B), not a confidence floor. Delete the `"high" if is_financial else "medium"` literals; pass a base derived from observed data completeness (e.g. `"high"` only when book value and ≥3y net income are observed and no proxy/integrity warning fired, else `"medium"`, else `"low"`).

**A3. Driver defaults: peer-median-or-unavailable (RC6).**
In `projection.py`, for each driver currently given a bare default — revenue growth (`:191/:543`), EBIT margin (`:214`), D&A % (`:226`), capex % (`:231`), working-capital % (`:239`), payout (`:244`):

1. If the symbol has usable history → use it (unchanged).
2. Else, if the **sector peer cohort** has an observed median for that driver → use the peer median and append `<driver>_from_peer_median` (this is Observed data, not invented). Pass the peer cohort into `build_projection` (the cohort already exists via `_peer_stats` in `compute_symbol_valuations`; thread it through, do not recompute).
3. Else → set `projection.fallback = True`, append `<driver>_unavailable_no_history_no_peer`, and have the dependent model(s) return `unavailable` rather than fabricate. The terminal-growth ceiling, tax fallback, rf/ERP remain registry assumptions (legitimate Class-3 values) — **only the operational drivers lose their silent constants.**

> **Do not** replace one magic number with another. If you cannot source a value as Observed or registry-Assumption, the answer is `unavailable`. The `maintenance_capex_pct`, `stable_payout_ratio` keys stay in the registry **only** as documented desk assumptions used in the explicit-forecast fade (they are Class-3), but they must **not** be used as the silent "no history" fill for the *starting* driver — that path becomes peer-median-or-unavailable.

**A4. Tests (Phase A).** `core/tests/test_fundamentals_no_fabricated_floor.py`:
- A DCF/DDM/RI that computes ≤0 equity value returns `fair_value is None`, `confidence == "unavailable"`, and an explanatory warning — never `0.0`, never `-100%` upside.
- A symbol with one revenue point and **no peer cohort** yields `unavailable` for projection-dependent models (no `0.03`/`0.10` injected).
- A financial with proxied book value does **not** get `"high"` RI/DDM confidence.
- Grep guard test: assert no float literal in `{0.03, 0.10, 0.04, 0.55}` appears as a driver fallback in `projection.py` model bodies (scan the AST or a curated line set).

---

## Phase B — Standard statistics replace heuristic bounds and weights (RC2, RC3)

This phase is a **net deletion** of bespoke constants, replaced by two textbook rules. It changes `compute_valuation_ensemble` and removes the price-anchored clamp.

**B1. Drop the price-anchored implied-price clamp.** Remove `_clamp_implied` usage in `_relative_multiples`/`_justified_multiples` and the `IMPLIED_PRICE_FLOOR_MULT`/`CEIL_MULT` constants. Anchoring a model's output to a band around the current price is itself a market-anchoring heuristic (it biases fair value toward price and contaminated the upside). Discipline comes from B2 instead, applied uniformly to **all** models.

**B2. Cross-model robust outlier rejection (the comps-analysis "exclude outliers" rule, generalized).** In `compute_valuation_ensemble`, after collecting each model's per-share `fair_value` (Observed/Derived only; `unavailable` already excluded):
1. Compute the cross-model **median** `m` and **MAD** = `median(|fairᵢ − m|)`.
2. Exclude any model whose value lies beyond `m ± k·(1.4826·MAD)` (k from registry, default **k=3.0**, documented as the standard robust 3-σ-equivalent rejection). With <4 surviving models, fall back to excluding only values outside `[0.25×, 4.0×]` of the surviving median (a *wide* structural sanity gate, registry-documented — not a tight price band).
3. Append `<model>_excluded_cross_model_outlier` for each rejected model.

This catches MLE's +8,805% (it is orders of magnitude from the peer median) without any per-model clamp, and it is symmetric (catches both fabricated highs and stray lows). Delete `_severe_valuation_exclusion_reason`'s `extreme_low_confidence_model_fair_value` branch and `EXTREME_LOW_CONFIDENCE_MODEL_UPSIDE`; keep the *structural* exclusions (g≥r, non-positive equity, dividend-yield-out-of-range) — those are availability gates, not magic thresholds.

**B3. Replace the weight tangle with eligibility + median (RC3).** Delete `MODEL_BASE_WEIGHTS`, `RELATIVE_FAMILY_WEIGHT_CAP`, `capex_heavy_*_weight_cap`, `capex_heavy_recovery_weight_multiplier`, and the family-cap rescale block (`compute_valuation_ensemble:2361-2377`). Replace with:
- **Eligibility matrix** (one small, explicit, documented table in `valuation.py`, sourced to standard practice): which models are *appropriate* per sector class.
  - *Financials* (bank/insurance/financing): `residual_income`, `ddm`, `justified_multiples` (P/B, P/E) eligible; FCFF/FCFE **not** eligible (already the case — keep).
  - *Cyclicals/commodities* (mining, cement, steel, energy — tag via sector): `relative_multiples` (EV/EBITDA on **mid-cycle** EBITDA, Phase C) and normalized-earnings RI eligible; raw-FCF DCF down-weighted to *informational* (eligible but flagged when trailing FCF is cycle-distorted).
  - *General industrials/consumer*: all seven as today.
- **Headline = median of the eligible, non-outlier model values** (robust, exactly the `comps-analysis` "median not average" rule). Band = (min, max) of survivors, or the 25th/75th if ≥4 survive. This removes the entire confidence-weighted-mean machinery and the Monte-Carlo shift; keep `model_dispersion_low/base/high` populated from the survivor spread. (If the desk wants to keep MC bands, retain `_monte_carlo_band` but re-center on the survivor median — do not let it reintroduce weighting.)
- Surface `model_weights` as the **post-rejection inclusion set** (1/N for survivors, 0 for excluded) so the UI can still show "which models counted."

> **Why median, not weighted mean:** the weighted mean with hand-tuned weights was the mechanism by which a single broken model (MLE RI, IAM zeros) moved the headline. The median of survivors is robust to one bad model by construction and is the documented rubric standard. This is the core simplification.

**B4. Tests (Phase B).** `core/tests/test_ensemble_robust_combine.py`:
- A 7-model set where one value is 100× the others → that model is excluded as a cross-model outlier; headline = median of the rest.
- A set where one model is 0 (should already be `unavailable` from Phase A, but assert it never pulls the median to 0).
- Financial-sector symbol → FCFF/FCFE not in the eligible set; headline from RI/DDM/justified.
- Removing the price-anchored clamp does not reintroduce >150% headline upside on any name in the BKGR fixture (cross-check with Phase E).

---

## Phase C — Mid-cycle normalization for cyclicals/commodities (RC5)

The one place we **add** methodology, because it is required by the rubric and is the direct fix for the SMI/TAQA/Managem misses. Keep it minimal and transparent.

**C1. Normalized earnings power.** For symbols tagged cyclical/commodity (sector-driven; reuse the same tag as B3), the *starting* profitability that feeds RI, DDM and justified/relative multiples is the **mid-cycle** figure, not the trailing year:
- Mid-cycle EBIT margin = **median EBIT margin over all available cycle years** (require ≥4 years; else mark the normalization `unavailable` and flag — do not normalize on 2 points).
- Mid-cycle ROE = median ROE over the same window.
- Apply mid-cycle margin to *current* revenue, mid-cycle ROE to *current* book value, to get normalized starting earnings. Surface `normalized_earnings_basis = {window, median_margin, median_roe, trailing_vs_midcycle_pct}` in `outputs`.
- EV/EBITDA relative multiple for these names uses **mid-cycle EBITDA** as the denominator (this is exactly how commodities are valued through-cycle; raw-trough EBITDA produces the −47% SMI artifact).

**C2. Capex through the cycle.** The existing "fade capex to maintenance" is correct in direction; ensure maintenance capex for cyclicals is **mid-cycle capex/sales median** (Observed), not the `0.04` registry norm, when ≥4y capex history exists. Falls back to the registry `maintenance_capex_pct` (Class-3 assumption) only when history is insufficient, flagged.

**C3. Tests (Phase C).** `core/tests/test_midcycle_normalization.py`:
- A synthetic miner with trough trailing earnings + healthy mid-cycle history → normalized fair value is materially above the trough-based value and the basis is reported.
- A name with <4 years → normalization marked unavailable, not applied on thin data.
- Non-cyclical names are unaffected (no normalization applied).

---

## Phase D — Confidence and rating recalibration (RC7, RC8, RC9)

**D1. Confidence must span [0,1] and be monotone, not double-penalized.** Replace `confidence = base_confidence × dispersion_factor` (`compute_valuation_ensemble:2391`) with a single transparent function of three Observed quantities:
```
confidence = w_n·coverage + w_a·agreement + w_d·data_quality      (weights in registry, sum to 1)
  coverage     = min(1, surviving_models / target_models)          # target_models from registry (default 5)
  agreement    = 1 − min(1, robust_cv)                             # robust_cv = 1.4826·MAD / |median|
  data_quality = fraction of required inputs Observed (not proxied/peer-filled)
```
No floor at 0.25, no multiplicative compounding of the dispersion penalty (agreement already captures dispersion once). Document the three weights in `_ASSUMPTION_META_OVERRIDES`. Remove `_dispersion_stats`' `max(0.25, …)` floor (keep it as a pure CV reporter).

**D2. Quorum for a rating (RC8).** Raise `MIN_USABLE_MODELS_FOR_RATING` (`fundamentals.py:263`) to **3** and require `agreement ≥ a_min` (registry, default 0.40) for a directional (BUY/SELL) call. Below quorum → **NR** with reason. One model never publishes a target.

**D3. Rating bands anchored to required return, not a bare upside number (RC7).** Replace the hard-coded `upside > 0.12` / `< -0.10` / `conf ≥ 0.45` in `derive_recommendation` with a **5-tier ladder on expected total return vs the stock's own cost of equity** — the academically grounded "is the expected return above the required return" test, and it maps cleanly onto BKGR's Acheter/Accumuler/Conserver/Alléger/Vendre:
```
expected_total_return = (target/price − 1) + forward_dividend_yield      # 12m horizon
excess = expected_total_return − cost_of_equity                          # alpha vs required return
  excess > +0.10  → BUY (Acheter)
  +0.03..+0.10    → ACCUMULATE (Accumuler)
  −0.03..+0.03    → HOLD (Conserver)
  −0.10..−0.03    → REDUCE (Alléger)
  excess < −0.10  → SELL (Vendre)
gated by: rating only if quorum (D2) met and confidence ≥ conf_min; else NR.
```
All five band edges + `conf_min` live in the registry as one documented `rating_policy` block (Class-3 desk policy), editable, with `source = "desk research policy"`. `cost_of_equity` is already Derived per symbol. Update `derive_conviction` to use the new confidence. Keep the API field `recommendation` shape; extend the allowed enum to the 5 tiers (coordinate with the FE label map — search `signal-fundamental-view.tsx` for the rating label dictionary; add Accumuler/Alléger).

**D4. Base-anchored headline (RC9).** Implement brief 32 **G1 only** here if not already done: `derive_research_overlay` headline `recommendation`/`target_price` anchor to the **base** ensemble regardless of the selected scenario; bear/bull remain a labelled risk band. Do not re-spec G2–G4 (that is brief 32's scope) — just ensure the headline does not follow the selected scenario.

**D5. Tests (Phase D).** `services/api/tests/test_rating_bands.py` + `core/tests/test_confidence_recalibration.py`:
- A name with 5 agreeing models and Observed inputs reaches confidence ≥ 0.6 (BUY gate is *reachable*).
- The 5-tier ladder maps known excess returns to the right label.
- 2 usable models → NR.
- Headline rating is invariant to the selected scenario toggle (anchored to base).

---

## Phase E — External sanity guardrail (RC10)

**E1. Commit the BKGR reference as a fixture.** `core/tests/fixtures/bkgr_jun2026.csv` — the mapped table below (engine ticker, BKGR target, BKGR upside %, BKGR rating). Source: `bkgr-stock-guide-juin-2026.pdf`, 25.05.26 prices.

| ticker | name | bkgr_target | bkgr_upside_% | bkgr_rating |
|---|---|---|---|---|
| ADH | Addoha | 42.3 | 28.2 | Acheter |
| GAZ | Afriquia Gaz | 4626 | 21.7 | Acheter |
| AKT | Akdital | 1868 | 58.9 | Acheter |
| ADI | Alliances | 599 | 41.9 | Acheter |
| ARD | Aradei Capital | 525 | 22.0 | Acheter |
| ATL | AtlantaSanad | 175 | 34.6 | Acheter |
| ATW | Attijariwafa Bank | 910 | 30.2 | Acheter |
| ATH | Auto Hall | 91 | 29.6 | Acheter |
| BCP | BCP | 405 | 68.8 | Acheter |
| BCI | BMCI | 846 | 41.9 | Acheter |
| CDM | CDM | 1420 | 39.9 | Acheter |
| CIH | CIH | 507 | 40.4 | Acheter |
| CMA | Ciments du Maroc | 2150 | 28.7 | Acheter |
| CMG | CMGP Group | 394 | 9.4 | Accumuler |
| COL | Colorado | 104 | 27.1 | Acheter |
| CSR | Cosumar | 220 | 19.2 | Accumuler |
| DWY | Disway | 881 | 10.8 | Accumuler |
| HPS | HPS | 774 | 23.8 | Acheter |
| IAM | Itissalat Al-Maghrib | 130 | 39.6 | Acheter |
| JET | Jet Contractors | 2984 | 33.3 | Acheter |
| LBV | Label Vie | 4414 | 14.4 | Accumuler |
| LHM | Holcim Maroc | 2428 | 30.6 | Acheter |
| MNG | Managem | 12135 | -26.9 | Conserver |
| CMT | Miniere Touissit | 4499 | -7.2 | Conserver |
| MUT | Mutandis SCA | 255 | 13.3 | Accumuler |
| RDS | Residences Dar Saada | 151 | -10.7 | Vendre |
| SMI | SMI | 10454 | 14.9 | Accumuler |
| MSA | Marsa Maroc (SODEP) | 1012 | 18.9 | Accumuler |
| SID | Sonasid | 2845 | 37.7 | Acheter |
| SOT | Sothema | 399 | 5.4 | Conserver |
| TQM | TAQA Morocco | 2977 | 65.4 | Acheter |
| TGC | TGCC S.A | 1016 | 33.7 | Acheter |
| TMA | TotalEnergies Marketing Maroc | 1748 | 12.7 | Accumuler |
| VCN | Vicenne | 498 | 25.6 | Acheter |
| WAA | Wafa Assurance | 5404 | -6.8 | Conserver |

> Codex must re-verify each ticker↔name mapping against `fundamental_company_map`/`stock_master` before committing; drop any row whose mapping is ambiguous and note it in `## Open questions`. (SGTM, Cash Plus, SMI vs. SMI-mining, and any post-split names need confirmation.)

**E2. Validation harness (script, not a hard CI gate).** `services/api/scripts/validate_vs_bkgr.py`: loads the latest base ensembles, joins the fixture, prints directional agreement, mean-bias, Spearman, and the per-name table; flags any name with `|upside| > 150%` not marked `unavailable`, and any ≤ −95% floor. This is a **diagnostic**, run on demand — it must not fetch anything external.

**E3. Sanity regression test (hard gate).** `core/tests/test_valuation_sanity.py` — runs the engine on the committed fixture symbols' stored snapshots and asserts the *structural* invariants (not BKGR tracking):
- **No fabricated extremes:** zero names with headline upside ≤ −95% or > +150% unless the ensemble is explicitly `NR`/insufficient-coverage.
- **No systematic bias:** median engine upside across the fixture ∈ [−15%, +25%] (a desk-plausible band; today it is −60%).
- **Directional sanity on unambiguous cases:** for names where BKGR upside is > +30% with a Buy rating *and* the engine has ≥3 surviving models at confidence ≥ 0.5, the engine sign must not be strongly negative (no SELL on a BKGR strong-Buy with high engine confidence).
- **At least one BUY/ACCUMULATE exists** across the fixture when ≥10 names have quorum (catches the "0 BUYs" collapse).

> These thresholds are **sanity bands, deliberately loose.** The goal is to catch the failure *classes* in §2, not to fit BKGR. Document this intent at the top of the test so no future change tightens it into curve-fitting.

---

## 4. Acceptance criteria (whole brief)

1. `python -m pytest core/tests/ -q` and the API tests pass from the worktree root.
2. New tests above all present and green.
3. Re-running `validate_vs_bkgr.py` after a full revalue shows: directional agreement materially up from 20% (target ≥ 60% on quorum names), mean-bias from −42.6% into [−15%, +25%], **no** name at ≤ −95% or > +150% unless `NR`, and **> 0** BUY/ACCUMULATE ratings.
4. Grep proves the deleted constants are gone: `MODEL_BASE_WEIGHTS`, `RELATIVE_FAMILY_WEIGHT_CAP`, `IMPLIED_PRICE_*_MULT`, `EXTREME_LOW_CONFIDENCE_MODEL_UPSIDE`, the `capex_heavy_*` weight knobs, and the `0.03/0.10/0.04/0.55/0.0` driver fallbacks in `projection.py` model bodies.
5. Every model output still carries `confidence` + ≥1 `warnings[]` (INDEX rule #6 preserved). Every `unavailable` carries a human-readable reason.
6. Docs `06`, `07`, `08` updated to describe: three-class number discipline, median-of-survivors combiner, cross-model outlier rejection, mid-cycle normalization, the new confidence formula, and the 5-tier return-vs-CoE rating ladder. `12-known-issues-and-limitations.md` updated to retire the over/under-valuation entries this brief closes.

---

## 5. What NOT to do (scope guards)

- **Do not** add new MCP/data integrations, currencies, or forward-consensus ingest (that is brief 8/P3 territory). This brief is correctness-only on existing data.
- **Do not** replace one magic number with another. Missing → Observed-peer-median → else `unavailable`. The only new constants allowed are the registry policy values (k=3.0 rejection, confidence weights, the 5 rating-band edges, target_models), each with `derivation`/`source`/`plausible_range`.
- **Do not** reintroduce price-anchored discipline (no clamp/band keyed to current price) — discipline is cross-model only.
- **Do not** tighten the Phase-E sanity bands toward exact BKGR tracking. They are guardrails against the failure classes, not a fit target.
- **Do not** touch the technical signal engine, backtest/WFO/optimization, scoring pillar weights, or UI design tokens.
- **Do not** rewrite `compute_symbol_valuations`' routing; extend it (thread the peer cohort into `build_projection`, swap the ensemble combiner).

---

## 6. Suggested sequencing (separate Codex runs — do not bundle)

1. **Phase A** (floors + driver defaults + sector confidence) — biggest single sanity gain, lowest risk; kills the −100% floor and the +8805% financial RI.
2. **Phase B** (robust combiner) — depends on A (unavailable models already excluded).
3. **Phase C** (mid-cycle normalization) — depends on B's eligibility tag.
4. **Phase D** (confidence + rating + base-anchor).
5. **Phase E** (fixture + harness + sanity gate) — last, validates 1–4.

After each phase, run a full revalue (`POST /fundamentals/recompute` path / the worker revalue task) on the BVC universe and re-run `validate_vs_bkgr.py` to watch the metrics move.

---

## Open questions (Codex: fill in, do not improvise)

- `_ddm` did not have the same `is_financial -> "high"` literal as `_residual_income`; only `_residual_income` had that sector confidence floor and Phase A removed it. Sector now affects eligibility/normalization, not a confidence floor.
- The available stock classification field is `stock_master.sector`; `stock_master` has no industry column. Phase A/C use `stock_master.sector` for peer-median operational driver fill and broad cyclical/commodity eligibility. Because the BVC `BTP` sector mixes construction, cement, steel, and materials, Phase C also documents a small explicit BVC materials/energy symbol registry in code for the ambiguous names.
- BKGR ticker/name mapping was verified against `stock_master` and `fundamental_company_map` before committing the fixture. The brief's `ALM | Alliances` row was corrected to `ADI | Alliances`: `ALM` is `Aluminium du Maroc`, while `ADI` is the active/unambiguous Alliances ticker. `SMI` is the active mining issuer (`Societe Metallurgique d'Imiter`) despite duplicate historical map rows; `SOT` is active Sothema with both provider and manual therapeutic-company map rows; `TGC` is active TGCC, while old manual workbook rows also reference SGTM names and are marked duplicate. Cash Plus (`CAP`) and SGTM (`GTM`) are present in the PDF/database, but they are not part of the Phase E fixture table and were not added beyond the brief scope.
