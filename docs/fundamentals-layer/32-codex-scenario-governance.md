# 32 — Codex brief: Scenario governance (base-anchored rating, no market-anchoring, documented probabilities)

> **Status.** Plan-only brief for Codex. Claude reviewed how the Bear/Base/Bull scenario switcher behaves end-to-end. The three scenarios are computed **desk-wide** (one `FundamentalEnsembleResult` per scenario) and the switcher is a **URL view toggle** (`?scenario=`), not a per-user preference — that part is correct and standard (the `financial-analysis:dcf-model` skill mandates a Bear/Base/Bull case selector). Four governance defects keep it from being desk-grade:
>
> 1. **The headline rating/target follows the toggled scenario.** `derive_research_overlay` is built from the *selected* scenario's ensemble, so flipping to Bull changes the BUY/HOLD/SELL call and the target price the user quotes. The house call must be anchored to **base**; bear/bull are the *risk band*, not selectable headlines.
> 2. **The "auto" scenario mode anchors to the market.** `_auto_scenario_from_ensembles` picks the scenario whose fair value is closest to the current price — circular: it makes the model agree with the market by construction.
> 3. **Scenario probabilities are hardcoded in the frontend** (0.25 / 0.55 / 0.20) and drive a probability-weighted "expected value" with no provenance.
> 4. **Bear/bull are presented as equally-valid selectable answers** rather than a labelled downside/upside band around the base case.
>
> **Plan-only.** This brief tells Codex *what* to change; the contracts below are binding. This brief is **cross-cutting** (engine defaults + API overlay + frontend) — keep the phases separate.
>
> **What this brief does NOT change:** the desk house deltas in `SCENARIO_DEFAULT_OVERRIDES` (bear/base/bull assumption shifts) are correct and stay as-is; the `scenario_hierarchy_checks` guardrail (bull ≥ base ≥ bear) stays. We are not re-deriving scenario economics — only fixing *which* scenario drives the headline and *where* the probabilities live.

---

## Files Codex MUST read first

1. `services/api/app/routers/fundamentals.py` — confirm line numbers for `_scenario_or_auto` (~448), `_auto_scenario_from_ensembles` (~455), and the two `derive_research_overlay(...)` call sites (~1772 detail, ~2229 list/summary). Cite actual lines in the PR.
2. `services/api/app/services/fundamentals.py` — `derive_research_overlay`, `derive_recommendation`, `derive_conviction`, `derive_revision_direction` (~233–348).
3. `core/quant_core/fundamentals/valuation.py` — `DEFAULT_ASSUMPTIONS` (~25), `SCENARIO_DEFAULT_OVERRIDES` (~303), `ASSUMPTION_META` block (~287) for where new keys must be registered.
4. `frontend/components/strategy/signal-fundamental-view.tsx` — `scenarioFromQuery` (~1365), the hardcoded probabilities and `expected` (~1841–1878), `buildScenarios` (~1781), the scenario switcher buttons (~4372), and `resolvedScenario` / `scenarioParam` (~5123, ~5207).
5. `docs/fundamentals-layer/25-codex-scenarios-per-symbol.md` and `08-assumptions-and-defaults.md` — scenario assumption-set scoping; new keys must follow the same registry pattern.

If any cited line number has shifted, **report the new line in the PR description and proceed**.

---

# PHASE A — Backend: base-anchor the headline, kill market-anchoring (one PR)

## Defect G1 — Headline rating/target follows the toggled scenario

### Where
`services/api/app/routers/fundamentals.py` — both `derive_research_overlay(... ensemble=ensemble ...)` calls (~1772, ~2229), where `ensemble` is the *selected* scenario's ensemble (`scenario = _scenario_or_auto(scenario)`).

### Symptom
Viewing a name at `?scenario=bull` returns a different `recommendation`, `conviction`, `target_price`, and `revision_direction` than `?scenario=base`. The user can flip to the most flattering case and quote it as "the call." There is no single house rating.

### Fix recipe
Split **headline** (always base) from **displayed scenario detail** (the toggle):

- Resolve the **base** ensemble independently of the query scenario and feed *that* to `derive_research_overlay`. The recommendation / conviction / target_price / revision_direction are **always** the base-scenario values.
- The selected scenario still drives the *displayed* ensemble block, per-model breakdown, fair-value range, and sensitivity — i.e. `detail.ensemble` stays the selected scenario, but the research overlay is base-anchored.
- Add the base values explicitly to the payload so the UI never has to infer them:

```python
HEADLINE_SCENARIO = "base"

base_ensemble = ensembles_by_scenario.get(HEADLINE_SCENARIO) or ensemble  # fallback if base missing
overlay = derive_research_overlay(
    db, symbol=symbol, scenario=HEADLINE_SCENARIO, ensemble=base_ensemble,
    import_row=import_row, current_price=current_price, free_float_pct=free_float_pct,
)
# expose: overlay["headline_scenario"] = HEADLINE_SCENARIO
# expose alongside selected-scenario detail: viewed_scenario = scenario
```

If the base ensemble is missing for a name (data gap), the headline is `recommendation="NR"` — do **not** silently fall back to a non-base scenario for the rating.

### Acceptance (`services/api/tests/`)
- `test_headline_recommendation_is_base_anchored_across_scenarios` — GET detail with `scenario=bull` and `scenario=bear` return the **same** `recommendation`, `target_price`, `conviction` as `scenario=base`; only `ensemble` / per-model detail differs.
- `test_headline_nr_when_base_ensemble_missing` — base ensemble absent ⇒ headline `recommendation="NR"`, even if bull/bear ensembles exist.

---

## Defect G2 — "auto" scenario mode anchors to the market price

