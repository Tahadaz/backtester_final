# Four-Page Layer Audit and WFO Verification

Date: 2026-04-03

Scope audited:
- Frontend: `/data`, `/signals`, `/strategy`, `/backtest`
- Backend/API: `market_data`, `strategy_signals`, `strategy`, `strategy_backtest_runs`
- Core: `signal_engine`, `strategy_plan`, `wfo`, and shared `pipeline`

Out of scope by design:
- `quant-backtesting-frontend/app/new-run`
- `quant-backtesting-frontend/app/runs`
- `/runs/*` product flows except where referenced only as secondary evidence that broader WFO machinery exists elsewhere in the repo

Implementation labels used:
- `Implemented`
- `Partial / deferred`
- `Documented but not wired`

Severity labels used:
- `Critical`
- `High`
- `Medium`
- `Low`

## Findings

### 1. Four-page backtest docs present full WFO as current product behavior, but the shipped four-page backtest is still direct-only
Severity: `Critical`
Category: `implementation gap` + `doc/contract drift`

Why it matters:
- The backtest docs describe the four-page backtest layer as the station that "implements pure Pardo methodology" with rolling IS/OOS optimization, WFE selection, statistical validation, and held-out test period.
- The actual four-page product explicitly tells the user it is still running a direct strategy backtest flow, not the full WFO executor.

Evidence:
- The backtest layer index describes current-state full WFO as the backtest layer contract: `docs/backtest-layer/00-INDEX.md`
- The overview doc says the backtest page evaluates through WFA and adds WFO mode detection and WFO result sections: `docs/backtest-layer/01-overview-and-design-philosophy.md`
- The four-page strategy page warns that direct backtest still uses seed values for WFO-marked fields: `quant-backtesting-frontend/app/strategy/page.tsx:66-67`
- The four-page backtest page repeats that it is the "current direct strategy backtest flow" and that the "full WFO executor is being built separately": `quant-backtesting-frontend/app/backtest/page.tsx:221-227`, `quant-backtesting-frontend/app/backtest/page.tsx:409`
- The clean-slice backtest-runs API rejects `mode="wfo"` with HTTP 422: `services/api/app/routers/strategy_backtest_runs.py:71-74`

Verdict:
- Four-page backtest WFO is `Documented but not wired`.

### 2. WFO-marked parameters are not optimized in the four-page backtest path; they are flattened into current `.value` seeds
Severity: `High`
Category: `methodology gap`

Why it matters:
- The strategy page is built around explicit WFO flags and scan ranges.
- The four-page backtest path does not consume those as an optimization surface. It converts the v2 strategy into a legacy direct-backtest config and lifts current `value` fields into fixed runtime parameters.
- That means the user can mark parameters as WFO in `/strategy`, but `/backtest` still evaluates a fixed seeded strategy instead of a walk-forward-optimized one.

Evidence:
- The direct backtest endpoint is explicitly a direct backtest: `services/api/app/routers/strategy.py:863`
- That endpoint calls `build_legacy_backtest_config_from_v2(...)` before execution: `services/api/app/routers/strategy.py:876`
- It then passes the converted config into `run_strategy_plan_backtest(...)`: `services/api/app/routers/strategy.py:901`
- The conversion function copies active strategy structure and risk fields by reading `.value`, not by executing any scan or optimization:
  - `services/api/app/strategy_v2.py:691-692` deep-copy entry/exit rules
  - `services/api/app/strategy_v2.py:697-705` derive per-stock stop/target/time-stop from `.value`
  - `services/api/app/strategy_v2.py:728-736` derive top-level stop/target/time-stop from `.value`
- The review logic counts WFO params correctly and blocks Option E at review level, but the execution path still remains direct-only: `services/api/tests/test_strategy_v2.py:88`

Verdict:
- Strategy authoring is WFO-aware.
- Four-page backtest execution is not WFO-aware.

### 3. Statistical-validation and held-out test-period docs are not wired into the four-page backtest flow
Severity: `High`
Category: `implementation gap`

