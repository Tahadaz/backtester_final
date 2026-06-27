# 30 — Codex brief: DDM and Residual Income — post-V3 corrections

> **Status.** Plan-only brief for Codex. Claude has reviewed the v3 implementations of `_ddm` and `_residual_income` against the CFA / Gordon-growth and Ohlson references and found two residual defects that survived the V2 / V3 fixes. Symptom in the field: on Managem (mining, BVC) the DDM prints ~1 532 MAD while RI prints ~950 MAD — a 60 % gap that is not explained by the *real* methodological difference between the two models. Both defects push the gap wider; fixing them should bring DDM and RI to within ~15 % of each other on the same inputs.
>
> **Plan-only.** This brief tells Codex what to change. Do not let Codex re-derive the math: the equations below are the contract.
>
> **Sanctioned exception to the "do not touch the engine" rule.** Index 21 forbids modifying the seven-model engine. This brief is the explicit override for that rule, scoped to `_ddm`, `_residual_income`, and one helper. Anything else in `valuation.py` remains untouched.

---

## Files Codex MUST read first

1. `core/quant_core/fundamentals/valuation.py` — confirm current line numbers for `_ddm`, `_residual_income`, `_sustainable_dividend_growth`, `_justified_growth`. Cite the actual lines in the PR description.
2. `docs/fundamentals-layer/06-valuation-models.md` §3 (DDM) and §4 (RI) — the post-fix worked examples here are the regression targets.
3. `docs/fundamentals-layer/12-known-issues-and-limitations.md` — read the V2, V3, V6 entries to understand the *history* of these models. Brief 30 supersedes the closing paragraphs of V2 and V3 by adding V13 and V14.
4. `docs/fundamentals-layer/08-assumptions-and-defaults.md` — locate `DEFAULT_ASSUMPTIONS` keys this brief references (`cost_of_equity`, `terminal_growth`, `growth_cap`, `fade_years`, `stable_payout_ratio`). Do not invent new keys.
5. `core/tests/test_fundamentals.py` — locate the existing DDM / RI tests so the new tests in this brief land beside them, not in a separate file.

If any cited line number has shifted, **report the new line in the PR description and proceed** — do not stop.

---

## Defect V13 — DDM mixes two growth rates in a single-stage Gordon formula

### Where

`_ddm` at `valuation.py:529-572`, final fair-value line:

```python
fair = dividend * (1.0 + growth) / (cost - terminal_growth) if dividend and cost > terminal_growth else None
```

### Symptom

- `growth` comes from `_sustainable_dividend_growth(...)` (post-V2): `ROE × (1 − payout)` capped at `growth_cap` ≈ 8 %.
- `terminal_growth` is the perpetuity rate, ≈ 3 %.
- The numerator uses the **sustainable** rate, the denominator uses the **terminal** rate. Gordon requires the **same** `g` on both sides. No standard model (single-stage Gordon, two-stage, H-model) produces this combination.

### Why it matters

The current formula has no clean economic interpretation. It systematically overstates fair value relative to a terminal-only Gordon (because the numerator carries a higher `g`) and understates it relative to a sustainable-only Gordon (because the denominator carries a smaller spread reduction). The error grows with the gap `(sustainable_growth − terminal_growth)` — so it is largest for cyclicals and high-payout names like Managem and CIH-style growth banks.

Worked example (cost = 10.5 %, sustainable g = 6 %, terminal g = 3 %):

| Formula | Multiple on D₀ |
|---|---|
| Current (buggy): `(1 + 0.06) / (0.105 − 0.03)` | **14.13×** |
| Single-Gordon at terminal g (conservative): `(1 + 0.03) / (0.105 − 0.03)` | 13.73× |
| Single-Gordon at sustainable g (only valid if `r > g_sus`): `(1 + 0.06) / (0.105 − 0.06)` | 23.6× |
| **H-model with H = fade_years / 2 = 2.5 (recommended)**: `[(1 + 0.03) + 2.5 × (0.06 − 0.03)] / (0.105 − 0.03)` | **14.73×** |

The H-model produces a value that lies between the two single-stage Gordons in proportion to the fade length — that is the correct shape for "the firm grows above trend for a while, then reverts to terminal." It is also consistent with how `_justified_growth` already models the fade for the justified-multiples model: brief 30 imports the same idea into DDM.

### Fix recipe

Replace the fair-value line in `_ddm` with the H-model:

```python
H = fade_years / 2.0
spread = max(0.0, growth - terminal_growth)
if dividend and cost > terminal_growth:
    fair = dividend * ((1.0 + terminal_growth) + H * spread) / (cost - terminal_growth)
else:
    fair = None
```

