# Codex Brief 1 — Cross-Asset Foundation (engine + persistence + API)

**Program:** `docs/cross-asset-product/00-program-plan.md` — read §4 (guardrails), §5 (reuse table), §6 (invariants) first. They are binding.
**Base spec:** `docs/ai/cross-asset-lab-slice1.md` §"Core specification" — implement it as written **except** where §2 below overrides it.
**Scope:** the shared engine and its plumbing. **No frontend in this brief** (Brief 2 builds it once). No real data sources (Brief 2 wires them). Fixtures only.
**Ship gate:** `pytest core/tests/test_ca_*.py services/api/tests/test_cross_asset_research_router.py` green; `core/quant_core/cross_asset/` imports nothing from `services/`, SQLAlchemy or FastAPI.

## 1. Guardrails (from program §4 — verbatim, binding)

1. Do not explore the repository. Every anchor is below, with file:line.
2. Never read `graphify-out/GRAPH_REPORT.md` or `graph.json` — they do not fit in context.
3. Scope test runs to the files above plus `core/tests`; run the full suite once, at the end.
4. Reuse before create (program §5). Do not reimplement WFO, bootstrap, deflated Sharpe or risk summaries.
5. If a file is not in §3 below, do not create it. No helper modules, no speculative interfaces.
6. Do not modify equity/signal/dashboard/fundamentals code. The only files you may modify are listed in §4.
7. Do not extend `run_signal_backtest` (`core/quant_core/signal_engine/backtest_mc.py:418`) — see program §5.

## 2. Overrides against `cross-asset-lab-slice1.md`

These supersede the base spec. Everything else in its §"Core specification" stands.

**O1 — No `cross_asset_run` table.** The base spec says to add one. Do not. Reuse the existing ledger:
- `Run` (`services/api/app/models.py:106`) with `run_type="cross_asset_strategy"`. `run_type` already exists at line 111 with default `"backtest"`.
- `Run` already carries `spec_json`, `spec_hash`, `git_commit`, `dataset_hash`, `seed`, `code_version` — the reproducibility fields. Use them; add nothing.
- Stage outputs → `Artifact` (`models.py:141`) via the existing MinIO helpers in `core/quant_core/s3_keys.py:10,28`.
- Scalar metrics → `RunMetric` (`models.py:161`).
- `rq_job_id` and status live on the `Run` row, exactly as `routers/strategy_backtest_runs.py:333` does it.

**O2 — Migration adds two tables, not three:** `cross_asset_instrument` and `cross_asset_strategy`, per base spec §DB. Follow the style in `services/api/alembic/versions/`.

**O3 — `ReturnSpec.kind` is a three-value union:** `"fx_excess" | "futures_excess" | "bond_duration"`. In this brief `returns.py` implements the dispatch plus `fx_excess` and `futures_excess`. `bond_duration` raises `NotImplementedError("bond_duration: Brief 4")` — Brief 4 fills it. The dispatch shape must not change when it does.

**O4 — No frontend files.** The base spec's §Frontend belongs to Brief 2.

**O5 — Deflated Sharpe:** import from `core/quant_core/research/stats/robustness.py:94`. A second implementation exists at `core/quant_core/wfo/statistical.py:260` — ignore it, do not merge them.

## 3. Files to create