Why it matters:
- The docs claim the four-page backtest layer delivers Monte Carlo, DSR, and a final held-out OOS test period.
- The four-page execution path does not call the WFO statistical or test-period utilities.

Evidence:
- Statistical validation is documented as part of the current backtest layer: `docs/backtest-layer/08-statistical-validation.md:1`, `docs/backtest-layer/08-statistical-validation.md:237-239`
- Held-out test-period validation is documented as part of the current backtest layer: `docs/backtest-layer/09-test-period-validation.md:7`, `docs/backtest-layer/09-test-period-validation.md:21`, `docs/backtest-layer/09-test-period-validation.md:190-194`
- The underlying core utilities do exist:
  - `core/quant_core/wfo/statistical.py`
  - `core/quant_core/wfo/test_period.py`
- But the four-page execution path does not reference `monte_carlo_permutation_test`, `deflated_sharpe_ratio`, `partition_test_period`, `assess_test_period_length`, or `run_wfo_engine` from:
  - `services/api/app/routers/strategy.py`
  - `services/api/app/routers/strategy_backtest_runs.py`
  - `core/quant_core/strategy_plan/backtest.py`
  - `quant-backtesting-frontend/app/backtest/page.tsx`

Verdict:
- These modules exist in core.
- They are `Documented but not wired` for the four-page backtest product.

### 4. The current Monte Carlo methodology in the docs is not the intended final-OOS robustness overlay
Severity: `High`
Category: `methodology gap`

Why it matters:
- The intended design is a post-backtest robustness simulation on the final held-out OOS optimized strategy, at both portfolio and per-stock levels, with many simulated timelines and equity fan charts.
- The current docs describe permutation testing on concatenated OOS trades from WFO windows. That is a different statistical object.

Evidence:
- The docs explicitly define Monte Carlo as a permutation test on OOS trades and returns: `docs/backtest-layer/08-statistical-validation.md`
- The current core implementation matches that framing:
  - `core/quant_core/wfo/statistical.py:68` defines `monte_carlo_permutation_test(...)`
  - it shuffles realized returns and computes sampled curves, percentile bands, and p-value
- This is useful for null-hypothesis significance, but it is not the same thing as:
  - bootstrapped alternative timelines for the final held-out OOS path
  - a robustness overlay on the final optimized strategy
  - per-stock plus portfolio post-backtest path simulation

Methodology verdict:
- Current docs conflate a permutation significance test with the intended robustness Monte Carlo.
- For the intended design, a block-bootstrap/path-bootstrap workflow on the final OOS test is the better fit than trade shuffling.

### 5. Regime-aware signal conditioning is partially implemented, but the docs disagree with themselves and the UI does not surface it cleanly
Severity: `Medium`
Category: `doc/contract drift`

Why it matters:
- The signal index says regime-aware conditioning is "designed, not yet implemented".
- The repo actually contains:
  - a regime endpoint
  - a hook
  - a regime computation module
  - a dedicated panel component
- But that panel/hook are not visibly wired into the main `/signals` page flow.

Evidence:
- Signal index says not yet implemented: `docs/signal-generation/00-INDEX.md:23`
- Actual implementation exists:
  - regime engine: `core/quant_core/signal_engine/regime.py:113`, `core/quant_core/signal_engine/regime.py:315`
  - API endpoint: `services/api/app/routers/strategy_signals.py:792`, `services/api/app/routers/strategy_signals.py:866-871`
  - frontend hook: `quant-backtesting-frontend/hooks/use-api.ts:475-482`
  - panel component: `quant-backtesting-frontend/components/strategy/regime-detail-panel.tsx:48`
- No usage of `useRegimeConsensus(...)` or `RegimeDetailPanel` was found outside their definitions in the frontend tree.

Verdict:
- Regime-aware conditioning is `Partial / deferred`, not simply "not implemented".

### 6. The shared core WFO stack has at least one failing aggregation test
Severity: `Medium`
Category: `implementation gap`

