# 13 - ADR: Strict Pardo Fold-Driven Window Policy

## Purpose
This ADR records the final decisions for strict WFO window sizing and explains why each decision was made.

Goal:
- remove hidden heuristics from window sizing logic
- make strict WFO behavior mathematically explicit and auditable
- preserve operational robustness with explicit fallback traceability

This document is designed for implementation review with another agent/human reviewer.

---

## Problem Statement
Current WFO behavior is method-inspired but not fully decision-transparent.
Two hardcoded behaviors are the main source of confusion:

1. `max_lookback` floor at `14`
2. train-window grid step at `21` bars

Observed effects:
- non-intuitive config counts for narrow parameter scans
- difficulty explaining why the engine evaluates many configs/windows
- mismatch between user intent ("strict methodology") and runtime behavior (implicit heuristics)

---

## Scientific Grounding
Primary reference:
- Pardo, *The Evaluation and Optimization of Trading Strategies* (2nd ed.)

Core methodological anchors used:
- Walk-forward window size is typically in the `25%` to `35%` region of optimization window size (Ch.11).
- Reliability improves with many walk-forwards; run as many as possible (Ch.11).
- Degrees of freedom should remain high (Ch.6, DF discussion).

Project interpretation used for strict mode:
- ratio constraint: `O / I in [0.25, 0.35]`
- DF simplification: `I >= 10 * L`
  - `L = effective max lookback from active WFO parameters`

Important clarification:
- `k = 10` is a derived implementation simplification from the DF target, not a literal universal constant stated by Pardo as code policy.

---

## Final Decisions

### D1. Default policy becomes strict fold-driven
Decision:
- default `window_policy = strict_fold_driven`
- keep `legacy_ratio_scan` for compatibility

Why:
- strict policy is explicit, reproducible, and easier to audit
- compatibility path is preserved for existing behavior comparisons

---

### D2. Keep horizon-year caps in strict mode
Decision:
- strict mode keeps horizon caps:
  - short: 5 years
  - medium: 10 years
  - long: 20 years
- cap usage is recorded in strict diagnostics

Why:
- preserves current horizon semantics and expected runtime envelope
- avoids sudden compute expansion for existing deployments
- keeps strict methodology behavior stable across horizons

Tradeoff:
- may reduce fold counts versus full-history strict analysis
- mitigated by explicit cap diagnostics and fallback traceability

---

### D3. Strict mode auto-derives OOS from IS
Decision:
- strict mode no longer depends on user-entered ratio list for config generation
- OOS is derived from IS using strict ratio anchors and validated by constraints

Why:
- prevents contradictory user inputs
- ensures ratio constraints are satisfied by construction

Compatibility:
- keep `is_oos_ratios` in API payload for backward compatibility
- strict mode explicitly ignores this field and records that fact in diagnostics

---

### D4. Use Top-K fold-driven configs with K=12 default
Decision:
- generate strict candidates via fold math
- rank and keep top `K` deterministic configs (`K=12` default)

Why:
- full enumeration can explode runtime and total windows
- Top-K gives strong coverage with predictable cost

---

### D5. Keep `min_walk_forwards` default = 5
Decision:
- default remains `5` for compatibility and user expectation continuity

Why:
- already widely used in current flows
- can be raised when stricter reliability is desired

---

### D6. Enable strict fallback with floor=1
Decision:
- if no strict config satisfies requested `min_walk_forwards`, auto-lower toward floor `1`
- if still impossible, fail with precise diagnostics

Why:
- avoids unnecessary hard-stop on thin data
- keeps behavior operational while preserving transparency

Guardrail:
- fallback must be explicitly labeled as degraded strict evidence

---

### D7. Persist fallback and policy diagnostics at run and stock levels
Decision:
- store requested/effective fold requirements and fallback metadata in run summary and stock result

Why:
- post-run auditability
- reproducibility of methodological state used to generate results

---

### D8. Keep optimization profile checks unchanged
Decision:
- strict mode does not alter optimization profile logic (neighbor averaging, profile pass/fail criteria, or thresholds)

