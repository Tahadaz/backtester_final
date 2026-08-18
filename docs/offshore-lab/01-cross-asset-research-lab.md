# Cross-Asset Strategy Research Lab — Stage 1 (Audit & Design)

**Date:** 2026-07-14
**Supersedes:** the fixed-income-first direction in `00-response.md` (kept for its repo audit + data appendix).
**Stage 2 implementation brief:** `docs/ai/cross-asset-lab-slice1.md`
**Decisions locked with the user:** classic quant strategies across **both commodities and FX**, build the **proper return pipeline** for them; docs extend this `offshore-lab/` folder; Codex implements Stage 2 from the brief; **MAD is monitor-only analytics**, never a backtested strategy (managed 60/40 basket + ±5% band would just rediscover the peg).

The strategic point (from the desk trader): the desk already has Bloomberg for pricing/analytics. The value this lab adds is what Bloomberg does **not** hand you: a transparent, reproducible, auditable environment to **replicate a paper, test a systematic signal point-in-time, survive costs, prove robustness, and monitor today's signal** — across asset classes, with every stage inspectable.

This document answers Part K Stage 1's 22 deliverables.

---

## 1. Verified repository architecture

Confirmed in source this session (not from the prior summary):

- **Quant core** `core/quant_core/` — installable, largely market-agnostic. 19k LOC. Key modules cited below by line.
- **API** FastAPI, `services/api/app/main.py`; 26 routers; async runs enqueued via RQ (`get_queue().enqueue(...)`, `strategy_backtest_runs.py:333`), job id stored on the `run` row, cancel via a redis `rq:cancel:{job_id}` key (`strategy_backtest_runs.py:601`).
- **Worker** RQ + APScheduler; ~40 tasks in `services/worker/tasks/`.
- **Frontend** Next.js App Router; zod + SWR client (`frontend/lib/api.ts`); plotly/recharts/lightweight-charts.
- **DB** Postgres, 83 tables (`services/api/app/models.py`), 87 Alembic migrations. Time series are **not** row-per-observation — `market_data_store` is one row per `(symbol, timeframe)` pointing at a **Parquet object in MinIO** (`object_key`), with denormalized freshness columns (`data_as_of`, `close_last`). Raw uploads land in `dataset` (object_key + `data_hash` + `meta_json`).

## 2. Exact reusable components

| Need | Reuse | Location |
|---|---|---|
| Walk-forward engine | `run_wfo_engine(data_length, config, evaluate_window)` — **fully generic**, takes any window-evaluating callable | `core/quant_core/wfo/engine.py:43` |
| Bootstrap / Monte-Carlo risk | `monte_carlo_equity_paths`, `stationary_block_bootstrap`, `trade_bootstrap`, `kelly_fraction`, `build_risk_summary` — operate on plain return arrays | `core/quant_core/risk.py` |
| Multiple-testing defence | `deflated_sharpe_ratio`, `probabilistic_sharpe_ratio`, `harvey_liu_expected_max_sharpe`, `stationary_bootstrap_ci`, `rolling_metric_cv` | `core/quant_core/research/stats/robustness.py` |
| Cross-market calendar alignment | `align_cross_market`, `align_factor_to_target`, staleness-guarded forward-fill (staleness explicit, not silent) | `core/quant_core/` (Community 25) |
| Reproducible run spine | `run` (spec_json, **spec_hash, git_commit, dataset_hash, seed, code_version**), `artifact` (MinIO objects + sha256), `run_metric`, `run_fold`, `run_risk`, `run_significance` | `models.py:106,141,161,258,328,311` |
| Async job pattern | RQ enqueue + job-id-on-row + poll endpoint | `routers/strategy_backtest_runs.py` |
| Raw-file import primitive | `dataset` table + MinIO + `data_hash` | `models.py:16` |
| **Bloomberg-export import boundary (already exists!)** | `bloomberg_ingest_batch` (raw+manifest+normalized object keys, sha256, row/series counts) → `bloomberg_series` (`security`,`field`,`periodicity` → Parquet) | `models.py:1114,1146` |
| Macro/offshore ingestion | yfinance OHLCV → Parquet, DB-registered series in `macro_factor_meta` (asset_type ∈ equity/commodity/forex/bond/crypto), user-addable | `core/quant_core/macro.py`, `models.py:494` |
| Asset classification | forex/commodity/bond/crypto roots incl. USDMAD/EURMAD, US2Y–US30Y | `services/api/app/asset_taxonomy.py` |