Why it matters:
- This does not drive the four-page product today as directly as Findings 1-4 do.
- It still matters because it weakens confidence in the shared WFO machinery the docs implicitly rely on.

Evidence:
- Targeted test run via `.venv\Scripts\python.exe -m pytest ...` produced `81 passed, 1 failed`
- Failing test:
  - `core/tests/test_pipeline_walk_forward.py:127`
  - `test_multi_horizon_wfo_top20_per_horizon_with_aggregate_summary`
- Observed failure: the per-horizon row cap expected by the test is violated (`75` rows observed where `<= 20` was expected)

Verdict:
- Shared WFO machinery is present, but not fully stable.

## Layer-by-Layer Implementation Assessment

### Data layer
Status: `Implemented`

Docs claim:
- `/data` is the control center for the canonical market-data pipeline
- dual freshness model, calendar/availability diagnostics, upload, refresh, and stock detail are current-state features

What is implemented:
- The page uses the expected catalog and tracked-stock hooks: `quant-backtesting-frontend/app/data/page.tsx:51-53`
- It wires the documented upload, refresh-status, and stock-detail UI components:
  - `quant-backtesting-frontend/app/data/page.tsx:7-9`
  - `quant-backtesting-frontend/app/data/page.tsx:192`
  - `quant-backtesting-frontend/app/data/page.tsx:464`
  - `quant-backtesting-frontend/app/data/page.tsx:471`
- Backend freshness logic uses business-day staleness:
  - `services/api/app/routers/market_data.py:436`
  - `services/api/app/routers/market_data.py:447-450`
- Availability-calendar endpoint exists:
  - `services/api/app/routers/market_data.py:907`
- Canonical `/data` market universe support is present:
  - `services/api/app/routers/market_data.py:1199`
- Frontend freshness badge component exists:
  - `quant-backtesting-frontend/components/data/freshness-badge.tsx:11`

What is partial or deferred:
- No major four-page data-layer gap surfaced from the sampled code and tests.

What is missing:
- No material missing feature was identified relative to the current docs in this audit scope.

Methodology/reasoning quality:
- Good.
- The dual freshness model described in docs is reflected in split backend/frontend behavior rather than being a vague prose-only claim.

Assessment:
- The data layer is the strongest match between docs and shipped four-page behavior.

### Signal layer
Status: `Implemented`, with a regime subfeature that is `Partial / deferred`

Docs claim:
- A full A->G out-of-sample signal pipeline powers `/signals`
- Variant detail and indicator explorer are available

What is implemented:
- The ensemble pipeline explicitly orchestrates A->G: `core/quant_core/signal_engine/ensemble.py:3`, `core/quant_core/signal_engine/ensemble.py:378`
- OOS evaluation is implemented in Layer B:
  - `core/quant_core/signal_engine/oos_eval.py:216`
- Survivor filtering and redundancy reduction are implemented:
  - `core/quant_core/signal_engine/ensemble.py:521`
  - `core/quant_core/signal_engine/ensemble.py:541`
- Variant detail/backtest endpoints are present:
  - `services/api/app/routers/strategy_signals.py:295`
  - `services/api/app/routers/strategy_signals.py:679`
- Raw indicator explorer endpoint exists:
  - `services/api/app/routers/strategy_signals.py:295`
- `/signals` page ships the technical analysis panel and indicator explorer:
  - `quant-backtesting-frontend/app/signals/page.tsx`

Test support:
- Signal-engine contract and no-lookahead checks:
  - `core/tests/test_signal_engine.py:78`
  - `core/tests/test_signal_engine.py:84`
  - `core/tests/test_signal_engine.py:121`
- Redundancy and ensemble tests:
  - `core/tests/test_signal_engine.py:197`
  - `core/tests/test_signal_engine.py:373`
- Variant detail/backtest API tests:
  - `services/api/tests/test_strategy_signals_variant_detail.py:113`
  - `services/api/tests/test_strategy_signals_variant_detail.py:243`

What is partial or deferred:
- Regime-aware conditioning exists in code and API, but is not cleanly surfaced in the main `/signals` UI and is described inconsistently in docs.

