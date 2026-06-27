# 31 — Codex brief: Valuation over-statement remediation (desk-grade fair values)

> **Status.** Plan-only brief for Codex. Claude reviewed the full v3 valuation + ensemble + scoring stack against (a) the engine's own integrity behaviour and (b) the canonical IB methodology encoded in the `financial-analysis:dcf-model` and `financial-analysis:comps-analysis` plugin skills. The DCF/comps references **confirm** every fix below: median (not average) for peer aggregation, mid-cycle margin normalization for cyclicals, exclusion/flagging of >2σ outliers, TV 50–70 % of EV, and 7–9 % WACC for stable names.
>
> **Field symptom.** Ordinary deep-value names print **+200 % to +500 % upside**. Reproduced in-engine: a normal industrial with a one-off earnings-spike year (spot PER 3.0×, spot ROE 27.5 %) produces an ensemble fair value of **+296 %**, driven by two unbounded re-rating models that together hold **63 % of ensemble weight**. The relative-multiples model — the single least trustworthy output — received the **largest** single weight (0.346) *because* it had the most peer multiples available.
>
> **Root causes (all four compound):**
> 1. Spot, un-normalized ROE/earnings flow straight into `justified_multiples`, `relative_multiples`, and the `value` scoring pillar.
> 2. Re-rating implied prices are uncapped (`current_price × peer/own` with no winsorization).
> 3. The ensemble central estimate is a **weighted arithmetic mean** with no outlier rejection, and re-rating models carry near-DCF weight.
> 4. "Confidence" measures **data availability**, not model reliability or output dispersion — so inflated targets still read "medium/high" and become BUYs.
>
> **Plan-only.** This brief tells Codex *what* to change. Do not re-derive the math; the equations and bounds below are the contract.
>
> **Sanctioned exception to the "do not touch the engine" rule (index 21).** Scoped to the functions named below in `valuation.py`, plus one assumption-set migration and the `value`-pillar input in `scoring.py`. Nothing else in the engine changes.

---

## Files Codex MUST read first

1. `core/quant_core/fundamentals/valuation.py` — confirm current line numbers for `_relative_multiples`, `_justified_multiples`, `_justified_growth`, `compute_valuation_ensemble`, `_data_quality`, `_confidence`, `MODEL_BASE_WEIGHTS`, `DEFAULT_ASSUMPTIONS`. Cite the actual lines in the PR description.
2. `core/quant_core/fundamentals/scoring.py` — `_score_group`, `VALUE_METRICS`, `_trailing_average` (already exists), `smoothing` block.
3. `docs/fundamentals-layer/06-valuation-models.md` §5 (relative), §6 (justified), §7 (ensemble) — worked examples are the regression targets.
4. `docs/fundamentals-layer/30-codex-ddm-ri-corrections.md` — same brief style; `_justified_growth` is shared with that work, do not regress it.
5. `core/tests/test_fundamentals.py` — land new tests beside the existing valuation/ensemble tests.

If any cited line number has shifted, **report the new line in the PR description and proceed** — do not stop.

---

# PHASE 1 — Correctness blockers (one PR per defect, ship in order)

## Defect O1 — Re-rating models consume spot, un-normalized inputs

### Where
- `_justified_multiples` at `valuation.py:1529` — `roe = _ratio(snapshot.metrics.get("ROE"))`, `payout = _ratio(...)`.
- `_relative_multiples` at `valuation.py:1597` — `own = _positive(snapshot.metrics.get(metric))` for PER / P/B / P/S.

### Symptom
A single cyclical-peak or one-off year sets ROE = 27.5 % (vs ~18 % through-cycle) or depresses spot PER to 3.0× (vs ~12× normalized). Justified P/B = `(ROE − g)/(ke − g)` then prints 6.1× instead of ~3.5×; relative PER target prints `100 × 15.5/3.0 = 511` instead of `100 × 15.5/12 = 129`.