**The single most important reuse:** the `run/artifact/run_metric/run_fold/run_risk/run_significance` spine already encodes reproducibility (spec hash + git commit + dataset hash + seed). The cross-asset lab **persists runs the same way** rather than inventing new bookkeeping.

## 3. Hidden equity assumptions found (line-level)

The existing signal backtester is **not** safe to reuse for cross-asset portfolios. Evidence:

- **`run_signal_backtest`** (`core/quant_core/signal_engine/backtest_mc.py:418`) is **single-instrument, scalar-position, price-return-only**:
  - returns are close-to-close on one price array: `raw_returns = np.diff(cl)/cl[:-1]` (`:493`). This is correct for a cash equity, **wrong for a futures roll or an FX excess return** — there is no roll-return, financing, or carry leg.
  - position is one scalar clipped to `[0,1]` (long-only) or `[-1,1]` (`:471-474`) — **no per-instrument weights, no notional, no contract multiplier, no portfolio.**
  - **no currency conversion** — every P&L is in the instrument's own quote units.
  - Good news (not equity-locked): execution is correctly **lagged one bar** (`desired_position[1:] = target_position[:-1]`, `:477`), and costs are proportional bps on `|Δposition|` (`:500-501`). Shorts *are* representable. So the **timing and cost discipline are reusable ideas**, but the engine shape is not.
- **Rates stored as levels, not returns.** `macro.py` stores `^TNX` (10y yield) as an OHLCV `Close` (`macro.py:147`). A naive `pct_change` on a yield is meaningless. Any rates strategy must convert yield changes → returns (via duration) or use a bond-future return series. Flagged as a Phase-3+ blocker, not in the first slice.
- **No point-in-time universe / survivorship handling** for a cross-sectional basket. `research/universe.py` is equity screening; there is no notion of "which futures/currencies were liquid as of date t."
- **No instrument reference data.** `stock_master`/`index_master`/`macro_factor_meta` carry `asset_type`/`market_region` but **no multiplier, currency, tick size, expiry, or contract lineage** anywhere. This is the core gap for futures.

## 4. Gaps blocking cross-asset research

1. **Instrument & contract model** (currency, multiplier, quote convention; for futures: expiry, first-notice, roll rule, contract lineage). None exists.
2. **Correct return construction** per asset class: FX excess return (spot + interest differential), futures excess return (price return + roll return + collateral), currency conversion to a base ccy. None exists.
3. **Multi-instrument portfolio engine** with per-instrument weights, vol targeting, gross/net/leverage limits, turnover — the current engine is single-series.
4. **Data-quality gate** that blocks a backtest over bad data (coverage, gaps, dup dates, roll jumps, staleness). None exists as a first-class report.
5. **Strategy specification** as a versioned, serializable object (the current backtester takes ad-hoc arrays).
6. **Research-source / replication metadata** (paper, deviations, faithful-vs-adapted). None exists.
7. **Contract-level futures data** — the hardest gap; free continuous tickers are not tradable-return-faithful (§16).

## 5. Added-value assessment vs Bloomberg

| Capability | Bloomberg | This lab's edge |
|---|---|---|
| Bond/FX/commodity pricing, DV01, curves | ✅ excellent | none — don't rebuild |
| Ad-hoc historical strategy backtest with correct costs/lag | partial (BQNT/manual) | **transparent, reproducible, versioned, auditable** |
| Paper replication with explicit deviations | ❌ | **first-class** (faithful/adapted/simplified/extension) |
| Multiple-testing-aware validation (deflated Sharpe, WFO, LOO) | ❌ (analyst discipline only) | **built-in, enforced** |
| Full methodology chain inspectable (raw→net) | ❌ black-boxish | **every stage a stored artifact** |
| "What is the signal today and why + what flips it" monitor | partial | **purpose-built, with staleness + reversal conditions** |
| Reproduce a result months later (code+data+params hash) | ❌ | **run spine already does this** |

