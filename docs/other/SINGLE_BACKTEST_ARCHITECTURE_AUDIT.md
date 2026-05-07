# Single Backtest Architecture Audit

Date: 2026-03-12

## Scope

This note audits the plain single-backtest path only.

It does not cover grid optimization or walk-forward optimization except where those paths reveal missing control surfaces that also affect single runs.

## Executive Summary

The single-backtest architecture currently has three different realities:

1. The spec the user thinks they submitted.
2. The spec the backend actually executes after defaults and mutations.
3. The spec/results the UI displays afterward.

Those three realities are not consistently aligned.

That is the main reason single backtests now feel "weird" or unreliable. The issue is not one isolated bug. It is a control-plane problem:

- the frontend shows defaults it does not always submit,
- the backend applies hidden defaults and runtime mutations,
- the execution layer has behavior changes that are not fully reflected in the UI,
- the results layer displays requested config more than effective config.

Until single backtest has one canonical effective-spec pipeline, it will keep producing runs that are hard to trust and hard to reason about.

## Current End-to-End Flow

Current single-backtest flow:

1. Frontend form builds `specJson` in `quant-backtesting-frontend/app/new-run/page.tsx`.
2. For single mode, it derives `strategy.params` only from `state.singleParams`.
3. API stores the run spec.
4. Worker loads the stored spec in `services/worker/tasks/execute_run.py`.
5. Worker mutates portfolio defaults before execution.
6. Pipeline takes the non-optimization branch in `core/quant_core/pipeline.py`.
7. `BacktestEngine(engine_spec).run()` builds strategy/portfolio objects using backend defaults in `core/quant_core/engine.py`.
8. Strategy semantics execute in `core/quant_core/strategy.py`.
9. Results metrics/tables are computed in `core/quant_core/results.py`.
10. Results UI reconstructs config mostly from stored run spec and local overrides in `quant-backtesting-frontend/components/run/single-backtest-results.tsx`.

The architecture gap is that steps 1, 5, 7, and 10 do not share one canonical configuration contract.

## Findings

### 1. Frontend shows defaults that it does not submit

File: `quant-backtesting-frontend/app/new-run/page.tsx`

- `singleParams` starts empty.
- The input UI displays `state.singleParams[fullKey] ?? defaultVal`.
- Submit logic only serializes a parameter if the user actually typed in that field.

Relevant lines:

- `singleParams: {}` around line 414
- submit logic around lines 763-775
- display logic around lines 1308-1319

Consequence:

- The user sees a value in the form.
- The backend may receive no value for that field.
- The engine then falls back to backend defaults.

This is the highest-confidence single-backtest control bug.

### 2. Frontend defaults do not match backend defaults

Frontend defaults come from `quant-backtesting-frontend/lib/api.ts`.

Examples:

- `strategy.sma_window`: frontend starts at `5`
- `strategy.rsi_window`: frontend starts at `7`
- `strategy.macd_fast_window`: frontend starts at `8`
- `strategy.bb_window`: frontend starts at `10`
- `strategy.obv_span`: frontend starts at `5`
- `strategy.k_window`: frontend starts at `7`
- `strategy.tenkan`: frontend starts at `7`

Backend execution defaults come from `core/quant_core/engine.py`.

Examples:

- `sma_price.window`: backend default `50`
- `ma_cross.fast/slow`: backend defaults `20/50`
- `rsi.period/low/high/mode`: backend defaults `14/30/70/reversal`
- `macd.fast/slow/signal/trigger`: backend defaults `12/26/9/cross`
- `bollinger.bb_window/bb_k`: backend defaults `20/2.0`
- `obv.obv_span`: backend default `20`
- `stoch_vwap.k_window`: backend default `14`
- `ichimoku.tenkan/kijun/senkou_b/shift`: backend defaults `9/26/52/26`

Consequence:

- An untouched single-run form can execute a materially different strategy than the screen suggests.
- Two people looking at the same UI can believe they launched one setup while the engine ran another.

### 3. Single-backtest UI does not expose the full strategy control surface

File: `quant-backtesting-frontend/lib/strategy-registry.ts`

Current `STRAT_PARAM_KEYS` is narrow:

- `sma_price`: only `sma_window`, `signal_mode`
- `ma_cross`: only fast/slow windows
- `rsi`: only window/oversold/overbought
- `macd`: only fast/slow/signal windows

Important backend knobs are not consistently exposed:

- `allow_short`
- `nan_policy`
- `rsi.mode`
- `macd.trigger`
- other strategy-specific fields

Consequence:

- Even if the form-submission bug is fixed, the single-backtest UI still cannot fully control the actual engine behavior.
- The user is not operating the full strategy contract, only a subset.

### 4. Worker mutates the portfolio spec before execution

File: `services/worker/tasks/execute_run.py`