### Fix recipe
Add a normalization helper (3-year trailing average, history-first, snapshot fallback). The trailing helper already exists in `scoring.py:221`; mirror it locally in `valuation.py` against the `history: list[AnnualMetricRow]` already passed to these models.

```python
def _normalized_roe(snapshot, history):
    """3y trailing ROE from history; fall back to spot snapshot ROE."""
    trailing = _trailing_average([v for v in (_ratio(x) for x in _metric_series_any(history, "ROE")) if v is not None], window=3)
    if trailing is not None:
        return trailing, "roe_3y_trailing"
    spot = _ratio(snapshot.metrics.get("ROE"))
    return spot, "roe_spot_fallback"
```

- `_justified_multiples` uses `_normalized_roe(...)` for the `roe` that feeds `justified_pb` and `sustainable_growth`.
- `_relative_multiples` denominator (`own`) for PER and P/S uses **normalized earnings/sales**: prefer 3y-average net income / revenue from `history` to rebuild the own multiple as `market_cap / avg_earnings`; fall back to the spot multiple with a `relative_own_multiple_spot_fallback` warning. (P/B uses book value, which is a stock not a flow — keep spot.)
- Record the source label in `inputs` (`roe_source`, `own_multiple_basis`).

### Acceptance (tests beside existing in `test_fundamentals.py`)
- `test_justified_pb_uses_trailing_roe_not_spot` — a snapshot whose latest ROE is 2× its 3y average yields justified P/B within 10 % of the trailing-ROE value, not the spot value.
- `test_relative_per_target_uses_normalized_earnings` — a one-off earnings spike (NI 2× trend) moves the relative PER target by < 15 %.
- Unleveraged steady-state firm (spot == trailing) is unchanged.

---

## Defect O2 — Re-rating implied prices are uncapped

### Where
- `_relative_multiples` implied loop `valuation.py:1597-1611`, median at `:1614`.
- `_justified_multiples` implied prices `valuation.py:1550, 1555`, median at `:1558`.

### Symptom
No bound on `implied = current_price × target/own`. A single distorted multiple → +400 % implied price flows into the median.

### Fix recipe
Clamp every per-multiple implied price to a band of current price before taking the median, and flag when the clamp binds. The comps skill's *"flag/exclude values >2σ"* is the canonical justification.

```python
IMPLIED_PRICE_FLOOR_MULT = 0.40   # add to module constants
IMPLIED_PRICE_CEIL_MULT  = 2.50

def _clamp_implied(price, current_price, label, warnings):
    if current_price is None or price is None:
        return price
    lo, hi = IMPLIED_PRICE_FLOOR_MULT * current_price, IMPLIED_PRICE_CEIL_MULT * current_price
    clamped = min(hi, max(lo, price))
    if clamped != price:
        warnings.append(f"{label}_implied_price_clamped")
    return clamped
```

Apply to each entry of `implied[...]` / `implied_prices[...]` before `median(...)`. Keep the **raw** (unclamped) values in `outputs["implied_prices_raw"]` for transparency.

### Acceptance
- `test_relative_implied_prices_clamped_to_band` — a peer/own ratio of 7× yields an implied price = `2.5 × current_price` with a `*_implied_price_clamped` warning.
- `test_justified_implied_prices_clamped_to_band` — same for justified P/B and P/E.
- Within-band implied prices are unchanged and emit no warning.

---

## Defect O3 — Ensemble uses a weighted mean with no outlier control; re-rating models over-weighted

### Where
`compute_valuation_ensemble` at `valuation.py:1772`; central estimate `:1811-1818`; `MODEL_BASE_WEIGHTS` at `valuation.py:346`.

### Symptom
`fair_base = Σ(fair·w)/Σw` (arithmetic mean). With models spanning 174→585, the mean = 396; the **weighted median** = 294 and the intrinsic-only median = 273. Relative + justified held 63 % of weight.

### Fix recipe
Two changes:

**(a) Central estimate → weighted median** (comps skill: *"should be median, not average"*). Keep the mean as a reported diagnostic.

