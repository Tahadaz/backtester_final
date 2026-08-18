# Offshore Markets Lab — Repository Audit, Architecture & Roadmap

**Date:** 2026-07-14
**Status:** ⚠️ **PIVOTED 2026-07-14** — after discussion with an offshore-desk trader, the bond-pricer-first roadmap below is **shelved**: the desk already has Bloomberg for instrument analytics, so a standalone pricer duplicates it. The lab's new direction is a **Cross-Asset Strategy Research Lab** (systematic-strategy research, replication, validation and monitoring across commodities, FX, rates, indices) — see `01-cross-asset-research-lab.md` in this folder. The repo audit (§1–3) and data-source appendix here remain valid and are referenced by the new plan. Do **not** implement `docs/ai/offshore-lab-phase1-fixed-income.md` (kept for reference; the bond-math conventions in it stay useful for later rates work).
**Phase 1 implementation brief (shelved):** `docs/ai/offshore-lab-phase1-fixed-income.md`
**Purpose:** Educational/analytical lab for a prop-trader role on an international desk (Eurobonds, rates & curves, FX, commodities, cross-asset risk). Scope: international core **plus a Moroccan angle** (BAM reference curve, dirham basket, CIP on EUR/MAD & USD/MAD), per `roadmap-interview-desk-international-bmce.md`. Data: **free sources only** — no Bloomberg/Refinitiv dependence.

This document answers the 13 deliverables of the originating prompt, corrected where its assumptions did not survive contact with the repository or with fixed-income practice.

---

## 1. Repository architecture summary

Verified in source (not guessed from filenames):

| Layer | What it is | Where |
|---|---|---|
| Quant core | Installable, **market-agnostic** Python package: backtest engine, signal engine, WFO, risk, portfolio, macro ingestion | `core/quant_core/` |
| API | FastAPI (`create_app()` in `services/api/app/main.py`), 26 routers, API-key auth via `Depends(auth.require_api_key)` | `services/api/app/routers/`, `services/api/app/services/` |
| Jobs | RQ worker (`services/worker/worker.py`) + APScheduler process (`services/worker/scheduler.py`), ~40 tasks | `services/worker/tasks/` |
| Frontend | Next.js **App Router**, TypeScript, zod-validated client (`frontend/lib/api.ts`) + SWR, backend proxied via `frontend/app/api/[...path]/` | `frontend/app/`, `frontend/components/` |
| DB | **Postgres 16** (not SQLite), 83 SQLAlchemy tables in `services/api/app/models.py`, 87 Alembic migrations in `services/api/alembic/versions/` | `services/api/` |
| Charts | plotly.js (`frontend/components/run/plotly-chart.tsx`), recharts, lightweight-charts | `frontend/components/` |
| Tests | pytest (~207 `test_*.py` across `core/tests/`, `services/api/tests/`, `services/worker/tests/`), frontend `*.test.mjs` via `node --test` | — |
| Deploy | docker-compose dev/prod (`infra/docker-compose*.yml`): Postgres, Redis, MinIO (S3), Caddy, Airflow; prod images on ghcr | `infra/` |

## 2. Reusable files and components

The originating prompt assumed no offshore scaffolding exists. **Wrong — a significant amount already does:**

- **Macro ingestion already covers offshore instruments.** `core/quant_core/macro.py` defines `MacroSeriesSpec`s for Brent (`BZ=F`), Gold (`GC=F`), Silver, DXY, EUR/USD, US 10Y (`^TNX`), BTC — ingested via yfinance by `services/worker/tasks/ingest_macro_series.py` into the `macro_factor_meta`-backed store. Phases 3/5/6 extend this pipeline instead of building a new one.
- **Asset taxonomy already exists.** `services/api/app/asset_taxonomy.py` classifies symbols into `asset_type ∈ {equity, commodity, forex, bond, crypto}` and `market_region`, with roots for US2Y–US30Y, OAT/BUND/GILT/JGB/MA10Y, USDMAD/EURMAD, energy/metals/ags.
- **Cross-market calendar alignment** utilities exist (`align_cross_market`, `align_factor_to_target`, staleness-guarded forward-fill in `core/quant_core/`): the exact machinery a cross-asset lab needs to compare series on different holiday calendars.
- **Risk toolkit is market-agnostic and reusable:** `core/quant_core/risk.py` (Monte-Carlo VaR/CVaR, block bootstrap, Kelly), HRP allocation, portfolio stats. Phase 7 must reuse this, not rewrite VaR.
- **Patterns to copy:** router registration in `main.py`; Pydantic response schemas per router; zod schema + fetcher pairs in `frontend/lib/api.ts`; chart wrappers above.
- **Bloomberg bridge** (`services/api/app/routers/bloomberg_bridge.py`, `bloomberg_*` tables) exists but is **out of scope** — free-data-only constraint.

