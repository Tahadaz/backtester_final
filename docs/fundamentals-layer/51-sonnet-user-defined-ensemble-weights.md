# 51 — User-defined ensemble model weights (desk override), implementer: Sonnet

> **Status. Plan-only.** No code to be written by the author of this plan. Builds directly
> on commit `f836b55` (brief 44 + the backend half of this feature). The combiner already
> *accepts* manual weights; this brief makes them **reachable and editable by the user** and
> surfaces the active weighting mode in the UI.
>
> **Why this exists.** The optimal ensemble model weighting is a desk judgment, not a
> provable constant (brief 44's anti-collapse guard "fixed" one name and regressed eight —
> evidence that no single auto-heuristic is right). The product answer is to let the desk pin
> the weighting per symbol/scenario when it disagrees with the auto (IC / reliability) blend.

---

## 0. What already exists (commit `f836b55`) — read before touching anything

In `core/quant_core/fundamentals/valuation.py`:
- `compute_valuation_ensemble(symbol, scenario, valuations, *, weight_overrides: dict[str,float] | None = None)` — when `weight_overrides` has positive weights for **usable** models, they take precedence over the IC/reliability auto-weighting, are renormalised over the usable set, and emit the warning `ensemble_user_defined_weights` (+ `ensemble_user_weights_partial_coverage` when only some usable models are weighted). Overrides apply **only to the usable set** (post severe-exclusion + cross-model outlier rejection) — a user **cannot** force a broken model back in. **Do not change this semantics.**
- `_ensemble_weight_overrides_from_assumptions(assumptions)` — reads `ensemble_weight_<model>` scalar keys **and** an `_ensemble_weight_overrides` dict from an assumptions mapping; keeps only positive weights; returns `None` if none.
- Threaded into the two call sites that matter: core `compute_symbol_valuations` (internal ensemble) and service `recompute_symbol_valuations` (the **persisted** ensemble, `services/api/app/services/fundamentals.py` ~4574).
- Unit tests already cover the combiner behaviour: `core/tests/test_ensemble_reliability_weighting.py::test_user_defined_weights_override_auto_weighting` and `::test_user_weights_cannot_resurrect_an_excluded_model`.

**The gap this brief closes:** the `ensemble_weight_<model>` keys are **not registered** in `DEFAULT_ASSUMPTIONS`, so the user-facing override API rejects them — `clean_assumption_override_values` (`services/api/app/services/fundamentals.py:3701`) raises `unknown assumption key` for any key not in `DEFAULT_ASSUMPTIONS`. So today the feature is only reachable programmatically, never by a user.

---

## 1. Files Sonnet must read first (gate — confirm current line numbers, the tree shifts)

1. `core/quant_core/fundamentals/valuation.py`:
   - `DEFAULT_ASSUMPTIONS` (~`:69`+), its **derivation/source registry** block (~`:397–490`, the dict of `{key: {label, unit, group, derivation, source, plausible_range}}`), `_ASSUMPTION_META_OVERRIDES` (`:111`), `ASSUMPTION_META` (`:561`, auto-generated per `DEFAULT_ASSUMPTIONS` key — `editable: True` by default).
   - `ENSEMBLE_INTRINSIC_METHOD_MODELS` / `ENSEMBLE_MARKET_METHOD_MODELS` (`:616–623`), `VALUATION_MODEL_ORDER`.
   - `compute_valuation_ensemble` + `_ensemble_weight_overrides_from_assumptions` (already committed — read, don't rewrite).
2. `services/api/app/services/fundamentals.py`: `clean_assumption_override_values` (`:3701`), `make_overrides_loader` (`:3720`), `active_assumptions_for`, `recompute_symbol_valuations` (`:4409`; the persisted ensemble call passes overrides).
3. `services/api/app/routers/fundamentals.py`: `PUT /{symbol}/assumptions/{scenario}/override` (`:3187`), `_assumption_bundle` (`:714`), `get_stock_assumptions` (`:3156`), the `ASSUMPTION_META` payload (`:3765`).
4. `frontend/components/strategy/signal-fundamental-view.tsx`: the **Hypotheses** tab (`DetailTab "assumptions"` `:44`, tab entry `:307`), per-model `assumptionKeys` arrays (`:359–419`), the per-model `weight` / `weightSource` display (`:77`, `:102` — already shows `"model weights" | "equal weights" | "ic fallback"`), `updateFundamentalAssumptions` / `updateFundamentalDeskAssumptions` (`:15–16`).
5. `frontend/lib/api.ts`: `FundamentalEnsembleSchema` (`model_weights` `:6068`, `warnings` nearby), `FundamentalAssumptionMetaSchema` (`:6425`), `updateFundamentalAssumptions` (`:6910`).

> If a cited line shifted, report the new line and proceed. Do not guess.

---

## 2. Phase A — Backend: register the six override keys (small, regression-critical)

In `valuation.py`:
1. Add to `DEFAULT_ASSUMPTIONS`, one per ensemble model, **default `0.0`** (0 = use auto weighting):
   `ensemble_weight_fcff_dcf`, `ensemble_weight_fcfe_dcf`, `ensemble_weight_ddm`,
   `ensemble_weight_residual_income`, `ensemble_weight_justified_multiples`,
   `ensemble_weight_relative_multiples`. Derive the model list from
   `ENSEMBLE_INTRINSIC_METHOD_MODELS | ENSEMBLE_MARKET_METHOD_MODELS` so it can't drift.
2. Add matching entries to the **derivation/source registry** block and/or
   `_ASSUMPTION_META_OVERRIDES`: `group: "ensemble_weights"`, `unit: "ratio"`,
   `plausible_range: [0.0, 1.0]`, `scope: "desk"`, `editable: True`, French label
   (e.g. `"Poids ensemble — FCFF DCF"`). Derivation: *"Poids manuel desk pour ce modèle
   dans l'ensemble. 0 = pondération automatique (IC puis fiabilité). Les poids positifs
   sont renormalisés sur les seuls modèles utilisables (les modèles exclus pour qualité de
   données ne peuvent pas être réintroduits)."* Source: *"Brief 51 desk weighting policy"*.
3. **Regression gate:** with all six at the `0.0` default, `_ensemble_weight_overrides_from_assumptions`
   must return `None` and the ensemble output must be **byte-identical** to pre-change auto
   weighting. Add/extend a test asserting this.

No other backend math changes. `clean_assumption_override_values`, `make_overrides_loader`,
`active_assumptions_for`, and the persisted recompute path then accept and thread the keys
**for free** because they validate against `DEFAULT_ASSUMPTIONS`.

---

## 3. Phase B — API: expose the active weighting mode

The ensemble already records the mode implicitly in `warnings_json`
(`ensemble_user_defined_weights`, `ic_weight_fallback_no_coverage`,
`ic_weight_fallback_for_uncovered_models`). Either:
- (preferred) add a derived `weight_mode: "user" | "ic" | "ic_fallback" | "reliability"`
  string to the ensemble payload (`_assumption_bundle` / the ensemble serialiser), computed
  from the warnings + `model_weights`, **or**
- (minimal) leave the payload as-is and let the frontend derive the mode from the existing
  warnings array.

Pick one; document the choice. Do **not** add a second source of truth that can disagree
with the warnings.

---

## 4. Phase C — Frontend: editor + mode badge (`signal-fundamental-view.tsx`)

1. In the **Hypotheses** tab add a **"Pondération de l'ensemble"** section that lists the
   symbol's **usable** valuation models (those with a non-null `weight` in the ensemble
   payload) with one numeric input each, range `0–1`, blank/0 = automatique. Show the current
   auto weight as the placeholder so the user sees what they are overriding.