Notes for Codex:
- `fade_years` is already in `DEFAULT_ASSUMPTIONS` — read it the same way `_justified_multiples` does (`int(assumptions["fade_years"])`). Add it to the existing `assumptions` access at the top of `_ddm`.
- The guard `cost > terminal_growth` is sufficient — H-model never divides by `(r − g_sus)`.
- `spread = max(0.0, growth - terminal_growth)` makes the formula degenerate to single-Gordon-at-terminal-g when sustainable growth is already at or below terminal, which is the correct conservative behaviour.
- Keep the existing `cost <= terminal_growth` warning. Add a new warning string `"ddm_growth_below_terminal"` when `growth < terminal_growth` so the UI can surface why the DDM looks "flat" for shrinking dividend payers.
- Inputs payload (line 559-569) MUST gain `fade_years` and `h_factor` keys so the frontend can show what the model assumed.

### Acceptance for V13

Add tests in `core/tests/test_fundamentals.py` next to the existing DDM tests:

1. `test_ddm_h_model_collapses_to_terminal_gordon_when_growth_equals_terminal`
   - Snapshot with ROE / payout such that `_sustainable_dividend_growth` returns `terminal_growth`.
   - Assert `fair == dividend * (1 + terminal_growth) / (cost - terminal_growth)` within `1e-6`.

2. `test_ddm_h_model_lies_between_two_single_stage_gordons`
   - Snapshot with sustainable growth = 6 %, terminal = 3 %, cost = 10.5 %, dividend = 10.
   - Compute the three multiples above. Assert `gordon_terminal < ddm_fair < gordon_sustainable`.

3. `test_ddm_returns_none_when_cost_le_terminal_growth`
   - Assumptions with `cost_of_equity = 0.03`, `terminal_growth = 0.04`.
   - Assert `fair_value is None` and `"cost_of_equity_not_above_terminal_growth"` in warnings.

4. `test_ddm_inputs_expose_fade_years_and_h_factor`
   - Assert `inputs["fade_years"] == DEFAULT_ASSUMPTIONS["fade_years"]` and `inputs["h_factor"] == DEFAULT_ASSUMPTIONS["fade_years"] / 2.0`.

---

## Defect V14 — Residual income fade starts at year 1

### Where

`_residual_income` at `valuation.py:575-616`, the per-year loop:

```python
for year in range(1, fade_years + 1):
    fade = year / fade_years
    year_roe = roe * (1.0 - fade) + cost * fade
    residual_income = book * (year_roe - cost)
    ...
```

### Symptom

At `year = 1` with `fade_years = 5`, `fade = 0.20`. The ROE is already pulled 20 % of the way toward cost of equity in the very first projection year. The fade reaches `ROE = cost` at `year = fade_years`, so `RI = 0` from that year on. The continuing-value beyond the horizon is implicitly zero, which is consistent — but the fade **starts too early**.

### Why it matters

Textbook Ohlson RI is `B₀ + Σ PV(RI_t)` with **constant ROE for an explicit horizon**, then a fade (or terminal zero spread). Starting the fade in year 1 front-loads the convergence and systematically suppresses near-term residual income for any firm where `ROE > r`. For a stock like Managem in a high-ROE phase, this understates fair value by 15 – 30 %, which is the *exact* shape of the 950 vs 1 532 gap we are debugging.

### Fix recipe

Split the projection into two horizons. The simplest change that respects existing assumptions is to shift the fade so year 1 is fully at `roe`:

```python
fade = (year - 1) / fade_years   # year = 1 → fade = 0 (full ROE)
year_roe = roe * (1.0 - fade) + cost * fade
```

This change alone closes most of the gap and requires no new assumption keys. The terminal year is now `fade_years + 1`, where `fade = 1` and `RI = 0` — which matches the existing "no terminal value needed" invariant.

If Codex wants the proper two-horizon structure (explicit period at constant ROE, then fade), use this instead:

```python
explicit_years = int(assumptions.get("ri_explicit_years", 3))
total_years = explicit_years + int(assumptions["fade_years"])
for year in range(1, total_years + 1):
    if year <= explicit_years:
        year_roe = roe
    else:
        fade = (year - explicit_years) / float(assumptions["fade_years"])
        year_roe = roe * (1.0 - fade) + cost * fade
    residual_income = book * (year_roe - cost)
    pv_residual_income += residual_income / ((1.0 + cost) ** year)
    projected.append({"year": float(year), "roe": year_roe, "book_value": book, "residual_income": residual_income})
    book *= 1.0 + year_roe * retention
```

If Codex picks the two-horizon path, add `ri_explicit_years` to `DEFAULT_ASSUMPTIONS` (suggested default: **3**) and update `08-assumptions-and-defaults.md` accordingly. **Pick exactly one of the two fixes** and state which one in the PR description. Default recommendation: the simple `fade = (year - 1) / fade_years` change unless the team wants the explicit-horizon knob exposed to the UI.

### Acceptance for V14

Add tests in `core/tests/test_fundamentals.py` next to the existing RI tests:

1. `test_residual_income_year1_uses_full_roe`
   - Snapshot with `ROE = 0.15`, `cost = 0.105`, `fade_years = 5`.
   - Inspect `outputs["projected_residual_income"][0]`; assert `roe == 0.15` (not `0.15 × 0.8 + 0.105 × 0.2 = 0.141`).