## 3. Problems and constraints discovered

1. The prompt's `offshore/` monolithic module sketch doesn't match this repo's layering (pure quant package / API services / worker / frontend). Adapted in §4.
2. Pricing logic in this repo lives in `core/quant_core` with **no DB or FastAPI imports** — bond math must follow the same discipline (pure functions, testable without services).
3. Free data has hard limits (detailed in §"Data-source strategy" below): no free Eurobond prices, no reliably free commodity futures chains. The roadmap is designed so no phase's core function depends on unavailable data.
4. The frontend is French-labelled and equity-centric; the lab needs its own route and must not touch the Signal/Dashboard equity pages.
5. Deployment is compose-based with a migration container; Phase 1 deliberately requires **no new tables** so it deploys with zero migration risk.

## 4. Proposed Offshore Markets Lab architecture

Adapting the conceptual `offshore/` sketch to the actual repo layering:

```
core/quant_core/fixed_income/        # Phase 1-2: pure, stateless calculators
    daycount.py                      # 30E/360, ACT/ACT-ICMA, ACT/365F
    cashflows.py                     # schedule generation
    pricing.py                       # PV, clean/dirty, accrued, YTM solver
    riskmeasures.py                  # durations, convexity, DV01
    scenarios.py                     # shocks, carry
core/quant_core/curves/              # Phase 3: bootstrapping, slopes, classification
core/quant_core/fx_lab/              # Phase 5: CIP, forward points, hedged returns
core/quant_core/commodities_lab/     # Phase 6: term structure, roll yield

services/api/app/routers/offshore_lab.py   # thin endpoints, same auth pattern
services/api/app/schemas/offshore_lab.py   # Pydantic contracts

frontend/app/offshore-lab/page.tsx         # lab entry point
frontend/components/offshore/              # forms, tables, interpretation blocks
```

Design rules (all consistent with existing repo practice):
- **Pure calculators in `quant_core`** — no I/O, no globals; the API layer only validates, calls, and wraps.
- **Every analytical response uses a transparency envelope** (see §8): inputs echo, methodology, data source, calculation date, assumptions, units, warnings, interpretation. Nothing is a bare number.
- **Separation from equity logic:** no imports from `signal_engine/`, no writes to equity tables; new tables (Phase 2+) prefixed `offshore_`.
- **Reuse of generic infra:** macro ingestion pipeline, alignment utils, chart components, auth, testing layout.

## 5. Phased roadmap (corrected)

Phase ordering follows the requested sequence with two corrections (marked ✱).

