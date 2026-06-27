# Fundamental engine — IB-grade remediation + modelling-transparency UI plan

**Status (2026-06-02):** Phases 1–5, Phase 2B, Phase 2C, and Part B are implemented in the
working tree. Phase 0 (MASI data) is RESOLVED — data present, 144 betas computed. The valuation
engine now uses per-model terminal growth, personalized capital weights, and synthetic-spread cost
of debt; the Hypothèses UI has per-model sections and explicit apply-to-stock/apply-to-desk scope.
`MODEL_VERSION` is `v3.1`.

**LOCKED DECISIONS (maintainer, June 2026):**
- **Phase 2 = Option A** — scenarios flex the discount rate via CAPM risk add-ons
  (`scenario_erp_addon`, `scenario_cost_of_debt_addon`), NOT hardcoded WACC overrides. WACC stays
  fully derivable and must be shown as such in the UI.
- **Phase 5.1 = full-year terminal value** — explicit FCFs mid-year, Gordon TV discounted at full
  year N, behind flag `mid_year_terminal` (default `0.0`).
- **UI scope expanded** — the Hypothèses tab becomes per-model editable sub-tabs with
  apply-to-stock vs apply-to-desk; see Phase B1 (rewritten below).
- **Phase 2B — stock-specific, per-model terminal growth (LOCKED):** replace the flat
  `terminal_growth = 0.025` with two computed sustainable growths — `g_firm = reinvestment_rate ×
  ROIC` for FCFF (and the shared operating fade) and `g_equity = retention × ROE` for
  DDM/FCFE/RIM/justified — each clamped to `[floor, macro_ceiling]` and `< discount_rate − buffer`.
  Macro ceiling = `risk_free_rate` (~2.9%), registered as editable. Use after-tax **ROIC** (NOT
  Greenblatt ROC). Financials run equity-only. Explicit analyst overrides still win.

**Audience:** Codex, executing one phase at a time.
**Style rules (project conventions):**
- Backend-first. Land and test each backend phase before touching the UI.
- Incremental phases — one reviewable commit per phase, never a big-bang.
- Do not weaken existing guards (currency mismatch, proxy weight caps, integrity haircuts).
- Bump `MODEL_VERSION` in `core/quant_core/fundamentals/valuation.py` from `"v3.0"` → `"v3.1"`
  once any model-output-changing phase (1, 2, 2B, 3, 4) lands, and note it in the PR body.

**How to run tests (from repo root):**
```
python -m pytest core/tests/ -q
cd frontend && npm run lint && npx tsc --noEmit   # for UI phases
```

---

## Background — what the audit found

The fundamental stack (`core/quant_core/fundamentals/`) is architecturally strong: multi-model
ensemble, PIT beta (`cost_of_capital.py`), shared 3-statement projection (`projection.py`),
integrity gating, scenario + sensitivity grids. The live WACC path
(`services/api/app/services/fundamentals.py::_apply_live_cost_of_capital`, ~L2150) correctly
rebuilds WACC from CAPM with a PIT beta and after-tax cost of debt.

Five defects keep it below desk grade. Phases 1–4 are correctness; Phase 5 is methodology
hardening. The UI work (Phase 6) makes the modelling legible and is the maintainer's headline ask.

---

## PART A — BACKEND CORRECTNESS

### Phase 0 — MASI proxy data (RESOLVED 2026-06-02 — data present; only data-page display remains)

**STATUS: not a blocker.** DB confirmed `market_data_store` has `MASI` (736 rows) and `MASI_20`
(764 rows) as `asset_class='index'` through 2026-06-01, and `fundamental_beta_history` has 144 rows
(latest 2026-06-01). So betas ARE computed from the real MASI regression — cost of equity / WACC are
genuinely personalized. The only residual: indices may not render on the **data page** (a frontend
display filter), even though `market_universe.py` includes an `asset_class='index'` branch
(L190–218). Optional follow-up: check the data-page client filter so MASI/MASI_20 show as indices.
The original analysis below is retained for context.

**Original problem (now resolved).** Beta is regressed against an **ingested MASI daily price series** read from
`market_data_store` (symbol ∈ {MASI, MASI_20, MASI20, MSI}, `timeframe='1D'`, `object_key` not null;
see `services/api/app/services/fundamental_beta.py::_resolve_market_proxy_symbol`). If no such row
exists, `recompute_universe_betas` raises and **no betas are ever stored**, so
`services/api/app/services/fundamentals.py` (~L2165) falls back to `beta = 1.0` for every symbol.
The app currently only has **synthetic** MASI definitions (`frontend/lib/masi20-flottant-index.ts`,
`builtin-dashboard-indices.ts::BUILTIN_WEIGHTED_MASI_INDEX`, `scripts/export_masi_shares.py`) —
those are constituent float-weights, NOT a price history, and cannot feed the regression. Indices
are absent from the data page because `market_universe.py` only surfaces indices that exist in
`market_data_store` with `asset_class='index'` (L190–218), and none do.

**Verify first** (read-only; maintainer to run/approve):
```
docker exec infra-quant_postgres-1 psql -U app -d quant -c \
  "SELECT symbol,asset_class,row_count,start_ts,end_ts FROM market_data_store \
   WHERE upper(symbol) IN ('MASI','MASI_20','MASI20','MSI');"
docker exec infra-quant_postgres-1 psql -U app -d quant -c \
  "SELECT count(*), max(as_of) FROM fundamental_beta_history;"
```
If the first is empty / second is 0 → confirmed: betas are all the 1.0 default.

**Fix.**
1. Obtain a MASI daily close series (the maintainer has the source) and ingest it into
   `market_data_store` with `symbol='MASI'`, `timeframe='1D'`, `asset_class='index'`, a populated
   `object_key`, and an `index_master` row (`symbol='MASI'`, `display_name='MASI'`,
   `market_region='masi'`) so it also renders on the data page via the index branch. Reuse the
   existing market-data ingest path (`services/worker/tasks/ingest_market_data.py` /
   `services/api/app/routers/market_data.py`); do NOT invent a new store.