Verdict: build the **research/validation/monitoring/reproducibility** layer; **never** rebuild pricing/analytics.

## 6. Candidate-strategy decision matrix

Scored 1–5 (higher = better/safer for a *first* slice). "Return correctness" = can we build the genuine tradable return from **free** data.

| Candidate | Data now | Return correctness | Desk relevance | Precedent | Educational | Reuse | Speed | Mislead risk (5=low) | **Total** |
|---|---|---|---|---|---|---|---|---|---|
| **FX carry + TSM (G10)** | 5 | 5 | 5 | 5 | 5 | 4 | 4 | 4 | **37** |
| Cross-asset TSM (FX+comm) | 3 | 3 | 5 | 5 | 5 | 5 | 3 | 3 | **32** |
| Commodity TSM (continuous) | 4 | **1** | 4 | 5 | 4 | 4 | 4 | **1** | **27** |
| Commodity curve carry | 2 | 2 | 4 | 5 | 5 | 4 | 2 | 3 | **27** |
| Govt-bond futures TSM | 2 | 2 | 5 | 4 | 4 | 3 | 2 | 2 | **24** |

Why FX wins the *correctness* axis decisively: an FX excess return is `spot return + (r_base − r_quote)·τ` and **both legs are free and reliable** (spot from yfinance; rates from FRED/central banks). A commodity continuous-ticker return silently mixes price and roll and is **not tradable** — the prompt's own warning.

## 7. Recommended first vertical slice

Per the user's steer — **both commodities and FX, proper pipeline** — the slice is a **cross-asset systematic-strategy engine** whose *pipeline* is asset-class-correct from day one, with the *first validated strategies* chosen by data honesty:

- **FX sleeve (real, end-to-end, defensible):** G10 **time-series momentum** (Moskowitz–Ooi–Pedersen 2012) and **carry** (Koijen–Moskowitz–Pedersen–Vrugt 2018; Lustig–Roussanov–Verdelhan 2011) on genuine excess returns from free data. This is a real backtest we can stand behind.
- **Commodity sleeve (real engine, honest data):** the same TSM + **curve carry / roll-yield** (Gorton–Rouwenhorst; Koijen et al.) signals, but run through a **contract-aware return model** (front/second contract, explicit roll return) validated on **fixtures + a manual contract-CSV import**. Continuous yfinance tickers are used **only** with an explicit roll-return correction and a loud data-quality warning; no commodity backtest is presented as tradable until contract data is imported.

This exercises the entire architecture (instruments, PIT signals, portfolio vol-targeting, costs, validation, monitoring) on **both** asset classes, while refusing to fabricate a commodity result from bad data.

## 8. Proposed architecture

Pure math in `quant_core`; data/persistence outside it (matches existing separation).

```
core/quant_core/cross_asset/
    instruments.py     # Instrument, FuturesContract, FxPair typed models (currency, multiplier, quote convention, expiry/roll)
    returns.py         # fx_excess_return(), futures_excess_return() (price+roll+collateral), to_base_ccy()
    signals.py         # time_series_momentum(), carry_signal(), vol_scale()  — PIT, explicit lag
    portfolio.py       # cross-sectional & TSM sizing: inverse-vol, vol-target, gross/concentration caps, turnover
    costs.py           # proportional bps + bid/ask + slippage; gross vs net
    strategy_spec.py   # StrategyDefinition dataclasses (serializable) — the Part C model
    dataquality.py     # coverage/gaps/dup/roll-jump/staleness report; blocks bad backtests
    backtest.py        # deterministic driver: spec + data → stages (raw→net) + metrics
    validation.py      # thin adapters over risk.py + robustness.py (deflated Sharpe, LOO, subperiod, cost sensitivity)

services/api/app/services/cross_asset/    # data assembly, run orchestration, persistence
services/api/app/routers/cross_asset_research.py
services/api/app/schemas/cross_asset_research.py
services/worker/tasks/cross_asset/run_backtest.py     # RQ task, same pattern as strategy_backtest_runs
frontend/app/cross-asset-research/                    # overview / methodology / results / robustness / current-signal / run-record
frontend/components/cross-asset/
```

