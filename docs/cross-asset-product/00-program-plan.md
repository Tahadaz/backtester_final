# Cross-Asset Product Program — Bonds, Commodities, FX

**Date:** 2026-08-03
**Owner:** Taha · **Implementer:** Codex (all briefs)
**Budget:** ~1 week of Codex tokens, whole program A→Z
**Supersedes on scope/sequencing:** `docs/trader-prep/04-build-track.md` (notebook-grade, hand-coded, serial) — that track was written for interview prep, not for shipping product. Its *teaching content* stays valid; its scope discipline does not apply here.
**Reuses on architecture:** `docs/offshore-lab/01-cross-asset-research-lab.md` (master design), `docs/ai/cross-asset-lab-slice1.md` (FX/engine build spec), `docs/ai/commodity-systematic-strategies-plan.md` (commodity vertical), `docs/ai/offshore-lab-phase1-fixed-income.md` (bond calculator).

This document is the **program spine**: what gets built, in what order, what was decided, and the guardrails that keep the token spend inside one week. The per-brief specs live in `docs/ai/ca-brief-*.md` and are written as **deltas against the existing specs above** — they do not restate them.

---

## 1. Decisions locked this session

| # | Decision | Rationale |
|---|---|---|
| D1 | **Codex implements everything**, including the `fixed_income` module bodies | User instruction. Overrides the hybrid hand-code rule — see §7 caveat. |
| D2 | **Full product, A→Z**: quant core + DB + API + worker + frontend, for all three asset classes | User instruction. Resolves the slice1-brief (full stack) vs build-track (notebook only) conflict in favour of full stack. |
| D3 | **Shared foundation first**, then three verticals as deltas | Cheapest path to three asset classes. Building FX, commodities and rates as independent stacks would triple the engine, the run plumbing and the UI. |
| D4 | **Commodities ship on fixtures + canonical CSV import.** No free per-contract sourcing attempt. | §22 open decision #1, answered. Free continuous tickers are not tradable-faithful; sourcing contract data is an open-ended time sink and would stall the whole program. |
| D5 | **One run ledger.** Reuse `Run` / `Artifact` / `RunMetric` with `run_type="cross_asset_strategy"`. **Do not** create `cross_asset_run`. | Resolves a direct conflict between the two existing briefs (slice1 §DB says add `cross_asset_run`; the newer commodity plan §2.4 says reuse `Run`). Verified: `Run.run_type` already exists at `services/api/app/models.py:111` with default `"backtest"`. Saves a table, a migration, a polling endpoint and a duplicate artifact path. |
| D6 | **One frontend route**, `/cross-asset-research`, parameterized by asset class. The bond calculator keeps its own small route `/offshore-lab`. | Three routes × six views = the single biggest avoidable cost. The calculator is a different shape (stateless, no run record) so it stays separate. |
| D7 | **One engine, three return kinds.** `ReturnSpec.kind ∈ {fx_excess, futures_excess, bond_duration}` | The asset classes differ *only* in return construction. Signal → position → cost → metrics → validation is identical for all three. This is the architectural claim the whole budget rests on. |
| D8 | **Curve lab is cut-first scope** (Brief 5) | It is the only piece with no downstream dependency. If the budget runs out, the product is still complete without it. |

## 2. Program shape

```
                    ┌─────────────────────────────────────────┐
   Brief 1          │  core/quant_core/cross_asset/           │
   FOUNDATION       │  instruments · returns · signals ·      │
   (no UI)          │  portfolio · costs · strategy_spec ·    │
                    │  dataquality · backtest · validation ·  │
                    │  importer                               │
                    │  + 2 DB tables + router + worker task   │
                    └────────────────┬────────────────────────┘
                                     │ same engine, different ReturnSpec.kind
             ┌───────────────────────┼───────────────────────┐
             ▼                       ▼                       ▼
      Brief 2: FX            Brief 3: COMMODITIES     Brief 4: RATES & BONDS
      fx_excess              futures_excess           bond_duration
      G10 TSM + carry        curve carry + TSM        bond TSM + carry
      REAL free data         fixtures + CSV import    FRED DGS* real data
      + builds the UI once   + reuses UI (param)      + bond calculator UI
                                     │
                                     ▼
                          Brief 5: CURVE LAB (cut-first)
                          2s10s/5s30s, roll-down, DV01-neutral trades
```