2. `test_residual_income_reaches_zero_spread_at_horizon_end`
   - Same snapshot; assert `outputs["projected_residual_income"][-1]["roe"] == approx(cost)` and `["residual_income"] == approx(0.0)`.

3. `test_residual_income_strictly_higher_than_pre_v14_for_high_roe_firms`
   - Hard-code the pre-V14 expected value for `ROE = 0.15, cost = 0.105, payout = 0.5, fade_years = 5, BVPS = 100`.
   - Assert the post-V14 fair value is strictly greater. Document the pre / post numbers in a comment.

4. **Regression invariant:** `test_ddm_and_ri_agree_within_15pct_on_clean_inputs`
   - Synthetic snapshot: `ROE = 0.15`, `payout = 0.5`, `Dividend_Yield = 0.04`, `Price_to_Book = 1.5`, `current_price = 100`, `cost = 0.105`, `terminal_growth = 0.03`, `fade_years = 5`.
   - Compute DDM and RI fair values. Assert `abs(ddm - ri) / max(ddm, ri) <= 0.15`.
   - This test pins the gap that motivated brief 30. If it fails, V13 or V14 has regressed.

---

## What this brief does NOT change

- The other five valuation models (FCFF, FCFE, justified multiples, relative multiples, reverse DCF). Anything you touch outside `_ddm`, `_residual_income`, and the test file is out of scope and the PR will be rejected.
- The ensemble blender (`compute_valuation_ensemble`) and weights (`MODEL_BASE_WEIGHTS`). Brief 30 is methodology-level; ensemble weights stay as-is.
- The confidence cascade. Existing `_confidence(...)` calls stay; only the new warning strings introduced above are added.
- `DEFAULT_ASSUMPTIONS` apart from the optional `ri_explicit_years` knob if Codex picks the two-horizon RI fix.
- API response shapes — `inputs["fade_years"]` and `inputs["h_factor"]` are additive on a dict that is already passed through unchanged.

---

## Documentation updates required in the same PR

1. `docs/fundamentals-layer/06-valuation-models.md` §3 (DDM)
   - Replace the equation block with the H-model formula.
   - Update the worked example to the H-model output (the existing MAD 145 / 5.5 % yield case should be recomputed with `H = fade_years / 2 = 2.5`).
   - Remove the V2 callout (V2 is now superseded by V13's fix).

2. `docs/fundamentals-layer/06-valuation-models.md` §4 (RI)
   - Replace the equation block with the new loop (whichever variant Codex picks).
   - Update the Moroccan bank worked example so year 1 uses full ROE.
   - Remove the V3 callout (V3 is superseded by V14's fix).

3. `docs/fundamentals-layer/06-valuation-models.md` §5 (Justified Multiples) — **already updated; do not edit in this PR.**
   - The §5 doc now describes a *target* methodology that is **stricter than the code**: an H-model-equivalent conversion of the supernormal phase into a single scalar growth, plus a 70 / 30 weighted-median between justified P/B and justified P/E for financials. The current `_justified_multiples` uses the simpler `_justified_growth` average and an unweighted median.
   - **Codex MUST NOT** attempt to align `_justified_multiples` to the §5 spec in this brief. That is a separate work item (future brief 31) and is **out of scope** for brief 30.
   - If Codex sees a temptation to "also fix" justified multiples while it is in `valuation.py`: stop. Reject the temptation. The PR will be rejected if `_justified_multiples` or `_justified_growth` are touched.

4. `docs/fundamentals-layer/12-known-issues-and-limitations.md`
   - Mark V2 and V3 as **superseded by V13 / V14** in their headers; do not delete them.
   - Add V13 and V14 entries (this brief is the source).
   - Update the v3-status paragraph at the top to mention "H-model DDM" and "RI fade with full first-year ROE".

5. `docs/fundamentals-layer/21-codex-briefs-INDEX.md`
   - Add a row for brief 30 in the briefs table. Mark priority **P1** and rubric anchor `equity-research:model-update` + `financial-analysis:dcf-model`.

---

## Open questions

- Should V14 introduce `ri_explicit_years` (default 3) as a first-class assumption surfaced in the UI, or keep the simple `fade = (year - 1) / fade_years` fix? Brief 30 leaves the choice to Codex but the PR description must state which one and why.
- Should the H-model factor `H` be exposed as a separate assumption (`ddm_h_factor`) instead of derived from `fade_years / 2`? Default answer: **no** — derive it, keep the assumption surface small.

---

## Verification

Run from the repo root before declaring done:

```
python -m pytest core/tests/test_fundamentals.py -q
python -m pytest core/tests/ -q
```

Both suites must pass. PR description must include:

- The actual line numbers of `_ddm` and `_residual_income` after this change (they may shift).
- Which V14 variant was chosen (simple shift or two-horizon).
- The pre/post fair-value numbers on Managem to confirm the headline 1 532 / 950 gap closes to within 15 %.