```python
def _weighted_median(pairs):  # pairs = [(value, weight), ...]
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    if total <= 0: return None
    acc = 0.0
    for value, w in ordered:
        acc += w
        if acc >= total / 2.0:
            return value
    return ordered[-1][0]
```

`fair_value_base = _weighted_median(usable_pairs)`; expose `fair_value_mean` (old formula) in `model_weights`/ensemble diagnostics. The Monte Carlo overlay re-centres on the median.

**(b) Cap the combined weight of the re-rating family.** After computing per-model weights, if `relative_multiples + justified_multiples` exceeds `RELATIVE_FAMILY_WEIGHT_CAP = 0.25` of total, scale both down proportionally so intrinsic models retain ≥ 75 %. Emit `relative_family_weight_capped`.

### Acceptance
- `test_ensemble_central_estimate_is_weighted_median` — on a fixture with one extreme model, base equals the weighted median, not the mean; both are exposed.
- `test_relative_family_weight_capped_at_25pct` — relative+justified combined weight ≤ 0.25 after normalization.
- `test_ensemble_unchanged_when_models_agree` — tight-cluster fixture: median ≈ mean, no cap warning.

---

## Defect O4 — Confidence ignores model dispersion

### Where
`_data_quality` at `valuation.py:568`; ensemble confidence at `valuation.py:1819`; consumed by `derive_recommendation` (`services/api/app/services/fundamentals.py:250`).

### Symptom
A 3.4× spread across models returned ensemble confidence 0.56 ("medium") → auto-BUY. Dispersion is the uncertainty signal and is currently ignored.

### Fix recipe
Multiply the ensemble confidence by a dispersion factor based on the coefficient of variation of usable model fair values:

```python
import statistics
def _dispersion_factor(fair_values):
    vals = [v for v in fair_values if v and v > 0]
    if len(vals) < 2: return 1.0
    cv = statistics.pstdev(vals) / statistics.mean(vals)
    return max(0.25, 1.0 - cv)          # cv≈0 → 1.0 ; cv≈0.75 → ~0.25 floor
```

`confidence_score *= _dispersion_factor(usable_fair_values)`; surface `model_dispersion_cv` and `dispersion_factor` on the ensemble. Do **not** change per-model `_data_quality`; this is an ensemble-level overlay so per-model rows stay interpretable.

### Acceptance
- `test_ensemble_confidence_penalized_by_dispersion` — the 174→585 repro fixture yields confidence ≈ 0.3 ("low") and `derive_recommendation` returns HOLD/NR, not BUY.
- `test_tight_cluster_confidence_unpenalized` — agreeing models keep confidence ≈ the pre-overlay value.

---

# PHASE 2 — Discount-rate regime + publication gating (one migration PR + one engine PR)

## O5 — Validate the risk-free rate (assumption-set migration, NOT source edit)
- **Where:** `risk_free_rate=0.029` in `DEFAULT_ASSUMPTIONS` (`valuation.py:26`) → WACC 7.3 %, at the very floor of the DCF skill's 7–9 % "stable" band.
- **Action:** verify 2.9 % against the current BDT 10-year (secondary market). If the curve is ~3.5–4 %, set the desk-scope `FundamentalAssumptionSet` (`scope_type="desk", scope_key="GLOBAL"`) via Alembic migration — do not edit source defaults. Document source + date in `08-assumptions-and-defaults.md`.
- **Acceptance:** universe WACC distribution lands in 8.5–10.5 %; migration is reversible; `_apply_live_cost_of_capital` provenance shows the desk override.

## O6 — Gate publication on integrity failure
- **Where:** `_apply_integrity_report` (`valuation.py:1707`) only haircuts confidence today; `derive_recommendation` (`fundamentals.py`).
- **Action:** when `IntegrityReport.overall_status == "fail"`, set the ensemble recommendation to **"NR" (Not Rated)** and suppress the headline target (keep per-model rows for diagnostics). A failed balance sheet must not produce a BUY.
- **Acceptance:** `test_failed_integrity_returns_not_rated` — fail-status report ⇒ recommendation "NR", `fair_value_base` flagged `withheld_integrity_fail`.

