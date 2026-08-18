# Commodity Systematic Strategies — Implementation Plan

**Status:** implementation plan only  
**Prepared:** 2026-07-16  
**Target product:** Offshore Markets Lab / Cross-Asset Strategy Research Lab  
**Primary route:** `/cross-asset-research/commodities`

## 1. Executive summary

The repository already has most of the platform infrastructure needed for a rigorous commodity-research product: a market-agnostic quant package, versioned run records, Parquet/MinIO storage, asynchronous workers, walk-forward testing, robust statistical utilities, risk analytics, API conventions, and mature frontend charting. It does **not** have the commodity-specific primitives that determine whether a futures backtest is financially valid: contract reference data, delivery-safe chain construction, explicit roll accounting, contract multipliers, curve snapshots, multi-leg spread risk, or commodity factor definitions.

Commodity Systematic Strategies should therefore be implemented as the commodity vertical of the planned Cross-Asset Strategy Research Lab. It should reuse the shared instrument, returns, portfolio, validation, persistence, import, and UI foundations described in `docs/offshore-lab/01-cross-asset-research-lab.md` and `docs/ai/cross-asset-lab-slice1.md`. It must not create a second backtester or a second run ledger.

The recommended MVP is deliberately narrow:

1. Contract metadata, immutable datasets, quality gates, and a delivery-safe futures-chain engine.
2. A curve explorer showing raw, unadjusted futures curves and contract liquidity.
3. Nominal curve carry using front/second and front/fourth definitions.
4. A preliminary cross-sectional long-short backtest with explicit outright, roll, collateral, FX, and cost legs.
5. Strong proxy-data warnings and a clean upgrade path to validated uploads or paid data.

The selected data policy is **free proxy first**. Existing Yahoo/yfinance series and freely accessible contract quotes may power exploratory views and preliminary backtests. They must never be labelled tradable or production-quality. Any run must expose its data tier, coverage, missing reference fields, and warnings. Validated exchange, Bloomberg, or vendor uploads use the same canonical schema and supersede proxy data without changing signal or backtest code.

The most important financial invariant is:

> A curve-carry signal is a forecast feature, not a guaranteed return. Tradable futures P&L must be reconstructed from the actual contracts held and rolled. Back-adjusted price series are display/research aids and must not manufacture backtest returns.

---

## 2. Repository audit

### 2.1 Backend architecture

The application is split into four active runtime layers:

| Layer | Current convention | Commodity implication |
|---|---|---|
| Quant core | `core/quant_core/`; pure Python, mostly market-agnostic | All chain, signal, return, portfolio and validation logic belongs here and must not import FastAPI, SQLAlchemy or settings. |
| API | FastAPI in `services/api/app/`; Pydantic schemas, router-level auth, thin orchestration | Commodity endpoints validate inputs, assemble data, enqueue jobs and serialize results; they do not implement finance math. |
| Workers | RQ tasks in `services/worker/tasks/`; queue-specific workers | Imports, proxy refreshes, backtests and expensive robustness jobs run asynchronously. |
| Persistence | Postgres metadata plus Parquet/JSON artifacts in MinIO | Store contract/reference metadata in Postgres; store observation panels and result stages in Parquet/JSON objects. |

`services/api/app/main.py` is the router composition root. Existing asynchronous APIs create a database row, enqueue an RQ job, persist the job id, return HTTP `202`, expose a status endpoint, and refuse to return an incomplete result. Commodity runs should follow that convention.

### 2.2 Frontend architecture

The active frontend is the Next.js App Router application under `frontend/`. Relevant patterns are:

- API calls and zod response validation in `frontend/lib/api.ts`.
- Shared cards, tables, tabs, tooltips, alerts and form controls under `frontend/components/ui/`.
- Plotly through `frontend/components/run/plotly-chart.tsx` for equity curves, drawdowns, heatmaps and dense financial charts.
- Recharts for compact dashboard charts and lightweight-charts for price-centric views.
- Background run polling and terminal-state handling in existing backtest panels.
- French-first labels with English quant terminology where it is standard.

The commodity product should be a dedicated route and component group. It should not add commodity controls to equity Signal or Dashboard screens.

### 2.3 API conventions

Commodity APIs should follow these existing conventions:

- Dedicated Pydantic schema module and router module.
- Existing API-key dependency on protected endpoints.
- JSON-safe numeric sanitization; unavailable values are `null`, not invented zeros.
- `202 Accepted` for imports, backtests and robustness jobs.
- Separate create, status, result and artifact/stage endpoints.
- Structured `422` validation failures and `409` for results requested before completion.
- Response provenance containing methodology version, dataset hash, specification hash, code/git version, timestamps and warnings.

### 2.4 Database and data models

Relevant existing models include:

- `Dataset`: source, content hash, MinIO object key, coverage timestamps and metadata.
- `MarketDataStore`: one current OHLCV object per `(symbol,timeframe)`; appropriate for simple nearby proxies, but not a futures-contract archive.
- `MacroFactorMeta`: currently registers Brent, gold and silver Yahoo futures proxies alongside FX, yields and other macro factors.
- `Run`, `Artifact`, `RunMetric`, `Fill` and run validation/risk records: generic reproducibility and result storage.
- `BloombergIngestBatch` and `BloombergSeries`: immutable Bloomberg bridge uploads, manifests and normalized series.

Do not add a `commodity_run` or duplicate `cross_asset_run` table. Use `Run` with `run_type="commodity_strategy"`. Materialize one immutable dataset-bundle manifest per run so `Run.dataset_id` and `dataset_hash` cover every contract, FX and macro input.

### 2.5 Existing market-data ingestion

The current ingestion system is optimized for OHLCV series:

- yfinance-backed macro ingestion already stores front-month Brent (`BZ=F`), gold (`GC=F`) and silver (`SI=F`).
- Uploaded Excel/CSV/Parquet data is normalized, hashed and stored in MinIO.
- The Bloomberg bridge already separates raw, manifest and normalized objects.
- Cross-market alignment utilities provide explicit lags and staleness-limited forward filling.

What is missing is an asset-class-neutral contract-series catalog. `MarketDataStore` cannot identify multiple delivery months of the same commodity, field-level series, reference-data versions, or point-in-time availability. Add a new series catalog rather than overloading its composite primary key.

### 2.6 Existing backtesting engines

There are several backtest paths, but none is directly suitable for commodity futures:

- `signal_engine/backtest_mc.py` is single-instrument, scalar-position and price-return-only. It has a useful one-bar execution lag and proportional cost convention, but no multipliers, roll legs, collateral, currency conversion or vector portfolio.
- `historical_portfolio.py` is point-in-time and cost-aware, but its opportunity, liquidity, benchmark, lot and Kelly rules are equity/MASI-specific.
- Fundamental cross-sectional backtests contain reusable ranking, turnover and cap ideas, but their cash-equity return model is unsuitable.
- The planned Cross-Asset engine is the correct shared foundation: vector weights, explicit return legs, base-currency conversion, costs, quality gates and inspectable stages.