Why:
- isolates this change to window sizing policy only
- preserves comparability of profile-based quality signals across legacy and strict modes

---

## Mathematical Specification
Definitions:
- `T`: pre-test bars available
- `L`: effective max lookback
- `I`: in-sample bars
- `O`: out-of-sample bars
- `S`: step bars (strict default `S = O`)
- `N`: realized walk-forward count

Strict constraints:
1. DF proxy: `I >= 10 * L`
2. ratio: `0.25 <= O / I <= 0.35`
3. folds: `N = floor((T - L - I) / O)` and `N >= N_min`

Fold-driven derivation:
- for each candidate fold count `N` and ratio anchor `r in {0.25, 0.30, 0.35}`:
  - `I = floor((T - L) / (1 + r * N))`
  - `O = round(r * I)`
- keep only candidates satisfying strict constraints and realized folds
- rank and keep Top-K

Reason for including `L`:
- window start is offset by lookback warmup in the current window builder
- if one pre-trims data (`T_usable = T - L`), formulas are equivalent

---

## Proposed API Contract Changes
Add to `wfo_config`:
- `window_policy: "strict_fold_driven" | "legacy_ratio_scan"` (default strict)
- `top_k_folds: int` (default `12`)
- `strict_fallback_enabled: bool` (default `true`)
- `strict_fallback_floor: int` (default `1`)

Existing fields retained:
- `is_oos_ratios` retained for compatibility
- strict mode ignores it and records ignored-input diagnostics

No endpoint split required.

---

## Proposed Runtime Diagnostics Schema
At stock result and run summary level, persist:
- `window_policy_used`
- `requested_min_walk_forwards`
- `effective_min_walk_forwards`
- `fallback_applied`
- `fallback_floor`
- `top_k_folds_used`
- `ignored_inputs` (for strict mode, includes `is_oos_ratios`)
- `feasibility`:
  - `horizon_cap_years`
  - `horizon_cap_applied`
  - `pretest_bars_after_cap`
  - `T_pretest_bars`
  - `L_max_lookback`
  - `max_feasible_folds_before_fallback`
  - `status` (`strict`, `strict_fallback`, `infeasible`)

---

## Quantitative Rationale Snapshot
For short-horizon-style data example (`T=1260`):
- strict compatibility of weekly OOS can fail under DF constraints
- example: `L=7` implies `I>=70`; strict ratio then implies `O` near `18..24`, not `5`

Implication:
- if user expects very short OOS in strict mode, constraints may conflict
- fallback path and clear diagnostics are mandatory for explainability

---

## Implementation Plan (Decision Complete)

### A. Backend API Contract and Normalization
Target files:
- `services/api/app/schemas/strategy_backtest_runs.py`
- `services/api/app/routers/strategy_backtest_runs.py`

Changes:
1. Extend `StrategyBacktestRunWfoConfig` with:
   - `window_policy: Literal["strict_fold_driven", "legacy_ratio_scan"] = "strict_fold_driven"`
   - `top_k_folds: int = 12` (bounds: `1..50`)
   - `strict_fallback_enabled: bool = True`
   - `strict_fallback_floor: int = 1` (bounds: `1..50`)
2. In `_normalize_wfo_config(...)`:
   - normalize and persist the four new fields
   - keep `is_oos_ratios` unchanged in payload for compatibility
   - explicit note: `_normalize_wfo_config(...)` is implemented in the router file (`strategy_backtest_runs.py`), not in schemas
3. In create-run validation:
   - no new endpoint
   - no rejection on `is_oos_ratios` when strict mode is selected
   - only validate `is_oos_ratios` range for `legacy_ratio_scan`

Rationale:
- contract is explicit and backward-compatible
- strict behavior becomes selectable and auditable

---

### B. WFO Engine Policy Routing and Config Generation
Target file:
- `core/quant_core/strategy_plan/wfo.py`

