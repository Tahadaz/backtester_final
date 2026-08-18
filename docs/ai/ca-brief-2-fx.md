# Codex Brief 2 — FX vertical (real data) + the frontend, built once

**Program:** `docs/cross-asset-product/00-program-plan.md` — §4 guardrails, §5 reuse, §6 invariants are binding.
**Prerequisite:** Brief 1 merged and green.
**Base spec:** `docs/ai/cross-asset-lab-slice1.md` §"Reference strategies to ship" (FX only) and §"Frontend".
**Scope:** wire real free data for FX, ship the two reference strategies, and build **the entire frontend once** in a form Briefs 3–5 extend by adding a union-type value — not a folder.
**Ship gate:** `/cross-asset-research` runs an FX strategy end-to-end against the API and shows methodology chain, metrics, robustness and current signal.

## 1. Guardrails (binding)

Program §4 applies verbatim. In particular: do not explore the repo; do not read `graphify-out/*`; create nothing outside §3; modify nothing outside §4; scope test runs, full suite once at the end.

**The frontend guardrail is the one that decides this brief's cost:** build **one** component set, parameterized by
```ts
type CrossAssetClass = "fx" | "commodity" | "rates";
```
Briefs 3 and 4 must be able to light up their asset class by adding a union member plus data, with **zero** new components. If you find yourself writing `fx-backtest-results.tsx`, stop — it is `backtest-results.tsx` taking an asset class.

## 2. Locked strategy choices (do not re-derive)

From `docs/trader-prep/04-build-track.md` §Build 2, resolving the master design's open decisions:

- **Universe:** G10 vs USD — EUR, JPY, GBP, CHF, AUD, CAD, NZD, NOK, SEK
- **Base currency:** USD
- **Rebalance:** monthly (matches the MOP / Koijen literature)
- **Rate legs:** FRED OIS-style policy-rate proxies, one per currency
- **Vol target:** 10% annual · **TSM lookback:** 12 months · lookback grid limited to {1,3,6,12} months
- **`replication_fidelity = "adapted"`** — required field. Document the deviations explicitly: monthly rebalance styling, proxy short rates rather than tradable forwards.

**Strategies:** (a) G10 time-series momentum — sign of own trailing 12m excess return, vol-targeted; (b) G10 carry — rank by rate differential, long high-yielders / short low-yielders, vol-targeted.

## 3. Files to create

```
services/api/app/services/cross_asset/datasources.py        # yfinance spot + FRED rates -> canonical panel
services/api/app/services/cross_asset/reference_strategies.py  # the two FX StrategyDefinitions as code

frontend/app/cross-asset-research/page.tsx
frontend/components/cross-asset/asset-class-tabs.tsx
frontend/components/cross-asset/strategy-overview.tsx
frontend/components/cross-asset/methodology-chain.tsx
frontend/components/cross-asset/backtest-results.tsx
frontend/components/cross-asset/robustness-panel.tsx
frontend/components/cross-asset/current-signal.tsx
frontend/components/cross-asset/run-record.tsx
frontend/components/run/plotly-heatmap.tsx                  # parameter heatmap — none exists yet

services/api/tests/test_cross_asset_datasources.py
core/tests/test_ca_fx_reference.py
```

## 4. Files you may modify (nothing else)

- `frontend/lib/api.ts` — zod schemas + fetchers for the Brief 1 endpoints.
- The sidebar/nav component where `dashboard`/`signals` links are declared — one entry "Cross-Asset Research" → `/cross-asset-research`.
- `services/api/app/services/cross_asset/orchestrator.py` — assemble real panels via `datasources.py`.

## 5. Data sources

| Leg | Source | Notes |
|---|---|---|
| FX spot | yfinance (`EURUSD=X` etc.) | Follow the existing ingestion pattern in `core/quant_core/macro.py:131`; `EURUSD=X` is already registered. Parquet → `macro_factor_meta` (`models.py:494`). |
| Short rates | FRED, one policy/OIS proxy series per G10 currency | Free, needs an API key. Read it from app settings the same way other external keys are read. If the key is absent, the endpoint fails **loudly** with a clear message — never silently substitute zeros or fall back to stale data. |

Day-count for the carry leg is explicit in `ReturnSpec`, not implied. Spot and rate series must be aligned with staleness surfaced, never silently forward-filled (program §6.3).

## 6. Frontend — six views, one component set

Route `/cross-asset-research`, French labels with English quant terms (matching the app). Asset-class tabs at the top; every view below takes the asset class as a prop.

| View | Content |
|---|---|
| **Overview** | thesis, research source, `replication_fidelity`, status, limitations |
| **Methodology** | the stage chain rendered from `GET /runs/{id}/stages`: raw → tradable → signal → position → executed → gross → net, each a chart or table |
| **Backtest** | equity, drawdown, rolling Sharpe/vol, turnover, exposure, per-instrument attribution, benchmark (plotly) |
| **Robustness** | parameter heatmap (new component), subperiod bars, cost sensitivity, WFO, leave-one-instrument-out, bootstrap CI |
| **Current signal** | latest signal, intended vs previous position, drivers, data timestamp, staleness, next rebalance, reversal conditions, fixed disclaimer |
| **Run record** | strategy version, git commit, dataset hash, seed, params, warnings, notes |

Every number carries a visible unit. Any `warnings` entry renders as a visible banner — this is how the non-tradable labelling in Brief 3 reaches the user, so wire it generically now.

## 7. Tests

- `test_ca_fx_reference`: the FX excess-return identity `total = spot_return + (r_base − r_quote)·τ` holds on a hand-built series; the two reference specs round-trip through `to_dict`/`from_dict` with a stable `spec_hash`.
- `test_cross_asset_datasources`: panel assembly with a mocked FRED/yfinance response; **missing API key raises a clear error rather than degrading silently**; staleness is surfaced.
- Extend `test_cross_asset_research_router` with an FX run (mocked data source) that completes and returns a populated envelope.

## 8. Acceptance

1. `/cross-asset-research` renders and runs an FX reference strategy end-to-end against the API, with the full methodology chain, real metrics, and at least the parameter heatmap plus deflated Sharpe with variant count in Robustness.
2. **Sanity band, not a golden number:** the TSM and carry results agree in sign and rough shape with the published MOP 2012 / Koijen et al. stylized facts. If they do not, say so in the run's `warnings` rather than tuning until they do.
3. The look-ahead shift test still passes; gross and net are shown side by side with turnover.
4. Adding an asset class requires no new component file — demonstrate by leaving the commodity and rates tabs present and empty-stated.
5. No file outside §3/§4 created or modified; full suite green.