### 2.7 Portfolio, risk and statistical modules

Reuse rather than duplicate:

- `core/quant_core/risk.py`: bootstrap/Monte-Carlo risk, VaR/CVaR helpers and Kelly utilities where appropriate.
- `core/quant_core/research/stats/ic.py`: Pearson/Spearman concepts and Newey-West/HAC machinery; add a cross-sectional panel adapter rather than another HAC implementation.
- `portfolio_stats.py`: Sharpe, Sortino, drawdown, Calmar, hit rate, turnover and after-cost conventions.
- `robustness.py`: probabilistic/deflated Sharpe, stationary bootstrap confidence intervals and rolling stability.
- `fdr.py`: Benjamini-Hochberg corrections and Sharpe haircuts.
- Generic walk-forward engine in `core/quant_core/wfo/engine.py`.

Existing portfolio functions may be reused for formulas or refactored into generic helpers, but commodity weights and P&L must be generated by the Cross-Asset engine.

### 2.8 Charting and UI components

Reuse:

- `PlotlyChart` for futures curves, equity/drawdown charts, correlation matrices, monthly-return heatmaps and parameter surfaces.
- Existing sensitivity heatmap and run-artifact patterns.
- Existing backtest polling, warning banners, stat cards, ledger tables, tab navigation and responsive layouts.
- Existing glossary/tooltip conventions, but source the formula text from backend strategy metadata so UI and engine definitions cannot drift.

### 2.9 Testing conventions

- Pure quant functions: deterministic pytest fixtures under `core/tests/`.
- API: FastAPI `TestClient`, SQLite/`StaticPool`, dependency overrides and fake queues.
- Worker: SQLite table subsets plus monkeypatched loaders/storage.
- Frontend utilities: Node `node:test` files; TypeScript checked separately.
- Database: Alembic single-head regression test.

Commodity fixtures must be small and hand-calculable. Large downloaded datasets must not be committed.

### 2.10 Existing commodity and offshore work

There is no implemented commodity research module. Existing commodity-related code is limited to:

- Asset taxonomy labels and Yahoo futures roots.
- Macro proxies for Brent, gold and silver.
- Commodity-producer classification used by equity fundamental valuation, which is unrelated to commodity futures strategies.
- Offshore/Cross-Asset design documents and an unimplemented implementation brief.

The prior Offshore Lab design correctly pivoted away from rebuilding Bloomberg pricing. This module continues that direction: transparent research, replication, validation and signal monitoring.

### 2.11 Existing scheduled jobs

The dedicated APScheduler registry currently owns live/daily market refreshes, dashboard snapshots, factor monitoring/recalibration, fundamentals, WFO, signal backtests, score history and point-in-time opportunity materialization. Airflow has manual trigger/sensor DAGs for the warehouse and weekly signal pipeline.

MVP commodity refreshes remain on-demand. After at least 30 successful refresh cycles and an acceptable error/freshness record, add:

- Weekday contract metadata refresh after relevant exchange settlements.
- Weekday proxy settlements refresh.
- Monthly index-methodology/event refresh where a licensed or manual source exists.

Scheduled work must use `scheduler_registry.py` and `scheduler_dispatch.py`, not legacy `rq-scheduler` rows.

### 2.12 Reuse, extend, refactor, avoid

| Action | Components |
|---|---|
| Reuse | `Dataset`, `Run`, artifacts/metrics/folds/risk/significance, MinIO storage, Bloomberg import boundary, alignment, WFO, risk/stats, RQ/API patterns, Plotly and frontend UI primitives. |
| Extend | Asset taxonomy, shared Cross-Asset instrument/spec/returns/portfolio modules, API client schemas, navigation, scheduler registry after MVP. |
| Refactor carefully | Extract generic run-status/artifact helpers if the commodity router would otherwise copy existing router code; extract panel IC/HAC adapters from current stats. |
| Avoid | Equity backtest engines, row-per-observation SQL tables, silent forward filling, ticker-based contract ordering, back-adjusted return calculation, direct vendor calls inside pure signal functions. |

---

## 3. Existing reusable components

The commodity layer depends on the planned shared package:

```text
core/quant_core/cross_asset/
    instruments.py
    returns.py
    portfolio.py
    costs.py
    strategy_spec.py
    dataquality.py
    backtest.py
    validation.py
    importer.py
```

Commodity-specific logic belongs below `cross_asset/commodity/`; it must not fork these shared concerns. If the shared package has not been implemented when commodity work starts, Phase 1 includes the minimum shared subset required by commodities. Its interfaces must remain compatible with the FX vertical described in `cross-asset-lab-slice1.md`.

Every pure signal function accepts already-normalized, point-in-time data and returns deterministic series/panels plus diagnostics. It does not load from the database, call vendors, infer current time, or mutate inputs.

---

## 4. Data architecture

### 4.1 Storage model

Add the following metadata tables through Alembic:

#### `cross_asset_instrument`

One row per commodity root or non-futures instrument.

| Field | Purpose |
|---|---|
| `id`, `canonical_symbol`, `display_name` | Stable internal identity. |
| `asset_class`, `sector`, `subsector` | Commodity grouping and neutralization. |
| `exchange`, `exchange_mic`, `trading_calendar` | Calendar and venue. |
| `currency`, `quote_unit`, `unit_of_measure` | Pricing interpretation. |
| `contract_multiplier`, `tick_size`, `tick_value` | Quantity and P&L. |
| `delivery_type` | `physical` or `cash`. |
| `source_priority_json` | Licensed/upload/proxy precedence. |
| `active_from`, `active_to`, `metadata_json` | Point-in-time universe and provider-specific fields. |

#### `futures_contract`

One row per listed delivery contract and metadata version.

| Field | Purpose |
|---|---|
| `instrument_id`, `contract_code`, `delivery_month` | Contract lineage. |
| `first_trade_date`, `expiry_date`, `first_notice_date`, `last_trade_date` | Ordering and delivery safety. |
| `first_delivery_date`, `last_delivery_date` | Diagnostics. |
| `multiplier_override`, `currency_override` | Historical specification changes. |
| `available_at`, `source`, `source_ref`, `quality_tier` | PIT and provenance. |
| `valid_from`, `valid_to` | Metadata revision history. |

Unique identity is `(instrument_id, contract_code, valid_from)`, not just ticker.

#### `cross_asset_series_store`

Catalogs immutable Parquet objects rather than storing observations in SQL.

| Field | Purpose |
|---|---|
| `dataset_id`, `instrument_id`, `contract_id` | Provenance and identity. |
| `field`, `frequency`, `object_key` | Series lookup. |
| `start_ts`, `end_ts`, `available_at`, `row_count` | Coverage/PIT. |
| `source`, `quality_tier`, `currency`, `sha256` | Audit and priority. |
| `quality_json` | Missing/stale/duplicate/outlier results. |