What is missing:
- No major gap in the A->G baseline signal engine was found.

Methodology/reasoning quality:
- Strong.
- The signal layer is the best-methodologized part of the four-page app after data.

Assessment:
- Signal generation is genuinely implemented.
- The regime subfeature needs doc/UI cleanup, not a full rewrite.

### Strategy layer
Status: `Implemented`

Docs claim:
- Per-stock strategy authoring, WFO flags, previews, review gate, and backtest handoff

What is implemented:
- The strategy page contains the full six-part authoring flow and per-stock tabs:
  - `quant-backtesting-frontend/app/strategy/page.tsx`
- WFO-awareness is present in draft state and review:
  - WFO warnings on the page: `quant-backtesting-frontend/app/strategy/page.tsx:66-67`
  - review/gating logic tested in `services/api/tests/test_strategy_v2.py:88`
- Strategy handoff exists:
  - `services/api/app/routers/strategy.py`
  - `services/api/tests/test_strategy_v2.py` handoff assertions
- v2 migration and review logic are tested:
  - `services/api/tests/test_strategy_v2.py:21-22`
  - `services/api/tests/test_strategy_v2.py:176`

What is partial or deferred:
- The strategy layer is internally coherent, but the execution path it hands off into is still direct-only on the four-page backtest side.

What is missing:
- Nothing major inside authoring/review itself.
- The missing piece is the receiving WFO executor, which belongs to the backtest layer.

Methodology/reasoning quality:
- Good inside its own boundary.
- The strategy layer correctly tracks WFO intent even though the four-page backtest layer does not yet honor it.

Assessment:
- Strategy authoring is ready before backtest execution is.

### Backtest layer
Status: `Documented but not wired`

Docs claim:
- Full WFO mode detection and execution
- WFE selection
- neighbor averaging
- optimization profile checks
- OOS-derived Kelly sizing
- statistical validation
- final held-out test period

What is actually implemented in the four-page product:
- Direct backtest execution of saved strategies:
  - `services/api/app/routers/strategy.py:863`
  - `services/api/app/routers/strategy.py:901`
- Queued clean-slice direct runs:
  - `services/api/app/routers/strategy_backtest_runs.py`
  - tested by `services/api/tests/test_strategy_backtest_runs.py:144`
- Direct backtest result rendering in `/backtest`:
  - `quant-backtesting-frontend/app/backtest/page.tsx`

What is partial or deferred:
- WFO artifacts and utilities exist elsewhere in repo core, but are not delivered through the four-page backtest flow.

What is missing:
- actual four-page WFO execution
- joint optimization of WFO-flagged fields
- per-window WFO result display for the clean-slice backtest
- WFE-driven configuration selection
- optimization-profile diagnostics
- OOS-derived Kelly replacement of placeholders in the four-page backtest flow
- held-out final OOS test flow
- post-backtest Monte Carlo robustness views at portfolio and stock levels

Methodology/reasoning quality:
- Weak relative to docs, because the docs describe a methodology that the product path does not actually execute.

Assessment:
- This is the primary implementation and contract gap in the four-page app.

## Dedicated WFO Methodology Verdict

### 1. Is full WFO available through the four-page app?
No.

Evidence:
- Strategy-page disclaimer: `quant-backtesting-frontend/app/strategy/page.tsx:66-67`
- Backtest-page disclaimer: `quant-backtesting-frontend/app/backtest/page.tsx:221-227`, `quant-backtesting-frontend/app/backtest/page.tsx:409`
- API rejection of `mode="wfo"`: `services/api/app/routers/strategy_backtest_runs.py:71-74`

### 2. Are WFO-marked fields optimized in the four-page backtest flow?
No.

Evidence:
- `services/api/app/routers/strategy.py:876` converts v2 strategy config into legacy direct config
- `services/api/app/strategy_v2.py:697-705`, `services/api/app/strategy_v2.py:728-736` extract current `.value` fields into fixed parameters
- `services/api/app/routers/strategy.py:901` runs the direct strategy-plan backtest over those fixed values