Each brief ends at a **green, shippable state**. If the budget dies after Brief 2 you have a real FX product; after Brief 3, two asset classes; after Brief 4, the full three.

## 3. Sequencing and ship gates

| Brief | Deliverable | Ship gate | Rough share of budget |
|---|---|---|---|
| **1 — Foundation** | `cross_asset` package, 2 tables, router, worker task. Tested with fixtures only. | `pytest core/tests/test_ca_*.py services/api/tests/test_cross_asset_research_router.py` green; package imports no SQLAlchemy/FastAPI | ~30% |
| **2 — FX vertical** | G10 TSM + carry on real free data (yfinance spot + FRED rates), **plus the entire frontend built once** | `/cross-asset-research` renders an FX run end-to-end: methodology chain, metrics, robustness, current signal | ~30% |
| **3 — Commodities** | Contract chain, roll accounting, curve carry; fixture + canonical CSV import; UI lights up via asset-class param | A commodity run completes through the identical engine and is labelled non-tradable from `warnings` | ~15% |
| **4 — Rates & bonds** | `fixed_income` bodies green + calculator route; `bond_duration` return kind wired to the engine on FRED `DGS*` | Bond calculator returns full analytics; a bond TSM run completes | ~20% |
| **5 — Curve lab** | 2s10s/5s30s history, steepener/flattener regimes, roll-down, DV01-neutral simulator | Curve views render | ~5%, **cut first** |

## 4. Token-economy guardrails (these go verbatim into every brief)

These exist because the constraint is the budget, not the design.

1. **Do not explore the repository.** Every anchor you need is in the brief, with file:line. If something is genuinely missing, make the minimal reasonable choice and note it — do not go reading.
2. **Never read `graphify-out/GRAPH_REPORT.md` (917 KB) or `graph.json` (38 MB).** They do not fit in context.
3. **Build strictly in brief order.** Do not start a later brief's files early.
4. **Scope your test runs.** Run the new test files plus the directly touched suites. Do not run the full repo suite on every iteration — once at the end of each brief is enough.
5. **Reuse before create** — see §5. If a capability is listed there, import it; do not reimplement it.
6. **If a file is not in the brief's file list, do not create it.** No helper modules, no extra abstractions, no speculative interfaces.
7. **Frontend: one component set, parameterized by asset class.** Zero per-asset component duplication. Adding an asset class must mean adding a value to a union type, not a folder.
8. **No Docker/E2E loops.** pytest plus one manual smoke per brief.
9. **No refactors of existing equity/signal/fundamentals code.** The only files you may modify outside your create-list are the ones the brief names.

## 5. Reuse table (verified in source, 2026-08-03)

Import these. Do not rebuild them.

| Need | Use | Location |
|---|---|---|
| Walk-forward engine | `run_wfo_engine(data_length, config, evaluate_window)` — generic, takes any window-evaluating callable | `core/quant_core/wfo/engine.py:43` |
| Bootstrap CI | `stationary_bootstrap_ci` | `core/quant_core/research/stats/robustness.py:108` |
| Deflated Sharpe | `deflated_sharpe_ratio` | `core/quant_core/research/stats/robustness.py:94` — **note:** a second implementation exists at `core/quant_core/wfo/statistical.py:260`. Use the `robustness.py` one; do not merge or refactor them. |
| Risk summary / MC paths | `build_risk_summary` and friends | `core/quant_core/risk.py:400` |
| Run ledger | `Run` (`run_type`, `spec_hash`, `git_commit`, `dataset_hash`, `seed`), `Artifact`, `RunMetric`, `Dataset` | `services/api/app/models.py:106,141,161,16` |
| Async job pattern | `get_queue().enqueue(...)`, store `rq_job_id` on the row, poll endpoint, cancel via `rq:cancel:{job_id}` | `services/api/app/routers/strategy_backtest_runs.py:333,601` |
| Object keys | `build_dataset_object_key`, `build_market_store_object_key` | `core/quant_core/s3_keys.py:10,28` |
| Macro/free-data ingestion | yfinance → Parquet → `macro_factor_meta`; already carries `BZ=F`, `GC=F`, `EURUSD=X` | `core/quant_core/macro.py:99,107,131`; `models.py:494` |
| Bloomberg import boundary | `bloomberg_ingest_batch` → `bloomberg_series` | `models.py:1114,1146` |
| Execution-lag & cost discipline (ideas only) | one-bar lag `desired_position[1:] = target_position[:-1]`; proportional bps on `|Δposition|` | `core/quant_core/signal_engine/backtest_mc.py:477,500` |