```
core/quant_core/cross_asset/__init__.py
core/quant_core/cross_asset/instruments.py      # Instrument, FuturesContract, FxPair (design §10)
core/quant_core/cross_asset/returns.py          # dispatch + fx_excess_return, futures_excess_return, to_base_ccy
core/quant_core/cross_asset/signals.py          # time_series_momentum, carry_signal, vol_scale — all lagged
core/quant_core/cross_asset/portfolio.py        # size_positions: unit | inverse_vol | vol_target, caps
core/quant_core/cross_asset/costs.py            # apply_costs -> (turnover, cost_series)
core/quant_core/cross_asset/strategy_spec.py    # StrategyDefinition tree, to_dict/from_dict, spec_hash
core/quant_core/cross_asset/dataquality.py      # data_quality_report, blocks_backtest
core/quant_core/cross_asset/backtest.py         # run_backtest(spec, panel, seed) -> stages + metrics + warnings
core/quant_core/cross_asset/validation.py       # thin adapters: WFO, param grid, LOO, subperiod, cost sens, bootstrap
core/quant_core/cross_asset/importer.py         # canonical long CSV -> tidy panel + quality report

services/api/app/schemas/cross_asset_research.py
services/api/app/routers/cross_asset_research.py
services/api/app/services/cross_asset/__init__.py
services/api/app/services/cross_asset/orchestrator.py
services/worker/tasks/cross_asset/__init__.py
services/worker/tasks/cross_asset/run_backtest.py
services/api/alembic/versions/<rev>_add_cross_asset_tables.py

core/tests/fixtures/cross_asset/fx_g10_sample.csv
core/tests/fixtures/cross_asset/commodity_contracts_sample.csv
core/tests/test_ca_returns.py
core/tests/test_ca_signals.py
core/tests/test_ca_portfolio.py
core/tests/test_ca_backtest.py
core/tests/test_ca_dataquality.py
core/tests/test_ca_importer.py
services/api/tests/test_cross_asset_research_router.py
```

## 4. Files you may modify (nothing else)

- `services/api/app/main.py` — one `include_router(cross_asset_research.router)`, same pattern as neighbours.
- `services/worker/tasks/__init__.py` — register the new task, matching how existing tasks are registered there.

## 5. API surface

Prefix `/cross-asset-research`, existing API-key auth (`Depends(auth.require_api_key)`).

- `POST /strategies` · `GET /strategies` · `GET /strategies/{id}` — versioned `StrategyDefinition`
- `POST /data-quality` — spec or dataset id → `DataQualityReport`. **Must pass before a backtest runs.**
- `POST /runs` → `202`, enqueue RQ (pattern: `routers/strategy_backtest_runs.py:333`), return run id
- `GET /runs/{id}` status + metrics · `GET /runs/{id}/stages` · `GET /runs/{id}/robustness`
- `GET /strategies/{id}/current-signal` — latest signal, intended vs previous position, drivers, data timestamp, staleness, next rebalance, reversal conditions

Every response carries the transparency envelope: `{inputs, methodology, data_source, calculation_date, assumptions, units, warnings, results, interpretation}`. `data_source` is `"fixture"` for fixture-backed runs. The monitoring payload carries a fixed disclaimer string and never implies guaranteed profit. Unavailable values are `null`, never invented zeros. `409` if a result is requested before completion.

## 6. Tests (all deterministic)

Per base spec §Tests, plus:
- `test_ca_returns`: FX excess-return identity on a hand-built series; futures roll-return reconstruction equals back-adjusted price return minus collateral; base-ccy conversion; `bond_duration` raises `NotImplementedError`.
- `test_ca_signals`: **look-ahead shift test** — shifting an input by one bar shifts the signal by exactly one bar and never uses `t`'s return at `t`.
- `test_ca_portfolio`: vol_target hits target on synthetic iid data within tolerance; caps enforced; shorts symmetric.
- `test_ca_backtest`: determinism (same spec+data+seed → identical metrics); stage dict has every key; `net == gross − costs`.
- `test_ca_dataquality`: corrupted fixture (dup dates / all-stale) sets `blocks_backtest=True` **and the driver refuses to run**.
- `test_cross_asset_research_router`: strategy CRUD; data-quality gate; run enqueues and polls; envelope fields present; disclaimer present; run row is a `Run` with `run_type="cross_asset_strategy"`.

## 7. Acceptance

1. Ship gate above is green, and the full existing suite still passes (run once, at the end).
2. `core/quant_core/cross_asset/` imports nothing from `services/`, SQLAlchemy or FastAPI.
3. No `cross_asset_run` table exists; a completed run is a `Run` row with stage `Artifact`s and `RunMetric`s.
4. No file outside §3/§4 was created or modified.
5. Program §6 invariants hold — in particular the look-ahead test and the determinism test.