#### `cross_asset_strategy`

Stores immutable strategy definitions: name, semantic version, specification JSON, stable hash, research source, replication fidelity, status and timestamps.

Phase 6 adds `commodity_index_methodology` and `commodity_index_event`. Do not create them in the MVP migration.

### 4.2 Canonical observation schema

All adapters normalize into a long-form contract:

```text
instrument_id
commodity_root
contract_code
trade_date
available_at
field                  # settle|open|high|low|close|volume|open_interest|fx|rate|inflation|index_weight
value
currency
contract_expiry
source
source_record_id
revision_id
```

`available_at` is mandatory for research-grade data. Proxy data without a reliable release timestamp receives a conservative availability rule defined by the adapter and a warning.

### 4.3 Minimum data by strategy

| Strategy | Essential data | Production-quality additions |
|---|---|---|
| Curve carry | Root, sector, contract code, expiry, settlement, multiplier, currency; at least two eligible maturities | FND/LTD, OI/volume, official exchange calendar, bid/ask, FX and collateral rate. |
| Curve shape/spreads | At least three simultaneous maturities and contract multipliers | Tick/spread liquidity, intraday or official spread settlements, covariance history. |
| Historical skewness | Tradable root-level excess returns and roll map | Longer clean history, costs and PIT universe membership. |
| Index rebalancing | Methodology version, target/current weights, announcement/effective/roll dates | Historical constituent files, tracking AUM, actual flows, contract-level index roll definitions. |
| Real carry | Nominal carry and inflation expectation with tenor/currency | Inflation swaps/surveys, revision-aware forecasts and commodity-specific inflation betas. |
| Multi-factor | Synchronized carry, momentum, skewness and curve panels | Longer common sample, value/inventory proxies and capacity data. |

### 4.4 Data availability tiers

#### Essential for MVP

- Commodity root, sector, exchange and currency.
- Contract code, delivery month/expiry, multiplier and daily settlement.
- Volume/open interest where available; missing liquidity fields reduce quality rather than being imputed.
- At least two simultaneous contracts for carry.
- Contract roll map and daily collateral-rate proxy.
- FX conversion for non-USD contracts.

#### Useful for production quality

- First notice, last trade and delivery dates from exchange reference data.
- Official holidays, settlement calendars and historical specification changes.
- Bid/ask spreads, ticks, commissions, margins, exchange position limits and spread volume.
- Revision-aware macro and inflation data.
- Index target/current weights, roll schedules and event timestamps.

#### Difficult or unavailable with free data

- Deep, clean histories of every expired individual contract with official settlement, OI and volume.
- Historical index weights, announcement files and roll calendars in machine-readable form.
- Historical tracking AUM and realized index-fund flows.
- Inflation swaps and professional survey vintages across currencies.
- Historical bid/ask and market-impact calibration.

#### Manual upload

- Exchange/vendor contract histories.
- Bloomberg exports through the existing bridge.
- Index methodology, constituent and target-weight files.
- Tracking-AUM scenarios and internally observed transaction costs.
- Inflation forecasts or swap curves licensed to the desk.

#### Paid provider

- CME DataMine for official CME/CBOT/NYMEX/COMEX history.
- ICE Data Services for ICE contracts and reference data.
- Bloomberg, LSEG/Refinitiv, FactSet or another approved institutional provider for normalized global chains, indices, macro and reference data.

### 4.5 Free and accessible sources

- Existing yfinance ingestion: nearby price display, momentum/skewness proxy and opportunistic individual contract data. Yahoo data is informational and not intended as trading validation.
- CME public product calendars and contract specifications: active metadata and delivery safety, subject to availability and website terms.
- CFTC COT: weekly aggregate positioning and open-interest context only; it cannot reconstruct a daily curve.
- FRED/Federal Reserve: collateral rates, breakeven inflation and real yields.
- EIA/USDA public data: later value/inventory context, not a substitute for futures settlements.
- Public S&P GSCI and Bloomberg Commodity Index methodologies: rules and selected current disclosures; detailed historical files remain licensing-sensitive.

Every adapter records source URL/provider, retrieval time, terms/licensing note, transformation version and raw hash. The UI must not imply redistribution rights merely because data was technically accessible.

### 4.6 Source priority and conflicts

Default priority is `licensed > uploaded_verified > proxy > fixture`. A higher-priority dataset never silently splices into a lower-priority history. It creates a new immutable dataset bundle, and comparison tools expose overlap differences before promotion.

---

## 5. Futures-chain methodology

### 5.1 Contract ordering and eligibility

For observation date `t`:

1. Select the metadata version known by `t`.
2. Exclude contracts not yet listed or already beyond their last trade date.
3. Compute the delivery-safety date.
4. Exclude contracts whose safety date is on/before the intended exit or roll date.
5. Apply settlement freshness and liquidity filters.
6. Order remaining contracts by expiry/delivery month, never symbol text.

Default safety date:

```text
min(first_notice_date, last_trade_date) - 5 exchange business days
```

If first notice is unavailable, use `last_trade_date - 5 exchange business days`. If both are unavailable, the contract is proxy-only and cannot pass the research-grade gate.

### 5.2 Liquidity and missing contracts

- Default eligibility requires a positive settlement and either OI or volume where supplied. Negative settlements remain valid; only missing/non-finite prices are invalid.
- Production default: trailing 20-session median volume and OI must exceed configurable per-root thresholds.
- A missing intermediate maturity is preserved as a gap. The API reports requested tenor, selected contract, actual maturity and gap reason.
- Stale settlement default: exclude after two expected exchange sessions without a new value; thresholds are configurable per market.
- No silent forward-fill across contract observations. Curves show missing points.

### 5.3 Roll rules

Support three named rules:

1. `delivery_safe`: roll five exchange sessions before the earlier of FND/LTD; MVP default.
2. `volume_crossover`: roll when next-contract volume exceeds current-contract volume for two consecutive sessions, bounded by the delivery-safe date.
3. `open_interest_crossover`: equivalent rule using OI, also safety-bounded.

The roll decision uses only data available at the prior settlement. The new contract becomes effective at the next configured execution settlement.

### 5.4 Continuous series

Produce separate artifacts:

- **Unadjusted active-contract series:** actual held contract price; gaps/jumps remain.
- **Ratio-adjusted series:** display/trend research where all splice prices are positive.
- **Difference-adjusted series:** optional display for histories containing non-positive prices.
- **Constant-maturity series:** interpolate in log price for positive prices; use linear price interpolation otherwise, with method flag.
- **Tradable return series:** reconstructed from actual held contracts and roll transactions; never derived from adjusted levels.

### 5.5 Return decomposition

For held contracts `q_t`, multiplier `M`, settlement `F_t`, base FX conversion `X_t`, and collateral rate `r_t`:

```text
outright_pnl_t = q_(t-1) * M * (F_t - F_(t-1)) * X_t
roll_pnl_t     = explicit close-old/open-new execution difference and costs on roll date
collateral_t   = collateral_balance_(t-1) * lagged_rate * day_fraction
fx_pnl_t       = local-currency P&L conversion effect
net_pnl_t      = outright + roll + collateral + fx - costs
```

The implementation may express roll as part of contract-level mark-to-market plus trade ledger cash flows, but reported attribution must reconcile exactly to total P&L.

### 5.6 Which series to use

| Use | Series |
|---|---|
| Signal calculation | Raw unadjusted simultaneous curves or explicitly labelled constant-maturity points. |
| Backtest returns | Actual contract settlement P&L and roll ledger. |
| Curve charts | Raw contract points with maturity, volume, OI and safety dates. |
| Long historical price charts | User-selectable unadjusted/ratio/difference-adjusted series, prominently labelled. |
| Momentum/skewness research | Tradable root-level excess-return series; adjusted prices only as a diagnostic comparison. |

---

## 6. Exact strategy specifications

### 6.1 Common signal contract

Every signal returns:

```text
value, raw_value, normalized_value, rank, direction,
as_of, available_at, inputs, selected_contracts,
formula_id, sign_convention, quality, warnings, rationale
```

Cross-sectional normalization is date-local. Default preprocessing is median/MAD z-score after cross-sectional 2.5%/97.5% winsorization when at least eight commodities are eligible; otherwise use percentile ranks and flag the small universe.

### 6.2 A. Commodity curve carry

#### Definitions

For near and far contracts with positive prices and maturities `T_n < T_f` in years:

```text
log_carry = ln(F_near / F_far) / (T_far - T_near)
```

Positive carry means backwardation: the near contract is more expensive than the far contract, so the signal favors a long position. Negative carry means contango and favors a short position in a long-short portfolio.

Supported variants:

- `front_second_log`
- `front_third_log`
- `front_fourth_log`
- `annualized_linear_slope = (F_near/F_far - 1) / ΔT`
- `carry_per_vol = log_carry / lagged_annualized_vol`
- Constant-maturity pairs such as 1m/3m, 1m/6m and 3m/12m.

For zero or negative prices, log carry is unavailable. A distinct fallback may be requested:

```text
simple_normalized_slope = (F_near - F_far) / (max(abs(F_near), epsilon) * ΔT)
```

It must retain a different `formula_id`; the engine never silently substitutes it.

#### Contract selection

- `front` means first delivery-safe and liquid contract, not nearest expiry unconditionally.
- Far legs are positions in the eligible ordered chain; missing maturities yield unavailable variants.
- Constant maturities interpolate only between bracketing contracts; no extrapolation beyond the observed curve.

#### Portfolio construction

- Default formation: last eligible settlement of each month.
- Signal is observed at `t`, weights are decided using data through `t`, and execution occurs at the next settlement.
- Default long top tercile / short bottom tercile.
- Equal 50% long and 50% short gross before volatility scaling.
- Optional inverse-volatility weights use 60-session exponentially weighted volatility, lagged one day.
- Portfolio volatility target: 10% annual.
- Maximum absolute commodity weight: 15%.
- Maximum sector gross exposure: 40%.
- Maximum gross leverage: 200%; maximum net: 10% for market-neutral mode.

Sector-neutral mode ranks and balances within sector. A sector with fewer than two eligible commodities is excluded from the neutral portfolio and reported; it is not paired against itself.

#### Required decomposition

The UI and result artifacts separately report:

- Curve-carry signal at formation.
- Outright futures price return.
- Realized roll P&L.
- Collateral return.
- Currency effect.
- Transaction costs.

No component is described as guaranteed carry.

### 6.3 B. Curve-shape and calendar-spread strategies

Support:

- Front/back slopes and changes in slope.
- Calendar-spread levels and changes.
- Three-point curvature:

```text
curvature = F_mid - [w * F_near + (1-w) * F_far]
w chosen from maturity spacing
```

- Butterflies implemented as explicit three-contract positions.
- Expanding-window curve PCA with level, slope and curvature scores.
- Mean reversion or momentum in standardized spread returns.

Risk normalization choices:

- **Multiplier neutral:** equal and opposite dollar contract notionals.
- **Dollar-vol neutral:** size legs using lagged individual dollar volatilities.
- **Spread-vol target:** size the complete spread/butterfly from its lagged realized P&L volatility.
- **Regression hedge:** expanding-window OLS hedge ratio with minimum 126 observations; coefficients lagged before use.

PCA is fit only on the expanding training window. Component signs are stabilized against prior loadings so a numerical sign flip cannot reverse a strategy. Missing tenors use the common supported-tenor subset; the engine does not impute a full curve from one price.

“DV01-like” commodity risk means dollar P&L for a standardized one-tick or 1% parallel curve move. It must not be labelled DV01 because commodity prices are not yields.

### 6.4 C. Historical skewness factor

Input returns are daily tradable commodity-root excess returns after explicit rolls, not percentage changes of a back-adjusted level.

Default windows:

- 63 sessions (~3 months)
- 126 sessions (~6 months)
- 252 sessions (~12 months)

Require at least 80% valid observations and at least 40/80/160 observations respectively.

Estimators:

1. Unbiased sample skewness.
2. Winsorized skewness after time-series 1%/99% clipping within the trailing window.
3. Bowley skewness `(Q3 + Q1 - 2*median)/(Q3-Q1)` for a robust quantile measure.

The primary hypothesis is long negative-skew commodities and short positive-skew commodities, consistent with compensation for crash/tail exposure. Because the hypothesis is not universally stable, both directions are pre-registered variants and corrected together for multiple testing.

Independence tests:

- Cross-sectional Fama-MacBeth-style or pooled regressions of forward returns on skewness plus carry, momentum, volatility, liquidity and sector controls.
- HAC-adjusted inference on coefficient time series.
- Factor-residual portfolios after neutralizing skewness against those controls using expanding data only.
- Sector-neutral and unrestricted portfolios.
- Leave-one-sector and leave-one-commodity-out analysis.

### 6.5 D. Commodity index rebalancing

Treat two event families separately.

#### Constituent/weight rebalancing

Store methodology version, announcement timestamp, reference/observation window, old weights, target weights, effective date and execution window. Estimated flow for commodity `i`:

```text
estimated_notional_i = (target_weight_i - estimated_current_weight_i) * tracking_AUM
estimated_contracts_i = estimated_notional_i / (futures_price_i * multiplier_i)
```

Tracking AUM is never inferred as fact. The UI supports low/base/high AUM scenarios and labels all flows “estimated”.

#### Futures roll flows

Store index roll calendar, old/new contract allocations, roll window, daily roll fractions and relevant calendar spread. Estimate buy/sell contracts separately from annual weight rebalance.

#### Event-study first design

Canonical events contain `known_at`, `announcement_date`, `execution_start`, `effective_date`, affected contracts, expected flow and confidence. Default event windows:

- Pre-event: `[-10,-2]`
- Immediate: `[-1,+1]`
- Execution: methodology-specific roll/rebalance window
- Reversal: `[+2,+10]`

Use the planned generic event-study engine for abnormal returns, CAR/CAAR, bootstrap confidence intervals and multiple-testing control. Until historical index data is validated, results are scenario studies rather than production signals.

### 6.6 E. Nominal versus real carry

Nominal carry is always computed and stored first. Inflation adjustment is a versioned strategy parameter:

1. Difference approximation:

```text
real_carry_difference = nominal_carry - expected_inflation
```

2. Fisher adjustment:

```text
real_carry_fisher = (1 + nominal_carry) / (1 + expected_inflation) - 1
```

3. Later beta-adjusted method:

```text
real_carry_beta = nominal_carry - beta_inflation_i * expected_inflation
```

`beta_inflation_i` must be estimated on an expanding window and lagged. Inflation sources may be breakevens, swaps, surveys or forecasts; the source, tenor, currency, release timestamp and revision policy are part of the specification.

If the same inflation scalar is applied to every commodity, the cross-sectional ordering usually does not change. The comparison view must state this and distinguish changes in absolute level/performance from changes in rankings.

### 6.7 Factor comparison and combinations

Register every factor with a common interface and metadata:

- Carry
- Momentum (1/3/6/12-month trailing excess return, with the most recent month optionally skipped)
- Skewness
- Curve slope
- Curve curvature
- Real carry
- Value-like signals when defensible inventory/spot/production data exists
- Index-event signals

Compare:

- Signal rank correlations.
- Pearson/Spearman IC and IC correlations.
- Portfolio return correlations.
- Position overlap and conflicting signs.
- Sector, volatility, carry and momentum exposures.
- Incremental regression contribution and leave-one-factor-out attribution.

Initial combinations:

- Equal-weight z-scores.
- 50/50 carry plus momentum.
- 50/50 carry plus skewness.
- Inverse-risk factor sleeves.
- Trailing OOS IC weights with shrinkage toward equal weight.

No trees, neural networks, automated feature search or opaque optimization in v1.

---

## 7. Backtesting methodology

### 7.1 Point-in-time rules

- Universe eligibility, contract metadata, settlements, OI/volume, FX, rates, inflation and index events use only versions available by the decision timestamp.
- The dataset bundle records every source object and content hash.
- Changes after a decision date must not alter earlier signals in perturbation tests.
- Delisted commodities/contracts remain in historical bundles; the current active universe cannot replace the historical universe.

### 7.2 Timeline

Default daily sequence:

1. Exchange settlement and ancillary fields become available.
2. Signal and lagged risk estimates are calculated.
3. Target weights/contracts are stored.
4. Execution occurs at the next settlement (`execution_delay=1`).
5. P&L accrues from previously executed positions.

Monthly strategies use the last valid formation settlement and next-session execution. Index-event specifications may define a different, explicit execution window.

### 7.3 Position and contract sizing

Research weights are converted to contracts using:

```text
contracts_i = target_weight_i * portfolio_NAV / (price_i * multiplier_i * FX_i)
```

The research engine may retain fractional contracts to compare signals cleanly, but must also report an integer-contract feasibility portfolio using deterministic rounding and residual cash. Small portfolios that cannot express neutral spreads receive a warning.

### 7.4 Costs and impact

Per trade, support:

- Half-spread in ticks or basis points.
- Commission/exchange fee per contract.
- Slippage in ticks.
- Optional square-root impact:

```text
impact_bps = eta * daily_vol_bps * sqrt(abs(quantity) / max(ADV_contracts, 1))
```

All parameters are instrument/source-specific where available. Proxy defaults are sensitivity assumptions, not measured costs. Report 0.5x, 1x, 2x and 3x cost scenarios.

### 7.5 Liquidity, capacity and limits

- Maximum participation in trailing median daily volume, default 5% for preliminary research.
- OI participation and exchange position-limit checks when metadata exists.
- Hard block when required delivery metadata is absent for a research-grade physical contract.
- Report turnover, contracts traded, estimated capacity and binding constraints.

### 7.6 Margin and collateral

- Futures exposure is measured on notional and dollar volatility, not cash paid.
- Default fully collateralized model earns the selected lagged collateral rate on unencumbered cash.
- Optional margin model stores initial/maintenance margin assumptions and financing cost but does not invent historical margin when unavailable.
- Leverage limits apply to gross futures notional and forecast volatility.

### 7.7 Portfolio modes

Support:

- Long-only.
- Long-short.
- Market-neutral by dollar gross/net.
- Sector-neutral.
- Volatility-scaled.

All modes share the same lag, contract, cost and return pipeline.

### 7.8 Failure regimes

Tag and analyze at least:

- 2008 financial crisis.
- 2014–2016 oil collapse.
- 2020 negative WTI/COVID shock.
- 2021–2022 inflation/energy shock.
- High/low cross-sectional dispersion.
- Backwardation/contango regimes.
- High/low volatility and liquidity regimes.

Date labels are configurable research annotations, not optimized filters.

---

## 8. Statistical-validation framework

### 8.1 Signal diagnostics

At each formation date calculate cross-sectional Pearson IC and Spearman/rank IC against 1-day, 1-week and next-rebalance tradable returns. Summarize the IC time series using:

- Mean, standard deviation and information ratio.
- Newey-West/HAC t-statistic of mean IC.
- Hit rate (`IC > 0`).
- Rolling mean and confidence bands.
- IC decay by horizon.

### 8.2 Portfolio metrics

- Gross/net annualized return and volatility.
- Sharpe and Sortino.
- Maximum drawdown and Calmar.
- Hit rate, profit factor and tail loss/expected shortfall.
- Turnover, cost drag and capacity.
- Gross/net exposure, sector exposure and per-commodity contribution.
- Long and short sleeve attribution.
- Roll, outright, collateral, FX and cost attribution.

### 8.3 Confounding exposures

For every factor, report exposure to momentum, carry, volatility, liquidity and sector. For skewness and real carry, report raw and residualized results. Use expanding-window neutralization; never residualize on the full sample.

### 8.4 Out-of-sample design

- Freeze a selection period, proof period and live/monitoring period in the run specification.
- Use expanding walk-forward folds with embargo at least equal to the longest forward-return horizon.
- Parameter variants are registered before running the proof period.
- Report fold-by-fold selections and stitched OOS returns; do not blend in-sample returns into the headline curve.

### 8.5 Bootstrap and multiple testing

- Stationary-block bootstrap confidence intervals for Sharpe, mean return, IC and maximum drawdown summaries.
- Benjamini-Hochberg FDR across related strategy variants.
- Deflated Sharpe using the full number of tried variants, including discarded ones.
- Parameter heatmaps show neighboring values, not only the winner.

### 8.6 Promotion gates

A signal may be labelled “validated” only if:

- Data quality passes the research-grade threshold.
- At least 60 formation dates and eight commodities are available, or the limitation is explicitly approved for a narrower specialist universe.
- OOS IC/portfolio direction agrees with the registered hypothesis.
- Net performance survives at least 2x assumed costs.
- Bootstrap uncertainty and FDR-adjusted evidence are disclosed.
- Leave-one-commodity-out results do not show that one instrument explains more than 50% of total P&L.
- Adjacent parameters do not reverse the result without an economic reason.

Proxy runs cannot be promoted beyond “preliminary”, regardless of statistical results.

---

## 9. UI and API design

### 9.1 Page information architecture

Create `frontend/app/cross-asset-research/commodities/page.tsx` with six views.

#### Market overview

Table columns:

- Commodity/root, sector, exchange and currency.
- Nearby price and active contract.
- Curve state, nominal carry, momentum, skewness and volatility.
- Current signal, intended position and change from previous position.
- Data tier, freshness, coverage and warnings.

#### Curve explorer

- Raw futures curve chart by maturity.
- Historical curve comparison for selected dates.
- Contract table with expiry/FND/LTD/safety date, settlement, volume, OI, multiplier and freshness.
- Calendar-spread table.
- Annualized carry, slope and curvature.
- Roll rule visualization and active/next contracts.
- Continuous-series method selector with explanatory warning.

#### Strategy explorer

- Strategy and formula selector.
- Formation frequency, near/far tenor, volatility, liquidity and neutrality controls.
- Current cross-sectional ranking and long/short baskets.
- Per-position rationale listing contracts, formula inputs, risk scale and constraints.
- Data-quality report and formula-specific warnings.

#### Backtest dashboard

- Gross/net equity curve and drawdown.
- Rolling Sharpe, volatility and factor IC.
- Monthly returns, turnover and costs.
- Sector/commodity/gross/net exposures.
- Outright/roll/collateral/FX attribution.
- Regime and subperiod analysis.
- Trade/roll ledger and rejected-position reasons.

#### Factor comparison

- Factor and IC correlation matrices.
- Individual and combined factor curves.
- Position overlap/conflicts.
- Marginal contribution and leave-one-factor-out results.
- Combination method and OOS weight history.

#### Index events

- Upcoming/past events, methodology version and confidence.
- Target/current weights, AUM scenario and estimated buy/sell contracts.
- Roll schedule and calendar-spread pressure.
- Event-study CAAR, confidence intervals, pre/event/reversal returns.

### 9.2 Tooltips and explanations

Every signal response includes structured methodology metadata used by a common tooltip:

- Formula and formula version.
- Economic meaning.
- Inputs and timestamps.
- Sign convention.
- Current interpretation.
- Main risks and data limitations.

Do not duplicate formula prose in individual React components.

### 9.3 API surface

Prefix: `/cross-asset-research/commodities`.

| Method/path | Purpose |
|---|---|
| `POST /datasets/validate` | Validate canonical upload/proxy bundle and return quality report. |
| `POST /datasets/import` | Persist accepted immutable dataset and enqueue normalization. |
| `GET /universe?as_of=` | PIT eligible universe, active contracts and freshness. |
| `GET /curves/{root}?as_of=&compare=` | Raw curve, contracts, spreads, roll map and diagnostics. |
| `POST /signals/preview` | Pure signal/ranking/position explanation without persisting a run. |
| `POST /runs` | Persist specification/dataset bundle and enqueue backtest. |
| `GET /runs/{id}` | Status, progress, provenance and terminal metrics. |
| `GET /runs/{id}/result` | Completed backtest result; `409` until terminal. |
| `GET /runs/{id}/stages` | Raw/tradable/signal/target/executed/gross/cost/net artifacts. |
| `GET /runs/{id}/robustness` | WFO, bootstrap, FDR, costs, LOO and subperiods. |
| `POST /factor-comparisons` | Factor/IC/portfolio correlations and combinations. |
| `GET/POST /index-events` | Query/import methodology and event records. |
| `POST /index-events/studies` | Enqueue event study. |

Expensive factor comparisons may return `202` and use the same run infrastructure.

### 9.4 Transparency envelope

Analytical payloads contain:

```json
{
  "inputs": {},
  "methodology": {"id": "...", "version": "..."},
  "data_source": {"tier": "proxy", "providers": []},
  "calculation_date": "...",
  "assumptions": [],
  "units": {},
  "warnings": [],
  "results": {},
  "interpretation": "..."
}
```

Proxy and fixture banners derive from `data_source.tier` and cannot be dismissed for the run.

---

## 10. Proposed file structure

```text
core/quant_core/cross_asset/
    instruments.py
    returns.py
    portfolio.py
    costs.py
    strategy_spec.py
    dataquality.py
    backtest.py
    validation.py
    importer.py
    commodity/
        __init__.py
        chains.py
        continuous.py
        carry.py
        curve_shape.py
        skewness.py
        real_carry.py
        index_events.py
        factors.py

services/api/app/
    schemas/cross_asset_research.py
    routers/cross_asset_research.py
    services/cross_asset/
        __init__.py
        datasets.py
        commodity.py
        runs.py

services/worker/tasks/cross_asset/
    __init__.py
    import_dataset.py
    refresh_proxy_data.py
    run_commodity_backtest.py
    run_commodity_validation.py

frontend/
    app/cross-asset-research/commodities/page.tsx
    components/cross-asset/commodities/
        market-overview.tsx
        curve-explorer.tsx
        contract-table.tsx
        strategy-explorer.tsx
        signal-rationale.tsx
        backtest-dashboard.tsx
        factor-comparison.tsx
        index-events.tsx
        methodology-tooltip.tsx

core/tests/
    fixtures/cross_asset/commodity_contracts_sample.csv
    fixtures/cross_asset/commodity_index_events_sample.csv
    test_commodity_chains.py
    test_commodity_returns.py
    test_commodity_carry.py
    test_commodity_curve_shape.py
    test_commodity_skewness.py
    test_commodity_real_carry.py
    test_commodity_index_events.py
    test_commodity_factor_portfolio.py

services/api/tests/test_commodity_research_router.py
services/worker/tests/test_commodity_research_tasks.py
```

Expected modifications are limited to router registration, API client/zod schemas, navigation, model/migration registration, worker task exports and—after MVP validation—scheduler registry/dispatch.

---

## 11. Testing plan

### 11.1 Hand-calculated chain fixtures

Build a five-contract synthetic oil chain with known expiry, FND, LTD, prices, OI and volume. Test:

- Expiry ordering independent of input/ticker order.
- Front selection before/after safety dates.
- Volume/OI crossover confirmation.
- Missing second/third maturity.
- Stale front contract exclusion.
- Physical-delivery avoidance.
- Different exchange holidays.

### 11.2 Carry fixtures

- Backwardation: `F1=100`, `F2=95`, `ΔT=0.25`; carry is positive.
- Contango: `F1=95`, `F2=100`; carry is negative.
- Annualization and log/simple formula values checked manually.
- Near-expiry contract excluded before formula evaluation.
- Zero and negative prices: log unavailable, explicit simple fallback works.
- Constant-maturity interpolation uses correct maturity weights and never extrapolates.