Changes:
1. Add policy router in `run_stock_walk_forward(...)`:
   - read `window_policy` from `wfo_config` (default strict)
   - strict path and legacy path share same downstream simulation loop
   - explicit integration point: wrap current `_window_configs(...)` invocation at the existing call site in `run_stock_walk_forward` (currently around the `configs = _window_configs(...)` block, near `wfo.py` lines ~589-604 depending revision)
2. Keep horizon cap behavior in strict mode:
   - continue using `HORIZON_LOOKBACK_YEARS` logic
   - add cap diagnostics fields (see section D)
3. Strict configuration builder (new helper):
   - name suggestion: `_strict_fold_driven_configs(...)`
   - required return type: `list[WalkForwardConfig]` (from `core.quant_core.wfo.config`) for direct compatibility with existing `build_walk_forward_windows(...)` usage
   - inputs: `data_length`, `max_lookback`, `requested_min_walk_forwards`, `top_k_folds`, `fallback_enabled`, `fallback_floor`
   - strict anchors fixed to `{0.25, 0.30, 0.35}`
   - derive candidates with fold-driven math:
     - `I_min = 10 * L`
     - estimate `N_upper` from minimum feasible `(I,O)` geometry
     - for `N` from `N_upper` down to `effective_min`:
       - for each `r` in anchors:
         - `I = floor((T - L) / (1 + r * N))`
         - `O = round(r * I)`
         - validate:
           - `I >= I_min`
           - `0.25 <= O / I <= 0.35`
           - `len(build_walk_forward_windows(...)) >= effective_min`
         - dedupe by `(I,O)`
   - ranking key (deterministic):
     1. realized fold count descending
     2. OOS bars ascending
     3. train bars ascending
   - select top `K` (`top_k_folds`)
4. Fallback loop (strict only):
   - start `effective_min = requested_min`
   - if no configs and fallback enabled, decrement `effective_min` until `strict_fallback_floor`
   - if still none, raise explicit infeasibility error containing strict diagnostics
5. Legacy mode:
   - preserve existing `_window_configs(...)` behavior
   - preserve `_WINDOW_GRID = 21` and ratio scan usage only in legacy path

Rationale:
- strict mode fully method-driven
- fallback behavior operationally resilient but auditable
- legacy behavior preserved for compatibility and A/B comparison

---

### C. Max Lookback Heuristic Removal (Strict Alignment)
Target files and call chain:
- `core/quant_core/strategy_plan/score_sources.py`
- `core/quant_core/strategy_plan/score_frame.py` (wrapper pass-through)
- `core/quant_core/strategy_plan/wfo.py` (caller)

Call chain to document in implementation notes:
- `wfo.py` -> `score_frame.derive_max_lookback(...)` -> `score_sources.derive_max_lookback(...)`

Changes:
1. Remove both hard floor `14` points from strict WFO lookback derivation path in `score_sources.py`:
   - initialization floor (`max_lookback = 14`)
   - return floor (`return max(max_lookback, 14)`)
   - current anchors are around `score_sources.py:270` and `score_sources.py:296` (line numbers may shift)
2. Replace with a strict-safe minimum of `1` in strategy WFO context:
   - effective lookback becomes data-driven from active rows/params
3. No change needed in `score_frame.py` logic itself (wrapper stays pass-through).
4. Keep indicator defaults for non-WFO contexts unchanged where required.

Rationale:
- removes hidden lookback inflation
- aligns strict window sizing with actual configured parameter space

Implementation note:
- if needed for compatibility, introduce optional parameter in derive function (e.g., `min_floor`) and pass strict value from WFO caller.

---

### D. Diagnostics and Result Schema Wiring
Target files:
- `core/quant_core/strategy_plan/wfo.py`
- `services/worker/tasks/strategy_backtest_runs.py`

Changes in stock-level `result["diagnostics"]` and summary:
1. Always persist strict policy context when strict mode is used:
   - `window_policy_used`
   - `requested_min_walk_forwards`
   - `effective_min_walk_forwards`
   - `fallback_applied`
   - `fallback_floor`
   - `top_k_folds_used`
   - `ignored_inputs` (must include `is_oos_ratios` for strict mode)