Relevant lines around 3414-3416:

- `portfolio_cfg.setdefault("fill_price_model", "next_open")`
- `portfolio_cfg.setdefault("mtm_model", "close_t1")`
- `spec_json["portfolio"] = portfolio_cfg`

Consequence:

- The executed run spec is not necessarily the stored/submitted spec.
- Those defaults are applied at execution time, not as part of one canonical spec-resolution stage.
- If the UI later displays the stored run spec rather than the effective runtime spec, the user sees an incomplete picture.

### 5. Results UI mostly reflects requested config, not guaranteed effective config

File: `quant-backtesting-frontend/components/run/single-backtest-results.tsx`

Relevant blocks:

- `baseRunStrategyParams` around line 1642
- `runStrategyParams` around line 1654
- `baseRunPortfolioConfig` around line 1659
- `runPortfolioConfig` around line 1664

The page reconstructs strategy/portfolio state from:

- `runSpec.strategy.params`
- `runSpec.portfolio`
- local override objects

Consequence:

- The display layer is not guaranteed to show the exact resolved config that the worker/engine used.
- This makes diagnosis difficult because the run detail page can look internally coherent while still not matching executed reality.

### 6. There is already an "effective params" helper, but it is not the canonical single-backtest resolver

File: `services/api/app/routers/runs.py`

Helper:

- `_effective_strategy_and_portfolio_params(...)` around lines 2024-2056

That helper already knows how to merge:

- base strategy params,
- prefixed overrides,
- nested strategy overrides,
- base portfolio config,
- prefixed portfolio overrides,
- nested portfolio overrides.

Consequence:

- The codebase already recognizes the need for an effective-params layer.
- But single backtest does not appear to use one canonical, persisted, backend-owned effective-spec resolution path end to end.

This is an architectural opportunity: the missing control layer already has a partial precedent.

### 7. Portfolio configuration advertises modes that the main run path does not truly honor

File: `core/quant_core/portfolio.py`

Relevant lines:

- `allow_short: bool = True` around line 93
- `sizing_mode: SizingMode = "target_weight"` around line 131
- `run(...)` around line 342
- docstring note around line 356: `target_weight mode is intentionally not used here`
- orders use `_deltas_pct_cash_shares(...)` around line 485

Consequence:

- The portfolio contract advertises more control than the execution path actually supports.
- `sizing_mode="target_weight"` exists in config but the main run path uses `% cash / % shares` delta logic.
- This is deeper than a UI bug; it is an execution-contract mismatch.

For single backtest, this means the user cannot fully trust that portfolio config fields correspond to live execution behavior.

### 8. Strategy semantics changed in ways that materially affect single runs

File: `core/quant_core/strategy.py`

### 8.1 `sma_price` changed long-only behavior

Relevant logic around lines 505-519.

Observed behavior:

- `-1.0` is now emitted below the SMA as an exit signal regardless of `allow_short`.

Consequence:

- If earlier behavior only produced `-1` when shorting was allowed, long-only runs now trade differently.
- This can change entry/exit timing even when the user never touched optimization.

### 8.2 `macd.trigger="zero"` semantics changed

Relevant logic around lines 712-713:

- `out[line > 0.0] = 1.0`
- `out[line < 0.0] = -1.0`

Consequence:

- `zero` no longer behaves like a zero-cross event trigger.
- It behaves like a sign-regime state.
- A single MACD backtest can therefore hold long/short states much longer than before.

This is a direct execution-semantics change.

### 9. The results UI still explains MACD using older zero-cross language

File: `quant-backtesting-frontend/components/run/single-backtest-results.tsx`

Relevant lines:

- `const trigger = ... "zero"` around line 986
- explanation text around line 1026 uses `prev(line<=0) and now(line>0)`

Consequence:

- The backend may execute one MACD behavior while the UI explains another.
- That creates false confidence during investigation because the explanation panel itself is now misleading.

### 10. Metrics semantics changed, so some "weirdness" is reporting drift rather than trade drift

File: `core/quant_core/results.py`

Changes visible in current code and diff against earlier commit:

- drawdown now returns `NaN` for undefined bars in `_drawdown_from_equity`
- CAGR now uses elapsed calendar time in `_annualized_return`
- Sortino uses downside semi-variance in `_sortino`
- trade-table front column contains `side^2` / `side²` instead of `side`

Consequence:

- A run can look different even if the signal path stayed the same.
- Users may interpret metrics changes as execution bugs.
- The `side²` typo suggests the reporting layer also has a schema-stability problem.

### 11. Default and control ownership is spread across too many layers

Today, single-backtest defaults and behavior are distributed across:

- frontend parameter suggestions in `quant-backtesting-frontend/lib/api.ts`
- frontend visible inputs in `quant-backtesting-frontend/lib/strategy-registry.ts`
- frontend submit logic in `quant-backtesting-frontend/app/new-run/page.tsx`
- worker execution defaults in `services/worker/tasks/execute_run.py`
- engine defaults in `core/quant_core/engine.py`
- strategy runtime semantics in `core/quant_core/strategy.py`
- results semantics in `core/quant_core/results.py`
- results-page config reconstruction in `quant-backtesting-frontend/components/run/single-backtest-results.tsx`

Consequence:

- No single module owns the truth for "what single backtest means."
- Changes in one layer can silently invalidate assumptions in the others.
- This is why behavior can seem broken even when tests still pass.

## Root Cause Statement

The single-backtest problem is fundamentally not "the engine broke" or "the UI broke" in isolation.

The root problem is that single backtest has no canonical effective-spec architecture.

Specifically:

- defaults are duplicated,
- control surfaces are incomplete,
- runtime mutations are hidden,
- displayed config is not guaranteed to equal executed config,
- behavior semantics changed without synchronized UI contract updates.

## What Must Exist To Take Control Of Single Backtest

### 1. One canonical backend-owned effective-spec resolver

Single backtest needs a single function that resolves:

- strategy kind,
- strategy params,
- portfolio params,
- execution defaults,
- worker defaults,
- derived defaults,
- schema normalization.

That resolver must run before execution and produce one persisted effective spec.

### 2. Requested spec and effective spec must both be stored

Store both:

- `requested_spec`
- `effective_spec`

Why:

- `requested_spec` preserves user intent.
- `effective_spec` preserves executed truth.

The results page should explicitly show both when they differ.

### 3. Frontend must submit explicit values, not display-only defaults

For single mode, every visible field should either:

- be initialized into state before submit, or
- be resolved by a backend schema endpoint and returned as an explicit effective form state.

A visible default that is not submitted is not a real default. It is a UI illusion.

### 4. Strategy schema must be backend-defined and complete

The frontend should not hardcode the effective control surface with a narrow `STRAT_PARAM_KEYS` list.

Single backtest needs a backend-owned schema describing, per strategy:

- all parameters,
- type,
- default,
- allowed values,
- whether it is expert-only or basic,
- whether it changes execution semantics.

Without that, the UI will keep drifting from the engine.

### 5. Portfolio contract must be honest

If `target_weight` is not implemented in the full run path, then one of these must happen:

- implement it properly, or
- remove it from the exposed single-backtest contract, or
- mark it unsupported for this execution path.

The same rule applies to any config field that is accepted but not actually honored.

### 6. Strategy semantic changes must be versioned or clearly surfaced

Behavioral changes like:

- `sma_price` exit semantics
- `macd zero` semantics

should not silently ride along as ordinary refactors.

Single backtest needs one of:

- versioned strategy semantics,
- migration notes attached to runs,
- release-note style warnings when a strategy contract changed.

### 7. Results pages must render executed truth, not reconstructed approximations

The run detail page should prefer:

- persisted `effective_spec`
- persisted execution metadata

over:

- re-merging `runSpec`
- local override reconstruction

Otherwise the results page remains a best-effort explanation rather than an authoritative audit surface.

### 8. Contract tests must cover single-backtest configuration resolution

Add tests for:

1. form-visible defaults vs submitted payload
2. submitted payload vs stored requested spec
3. requested spec vs effective spec
4. effective spec vs engine-instantiated strategy params
5. effective spec vs results-page displayed config

Without these tests, architecture drift will keep returning.

## Priority Order For Repair

If the goal is to regain control quickly, fix in this order:

1. Define and persist canonical `effective_spec` for single backtest.
2. Fix the frontend so visible defaults are explicitly submitted.
3. Replace hardcoded frontend strategy param lists/defaults with backend-owned schema.
4. Align results UI to display `effective_spec`.
5. Audit strategy semantic changes and either revert, version, or surface them.
6. Audit portfolio fields and remove unsupported illusions like dormant sizing modes.
7. Add end-to-end contract tests around spec resolution and display.

## Most Likely Reasons You Feel Single Backtest "Broke"

If the issue started after recent changes, the strongest candidates are:

1. The form now displays strategy defaults that are not actually submitted, causing backend defaults to take over silently.
2. Backend strategy semantics changed for `sma_price` and `macd`, altering trade behavior in ordinary single runs.
3. Results metrics changed, making output look inconsistent even when trading logic is only partly changed.
4. The results page may be showing a reconstructed configuration that does not fully match executed runtime config.

## Bottom Line

Single backtest currently lacks a trustworthy source of truth.

Until the architecture is rebuilt around one canonical effective-spec pipeline, single runs will remain vulnerable to:

- hidden defaults,
- incomplete controls,
- silent runtime mutations,
- display/execution mismatches,
- semantic drift across layers.

That is the real problem to fix.