### 11.3 Return and roll fixtures

- Two contracts with a known roll date and multiplier; contract ledger P&L reconciles to NAV change.
- Back-adjusted display return is never consumed by the backtest path.
- Outright + roll + collateral + FX − costs equals net P&L exactly.
- Currency conversion uses same-date available FX and correct quote direction.
- Multiplier/tick-value changes create a new metadata version.

### 11.4 Curve-shape fixtures

- Calendar spread signs and changes.
- Uneven-maturity curvature weights.
- Butterfly quantities and dollar risk.
- Spread-vol scaling.
- Expanding regression hedge ratio excludes future observations.
- PCA loadings and scores are expanding-window and sign-stable.

### 11.5 Skewness fixtures

- Symmetric returns produce approximately zero skew.
- Engineered negative-tail sample yields negative skew and a long signal.
- Winsorization reduces a single-outlier effect.
- Bowley skewness matches hand-calculated quartiles.
- Minimum observation requirements produce unavailable status.

### 11.6 Portfolio and cost fixtures

- Long/short gross and net neutrality.
- Sector neutrality and insufficient-sector exclusion.
- Maximum commodity/sector/gross caps.
- Lagged volatility targeting and no-look-ahead perturbation.
- Tick spread, commission, slippage, square-root impact and turnover arithmetic.
- Liquidity/position-limit rejection reasons.
- Fractional research vs integer-contract feasibility reconciliation.

### 11.7 Real carry and index fixtures

- Difference and Fisher real-carry formulas.
- Common inflation scalar leaves ranks unchanged and triggers explanatory diagnostic.
- Lagged commodity-specific beta adjustment.
- Index target/current weight flow arithmetic.
- AUM low/base/high scaling is linear.
- Announcement known after cutoff cannot affect prior event signal.
- Annual weight rebalance and contract roll flows remain separate.

### 11.8 Integration and regression

- Import → dataset hash → curve → signal → run → artifact → UI schema.
- Same spec, dataset bundle and seed produce identical outputs.
- Fake RQ queue persists job id and exposes status.
- Incomplete result returns `409`; failed run returns structured error.
- Proxy tier always emits non-tradable warnings.
- Existing core/API/worker tests remain green.
- Alembic has one head.
- Frontend zod rejects malformed financial payloads; TypeScript/build pass.

Verification commands:

```text
python -m pytest core/tests -q --tb=short
python -m pytest services/api/tests services/worker/tests -q --tb=short
cd frontend && node --test "lib/*.test.mjs"
cd frontend && npx tsc --noEmit
cd frontend && npm run build
alembic -c services/api/alembic.ini heads
```

After any implementation code changes, run `graphify update .` as required by `AGENTS.md`.

---

## 12. Phased roadmap

### Phase 1 — Futures curve foundation

**Objective:** establish trustworthy contract identity, datasets, chains and curve visualization.

**Backend:** shared instrument/spec/import subset; metadata/series tables; canonical import/proxy adapters; quality gates; delivery-safe chain and continuous display series.

**Frontend:** commodity route, market overview, curve explorer, contract table, freshness/quality banners.

**Data:** synthetic fixtures, existing nearby proxies, selected individual free contract proxies, manual CSV/Bloomberg import.

**Tests:** ordering, expiry/FND/LTD, rolls, gaps, stale data, multipliers, currencies, negative prices and import hashes.

**Acceptance:** a user can inspect an unadjusted curve, see exactly which contracts are eligible, understand the roll boundary and reproduce the dataset from its manifest.

**Main risks:** inconsistent free symbols, missing expired contracts and incomplete delivery metadata.

**Complexity:** Large.

### Phase 2 — Nominal carry

**Objective:** calculate transparent carry variants and run the first preliminary futures-aware backtest.

**Backend:** carry calculators, rankings, long-short construction, roll/collateral/FX decomposition, costs and core validation.

**Frontend:** strategy explorer, formula/rationale tooltips, current baskets and basic backtest dashboard.

**Data:** at least two maturities per eligible root; collateral and FX proxies.

**Tests:** carry signs/annualization, near-expiry rules, constant maturity, neutrality, P&L reconciliation and look-ahead prevention.

**Acceptance:** every position traces to curve inputs and contract quantities; net returns reconcile; proxy runs remain labelled preliminary.

**Main risks:** small proxy universe, spurious results from noisy continuous/contract data and unrealistic cost assumptions.

**Complexity:** Medium.

### Phase 3 — Curve relative value

**Objective:** support spreads, slope/curvature and multi-leg curve trades.

**Backend:** calendar spread/curve-change features, butterflies, expanding PCA and four normalization modes.

**Frontend:** spread matrix, historical curve comparison, multi-leg ticket/risk and PCA diagnostic views.

**Data:** three or more simultaneous maturities, multiplier history and spread liquidity.

**Tests:** hedge ratios, butterfly risk, PCA PIT behavior, negative/missing maturities and spread costs.

**Acceptance:** each multi-leg trade has quantities, dollar/tick risk, expected costs and a reconciled ledger.

**Main risks:** unstable PCA in small samples and underestimating spread execution costs.

**Complexity:** Large.

### Phase 4 — Historical skewness factor

**Objective:** evaluate whether commodity skewness predicts returns independently of known factors.

**Backend:** three estimators/windows, rankings, residualization, exposure regressions and robustness tests.

**Frontend:** estimator comparison, current ranks, IC decay, control exposures and outlier diagnostics.

**Data:** clean tradable excess-return histories, preferably 3+ years.

**Tests:** skew/outlier/minimum-observation fixtures, neutralization and no-look-ahead regressions.

**Acceptance:** raw and controlled results are shown side by side with sector, carry, momentum, vol and liquidity exposures.

**Main risks:** outlier sensitivity, short history and dependence on the roll construction.

**Complexity:** Medium.

### Phase 5 — Real carry

**Objective:** compare configurable inflation-adjusted carry with nominal carry.

**Backend:** FRED/inflation adapters, PIT alignment, difference/Fisher methods, later expanding beta method and incremental tests.

**Frontend:** source/method selector, nominal-vs-real ranks, performance and incremental IC panels.

**Data:** breakevens/real yields for MVP; licensed swaps/survey vintages later.

**Tests:** formulas, release lags/revisions, common-scalar ranking diagnostic and beta look-ahead.

**Acceptance:** method/source/tenor is explicit, nominal values remain available, and incremental value is quantified rather than assumed.

**Main risks:** provider definitions differ and a common inflation adjustment may add no cross-sectional information.

**Complexity:** Medium.

### Phase 6 — Index rebalancing

**Objective:** create a point-in-time event-study framework for index weight and roll flows.

**Backend:** methodology/event tables, importers, scenario AUM, flow estimation, roll-pressure features and event-study integration.

