# Codex Task — Phase UI-2: Fundamental explanation & justification visual layer

## Context (read first)
The fundamental rigor upgrade (`docs/fundamental_rigor_upgrade_plan.md`) is implemented and tested on
the **backend**: per-stock beta + WACC build-up, the shared 3-statement projection with per-driver
`DriverEstimate` evidence (history + derivation), projection integrity, PIT, and the signal backtest.
The **frontend** renders the structure (per-model sub-tabs, football field, a sensitivity heatmap,
editable rf/ERP, a projection *table*) but **does not draw the justification visuals** that make each
model "understood and justifiable." **The data already exists in the API payloads — this task mostly
draws it.** No new financial methodology.

Repo: `C:\Users\taha\Downloads\backtester_signal_engine_autoaccept`. Main file:
`frontend/components/strategy/signal-fundamental-view.tsx` (+ small new chart components, `lib/api.ts`
types). Backend payloads already carry: `detail.assumptions.cost_of_capital_build_up`, the projection
`DriverEstimate{projected_by_year, method, historical_series, anchor_value, divergence}` (via
`projection.to_dict()` / `FundamentalProjection.evidence_json`), per-model `inputs`/`outputs`, and the
sensitivity payload. Extend the backend payload ONLY where a specific series is missing (call it out).

## 0. Finalize prerequisites (so the visuals show real data)
- Run `POST /fundamentals/recompute-betas` then the universe valuation recompute; confirm a high-beta
  vs low-beta name shows different WACC and `provenance.beta == "beta_history"`. (If the MASI index
  price series is absent in `market_data_store`, report the exact ingestion step.)
- Fix the 2 pre-existing failures in `services/api/tests/test_market_universe.py` (the stale
  `MarketUniverseInstrument` shares_* fields from commit `eeeda68`): make the 4 fields optional/defaulted
  and update the test. Goal: `services/api/tests/ -q` 0 failures.

## 1. Cost-of-equity / WACC build-up panel  (the "clearly defined cost of equity")
New component `CostOfCapitalBuildUp` rendered in each model's `ModelDetailPanel` header **and** in the
Hypotheses tab. Render the chain from `detail.assumptions.cost_of_capital_build_up`:
```
Ke  = rf 2.9% + β 1.12 × ERP 6.0%  = 9.6%
WACC = 70% × Ke 9.6% + 30% × Kd 5.5% × (1−35%) = 7.8%
```
Each term shown with its value + provenance badge (default / beta_history / desk / symbol). rf and ERP
link to the editable Assumptions controls. Show β's `method`, `r2`, `n_obs`, `liquidity_flag` on hover.

## 2. Per-driver estimation justification  (§3.5 — "show where the estimate came from")
For every driver in the shared projection (`SharedProjectionPanel`) and each DCF model's cash-flow series:
- **`DriverEvidenceChart`** — historical actuals (`historical_series`, solid bars/line) + the projected
  path (`projected_by_year`, lighter), on one axis, with the `anchor_value` marked. A one-line
  **derivation** (`method`) and a **divergence badge** when the estimate is off-anchor.
- **`GrowthDecompositionChart`** — overlay the company's historical **revenue / EBIT / net-income /
  FCF growth** series with the series the growth assumption is anchored to highlighted and the **fade
  path** to terminal drawn. (If any of those growth series isn't in the payload, add it to
  `projection.to_dict()` evidence in `core/quant_core/fundamentals/projection.py`.)
- **`FcfBridge`** (DCF models) — a small waterfall: Revenu → EBIT (×marge) → NOPAT (−impôt) →
  −réinvestissement (Capex + ΔBFR − D&A) = **FCFF**, for Year 1 (and selectable year).
- Caption every chart with the numbers (e.g. "Croissance Yr1 6.2 % = mélange(CAGR 3 ans 5.1 %, dernière
  année 8.0 %) → 2.5 %").

## 3. Formula instantiated with the stock's own numbers
In `ValuationMethodCard`, render the model formula **with values substituted**, not the abstract
`MODEL_FORMULA_META.formula`. Use the model's persisted `inputs`. Examples:
- DDM: `FV = 4.20 × (1+2.5%) / (8.9% − 2.5%) = 65.6`
- FCFF: `FV = (Σ PV(FCFF) 312 + PV(TV) 540 − dette nette 80) / 12.0 actions = 64.3`
Keep the abstract formula as a secondary line.

## 4. Per-model sensitivity (not one shared heatmap)
Render a `SensitivityHeatmap` **inside each intrinsic model's sub-tab**, parameterized by that model's
own drivers: FCFF → WACC × g; FCFE/DDM/RIM → Ke × (g or payout); relative → peer-set composition.
Keep odd 5×5 with base-case = highlighted center cell. If the sensitivity payload currently returns a
single shared grid, extend the sensitivity endpoint to return **per-model grids** keyed by model.

## 5. Charting approach
Reuse the existing hand-rolled SVG pattern (`FootballField`, the backtest equity curve) or a lightweight
chart lib already in `frontend/package.json`. Keep one consistent visual style. New components live next
to the existing ones in `signal-fundamental-view.tsx` (or a new `fundamental-charts.tsx`). Add any new
payload fields to `frontend/lib/api.ts` Zod schemas.

## Acceptance
- Each model sub-tab shows: **numeric formula**, the **Ke/WACC build-up**, **its own sensitivity**, and
  (DCF models) the **FCF history→projection chart + bridge**.
- Every projection driver shows **history + derivation + divergence**; the **growth-decomposition chart**
  makes "where the growth rate came from" obvious.
- rf and ERP are editable and changing them visibly moves Ke/WACC and the fair values.
- `cd frontend && npx tsc --noEmit` clean; `services/api/tests/ -q` 0 failures.
- On a real recomputed stock, the build-up shows a non-default β with provenance `beta_history`.

## Constraints
- Frontend-first; consume existing payload data — extend backend payload only where a named series is
  missing (state which). No valuation-methodology changes. Do not run the Gemini mass scrape.
- One commit per section; update the `## Progress log` of this file with the real before/after of a
  sample stock.
```

## Progress log
- 2026-06-01: Implemented UI justification pass. Added beta diagnostics to `cost_of_capital_build_up`, added `growth_decomposition` to projection evidence, added per-model sensitivity grids to `compute_sensitivity`, restored Estimations/Comparables top tabs, and added French WACC build-up, numeric formulas, driver evidence charts, growth decomposition charts, DCF FCF bridges, and per-model sensitivity panels. Fixed the market-universe shares defaults and added a Plotly/Narwhals guard for the local `xbbg` native-SDK failure. Verification: `python -m pytest core/tests/ services/api/tests/ -q` -> 1294 passed; `cd frontend && npx tsc --noEmit` -> clean; `cd frontend && npm run build` -> success.