2. Persist cap-related diagnostics:
   - `horizon_cap_years`
   - `horizon_cap_applied`
   - `pretest_bars_after_cap`
3. Persist feasibility snapshot:
   - `T_pretest_bars`
   - `L_max_lookback`
   - `max_feasible_folds_before_fallback`
   - `status` in `{strict, strict_fallback, infeasible}`
4. Worker-level run summary:
   - aggregate strict usage flags and fallback counts/symbol lists
   - do not alter run terminal status semantics

Rationale:
- full audit trail for methodological review
- allows later UI surfacing without backend changes

---

### E. Frontend Compatibility (No New UI Requirement)
Target file:
- `frontend/lib/api.ts`

Changes:
1. Extend WFO create payload typing with new optional fields:
   - `window_policy`
   - `top_k_folds`
   - `strict_fallback_enabled`
   - `strict_fallback_floor`
2. No required UI changes in this phase; backend defaults apply.
3. Apply edit at inline WFO config type declaration in `createStrategyBacktestRun(...)` payload typing (not a separate named interface).
   - current inline block location is around `frontend/lib/api.ts` (line numbers may shift)

Rationale:
- type-level compatibility for strict-mode requests
- avoids forcing UI scope creep

---

### F. Profile Logic Invariance
Decision lock:
- optimization profile checks remain unchanged under strict mode:
  - same neighbor-averaging behavior
  - same profile pass/fail logic and thresholds
  - same viability decision mechanics

Implementation guard:
- no edits to `evaluate_optimization_profile` behavior or thresholds in this scope.

---

### G. Ordered Execution Sequence
1. Add schema fields and router normalization/validation support.
2. Implement strict config builder + fallback loop in WFO engine.
3. Add strict diagnostics to stock result payloads.
4. Add run-level summary aggregation for strict diagnostics in worker.
5. Add frontend API type compatibility fields.
6. Implement/update tests (core, API, worker) and run targeted suite.

---

### H. Out of Scope (Explicit)
- no new frontend diagnostic cards/tables in this phase
- no removal of legacy mode
- no changes to optimization profile thresholds/criteria
- no changes to portfolio aggregation methodology

---

## Test and Acceptance Criteria
Core tests:
- strict generator enforces DF + ratio + fold constraints
- strict generator deterministic under same inputs
- Top-K bound respected
- fallback lowers `N_min` to floor when needed and records trace
- hard failure when infeasible even at floor
- strict mode keeps horizon caps and records cap diagnostics
- profile checks remain unchanged in strict mode

API/worker tests:
- strict defaults applied when fields omitted
- `is_oos_ratios` ignored in strict mode with recorded warning
- run and stock diagnostics include requested/effective/fallback fields
- legacy mode unchanged when explicitly selected
- strict fields accepted and normalized in `wfo_config`
- strict fallback trace appears in run summary and stock result

Regression checks:
- no break in existing run creation/list/get endpoints
- status semantics remain unchanged from latest accepted worker behavior
- direct mode behavior unchanged

---

## Risks and Mitigations
Risk:
- fallback may reduce strictness silently

Mitigation:
- never silent; always persisted and visible in run + stock diagnostics

Risk:
- increased runtime on large baskets

Mitigation:
- Top-K bound and deterministic ranking

Risk:
- confusion during transition

Mitigation:
- explicit `window_policy` in request/result and preserved legacy mode

---

## Migration / Rollback
Migration:
- default strict mode for new runs
- legacy mode still callable explicitly

Rollback:
- server default can be switched back to legacy without schema removal
- strict implementation remains available for controlled rollout

---

## Decision Status
Status: **Approved for implementation**

Approved choices captured from planning:
- strict fold-driven default
- keep horizon caps in strict mode and record cap usage in diagnostics
- Top-K folds strategy with default `K=12`
- keep `min_walk_forwards` default `5`
- strict fallback enabled with floor `1`
- `is_oos_ratios` ignored in strict mode with explicit diagnostics