### Where
`_scenario_or_auto` (~448) and `_auto_scenario_from_ensembles` (~455), which selects the scenario minimizing `abs(fair_value − current_price)`.

### Symptom
An unspecified/`auto` scenario resolves to "whichever case best matches today's price." That is anchoring: the model is made to agree with the market, defeating the purpose of an independent house base case, and inflating apparent hit-rate.

### Fix recipe
- `_scenario_or_auto` defaults any unspecified/`auto` request to **`base`**. Remove `auto` from accepted headline-driving values (or redefine it to return `"base"` and emit a deprecation note in the response).
- Repurpose `_auto_scenario_from_ensembles` **only** as a read-only diagnostic — e.g. `market_implied_scenario` surfaced in the response for color ("the market is currently pricing closest to our Bear case") — and ensure nothing in the headline/recommendation path consumes it.

### Acceptance
- `test_unspecified_scenario_resolves_to_base` — request with no `scenario` (and `scenario=auto`) drives the headline from base, not the closest-to-price scenario.
- `test_market_implied_scenario_is_diagnostic_only` — `_auto_scenario_from_ensembles` output appears only as a labelled diagnostic field, never as the rating driver.

---

# PHASE B — Engine + API: documented, overridable scenario probabilities (one PR)

## Defect G3 — Probabilities hardcoded in the frontend

### Where
`frontend/.../signal-fundamental-view.tsx:1841/1849/1857` (`probability: 0.25 / 0.55 / 0.20`), expected value at `:1878`.

### Symptom
The probability-weighted "expected value" is built from magic numbers in a UI component, with no provenance, no override path, and no sum-to-1 guarantee.

### Fix recipe
Move probabilities into the assumption registry as first-class, scenario-scopable, documented assumptions:

- Add to `DEFAULT_ASSUMPTIONS` (`valuation.py`):
  ```python
  "scenario_probability_bear": 0.25,
  "scenario_probability_base": 0.55,
  "scenario_probability_bull": 0.20,
  ```
  Register each in `_ASSUMPTION_META_OVERRIDES` (group `"scenario"`, unit `"percent"`, plausible_range `[0.0, 1.0]`, source `"desk scenario policy"`).
- Validate sum ≈ 1.0 (tolerance 1e-6) wherever assumptions are resolved; if a desk/sector/symbol override breaks the sum, **renormalize** and emit a `scenario_probabilities_renormalized` warning rather than silently trusting them.
- Surface the resolved probabilities in the valuation/assumptions API payload (alongside `cost_of_capital_build_up`) so the frontend reads them, not constants.
- Frontend: `buildScenarios` consumes the API probabilities; the probability-weighted figure is labelled **"Valeur pondérée par scénario (probabilités maison)"** and the per-card `P=` reflects the resolved values.

### Acceptance
- `test_scenario_probabilities_in_defaults_sum_to_one`.
- `test_scenario_probabilities_renormalized_when_override_breaks_sum`.
- API contract test: the detail payload exposes `scenario_probabilities` and the frontend no longer holds probability constants (grep guard in the FE test).

---

# PHASE C — Frontend: base headline + bear/bull as a labelled risk band (one PR)

## Defect G4 — Bear/bull presented as selectable headlines

### Where
Valuation tab in `signal-fundamental-view.tsx` — scenario switcher (~4372), headline/recommendation rendering, `resolvedScenario` (~5207).

### Fix recipe
- The **rating chip + target price are always the base headline** (from Phase A's `headline_scenario` payload) and do **not** change when the user toggles scenarios.
- The scenario switcher changes only the *detail view* (displayed ensemble, per-model breakdown, sensitivity grid). When the viewed scenario ≠ base, show a clear banner: **"Vous consultez le scénario {X} (vue maison) — la recommandation reste ancrée au scénario de base."**
- Render bear/base/bull as a **labelled band** (downside / central / upside) around the base target — base is the anchor, bear/bull are cases with their probabilities. Reuse the existing football-field/range exhibit if O12 (brief 31) lands first.

### Acceptance (FE component test)
- Toggling `scenario` does not change the rendered recommendation chip or headline target.
- A non-base scenario shows the "vue maison / ancrée au base" banner.
- Scenario cards display API-sourced probabilities.

---

## Sequencing & PR discipline

| Phase | PR | Touches | Gate |
|---|---|---|---|
| A | G1 + G2 | `routers/fundamentals.py`, `services/fundamentals.py` + API tests | highest impact, ship first |
| B | G3 | `valuation.py` defaults/meta + API payload + FE read + tests | after A |
| C | G4 | `signal-fundamental-view.tsx` + FE tests | after A & B |

- Backend-first (A, B) before the FE presentation change (C), per house convention.
- One defect cluster = one PR + its tests + the matching update to `08-assumptions-and-defaults.md` (G3 adds three keys) and `06-valuation-models.md` §7 (scenario governance note).
- **Regression invariant for Phase A:** `recommendation`, `target_price`, and `conviction` are byte-identical across `scenario=base|bear|bull|auto` for the same name and import. Pin as `test_headline_invariant_across_scenarios`.

## Cross-references
- IB methodology: `financial-analysis:dcf-model` SKILL.md — Bear/Base/Bull case selector is canonical; **base = the house call**, bear/bull = the range. Anchoring valuation to the prevailing market price is explicitly an anti-pattern.
- Related: brief 31 (over-statement remediation; O12 football-field is the natural home for the bear/bull band), brief 25 (per-symbol scenario assumption sets — the new probability keys follow the same scoping).
- Guardrail kept: `scenario_hierarchy_checks` in `projection.py` (bull ≥ base ≥ bear).