2. Run `POST /fundamentals/recompute-betas` (admin) and confirm `fundamental_beta_history` populates
   with `method='ols'` for liquid names (not all `default_beta`).
3. Add a guard/telemetry: when `_apply_live_cost_of_capital` uses the default beta (no beta row),
   surface `beta_source='default_beta'` to the UI (already present on `build.beta_source`) and add a
   visible warning in the assumptions UI (Phase B) so a missing proxy is never silent again.

**Acceptance:** after ingest + recompute, a spot-checked liquid MASI name shows `beta_source!='default'`,
`beta_method='ols'`, `n_obs` ≳ 60, and a non-trivial R²; the data page lists MASI under indices.

---

### Phase 1 — Make the projection's integrity checks non-vacuous (HIGHEST PRIORITY)

**Problem.** In `core/quant_core/fundamentals/projection.py::build_projection`, the projected
balance sheet does not articulate an asset side. Specifically:
- `total_assets = total_liabilities + ending_equity` (≈L265) — assets are *defined* as L+E, so
  `projection_bs_balance_*` (Δ = assets − liabilities − equity) is **0 by construction** and always passes.
- `"cash": ending_cash` is set equal to `ending_cash` (≈L292), so `projection_cash_tie_out_*` is
  **always 0** — `ending_cash` (the computed CFS cash) is **never carried into total_assets**.
- `projection_net_income_link_*` (≈L469) computes `ni_delta = net_income − statement["net_income"]`
  → comparing a value to itself → **always 0**.
- `projection_retained_earnings_*`: `ending_equity = previous_equity + net_income − dividend`
  (≈L259) and the check recomputes exactly that → **always passes**.

Four of six checks are tautological; only `margin_hierarchy` and `sign_conventions` test anything.
A reviewer reads "all integrity checks pass" as independent validation; today it is circular.

**Fix — articulate the asset side so the balance sheet balances *because the model is right*,
not by definition.** In `build_projection`, replace the plug with an explicit composition:

1. Carry a real non-cash asset roll-forward. Introduce `non_cash_assets` seeded from
   `latest_assets − latest_cash` (use the existing `_latest_or_snapshot(... TOTAL_ASSET_ALIASES)`
   and `... CASH_ALIASES`; if total assets is missing, seed `non_cash_assets` as
   `working_capital + net_ppe_proxy` from available lines and record a `warning`).
2. Roll non-cash assets forward with the operating drivers already computed each year:
   `non_cash_assets += delta_wc + capex − dand_a` (net PP&E + working-capital investment;
   reuse `reinvestment` so it stays consistent with FCFF).
3. Build the asset side as `total_assets = ending_cash + non_cash_assets` (cash now a real line).
4. Keep `total_equity = previous_equity + net_income − dividend` and
   `total_liabilities = latest_debt + other_liabilities` as today.
5. The balance check becomes meaningful: `total_assets − total_liabilities − total_equity` is now a
   real residual driven by whether cash generation + asset roll-forward reconcile with the
   financing/equity side. Where they don't tie, route the residual into a single explicit
   **balancing line** (e.g. `other_equity_adjustment` or revolver/`plug` field) AND set the
   `projection_bs_balance_*` check status from the residual *before* plugging, so the check reports
   the true gap. Persist both the pre-plug delta (for the check) and the plug amount (for display).

**Rewrite the four checks in `projection_integrity_checks`** so each compares two
*independently produced* quantities:
- `bs_balance`: pre-plug `total_assets(=cash+non_cash) − liabilities − equity`.
- `cash_tie_out`: CFS `ending_cash` vs the cash line actually placed on the balance sheet
  (they should match by construction *only after* cash is a genuine asset line — keep the check as a
  regression guard, but compute BS cash independently as `total_assets − non_cash_assets`).
- `net_income_link`: tie IS net income (`(ebit − interest)·(1−tax)`) to the net income used at the
  **top of the cash-flow statement** (`operating_cash_flow − dand_a + delta_wc`) — these are now two
  different code paths, so the check is real.
- `retained_earnings`: keep, but compute the equity roll independently from a stored
  `beginning_equity[index]` array rather than re-deriving from the same expression.

**Tests** (`core/tests/test_fundamental_projection.py`, extend or create):
- A normal name: all six checks `pass`.
- Inject an inconsistent input (e.g. force `capex` huge for one year via `overrides`) and assert
  `projection_bs_balance_*` flips to `warn`/`fail` with a non-zero `delta` — proving the check is no
  longer vacuous (this test would PASS today against the old code, which is the bug).
- Assert `ending_cash` now appears inside `total_assets` (i.e. `total_assets ==
  ending_cash + non_cash_assets` to 1e-6).

**Acceptance:** the "inconsistency" test fails against current `main` and passes after the fix.

---

### Phase 2 — Scenario discount-rate overrides must survive cost-of-capital enrichment

**Problem.** `valuation.py::SCENARIO_DEFAULT_OVERRIDES` sets bear `wacc=0.090 / cost_of_equity=0.105`
and bull `wacc=0.070 / cost_of_equity=0.080`. But `active_assumptions_for` (L2238) and
`resolved_assumptions_with_provenance` (L2274) call `_apply_live_cost_of_capital` **last**, which
unconditionally does `out["wacc"] = build["wacc"]` and `out["cost_of_equity"] = build["cost_of_equity"]`
(L2211–2212). The build-up reads only rf/ERP/beta/Kd/weights — none flexed by scenario. **Net effect:
bear and bull use the same discount rate as base.** Scenarios differ only via `growth_cap` /
`terminal_growth`.

**DECISION (maintainer must pick before Codex codes this):**