Decision on reuse vs new engine: **new engine.** `backtest_mc.run_signal_backtest` is financially inappropriate for a multi-instrument, multi-currency, roll-aware portfolio (§3). We **reuse** WFO, risk, robustness, alignment, run-spine, import boundary — but the return/position/portfolio core is new. This is the prompt's "do not force reuse when the abstraction is financially inappropriate."

## 9. Strategy-definition model (Part C, adapted)

Typed, serializable dataclasses in `strategy_spec.py` — domain objects, not a free-form blob:

```python
@dataclass(frozen=True)
class StrategyDefinition:
    identity: Identity          # id, name, version, asset_class, family, research_source
    universe: Universe          # instruments, inclusion/exclusion, point_in_time flag
    data: DataRequirements      # fields, frequency, source, freshness, fallback_policy
    signal: SignalSpec          # kind(TSM|CARRY), lookback, lag, transform, rank/threshold, missing_policy
    positions: PositionSpec     # direction, sizing(unit|inv_vol|vol_target), vol_target, leverage/concentration caps, neutrality
    execution: ExecutionSpec    # rebalance_freq, execution_delay, price_used, cost_model, slippage, turnover_cap
    returns: ReturnSpec         # instrument_return kind, financing, collateral, fx_conversion, roll_method
    validation: ValidationSpec  # benchmark, IS/OOS, walk_forward, parameter_grid, tests
    disclosures: Disclosures    # assumptions, deviations_from_source, limitations, unsupported
```

`replication_fidelity ∈ {faithful, adapted, simplified, extension}` is a **required** field on `research_source`. An adaptation is never labelled a replication.

## 10. Instrument and contract models

```python
@dataclass(frozen=True)
class Instrument:
    symbol: str; asset_class: str; currency: str
    quote_convention: str          # e.g. "USD_per_unit", "base/quote" for FX
    point_value: float = 1.0       # contract multiplier for futures; 1.0 for FX/spot

@dataclass(frozen=True)
class FuturesContract(Instrument):
    root: str; expiry: date; first_notice: date | None
    roll_rule: str                 # "n_days_before_expiry" | "first_notice" | "volume_crossover"
    tick_size: float | None = None

@dataclass(frozen=True)
class FxPair(Instrument):
    base_ccy: str; quote_ccy: str  # long 1 unit base vs quote; return sign defined explicitly
```

Persisted in a new `cross_asset_instrument` table (no coupling to `stock_master`).

## 11. Return-construction model

Distinct, separately-inspectable legs (never a back-adjusted chart diff):

- **FX:** `total = spot_return + carry`, `carry = (r_base − r_quote)·τ` (day-count explicit); optional bid/ask on rebalance. Long/short sign defined on the pair explicitly.
- **Futures:** `excess = price_return(front) + roll_return + collateral_return`; `roll_return` computed from the front→next price ratio on the roll date per `roll_rule`; `collateral_return = cash_rate·τ`. Back-adjusted series allowed **only** as a display convenience, with a test proving it reproduces the leg-summed tradable return.
- **Base-currency conversion:** every instrument P&L converted to the portfolio base ccy (default USD) via same-day FX, timestamped.

## 12. Execution and cost model

- Signal at observation cutoff `t` → position effective at `t + execution_delay` (default 1 bar) — the same discipline already in `backtest_mc.py:477`, generalized to a weight vector.
- Cost per rebalance: `Σ_i |Δw_i| · (half_spread_i + slippage_i + commission_i)` in bps; report **gross and net** side by side.
- Turnover cap and volatility target applied on **lagged** estimates only (no look-ahead vol).

## 13. Research-run persistence model