### 3. Does the repo contain WFO primitives not integrated into the four-page product?
Yes.

Evidence:
- WFO engine/config/statistical/test-period modules exist:
  - `core/quant_core/wfo/engine.py`
  - `core/quant_core/wfo/statistical.py`
  - `core/quant_core/wfo/test_period.py`
  - `core/quant_core/wfo/wfe.py`
- Shared pipeline WFO machinery exists in `core/quant_core/pipeline.py`
- But the four-page backtest flow does not call them

### 4. Are the statistical-validation docs true for the four-page flow?
No.

Evidence:
- The modules exist in core
- The four-page execution path does not wire them into `/backtest`

### 5. Is there a separate core WFO defect worth noting?
Yes.

Evidence:
- `core/tests/test_pipeline_walk_forward.py:127`
- Targeted test run observed `81 passed, 1 failed`

Overall WFO verdict:
- The repo contains meaningful WFO building blocks.
- The four-page app does not currently expose or execute the documented full WFO methodology.

## Dedicated Monte Carlo Methodology Verdict

Intended design for this audit:
- Monte Carlo should occur after the optimized strategy produces its final held-out OOS test result
- It should run for:
  - portfolio/general strategy path
  - each stock path
- It should visualize many alternative plausible timelines and equity curves

Current repo reality:
- The documented/current implementation concept is a permutation test on realized OOS returns:
  - `docs/backtest-layer/08-statistical-validation.md`
  - `core/quant_core/wfo/statistical.py:68`

Why this is a mismatch:
- Permutation testing answers: "is observed performance distinguishable from random ordering under a null?"
- It does not answer: "how robust is the final optimized strategy under alternative plausible timelines of the held-out OOS path?"
- DSR answers yet another question: "is Sharpe inflated by multiple testing and non-normality?"
- These are complementary ideas, not interchangeable ones.

Best-fit methodology for the intended design:
- `block bootstrap / path bootstrap` on the final held-out OOS return path

Reasoning:
- Better aligned with "different timelines"
- Better preserves local dependence than naive reshuffling
- Less model-dependent than fitting a fully synthetic process
- Naturally supports:
  - portfolio equity fan chart
  - per-stock equity fan charts
  - percentile bands with actual OOS path overlay

Current implementation verdict:
- For the intended final-OOS robustness overlay, Monte Carlo is `Missing`
- The current permutation design is useful, but it is a different statistical tool

## Missing Items by Layer

### Data layer
- No major missing item found inside the audited four-page scope

### Signal layer
- Regime-aware feature wiring into main `/signals` UX
- Doc cleanup so implementation status is consistent across index and feature doc

### Strategy layer
- No major authoring-gap found
- Main missing dependency is the backtest-side WFO executor that should consume strategy WFO flags

### Backtest layer
- Real four-page WFO execution mode
- Per-window WFO diagnostics in the clean-slice flow
- WFE selection and robustness checks in product path
- OOS-derived Kelly sizing replacing placeholder/direct calibration path
- Held-out final OOS test flow
- Portfolio-level and per-stock post-final-OOS Monte Carlo robustness simulation
- UI results sections matching the backtest docs

## Residual Risks and Test Gaps

- The targeted verification run succeeded broadly but not fully:
  - `81 passed, 1 failed`
  - failing test: `core/tests/test_pipeline_walk_forward.py::test_multi_horizon_wfo_top20_per_horizon_with_aggregate_summary`
- The signal layer has better direct test evidence than the four-page backtest layer
- The backtest docs are materially ahead of the four-page backtest product
- Because the four-page app does not yet wire the WFO modules, some of the repo's WFO correctness is only indirectly relevant to end users today

## Bottom Line

- `Data`: well implemented and largely honest relative to docs
- `Signals`: well implemented, with a partially surfaced regime feature and minor doc drift
- `Strategy`: well implemented as an authoring/review layer
- `Backtest`: the main gap; docs describe a full WFO station, but the four-page product still runs a direct seeded backtest path rather than the documented WFO methodology