- **Option A (recommended) — flex the CAPM *inputs* per scenario.** Replace the hardcoded scenario
  `wacc`/`cost_of_equity` outputs with scenario *risk add-ons* that feed the build-up, so WACC stays
  internally CAPM-consistent. Add to `SCENARIO_DEFAULT_OVERRIDES`:
  `bear: {"scenario_erp_addon": 0.015, "scenario_cost_of_debt_addon": 0.010}`,
  `bull: {"scenario_erp_addon": -0.010, "scenario_cost_of_debt_addon": -0.005}`.
  In `_apply_live_cost_of_capital`, add the add-ons to `erp` and `cost_debt` before
  `cost_of_equity_capm` / `wacc_build_up`. Register the two new keys in `DEFAULT_ASSUMPTIONS`
  (default `0.0`) and `_ASSUMPTION_META_OVERRIDES` (group `cost_of_capital`, `editable: True`).
  Result: bear WACC > base WACC > bull WACC, derived not asserted.

- **Option B (minimal) — explicit override wins.** In `_apply_live_cost_of_capital`, if the incoming
  `assumptions` carry `wacc` / `cost_of_equity` whose provenance is `scenario` or `symbol`, do NOT
  overwrite them; only set the computed value when provenance is `default`. Requires threading
  provenance into the function (it already receives `provenance` in the `resolved_*` path; add it to
  the `active_*` path too).

Recommend **Option A** — it keeps the cost of capital fully derivable and explainable in the UI
(Phase 6 shows the add-on as a line in the WACC bridge).

**Tests** (`services/api/tests/` near the existing assumptions tests, or
`core/tests/test_cost_of_capital.py`):
- Resolve assumptions for the same symbol under bear/base/bull and assert
  `wacc_bear > wacc_base > wacc_bull` and likewise for `cost_of_equity`.
- Assert provenance/derivation reflects the scenario add-on (Option A) or the override (Option B).

**Acceptance:** scenario toggle changes the discount rate end-to-end (DCF fair values move).

---

### Phase 2B — Stock-specific, per-model terminal growth (LOCKED methodology)

**Problem.** `valuation.py::DEFAULT_ASSUMPTIONS["terminal_growth"] = 0.025` is a single desk-wide
constant applied to every stock and every intrinsic model. A high-ROE compounder and a low-return
utility get the same perpetuity growth. It should be stock-specific and fundamentally derived — but
NOT a naive historical CAGR (history overstates perpetuity growth and can push `g ≥ WACC` → the
Gordon TV blows up). The recent trajectory already drives the *explicit-period* growth fade; the
terminal rate must be the lower, macro-anchored steady state.

**Methodology (locked).** Growth = reinvestment × return on reinvestment, in two flavours that must
match the cash flow being discounted (Damodaran consistency):

- **Firm level** (FCFF, discounted at WACC, and the shared operating revenue fade):
  `g_firm = reinvestment_rate × ROIC`
  - `reinvestment_rate = (Capex − D&A + ΔWorking_Capital) / NOPAT`, `NOPAT = EBIT × (1 − tax)`
  - `ROIC = NOPAT / Invested_Capital` — **after-tax**. Reuse the invested-capital definition already
    in `screens.py::eva` (`total_debt + book_equity`, i.e. `debt + (TA − TL)`). **Do NOT use
    Greenblatt's pre-tax ROC** from `screens.py::magic_formula` — pre-tax overstates by ~the tax rate.
- **Equity level** (DDM, FCFE, residual income, justified multiples; discounted at cost of equity):
  `g_equity = retention × ROE`
  - `retention = 1 − payout` (trailing-average payout the projection already computes)
  - `ROE` normalized (trailing-average, not a single noisy/buyback-distorted year).

**Both** are then clamped:
`g = clamp(g_raw, floor, macro_ceiling)` and forced `g ≤ discount_rate − buffer`, where:
- `macro_ceiling = risk_free_rate` (~2.9%) — rf ≈ long-run nominal GDP and guarantees `g < WACC`
  (since `WACC > rf`). Register a key `terminal_growth_ceiling_source` (default `"risk_free_rate"`)
  so the desk can switch it later; for now resolve it to `assumptions["risk_free_rate"]`.
- `floor` = new key `terminal_growth_floor` (default `0.0`).
- `buffer` = new key `terminal_growth_discount_buffer` (default `0.01`) — keeps TV finite/sane even
  if rf ever approaches WACC.

**Financials** (`_is_financial`): FCFF is already disabled, so compute **only `g_equity`**; skip the
firm path entirely (no ROIC for banks/insurers).

**Steady-state note for the implementer:** in a stable-leverage steady state `g_firm` and `g_equity`
theoretically converge; we use the matched measure per model because each is *estimated from
different data* (ROE vs ROIC) and is the relevant driver for its cash-flow stream. Do not try to
force them equal.

**Where to change:**
1. New pure helpers (put in `valuation.py`, or a small `terminal_growth.py` imported by both
   `valuation.py` and `projection.py`):
   - `sustainable_growth_equity(snapshot, history, assumptions) -> (g, components_dict)`
   - `sustainable_growth_firm(snapshot, history, assumptions) -> (g, components_dict)` (None for financials)
   - `clamp_terminal_growth(g_raw, *, ceiling, floor, discount_rate, buffer) -> (g, binding_constraint)`
   - Each returns the components (ROE/retention or ROIC/reinvestment_rate, ceiling, which constraint
     bound) so the UI can render the derivation.
2. `compute_symbol_valuations` (valuation.py ~L1328): after assumptions/projection are resolved,
   compute `g_firm` and `g_equity`, clamp each (firm uses WACC as `discount_rate`; equity uses
   `cost_of_equity`), and inject `terminal_growth_firm` / `terminal_growth_equity` into the
   per-model assumptions so each model reads its own. **Precedence:** if the analyst set an explicit
   `terminal_growth` override (provenance `symbol`/`scenario`), that value wins for both (respect
   analyst intent); otherwise the computed values are the defaults. Allow explicit
   `terminal_growth_firm` / `terminal_growth_equity` overrides for power users.
3. Each model function reads its matched key: `_fcff_dcf` → `terminal_growth_firm`; `_fcfe_dcf`,
   `_ddm`, `_residual_income`, `_justified_multiples` → `terminal_growth_equity`. Keep a single
   fallback to `terminal_growth` if the computed/override keys are absent.