2. On save, call `updateFundamentalAssumptions` (per-symbol) — and respect the existing
   desk-vs-symbol scope control if present (`updateFundamentalDeskAssumptions`) — writing the
   `ensemble_weight_<model>` keys. Omit/clear a key to fall back to auto for that model.
3. Add a small **mode badge** near the model-weights table: *Auto (IC)* / *Auto (fiabilité)* /
   *Défini par l'utilisateur*, driven by Phase B. Extend the existing `weightSource` union
   (`:102`) with `"user weights"`.
4. Client-side validation: weights ≥ 0; if every input is empty/0, send no override keys
   (or send 0s) so the result is auto. Show a normalised-percent preview so the user sees the
   effective split before saving.

---

## 5. Phase D — Tests & acceptance

1. `python -m pytest core/tests/ -q` and the touched API tests pass.
   *(Note: run from the full working tree — see §7; HEAD alone does not import.)*
2. Backend: extend `services/api/tests/test_fundamentals_assumption_overrides.py` — the
   override `PUT` accepts `ensemble_weight_relative_multiples=1.0`; a recompute then yields a
   headline equal to the relative model and `ensemble_user_defined_weights` in the warnings;
   clearing the override reverts to auto.
3. Regression: all-default (0.0) ensemble == pre-change auto ensemble (Phase A gate).
4. Frontend: `tsc` 0 errors; if the repo has component tests, a render test of the new editor.
5. Acceptance demo: in the UI, pin `relative_multiples` to 1.0 for one symbol → headline
   follows the comp + mode badge reads *Défini par l'utilisateur*; clear it → reverts.

---

## 6. What NOT to do

- Do **not** let overrides bypass severe-exclusion or cross-model outlier rejection — they
  apply to the **usable** set only. Keep it that way.
- Do **not** change the auto weighting math (IC × reliability, class representatives, review
  gate). This is an opt-in override layered on top.
- Do **not** register the keys anywhere other than `DEFAULT_ASSUMPTIONS` — the override
  validator (`clean_assumption_override_values`) and the assumption-meta payload both key off it.
- Do **not** normalise the stored override values to sum to 1 on write; store the raw desk
  inputs and let the combiner renormalise over the usable set (a model may be excluded for one
  vintage and usable for another).

---

## 7. Prerequisite / hygiene (separate from this feature — flag to the user, do not bundle)

Branch `chore/repo-cleanup` HEAD is **pre-existingly inconsistent**:
`core/quant_core/fundamentals/signal_backtest.py` (committed) imports `assign_quintiles`
from `core/quant_core/research/stats/portfolio_stats.py`, but that helper (and
`forward_return` / `rebalance_dates` / `quintile_return_summary` / `equity_curve_with_stats`)
lives only in the **uncommitted** in-flight tree — so `core.quant_core.fundamentals` does not
import at HEAD in isolation (a `git worktree` at the commit fails test collection). The full
working tree is consistent. Commit the `portfolio_stats` helper-extraction (+ its
`cross_sectional.py` / `signal_backtest.py` callers) as **its own commit** to un-break HEAD
before this work is shared. This is unrelated to brief 51.