---

# PHASE 3 — Methodology depth (separate PRs, lower urgency)

- **O7 — Promote trailing smoothing into scoring pillars.** Use `_trailing_average` (`scoring.py:221`) for the cyclical-sensitive `value`/`quality` metrics in `_score_group`, not just the `diagnostics.smoothing` block. Acceptance: a cyclical at trough vs peak no longer flips pillar score by > 1 quintile.
- **O8 — Full equity bridge.** Extend `_net_debt_bridge` (`valuation.py:738`, used `:1178`) and the FCFF/relative EV→equity steps to surface **minority interest, associates/investments, pension & lease obligations** (handle if present, else emit an explicit `bridge_simplified_net_debt_only` note). The DCF skill lists these as required "other adjustments".
- **O9 — Report justified multiples as multiples.** Add `implied_pb` / `implied_pe` and the implied-vs-current multiple delta to `outputs`, so the desk reads a re-rating multiple, not only a re-rated price.

---

# PHASE 4 — Desk-presentation surfacing (UI, after engine PRs)

**2026-06-02 implementation note:** O10-O12 are now represented in the fundamental tear sheet. The valuation summary includes the football-field exhibit, a WACC/cost-of-equity build-up panel with raw Ke, Ke floor and floor-binding status, and a coverage/rating panel with `overall_coverage_pct`, per-pillar score scope, `model_dispersion_cv`, `dispersion_factor`, mean-vs-median diagnostics, warning chips, and the rating gate text. The methodology doc now pins the BUY/HOLD/SELL/NR thresholds and conviction ladder.

- **O10 — Reproducibility panel.** Surface the existing `cost_of_capital_build_up` (WACC build-up, beta source/method/R²/n_obs, `terminal_growth_basis`, `model_weights`, dispersion CV, any clamp/cap warnings) as a one-click "how this target was derived" exhibit.
- **O11 — Coverage & rating transparency.** Show `overall_coverage_pct` + per-pillar `scope` (sector/market/insufficient), and pin the BUY/HOLD/SELL/NR thresholds (`fundamentals.py:250`) and conviction ladder in `13-methodology-and-sources.md` and on the tear sheet.
- **O12 — Football-field exhibit.** Assemble the per-model fair-value range + Monte Carlo band + sensitivity grids (all already computed) into a single range chart.

---

## Sequencing & PR discipline

| Phase | PRs | Touches | Gate |
|---|---|---|---|
| 1 | O1, O2, O3, O4 (4 PRs) | `valuation.py` + tests only | each PR green before next |
| 2 | O5 (migration), O6 (engine+API) | assumption set, gating | after Phase 1 |
| 3 | O7, O8, O9 | `scoring.py`, `valuation.py` | after Phase 2 |
| 4 | O10–O12 | frontend | after engine stable |

- One defect = one PR = one test file addition + the matching `06-valuation-models.md` worked-example update.
- Do not bundle O1+O2+O3. The regression invariant for Phase 1 is: **the repro fixture (spot PER 3.0×, spot ROE 27.5 %, one-off NI spike) moves from +296 % ensemble upside to ≤ +120 %, confidence "low", recommendation HOLD/NR.** Pin this as `test_overvaluation_repro_fixture_is_contained`.

## Cross-references
- IB methodology validation: `financial-analysis:dcf-model` SKILL.md (TV 50–70 % of EV; mid-cycle normalization; minority/pension/lease bridge; WACC 7–9 % stable) and `financial-analysis:comps-analysis` SKILL.md (median not average; flag/exclude >2σ outliers; normalized margins; "better 3 perfect comps than 6 questionable").
- Prior engine corrections: brief 30 (DDM/RI). Issue history: `12-known-issues-and-limitations.md`.