Reuse the existing spine; add three cross-asset tables:
- `cross_asset_instrument` (§10).
- `cross_asset_strategy` (versioned `StrategyDefinition` JSON + `spec_hash` + `replication_fidelity`).
- `cross_asset_run` (FK strategy, `dataset_hash`, `git_commit`, `seed`, params JSON, status, `rq_job_id`, metrics JSON) — mirrors `run` (`models.py:106`).
Stage artifacts (raw, tradable, signal, position, executed, gross, net, per-instrument attribution) stored as MinIO objects via the existing `artifact` mechanism, so a run is fully reproducible.

## 14. API contracts

Same auth/pattern as the 26 existing routers. Endpoints (all under `/cross-asset-research`):
- `POST /strategies` create/version a `StrategyDefinition`; `GET /strategies[/{id}]`.
- `POST /data-quality` run the §4 report on a spec's universe (returns coverage/gaps/roll-jumps/staleness) — **must pass before backtest**.
- `POST /runs` enqueue a backtest (RQ, returns run id); `GET /runs/{id}` poll status/metrics; `GET /runs/{id}/stages` fetch stage artifacts; `GET /runs/{id}/robustness`.
- `GET /strategies/{id}/current-signal` monitoring payload (latest signal, intended vs previous position, drivers, data timestamp, staleness, next rebalance, reversal conditions).
All responses carry a transparency envelope (data_source, calculation_date, assumptions, units, warnings, interpretation) — reused from the `00-response.md` design.

## 15. Frontend information architecture

Route `frontend/app/cross-asset-research/` with six views (Part H): **Overview** (thesis, source, status, limitations) · **Methodology** (raw→tradable→signal→position→executed→gross→net, each stage a chart/table) · **Backtest** (equity, drawdown, rolling Sharpe/vol, turnover, exposure, per-instrument, benchmark) · **Robustness** (parameter heatmap, subperiod, cost sensitivity, WFO, leave-one-instrument-out, bootstrap CI) · **Current signal** (monitor) · **Run record** (strategy version, git commit, dataset hash, params, warnings, notes — reproducible). Charts: plotly for equity/heatmap (a heatmap needs adding — none exists yet), recharts for small multiples.

## 16. Data-source and import strategy

| Tier | Source | Use | Caveat |
|---|---|---|---|
| Public authoritative | FRED (rates, SOFR, DFII10), treasury.gov, ECB SDW, BAM reference rates | FX carry legs, rates, MAD monitor | free, redistributable; key for FRED |
| Free unofficial | yfinance (FX spot, commodity front-month) | FX spot, commodity display | unofficial; **continuous ≠ tradable** |
| User uploads | canonical CSV (§ below) | **contract-level futures**, curves, bond marks | validated before eligible |
| Bloomberg exports (later) | existing `bloomberg_ingest_batch`/`bloomberg_series` boundary | institutional data when desk-authorized | already built; no live coupling |
| Synthetic fixtures | committed test data | engine validation | tests only, never shown as results |

**Canonical import schema** (long format, one row per obs), validated + previewed before acceptance, hashed into `dataset`:
`instrument_id, date, field (settle|open|high|low|close|volume|open_interest|rate|forward_points), value, currency, contract_expiry (nullable), source`.
This is the single door for Bloomberg exports, contract data, curves, and FX forwards — no production logic written directly against an undocumented endpoint.

## 17. Validation framework

Reuse `risk.py` + `research/stats/robustness.py`; the lab **enforces** (not merely offers): IS/OOS split, expanding WFO (`run_wfo_engine`), parameter heatmap, per-instrument & subperiod & vol-regime breakdowns, drawdown analysis, turnover/cost sensitivity, **leave-one-instrument-out**, signal autocorrelation, bootstrap CIs (`stationary_bootstrap_ci`), and **deflated/probabilistic Sharpe** (`deflated_sharpe_ratio`) with an explicit **multiple-testing warning** whenever >1 variant is compared. Report the full metric set (ann. return/vol, Sharpe, Sortino, maxDD, Calmar, hit rate, skew, tail loss, turnover, leverage, net exposure, costs, long/short & per-instrument attribution, effective-sample caveat). **A high Sharpe is never treated as proof** — the UI states the deflated Sharpe and the number of variants tried.

## 18. Testing plan