- **Phase 1 — Fixed-income calculation engine.** User-entered fixed-rate bullet bonds. Cash-flow schedule, accrued, clean/dirty, YTM, current yield, Macaulay/modified duration, convexity, DV01, approximate vs exact shock repricing, holding-period carry. Annual + semiannual coupons; 30E/360, ACT/ACT-ICMA, ACT/365F; T+2 default settlement. Stateless — no DB. *(First slice, §6; Codex brief exists.)*
- **Phase 2 — Bond scenario & P&L lab.** Saved bonds (first `offshore_` tables), parallel rate shocks, spread shocks, combined matrices, carry over holding period, approximate vs exact P&L decomposition. **✱ Roll-down is moved to Phase 3** — it is undefined without a curve, and Phase 2 has none. ✱ Correction on the decomposition ΔP ≈ −DV01_rates·Δr − DV01_spread·Δs + carry (+ roll-down): under Phase 1-2 flat-YTM pricing, rate DV01 and spread DV01 are **identical by construction** (y = r_bench + s enters the discount factor as one number). The lab displays them as one total-yield DV01 with the additive split labelled explicitly as a trader approximation; genuinely distinct sensitivities only exist once bonds are priced off a curve plus Z-spread (Phase 4).
- **Phase 3 — Yield-curve lab.** Ingest UST par yields (FRED `DGS*` / treasury.gov), ECB euro-area AAA curve, and **BAM's daily MAD reference curve** through the existing macro-ingestion pattern. Curve snapshots, 2s10s/5s30s slopes, daily/weekly/monthly changes, bull/bear steepener/flattener classification from actual yield changes, historical curve visualization, roll-down (now well-defined), simple curve-trade simulator with DV01-neutral sizing. ✱ Note: `^TNX` is the CBOE 10-year yield index ×10 — a single-point proxy, not a curve; the curve lab uses the proper sources and keeps `^TNX` only as an intraday-ish cross-check.
- **Phase 4 — Credit & Eurobond monitor.** Sovereign/corporate Eurobond definitions (issuer, seniority, currency, coupon, maturity), benchmark mapping, G-spread vs the Phase 3 curves, spread history **from user-entered price/yield marks** (free Eurobond prices effectively do not exist — see §"Data"), duration & spread sensitivity, carry, relative value, liquidity and stale-mark warnings. Z-spread only after Phase 3 zero-curve bootstrapping is validated; ASW/OAS deferred indefinitely (need swap curves / vol — the prompt's own caution, endorsed).
- **Phase 5 — FX lab.** Spot & cross-rate calculator (spot already ingested), CIP forward F = S·(1+r_d·τ_d)/(1+r_f·τ_f), forward points, FX carry, FX-hedged bond-return calculator, exposure/P&L scenarios, base-vs-quote pedagogy. **Moroccan module:** 60% EUR / 40% USD basket mechanics for USD/MAD (what EUR/USD moves imply mechanically), CIP/forward-points on EUR/MAD & USD/MAD using BAM reference rates, note on the ±5% band and the 2026 flexibilization path.
- **Phase 6 — Commodities lab (Brent + gold only).** Front-month continuous prices (already ingested), contango/backwardation from **user-entered or snapshot curve points** (free full futures chains are unreliable), calendar spreads, roll-yield arithmetic, gold vs 10y real yields (FRED `DFII10`) and DXY. No supply/demand modelling.
- **Phase 7 — Cross-asset portfolio risk.** Position objects across bonds/FX/commodities/indices; market value, DV01, spread DV01, FX delta, commodity delta; gross/net exposures; historical + user-defined stress scenarios; concentration report. VaR **last**, and by reusing `core/quant_core/risk.py` — not a new implementation.

## 6. Recommended first implementation slice

**Stateless fixed-rate bullet-bond calculator** — confirmed as the right first slice after the audit, because it needs zero new data infrastructure, zero migrations, and produces the numbers the desk uses daily (price/yield/duration/DV01).

- Backend: `core/quant_core/fixed_income/` (4 modules above) + `services/api/app/routers/offshore_lab.py` with two POST endpoints (§8) + `schemas/offshore_lab.py`.
- Frontend: `frontend/app/offshore-lab/page.tsx` — bond form, analytics panel, cash-flow table, yield-shock table, interpretation blocks with units and assumptions.
- Tests: textbook vectors + property tests + optional QuantLib cross-check (§10).

## 7. Exact files created or modified (Phase 1)

**Created:**
- `core/quant_core/fixed_income/__init__.py`, `daycount.py`, `cashflows.py`, `pricing.py`, `riskmeasures.py`, `scenarios.py`
- `services/api/app/schemas/offshore_lab.py`
- `services/api/app/routers/offshore_lab.py`
- `frontend/app/offshore-lab/page.tsx`
- `frontend/components/offshore/bond-form.tsx`, `bond-analytics-panel.tsx`, `cashflow-table.tsx`, `shock-scenario-table.tsx`, `interpretation-block.tsx`
- `core/tests/test_fixed_income_daycount.py`, `test_fixed_income_pricing.py`, `test_fixed_income_risk.py`, `test_fixed_income_scenarios.py`
- `services/api/tests/test_offshore_lab_router.py`

**Modified (only):**
- `services/api/app/main.py` — register the new router (one include, same pattern as the other 26)
- Frontend navigation component (wherever `dashboard`/`signals` links are declared) — one nav entry "Offshore Lab"
- `frontend/lib/api.ts` — zod schemas + fetchers for the two endpoints

No models.py changes, no migrations, no worker/scheduler changes, no equity-page changes.

## 8. Data models and API contracts (Phase 1)

**BondDefinition (input):** `face_value` (default 100), `currency` (ISO string; display only), `coupon_rate` (decimal p.a., e.g. 0.05), `coupon_frequency` (1 or 2), `maturity_date`, `settlement_date`, `day_count` (`"30E/360" | "ACT/ACT-ICMA" | "ACT/365F"`), `redemption` (per 100, default 100). Schedule generated backwards from maturity; short first period allowed.

**Endpoints** (both `POST`, API-key auth like every other router):
- `/offshore-lab/bond/analytics` — body: `{bond, quote: {type: "yield"|"clean_price"|"dirty_price", value}}`. Returns full analytics + cash-flow schedule.
- `/offshore-lab/bond/scenarios` — body: `{bond, quote, shocks_bp: [-100,-50,-25,-10,-1,0,1,10,25,50,100], holding_period_days?: int}`. Returns exact repricing vs duration/convexity approximation per shock, plus carry.

**Transparency envelope** (every response):

```json
{
  "inputs": { ...echo of request... },
  "methodology": "Discounted cash flows at flat yield y compounded at coupon frequency; ...",
  "data_source": "user-entered",
  "calculation_date": "2026-07-14",
  "assumptions": ["T+2 settlement", "bullet redemption at 100", "no default/optionality", "flat yield curve"],
  "units": { "clean_price": "per 100 face", "ytm": "decimal p.a.", "dv01": "currency per 1bp per position notional", "macaulay_duration": "years" },
  "warnings": ["settlement after last coupon", "yield solver hit bracket bound", ...],
  "results": { ... },
  "interpretation": "A DV01 of 72.10 MAD means this 1,000,000 MAD position gains/loses ≈72 MAD per 1bp parallel yield move..."
}
```

Interpretation strings are computed server-side from actual notional and currency, never hardcoded examples.

## 9. Calculation conventions (Phase 1)

- Price quoted **per 100 of face value**; clean = dirty − accrued.
- YTM: for annual bonds, annual compounding; for semiannual bonds, **semiannual bond-equivalent yield** (y/2 per period). Yields as decimals in the API, bp only in shock inputs.
- Day counts: `30E/360`, `ACT/ACT-ICMA` (Eurobond standard), `ACT/365F` (Moroccan BDT convention). UST-style ACT/ACT with semiannual coupons is representable via ACT/ACT-ICMA.
- Settlement: user-supplied, default T+2 from "today"; accrued from last coupon (or issue proxy) to settlement.
- Solver: Newton–Raphson with analytic derivative, bisection fallback on bracket [−0.99, 10.0]; convergence 1e−10 on price.
- Carry (Phase 1 definition): coupon income + pull-to-par at unchanged yield over the holding period; explicitly labelled "unchanged-yield carry" (no roll-down until Phase 3).

## 10. Testing plan

- **Textbook vectors** (hand-checked, in the Codex brief with expected values to 4 dp): par bond prices at exactly 100; 5y 6% annual @ 4% = 108.9036; 5y 4% annual @ 6% = 91.5753; 10y zero @ 5% = 61.3913 (MacDur exactly 10, ModDur 9.5238); 10y 8% semiannual @ 6% BEY = 114.8775; 30E/360 accrued of a 6% annual bond half-way = 3.00 per 100.
- **Property tests:** price↔yield round-trip to 1e−8; price monotonically decreasing in yield; convexity > 0; DV01 ≈ (P(y−1bp) − P(y+1bp))/2 within tolerance; duration approximation error grows with |Δy| and is reduced by the convexity term; near-maturity bond → price ≈ PV of final flow.
- **Validation-only cross-check:** optional `QuantLib` dev dependency, `pytest.mark.skipif` when absent — used to independently confirm our numbers, never as the production pricer.
- **Error handling:** settlement after maturity, negative coupon, absurd yields, invalid day count → 422 with explicit messages.
- **Router tests:** FastAPI TestClient, both endpoints, envelope completeness (every field of §8 present).

## 11. Key technical and financial risks

1. **Convention drift** — day-count/compounding mismatches produce plausible-looking wrong numbers. Mitigation: conventions are explicit inputs, echoed in every response, and pinned by tests.
2. **False precision on free data** — delayed/stale quotes presented as live. Mitigation: `data_source` + staleness warnings are mandatory envelope fields from day one.
3. **DV01 decomposition overclaim** (§5 Phase 2 correction) — the UI must label the rate/spread split as an approximation under flat-YTM pricing.
4. **Eurobond data mirage** — any design assuming downloadable Eurobond price history will fail; Phase 4 is user-mark-driven by design.
5. **Scope creep into the equity platform** — enforced by module boundaries (§4) and "no equity imports" review rule.
6. **Educational tool ≠ production risk system** — VaR and stress outputs are for learning; banner this in the UI.

## 12. Open decisions

1. Phase 2 persistence shape: dedicated `offshore_instrument` table vs JSON blob per saved bond (leaning table, consistent with repo style).
2. Whether Phase 3 MAD curve ingestion scrapes BAM's site directly or starts from manual CSV upload (BAM publishes daily; scraper fragility unknown — start manual, automate after).
3. Frontend language: existing app is French-labelled; lab pages French, English, or bilingual tooltips (lean French labels + English financial terms, matching the app).
4. Whether the lab gets its own top-level nav section or nests under an existing one.
5. FRED API key handling (free but required): env var via compose, same pattern as existing secrets.

## 13. Codex implementation brief

The separate, self-contained, implementation-ready Phase 1 brief is at **`docs/ai/offshore-lab-phase1-fixed-income.md`**. It contains exact file paths, function signatures, conventions, numeric test vectors, and acceptance criteria, and requires no context beyond the repository itself.

---

## Appendix — Data-source strategy (free-only)

| Category | Source | Coverage | Frequency / depth | Reliability | Use |
|---|---|---|---|---|---|
| User-entered instruments | — | any bond/curve point/futures point | — | as good as the user's marks | **Primary for Phases 1, 2, 4, 6 term structure** |
| UST par yield curve | FRED `DGS1MO…DGS30` / treasury.gov CSV-XML | full curve | daily, decades of history | high | Phase 3 core; production-grade for EOD education |
| Euro-area AAA curve | ECB Data Portal (SDW) | spot/fwd curve params | daily, 2004+ | high | Phase 3 |
| MAD reference curve | Bank Al-Maghrib website (daily publication) | BDT curve | daily; scraping fragility unknown | medium | Phase 3 Moroccan module; start manual CSV |
| FX spot | yfinance (already ingested: EURUSD; add USDMAD, EURMAD, majors) | majors + MAD | daily EOD (delayed intraday) | medium | Phase 5; education only for intraday |
| Deposit/short rates for CIP | FRED (SOFR, €STR via ECB), BAM policy/money-market rates | major ccys + MAD | daily | high/medium | Phase 5 forwards |
| Commodities front-month | yfinance `BZ=F`, `GC=F` (already ingested) | Brent, gold | daily, years | medium | Phase 6 |
| Commodity futures chains | individual Yahoo contract tickers / stooq | spotty, shallow history | daily | **low** | Phase 6 snapshots only, with warnings |
| Eurobond prices | none free (Börse Frankfurt/Luxembourg delayed pages: fragile, ToS-limited) | — | — | **unsuitable** | Phase 4 is user-mark-driven |
| Real yields | FRED `DFII10` | US TIPS 10y | daily | high | Phase 6 gold analysis |

Licensing note: FRED/ECB/treasury.gov are freely redistributable for this use; yfinance is an unofficial API — fine for education, never production; BAM publishes for public information — cache politely, attribute.