4. `projection.py::build_projection`: the revenue/operating fade target (currently
   `terminal_growth`) becomes `terminal_growth_firm` (operating/firm steady state). Thread it through
   the same precedence. Keep the existing `_fade_path`.
5. Register the new keys (`terminal_growth_firm`, `terminal_growth_equity`,
   `terminal_growth_floor`, `terminal_growth_discount_buffer`, `terminal_growth_ceiling_source`) in
   BOTH `DEFAULT_ASSUMPTIONS` and `_ASSUMPTION_META_OVERRIDES` (group `projection`, with derivation
   text). Mark `terminal_growth_firm`/`terminal_growth_equity` `editable: True` (analyst can pin
   them); they show in the per-model sub-tabs (Phase B1). The legacy `terminal_growth` stays as the
   manual master override.
6. Persist the derivation components into each `ValuationResult.inputs` (e.g.
   `terminal_growth_basis: {value, roe|roic, retention|reinvestment_rate, ceiling, binding}`) so
   Phase B can show "terminal g = min(rf 2.9%, ROE 14% × b 40% = 5.6%) = 2.9% (ceiling binds)".

**Tests** (`core/tests/test_fundamental_terminal_growth.py`, new):
- Levered firm: assert `terminal_growth_firm != terminal_growth_equity` (ROIC vs ROE diverge).
- High-ROE / low-payout name: `g_equity` raw > ceiling ⇒ clamped to `risk_free_rate`.
- Low-ROE / high-payout name: `g_equity` lands strictly below the ceiling, and the resulting
  DDM/RIM fair value is lower than under the old flat 2.5% (proves it now differentiates).
- Invariant: `g < WACC` (firm) and `g < cost_of_equity` (equity) for every fixture — no TV blow-up.
- Financials fixture: `g_firm` is None / firm path skipped; only `g_equity` used.
- Explicit `terminal_growth` override still wins for both families.

**Acceptance:** two different stocks produce two different terminal growths with visible derivations,
no `g ≥ discount_rate` cases, and FCFF vs equity models can carry different terminal g on the same name.

---

### Phase 2C — Personalize capital structure weights + cost of debt (per stock)

**Problem.** Two cost-of-capital inputs are still flat across the whole universe:
- **Capital weights** default to 70/30 because `use_balance_sheet_capital_weights = 0.0`; market-value
  weights are computed only when that flag is explicitly on
  (`services/api/app/services/fundamentals.py::_apply_live_cost_of_capital`, ~L2274-2285). So every
  stock's WACC uses the same 70/30 mix regardless of its actual leverage.
- **Cost of debt** is a flat `0.055` for every issuer (`DEFAULT_ASSUMPTIONS["cost_of_debt"]`),
  ignoring how levered or creditworthy each name is.

Both feed WACC, so today two companies with very different balance sheets can get nearly identical
WACCs — exactly the "not personalized" problem.

**Fix — capital weights (personalize by default).** In `_apply_live_cost_of_capital`, **always**
compute market-value weights when `market_cap` and `total_debt` are available, falling back to the
70/30 target only when data is missing. (Either flip `use_balance_sheet_capital_weights` default to
`1.0`, or — cleaner — drop the gate and treat the flag as a "force target weights" override.)
- Equity weight = market cap; debt weight = book total debt (acceptable proxy for market value of
  debt for MAD corporates without traded debt — document this). Keep `weight_source` provenance
  (`market_cap_plus_debt` vs `default_target`).

**Fix — cost of debt (stock-specific). LOCKED METHOD: synthetic interest-coverage spread as primary;
effective rate as a displayed cross-check + fallback.** WACC needs the *marginal* (forward) cost of
debt, and MASI names are effectively unrated, so use the Damodaran synthetic-rating approach:
- **Primary — `kd = risk_free + default_spread(interest_coverage)`** where
  `interest_coverage = EBIT / interest_expense` (use `EBIT`/`Resultat_dexploitation` and
  `Interest_Expense`/`Charges_Interets`, trailing). Map coverage → spread via a small bucketed table
  (~8 rows) using Damodaran's *relative* steps, **calibrated to Morocco** so the median-coverage MASI
  name reproduces ≈ the current `cost_of_debt` 5.5% (i.e. anchor the BBB-ish/average bucket at
  `risk_free + ~0.026`). Codex should compute the universe-median coverage once to set the anchor,
  then store the calibrated table as a module constant with a comment showing the calibration.