- **Unit (quant_core):** day-count & carry math; FX excess-return identity; futures roll-return reconstruction == leg-summed tradable return; vol-target sizing hits target on synthetic data; cost/turnover accounting; PIT lag (no look-ahead — a shifted-input test).
- **Property:** deterministic given (spec, data, seed); shorts symmetric; missing-data policy never silently drops an instrument (it warns).
- **Integration:** fixture dataset → full pipeline → stable metrics snapshot; API run enqueues, polls, returns artifacts; data-quality gate blocks a deliberately corrupted fixture.
- **Reference-strategy check:** FX TSM sign-agreement and rough Sharpe range against the published MOP 2012 stylized facts (as a sanity band, not a golden number).

## 19. Phased implementation roadmap

- **Slice 1 (Stage 2, this brief):** cross_asset package (instruments, returns, TSM+carry signals, vol-target portfolio, costs, data-quality, deterministic backtest, validation adapters) + canonical import + FX reference strategy on real free data + commodity path on fixtures/import + one router + minimal UI + tests.
- **Phase 2:** cross-sectional momentum & carry ranking; parameter heatmap + WFO wired to UI; monitoring view.
- **Phase 3:** commodity curve carry with real imported contract data; rates sleeve (yield→return via duration) — unblocks bond-future TSM/carry.
- **Phase 4:** Eurobond RV — **data-blocked** until Bloomberg exports; only the import boundary is built now.
- **Phase 5:** equity-index/ETF futures momentum & vol-targeting (must not duplicate the Moroccan single-stock factor platform).
- **MAD monitor (any time):** basket-implied vs observed USD/MAD, CIP-deviation tracker on BAM rates — analytics only.

## 20. Exact files to create or modify

**Create:** the `core/quant_core/cross_asset/` modules (§8); `services/api/app/schemas/cross_asset_research.py`, `routers/cross_asset_research.py`, `services/cross_asset/`; `services/worker/tasks/cross_asset/run_backtest.py`; `frontend/app/cross-asset-research/` + `frontend/components/cross-asset/`; fixtures under `core/tests/fixtures/cross_asset/`; tests under `core/tests/` and `services/api/tests/`; one Alembic migration adding `cross_asset_instrument`, `cross_asset_strategy`, `cross_asset_run`.
**Modify (only):** `services/api/app/main.py` (register router); `frontend/lib/api.ts` (schemas+fetchers); nav component (one entry). No equity code touched.

## 21. Technical and financial risks

1. **Continuous-ticker contamination** — the biggest one; mitigated by the explicit roll model + data-quality gate + refusing to present continuous-based commodity returns as tradable.
2. **Rates-as-levels** (`^TNX`) — excluded from slice 1; flagged for Phase 3.
3. **Multiple testing** — mitigated by mandatory deflated Sharpe + variant-count disclosure.
4. **Look-ahead via vol/rank** — mitigated by lag tests; all estimators use data ≤ t−delay.
5. **FX carry data-quality** — short-rate proxies must match the pair's settlement/day-count; mitigated by explicit `ReturnSpec`.
6. **Scope creep vs equity platform** — enforced by package boundary + "no equity imports" rule.
7. **Overfitting the UI into a decorative dashboard** — each view must change a research decision or be cut.

## 22. Open decisions requiring your judgment

1. **Commodity data path for slice 1:** ship FX as the only *real* backtest and commodities as fixture+import-only (honest, recommended), or attempt free per-contract sourcing (Stooq) and risk stalling? *(Recommend the former.)*
2. **FX short-rate source:** FRED per-currency policy/OIS proxies vs a simpler flat-carry-from-forward-points approach (if we later import forwards). *(Recommend FRED OIS-style proxies now.)*
3. **Base currency:** USD (recommend) vs EUR (closer to the desk's book).
4. **G10 universe exact list** for the FX sleeve (recommend: USD, EUR, JPY, GBP, CHF, AUD, CAD, NZD, NOK, SEK).
5. **Rebalance frequency** for the reference strategy: monthly (recommend, matches MOP/carry literature) vs weekly.
6. **UI language** (French labels + English quant terms, matching the app) — confirm.