**Do not extend `run_signal_backtest`** (`core/quant_core/signal_engine/backtest_mc.py:418`). It is single-instrument, scalar-position, close-to-close price-return only (`raw_returns = np.diff(cl)/cl[:-1]`, line 493) with no weights, multiplier, roll, financing or FX conversion. The new engine replaces it for cross-asset work; the equity path keeps using it untouched.

## 6. The financial invariants (non-negotiable across all briefs)

These are what make the product defensible rather than decorative. A brief that ships without them has failed even if the tests pass.

1. **Tradable return, or labelled otherwise.** A back-adjusted or continuous price series is a display aid. Backtest P&L is reconstructed from the contracts actually held and rolled. Any run built on proxy data carries a `warnings` entry and the UI shows it.
2. **No look-ahead.** Signals, vol estimates and ranks use data ≤ `t − lag`. Every signal module gets a shift test: shifting an input by one bar shifts the output by exactly one bar.
3. **No silent anything.** No silent forward-fill, no silent instrument drops, no invented zeros. Missing means missing, and it warns.
4. **Gross and net side by side**, always, with turnover.
5. **Multiple testing is disclosed.** Any run comparing >1 variant reports the deflated Sharpe and the variant count. A high Sharpe is never presented as proof.
6. **Determinism.** `(spec, data, seed)` → identical metrics, verified by test.
7. **Reproducibility.** Every run record carries spec hash, dataset hash, git commit, seed.

## 7. Caveat on D1 — the fixed-income hand-coding rule

`core/quant_core/fixed_income/` was deliberately left as a RED scaffold (five modules, every function `NotImplementedError`, four failing test files) because you decided to hand-code the bond math yourself — it is Build 1 of the trader-prep track and the "Iron Rule" in `docs/trader-prep/08-coding-readiness.md`. The stated reason was that writing day-count, accrued, YTM and DV01 code by hand is what makes that block of the syllabus permanent for the interview.

Handing it to Codex ships the product faster and loses that. Both are legitimate; it is your call, and D1 records that you chose speed.

**If you change your mind, the swap is cheap and localized:** delete §3 of `docs/ai/ca-brief-4-rates-bonds.md`. Codex then builds the calculator's schemas, router, frontend and the `bond_duration` return kind against the existing test harness, and the five module bodies stay yours to fill. Nothing else in the program moves — the tests in `core/tests/test_fixed_income_*.py` are the interface either way.

## 8. What this program deliberately does not build

- **Free per-contract commodity sourcing** (D4). Canonical CSV import is the door.
- **Eurobond RV engine** — data-blocked without Bloomberg exports. Only the import boundary exists, and it already does.
- **MAD peg strategy.** Monitor-only analytics, never a backtested strategy: a managed 60/40 basket with a ±5% band would just rediscover the peg. Unchanged from the master design.
- **Equity-index futures** — would duplicate the existing Moroccan single-stock factor platform.
- **Any modification to equity/signal/dashboard/fundamentals code.**

## 9. Brief index

| Brief | File | Leans on |
|---|---|---|
| 1 — Foundation | `docs/ai/ca-brief-1-foundation.md` | `cross-asset-lab-slice1.md` §Core specification |
| 2 — FX vertical + UI | `docs/ai/ca-brief-2-fx.md` | `cross-asset-lab-slice1.md` §Reference strategies, §Frontend |
| 3 — Commodities | `docs/ai/ca-brief-3-commodities.md` | `commodity-systematic-strategies-plan.md` |
| 4 — Rates & bonds | `docs/ai/ca-brief-4-rates-bonds.md` | `offshore-lab-phase1-fixed-income.md` (new spec for the rates sleeve) |
| 5 — Curve lab | `docs/ai/ca-brief-5-curve-lab.md` | `offshore-lab/00-response.md` §5 Phase 3 |