- **Cross-check + fallback — effective rate** `kd_effective = interest_expense / average_total_debt`
  (`Total_Debt`/`Dettes_de_financement`). Always compute it and expose it for display ("what they
  actually pay"), and **use it as the fallback** when coverage is unusable (EBIT ≤ 0, interest ≈ 0).
  Final fallback = registry flat `cost_of_debt`.
- Clamp the chosen Kd to `[risk_free + 0.005, risk_free + 0.06]` (within registry `plausible_range`
  [0.035, 0.085]).
- Provenance: `cost_of_debt_source ∈ {synthetic_interest_coverage_spread, effective_from_interest_and_debt,
  registry_default}`; expose `kd_synthetic`, `kd_effective`, `interest_coverage`, the matched bucket,
  and the spread in the build-up dict so Phase B can render the full chain
  ("couverture 4.2x → BBB → spread 2.0% → Kd 4.9% (effectif 5.1%)").
- **Financials:** banks fund largely via deposits, so neither coverage-spread nor `interest/debt` is
  a clean borrowing cost — for `_is_financial`, use the registry default and flag it; do not let a
  bank's deposit cost distort Kd.

**Surface in the build-up** (`cost_of_capital_build_up`): add `cost_of_debt_source` next to the
existing `weight_source`, plus the raw inputs (interest, avg debt) so Phase B can show the derivation
("Kd = intérêts 120 / dette moy. 2 400 = 5.0%, plafonné à [3.4%, 8.9%]").

**Tests** (`services/api/tests/` near the existing cost-of-capital tests):
- Two stocks, different leverage → different `debt_weight` and different WACC (not 70/30 for both).
- Low-coverage (weak) stock → wider synthetic spread → higher Kd than a high-coverage peer; both
  within the clamp band; `cost_of_debt_source == "synthetic_interest_coverage_spread"`.
- Calibration check: a name at the universe-median coverage lands within ~25bps of 5.5%.
- EBIT ≤ 0 or interest ≈ 0 → falls back to `effective_from_interest_and_debt`, else `registry_default`.
- Financial-sector name → synthetic + effective skipped, `registry_default` used.

**Acceptance:** two stocks with materially different balance sheets show materially different WACCs,
each with a visible weight + cost-of-debt derivation.

---

### Phase 3 — Bridge EV/EBITDA through net debt in relative multiples

**Problem.** EV-based multiples are applied as a direct equity-price ratio in two places:
- Backend `valuation.py::_relative_multiples` (≈L1111): `implied[metric] = current_price * peer/own`
  for every metric in `("PER","Price_to_Book","Price_to_Sales","EV_to_EBITDA")`.
- Frontend `signal-fundamental-view.tsx::comparableModelSummary` (≈L960) and
  `comparablePeerFairValueSummary` (≈L1006) do the same for `VALUATION_COMPARABLE_METRICS`
  (which includes `EV_to_EBITDA`).

Price-ratio scaling is exact for **equity** multiples (PER, P/B, P/S) but wrong for **EV/EBITDA**:
it implicitly assumes net debt scales with the multiple. Correct bridge:
`equity_value = peer_EV/EBITDA × EBITDA − net_debt`, then `÷ shares`.

**Fix (backend).** In `_relative_multiples`, special-case `EV_to_EBITDA`:
- Need EBITDA (`_latest_metric(history, *EBITDA_ALIASES)` or `snapshot.metrics["EBITDA"]`),
  net debt (reuse `_net_debt_bridge(history)`), and shares (`_shares(snapshot)`).
- `implied_eps = max(0.0, peer_multiple * ebitda - net_debt) / shares` when all three exist;
  otherwise **drop EV/EBITDA from the implied set** and append warning
  `ev_multiple_skipped_missing_bridge`. Keep PER/P/B/P/S on the existing exact path.
- `_relative_multiples` currently has only `snapshot, current_price, peer_stats, scenario`; thread
  `history` in (the caller `compute_symbol_valuations` already holds `history`).

**Fix (frontend).** Mirror the bridge in `comparablePeerFairValueSummary` /
`comparableModelSummary`: for `EV_to_EBITDA`, compute
`(peerMultiple × ownEbitda − netDebt) / shares` using values available on
`detail.metrics` (`EBITDA`, `NetDebt`/`Total_Debt`+`Cash`, `Shares_Outstanding`); if missing, omit
EV/EBITDA from the peer fair value (do not fall back to the price ratio). Add a small footnote in the
Comparables tab noting EV multiples are net-debt-bridged.

**Tests:** unit test `_relative_multiples` with a levered vs unlevered pair sharing the same
EV/EBITDA — assert the implied equity value differs by net debt (i.e. the bridge is applied), and
assert EV/EBITDA is skipped (with the warning) when EBITDA/shares are absent.

---

### Phase 4 — Reconcile the cost-of-capital constants

**Problem.** Three inconsistent constants:
- `valuation.py::DEFAULT_ASSUMPTIONS["wacc"] = 0.0786` but its own comment formula
  `0.70×0.089 + 0.30×0.055×(1−0.35)` = **0.0730**. `0.0786` is the *pre-tax* number (tax shield
  dropped). Live path recomputes WACC, so this bites only fallback paths (reverse-DCF, default
  sensitivity centers, EVA).
- `screens.py::eva` uses `assumptions.get("wacc", 0.0851)` (≈L375, L410) — a *third* WACC default —
  and `assumptions.get("tax_rate", 0.30)` (≈L387) vs the registry's `0.35`.

**Fix.**
- Set `DEFAULT_ASSUMPTIONS["wacc"] = 0.073` (matches the documented after-tax build-up) and fix the
  comment to the correct arithmetic. Keep `cost_of_equity = 0.089` (correct: rf 0.029 + ERP 0.060).
- In `screens.py::eva`, change both WACC fallbacks from `0.0851` to
  `DEFAULT_ASSUMPTIONS["wacc"]` (import it; it is already imported in `scoring.py`) and the tax
  fallback from `0.30` to `DEFAULT_ASSUMPTIONS["tax_rate"]`. Better: EVA should never need a literal —
  pass the resolved `assumptions` (which carry the live WACC) and only fall back to the registry.

**Tests:** assert `DEFAULT_ASSUMPTIONS["wacc"]` equals the `wacc_build_up(...)` of the documented
inputs to 1e-4; assert `eva()` with empty `assumptions` uses the registry WACC/tax, not literals.

---

### Phase 5 — Methodology hardening (lower severity; can be one combined commit)

1. **Mid-year terminal value.** `valuation.py::_discount_projected_cash_flows` (≈L669) discounts the
   Gordon TV at period `N − 0.5`. A perpetuity is valued as of end-of-year `N`; most desks discount
   TV at full year `N`. **DECISION:** keep mid-year for explicit flows but discount TV at full `N`
   (recommended), or document the chosen convention. Implement behind an assumption flag
   `mid_year_terminal` (default `0.0` = full-year TV) so it is explicit and testable.
2. **Monte-Carlo correlation.** `_monte_carlo_band` (≈L1238) shocks each model independently, so the
   5–95 band is too tight (models share inputs). Introduce a shared common-factor shock:
   `shock_i = ρ·z_common + sqrt(1−ρ²)·z_i` with `ρ≈0.6` (new constant `MODEL_SHOCK_CORRELATION`).
   Add a test asserting the band widens vs the independent case.
3. **Altman Z on financials.** `screens.py::altman_z` runs Z'' on banks/insurers. Suppress for true
   financials (return `_screen_unavailable("altman_not_applicable_financials", ...)`), consistent with
   EVA already skipping financials.
4. **Pandas deprecation.** `cost_of_capital.py::_period_returns` (≈L267) uses `resample("M")`; change
   to `"ME"` to silence the pandas ≥2.2 FutureWarning. (Weekly `"W-FRI"` is fine.)

---

## PART B — MODELLING-TRANSPARENCY UI

> The maintainer's ask: "a part where the user can clearly see the different parts and components of
> the modelling and the work — a tab for assumptions where beta and WACC are well presented, clearly
> shown (values) and justified / shown how we got them."

**Important — much of this already exists.** Do NOT rebuild from scratch. In
`frontend/components/strategy/signal-fundamental-view.tsx` there is already:
- A 7-tab detail view incl. **"Hypothèses"** (`AssumptionsTab`, ≈L3099).
- `CostOfCapitalBuildUp` (≈L2396): renders the instantiated `Ke = rf + β·ERP` and
  `WACC = We·Ke + Wd·Kd·(1−IS)` formulas with live values, plus beta meta
  (source/method/proxy/freq/window/n/R²/zero-week-frac).
- A registry table with value · provenance · plausible range · source · derivation · editable input.
- Backend already serves it: `GET /fundamentals/stocks/{symbol}` →
  `FundamentalStockDetailOut.assumptions` + `assumption_provenance`, and
  `GET /fundamentals/stocks/{symbol}/assumptions/{scenario}` (`AssumptionResolvedOut` with
  `provenance`), and `GET /fundamentals/methodology` (`AssumptionMetaOut` with `derivation`/`source`/
  `plausible_range`).

So Part B = **elevate, restructure, and complete** the transparency story, and wire in the new
Phase 1–2 outputs. Phases B1–B4 below.

### Phase B1 — Rebuild the Hypothèses tab as per-model editable sub-tabs (maintainer's headline ask)
File: `signal-fundamental-view.tsx::AssumptionsTab` (currently one flat registry table at ~L3099).

**Target layout — a left rail of sub-tabs, a content pane on the right:**
1. **Cost of capital** (shared across all models) — the centerpiece:
   - A **WACC bridge** visual (horizontal waterfall): `rf → +β·ERP → +scenario ERP add-on → Ke`,
     then `We·Ke + Wd·Kd·(1−tax) → WACC`. Render as labeled segments (not just the existing `<code>`
     string), with each segment's value + provenance badge. Reuse `costOfCapitalBuildUp(detail)`;
     keep the exact `<code>` arithmetic underneath.
   - A **Beta evidence card**: value + method routing (OLS → Dimson+Blume → peer relever from
     `build.beta_method`), `n_obs`, `R²`, `zero_week_frac`, `liquidity_flag`, `proxy`, `window`,
     `as_of`, `beta_source`. If `beta_source==='default_beta'` (no MASI proxy — see Phase 0), show a
     prominent amber banner: "Beta non estimé — série proxy MASI absente; WACC utilise β=1.0 par
     défaut." If `beta_method!=='ols'`, a one-line plain-language note on *why* the fallback fired.
2. **Projection (3-statement)** — the driver assumptions: `revenue_growth`, `ebit_margin`,
   `tax_rate`, `capex_pct`, `working_capital_pct`, `depreciation_amortization_pct`, `payout_ratio`,
   plus `terminal_growth`, `forecast_years`, `growth_cap`, `mid_year_discounting`,
   `mid_year_terminal`. Each row: current value · provenance · anchor/divergence (from
   `projection.drivers[*]`) · plausible range · derivation · editable input.
3. **One sub-tab per valuation model** — `fcff_dcf`, `fcfe_dcf`, `ddm`, `residual_income`,
   `justified_multiples`, `relative_multiples`, `reverse_dcf`. Drive these from the existing
   `MODEL_FORMULA_META[model].assumptionKeys` (already defined, ~L203): show only the assumptions
   that model actually consumes, the model's `formula`/`secondaryFormula`/`explanation`, and the
   live instantiated values. This is what makes "the different parts of the modelling" legible —
   the user sees exactly which knobs each model turns.
   - Reuse `assumptionGroupLabel`, `fmtAssumptionValue`, and the registry meta
     (`methodology.assumptions[key]`) for labels/units/ranges/derivation so nothing is duplicated.
   - **Terminal growth derivation (Phase 2B):** each model sub-tab shows its *own* terminal growth
     with the derivation read from `row.inputs.terminal_growth_basis` — FCFF shows
     `g_firm = reinvestment_rate × ROIC` capped at the macro ceiling; the equity models show
     `g_equity = retention × ROE` capped — including which constraint bound (`ceiling` / `buffer` /
     `raw`). This is the concrete payoff of making terminal growth stock-specific: the user sees, per
     model, exactly how the perpetuity growth was computed and why it differs across names.

**Editing + apply scope (the new functional requirement):**
- Every editable assumption stays an inline numeric input bound to the existing `draft` state.
- Replace the two existing buttons with an explicit **apply-scope control** per save:
  - **"Appliquer à ce titre"** → existing `onSaveSymbol` →
    `PUT /fundamentals/stocks/{symbol}/assumptions/{scenario}/override` (already wired).
  - **"Appliquer à tout le desk"** → existing `onSaveDesk` →
    `PUT /fundamentals/assumptions/{scenario}` (desk/global scope, already wired). Gate behind the
    admin check the endpoint already enforces; if the user lacks admin, disable with a tooltip.
  - Add a confirmation step for the desk-wide apply ("Ceci modifie les hypothèses pour toutes les
    valeurs du scénario {scenario}. Continuer ?") since it is a broad, hard-to-undo action.
  - Show which scope each currently-displayed value came from via the provenance badge
    (`default` / `scenario` / `symbol`) so the user always knows whether they're overriding a desk
    default or a stock-specific value.
- Keep a **"Réinitialiser"** per-row (clears that key from `draft`) and a global reset.
- After a successful save, revalidate the SWR keys for the stock detail + `/assumptions/{scenario}`
  so the recomputed WACC/Ke and downstream fair values refresh in place.

**No backend change needed** — symbol and desk override endpoints, the methodology registry, and the
new `scenario_*_addon` / `mid_year_terminal` keys (registered in Phase 2 / 5.1) already flow through
`FundamentalMethodologyOut`. Just ensure the new keys are editable in the registry meta so they
appear as inputs here.

### Phase B2 — New "Modelling map" sub-view (the components of the work)
Add a compact panel (top of the Assumptions tab, or a new lightweight tab `DetailTab = "model"`)
that lists the **modelling pipeline end-to-end** so a reviewer sees every moving part:
1. Inputs → snapshot + annual history (counts, `as_of`, data source, currency).
2. Cost of capital → beta → Ke → WACC (link to B1).
3. Projection (3-statement) → drivers (`revenue_growth`, `ebit_margin`, `tax_rate`, `capex_pct`,
   `working_capital_pct`, `d&a_pct`, `payout_ratio`) each with method + anchor + divergence
   (already in `projection.drivers[*]` → `to_dict()`); render as a driver table.
4. Per-model fair values → the 7 models with FV · weight · confidence · proxy flag (reuse
   `MODEL_LABELS`, the valuation rows already loaded).
5. Ensemble → dispersion band + Monte-Carlo band + model weights.
6. Integrity → the now-meaningful checks from Phase 1 (status chips per check), surfaced from
   `GET /fundamentals/stocks/{symbol}/integrity` (`IntegrityReportOut`) and the projection's
   `integrity_checks`.
Each step = one card with the key numbers; clicking deep-links to the relevant existing tab.

### Phase B3 — Surface the Phase-1 projection integrity honestly
- In the Modelling map (B2.6) and/or the Estimations tab, render the six projection checks with
  status chips (pass/warn/fail) and the real `delta` / `rel_delta`. This is the visible payoff of
  Phase 1 — the QA now means something, so show it.
- If a balancing plug was introduced (Phase 1 step 5), display the plug magnitude as a labeled line
  so it is never hidden.

### Phase B4 — Scenario clarity
- Now that bear/base/bull flex WACC (Phase 2), show the three scenarios' WACC / Ke / terminal growth
  side by side (small 3-column strip) at the top of the Assumptions tab, with the active scenario
  highlighted. Pull per-scenario values via the existing `/assumptions/{scenario}` endpoint (one call
  per scenario, cached with SWR like the existing snapshot batch).

**UI acceptance:**
- A non-finance reviewer can answer, from the Assumptions/Modelling tab alone: *what is WACC, what
  beta produced it, how was that beta estimated, why this value, and how does it change across
  scenarios.*
- `npm run lint` and `npx tsc --noEmit` clean. No new `any` leaks beyond existing patterns.
- No backend schema change needed for B1/B4 (data already served). B2/B3 may add a thin
  `projection`/`integrity` block to `FundamentalStockDetailOut` only if not already present — check
  `schemas/fundamentals.py` first and reuse `IntegrityReportOut` rather than inventing shapes.

---

### Phase B5 — Redesign the FCFF & FCFE DCF sub-tabs (Valorisation tab) into a step-by-step story

File: `frontend/components/strategy/signal-fundamental-view.tsx`. The two DCF sub-tabs render through
`ValuationMethodCard` (~L2762) when `dcfMode = "fcff" | "fcfe"`. Today it stacks: header tiles →
text formula → `CostOfCapitalBuildUp` → `driver-evidence-grid` (`DriverEvidenceChart` + `FcfBridge`)
→ three raw `ModelValueGrid` dumps (Hypothèses / Inputs / Outputs) → `ModelSensitivityPanel` →
statement evidence → warnings. The DCF *math itself is illegible*: there is **no year-by-year
discounting table** and **no visual bridge from cash flows → EV/equity → fair value per share** — the
result lives only in the one-line `instantiatedFormula` string, and the rest is jargon key dumps.

**No backend change.** All inputs already exist on `row.outputs.dcf_bridge`
(`cash_flows[]`, `periods[]`, `explicit_pv`, `terminal_value`, `terminal_pv`, `total_value`,
`terminal_value_pct`), `row.inputs` (`fcf_start`, `growth`, `wacc`/`cost_of_equity`,
`terminal_growth`, `mid_year_discounting`, `net_debt`, `net_debt_source`), `row.outputs`
(`projected_fcff`/`projected_fcfe`, `implied_exit_ev_to_ebitda`), and shares via
`detail.metrics.Shares_Outstanding`. When Phase 2B lands, also read `row.inputs.terminal_growth_basis`.

**Build a dedicated `DcfMethodView` (fcff | fcfe)** rendered in place of the current flat stack for
the two DCF models (keep `ValuationMethodCard` for the non-DCF models). Sections, top to bottom:

1. **Result header.** Fair value/share · current · upside (toned) · confidence · weight, plus a
   one-line plain-language verdict ("Sous-évalué de +24% selon le DCF FCFF" / "surévalué"). Reuse the
   existing tiles; add the verdict sentence.
2. **Étape 1 — Taux d'actualisation.** Keep `CostOfCapitalBuildUp` (already strong: WACC/Ke build-up,
   beta evidence, default-beta amber banner). Label it "WACC" for FCFF, "Coût des fonds propres (Ke)"
   for FCFE, and add a one-liner on *why* that rate ("FCFF = flux à tous les apporteurs → WACC";
   "FCFE = flux aux actionnaires → Ke").
3. **Étape 2 — Flux projetés & actualisation (NEW table).** Columns: Année · FCFF/FCFE · croissance %
   · période t (mid-year aware) · facteur 1/(1+r)^t · PV. Build rows from
   `dcf_bridge.cash_flows[i]` + `periods[i]` with `r = wacc` (fcff) or `cost_of_equity` (fcfe);
   `factor = 1/(1+r)^period`, `pv = cash_flow*factor`. Footer row = `Σ PV explicite` (= `explicit_pv`,
   assert they reconcile). Optional inline bar per row (nominal vs discounted).
4. **Étape 3 — Valeur terminale (NEW block).** Instantiated `TV = FCF_n × (1+g)/(r − g)` with the
   live numbers; show `g` (stock-specific once Phase 2B lands, with `terminal_growth_basis` derivation
   in a tooltip), TV nominal, its discount factor, `PV(TV)` (= `terminal_pv`), **TV as % of total**
   (= `terminal_value_pct`, render the >75% case as an amber "poids terminal élevé" chip), and
   `implied_exit_ev_to_ebitda` for FCFF.
5. **Étape 4 — Pont vers la valeur par action (NEW waterfall + reconciling table).**
   - **FCFF:** `Σ PV explicite + PV terminale = Valeur d'entreprise (EV)` → `− Dette nette` (show
     `net_debt_source`) → `Capitaux propres` → `÷ actions` → `Juste valeur / action`.
   - **FCFE:** `Σ PV explicite + PV terminale = Capitaux propres` → `÷ actions` →
     `Juste valeur / action`, with an explicit note "FCFE est déjà un flux aux actionnaires — pas de
     pont dette nette" so the FCFF/FCFE difference is visually obvious.
   - Render as a small horizontal waterfall (reuse the `fcf-bridge` bar styling) plus a 1-column
     reconciling table. This is the single most important addition.
6. **Construction du flux (supporting).** Keep the existing `DriverEvidenceChart` + `FcfBridge`
   (CA→EBIT→NOPAT→FCFF per year) under a "Comment le flux est construit" heading — relegated below the
   valuation math, since it is operating detail, not the valuation bridge.
7. **Hypothèses du modèle.** Replace the raw "Hypothèses" `ModelValueGrid` with a compact list of
   *only this model's* assumptions via `MODEL_FORMULA_META[row.model].assumptionKeys`, each with value
   + provenance badge (links conceptually to Phase B1's per-model sub-tabs).
8. **Contrôles de cohérence & warnings.** Friendly chips: `g < r ✓`, `VT < 75% ✓/⚠`, proxy flag,
   `mid_year` on/off, plus the existing `row.warnings` as chips.
9. **▸ Données brutes (avancé).** Collapse the existing `ModelValueGrid` Inputs/Outputs dumps and the
   statement-evidence cards behind a disclosure so nothing is lost for power users. Keep
   `ModelSensitivityPanel` visible (above this disclosure or just under Étape 4).

**Reuse, don't duplicate:** keep `CostOfCapitalBuildUp`, `DriverEvidenceChart`, `FcfBridge`,
`ModelSensitivityPanel`, `StatTile`, `fmt*` helpers; add small new presentational components
(`DcfPvTable`, `TerminalValueBlock`, `DcfValueWaterfall`). Add CSS in `frontend/app/globals.css`
alongside the existing `fcf-bridge`/`cost-build` classes.

**Sequencing:** best landed with or after **Phase 2B** so the terminal growth shown is the
stock-specific value + derivation; it works today against the flat `terminal_growth` too (the
`terminal_growth_basis` block is read defensively — show "défaut desk" when absent).

**UI acceptance:**
- From the FCFF sub-tab a reader can trace, on screen, every step: rate → each year's discounted FCF
  → terminal value → EV → minus net debt → equity → ÷ shares → fair value/share, with the numbers
  reconciling to `dcf_bridge` (PV table sum == `explicit_pv`; EV == `total_value`; final == header FV).
- The FCFE sub-tab clearly shows the **absence** of the net-debt bridge vs FCFF.
- `npm run lint` and `npx tsc --noEmit` clean.

---

## Execution order & checklist
- [x] Methodology decisions locked: Phase 2 = Option A; Phase 5.1 = full-year TV.
- [x] Phase 1 (projection integrity) — DONE in working tree (`non_cash_assets`; tests green).
- [x] Phase 2 (scenario WACC) — DONE in working tree (`scenario_erp_addon`/`_cost_of_debt_addon`).
- [x] Phase 3 (EV/EBITDA bridge) — DONE (`valuation.py:1216-1225`, `ev_multiple_skipped_missing_bridge`).
- [x] Phase 4 (constants) — DONE (`wacc=0.073025`; EVA uses `DEFAULT_ASSUMPTIONS["wacc"]`).
- [x] Phase 5 (Altman-financials suppressed, pandas `ME`) — DONE.
- [x] Implemented-phases check: `pytest core/tests/test_projection.py test_cost_of_capital.py
      test_fundamentals.py test_fundamentals_screens.py` → 37 passed (2026-06-02). Still bump
      `MODEL_VERSION` → `v3.1` before committing these.
- [x] Phase 0 (MASI proxy data) — RESOLVED: MASI/MASI_20 present, 144 betas computed (2026-06-01).
      Optional: make indices visible on the data page (frontend filter).
- [x] Phase 2B (stock-specific per-model terminal growth) — backend + tests.
- [x] Phase 2C (capital weights + cost of debt via synthetic coverage spread) — backend + tests.
- [x] Phase B1–B4 (UI) — per-model Hypothèses sections + explicit apply scope.
- [ ] Phase B5 (FCFF/FCFE DCF sub-tab redesign — step-by-step PV table + value waterfall).
      No backend change; best landed with/after Phase 2B. **NOT started.**
- [ ] Full `python -m pytest core/tests/ -q` green; note new/changed counts in PR body.
- [ ] After code changes, run `graphify update .` to refresh the knowledge graph.

## Guardrails for Codex
- Do not change the currency-mismatch short-circuit in `compute_symbol_valuations`.
- Do not remove the proxy weight cap or the integrity confidence haircut.
- Keep all model formulas that the audit confirmed correct (FCFF=NOPAT+D&A−Capex−ΔWC, H-model DDM,
  RIM continuing value, justified P/B & P/E, CAPM, Blume/Dimson beta) — only the items above change.
- Terminal growth (Phase 2B) must use after-tax **ROIC** for the firm path, never Greenblatt's
  pre-tax ROC; never derive terminal growth from a raw historical CAGR; always enforce `g < discount
  rate` and the macro ceiling. Financials get the equity path only.
- Every new assumption key must be registered in BOTH `DEFAULT_ASSUMPTIONS` and
  `_ASSUMPTION_META_OVERRIDES` so it flows to the methodology endpoint and the UI registry table.