**Frontend:** event calendar, weight/flow tables, scenario controls, CAAR and reversal views.

**Data:** methodology documents and manually/licensed historical weights/events; AUM scenarios.

**Tests:** PIT timestamps, flow arithmetic, roll-vs-weight separation, event windows and multiple testing.

**Acceptance:** users can reproduce each estimate from weights, AUM, prices and multipliers; no estimate is presented as observed flow.

**Main risks:** historical data licensing, methodology changes, uncertain AUM and crowded-event inference.

**Complexity:** Large.

### Phase 7 — Multi-factor commodity portfolio

**Objective:** compare and combine carry, momentum, skewness and curve factors under shared risk controls.

**Backend:** factor registry, comparison engine, simple combinations, trailing-OOS IC weights and factor attribution.

**Frontend:** correlation/overlap matrices, combination controls, marginal contribution and portfolio monitor.

**Data:** common PIT panel across factors and a sufficiently long OOS sample.

**Tests:** z-score combination, OOS weights, caps, attribution reconciliation and factor removal.

**Acceptance:** individual and combined results use the same universe/returns/costs; combined weights are reproducible and contain no full-sample training.

**Main risks:** data-mining, short common sample and hidden duplicated exposures.

**Complexity:** Large.

---

## 13. Risks and limitations

1. **Free-data illusion:** visible prices do not imply complete, redistributable or research-grade histories. Mitigate with immutable source tiers and non-tradable proxy labels.
2. **Back-adjustment error:** adjusted levels can create artificial returns. Enforce contract-ledger P&L and tests that prevent adjusted series from entering the backtest path.
3. **Physical delivery:** incorrect FND/LTD metadata can create impossible holdings. Use hard safety dates and block research-grade runs without required metadata.
4. **Roll attribution ambiguity:** some continuous methods embed rolls differently. Define P&L from trades first and treat display series as derived artifacts.
5. **Negative prices:** log formulas and percentage returns may be undefined. Preserve dollar P&L and expose explicit alternative formula status.
6. **Cross-market timing:** settlements occur in different time zones. Store exchange-local timestamps plus UTC availability; apply conservative execution lags.
7. **Liquidity/cost uncertainty:** proxy volume and assumed spreads can overstate performance. Require sensitivity, participation and capacity reports.
8. **Small cross-section:** sector neutrality and IC estimates become unstable. Enforce minimum breadth and display effective sample size.
9. **Index data licensing/AUM uncertainty:** methodology may be public while history and professional use are licensed. Keep scenario assumptions and source permissions explicit.
10. **Real-carry definition risk:** inflation adjustment is not universal and may not alter ranks. Version methods and measure incremental value.
11. **Multiple testing:** many tenors/windows can create false discovery. Pre-register variants, count all trials and apply FDR/deflated Sharpe.
12. **Architecture overlap:** the existing Cross-Asset brief is unimplemented. Commodity work must land on the same shared foundation, not create incompatible parallel types.

---

## 14. Open design decisions

### Resolved

| Decision | Resolution |
|---|---|
| Product placement | Commodity vertical inside Cross-Asset Research. |
| MVP data policy | Free proxy first, always preliminary/non-tradable; validated uploads supported. |
| Base currency | USD default, configurable in strategy specification. |
| Run persistence | Reuse generic `Run`/`Artifact`; no commodity run table. |
| Observation storage | Immutable Parquet objects plus SQL metadata catalog. |
| Default roll | Delivery-safe, five exchange sessions before earlier FND/LTD. |
| Execution lag | One settlement by default. |
| Headline carry | Positive log near/far carry means backwardation/long preference. |
| ML | Out of scope for v1. |
| Scheduling | On-demand in MVP. |

### Phase-gated external decisions

These do not block the MVP and are resolved by an explicit trigger rather than implementer discretion:

- **Paid provider:** remain adapter-neutral until the desk selects an approved provider and confirms professional-use/redistribution rights.
- **Tracking AUM:** use user-supplied low/base/high scenarios until an approved historical source exists.
- **Inflation swaps/surveys:** use FRED breakeven/real-yield methods first; add a provider adapter only when licensed data is supplied.
- **Exchange-specific liquidity thresholds:** start as configuration with documented proxy defaults; promote per-root thresholds after at least one year of validated contract data or desk-provided limits.

---

## 15. Recommended MVP

### In scope

- Shared Cross-Asset instrument, specification, dataset, quality, return, cost and run foundations required by commodities.
- Contract/reference metadata and immutable series catalog.
- Canonical CSV/Bloomberg import plus free proxy adapter.
- Delivery-safe chain construction.
- Raw futures curve and contract/liquidity explorer.
- Unadjusted and labelled continuous display series.
- Front/second and front/fourth nominal carry.
- Cross-sectional monthly long-short portfolio with volatility scaling and caps.
- Explicit outright, roll, collateral, FX and cost attribution.
- IC, HAC, performance, turnover, exposure, cost sensitivity, bootstrap and leave-one-commodity-out diagnostics.
- Proxy/quality/freshness warnings and run reproducibility record.

### Out of scope

- Production claims from free proxy data.
- Intraday execution or market making.
- Supply/demand forecasting.
- PCA/curve butterflies, skewness, real carry and index events until later phases.
- Machine learning and unconstrained portfolio optimization.
- Automatic live trading/order routing.

### MVP acceptance criteria

1. A hand-calculated contract fixture passes chain, carry, roll, multiplier, currency and cost tests.
2. A user can inspect the exact curve and metadata used for a signal.
3. Every proposed position includes formula inputs, contract quantities, risk scaling, constraints and warnings.
4. Backtest net P&L reconciles exactly to its return legs and costs.
5. No backtest return is derived from a back-adjusted level.
6. Proxy runs are permanently labelled preliminary/non-tradable.
7. Identical specification, dataset bundle and seed reproduce identical metrics.
8. Existing core/API/worker/frontend checks remain green.

### First five implementation tasks

1. **Land the shared foundation contract:** reconcile `cross-asset-lab-slice1.md` with generic `Run`/`Artifact`, define frozen strategy/instrument types, and create the metadata/series migration without a duplicate run table.
2. **Build the data boundary:** canonical importer, proxy adapter, dataset-bundle manifest, source tiers, quality report and committed fixtures.
3. **Build the futures-chain engine:** metadata versioning, exchange calendars, delivery-safe eligibility, liquidity crossover, curve snapshots, continuous display series and roll ledger.
4. **Build nominal carry and the portfolio backtest:** exact formulas, rankings, risk/caps, settlement P&L, collateral/FX, costs and validation artifacts.
5. **Expose the research workflow:** API schemas/router/worker jobs plus Market Overview, Curve Explorer, Strategy Explorer and Backtest views with generated rationale/tooltips.

This sequence creates a useful trader-facing research product quickly while preserving the strict boundary between exploratory proxy evidence and a research-grade futures backtest.
