# Four-Page Docs-to-Implementation Audit

Date: 2026-04-04

Scope reviewed:
- `docs/architecture`
- `docs/data-layer`
- `docs/signal-generation`
- `docs/strategy-layer`
- `docs/backtest-layer`

Product surface audited:
- Frontend: `/data`, `/signals`, `/strategy`, `/backtest`
- API routers: `market_data`, `strategy_signals`, `strategy`, `strategy_backtest_runs`
- Core modules actually used by those pages and routers
- Worker task path used by the current four-page WFO flow

Out of scope except as supporting evidence:
- `docs/other`
- legacy and broader-platform routes such as `/new-run`, `/runs/*`, `/results`

Review rule used:
- prefer the shipped four-page product over repo-only modules
- distinguish `implemented in repo` from `implemented in the four-page flow`
- treat roadmap and source/reference docs as non-contract unless they present behavior as current

Verification evidence gathered:
- `quant-backtesting-frontend`: `npm run build` -> passed
- API verification set:
  - `services/api/tests/test_market_data_formats.py` -> passed
  - `services/api/tests/test_market_holidays.py` -> 1 failing assertion on holiday name text
  - `services/api/tests/test_strategy_signals_variant_detail.py` -> passed
  - `services/api/tests/test_strategy_v2.py` -> passed
  - `services/api/tests/test_strategy_backtest_runs.py` -> passed
- Core verification set:
  - `core/tests/test_signal_engine.py` -> passed
  - `core/tests/test_strategy_plan_backtest.py` -> passed
  - `core/tests/test_strategy_levels.py` -> passed
  - `core/tests/test_strategy_universe.py` -> passed
  - `core/tests/test_wfo_engine.py` -> passed
  - `core/tests/test_wfo_statistical.py` -> passed
  - `core/tests/test_test_period.py` -> passed
  - `core/tests/test_pipeline_walk_forward.py` -> 1 failing assertion on multi-horizon row capping

Implementation labels used:
- `Implemented`
- `Partial / deferred`
- `Documented but not wired`
- `Doc drift / inaccurate`
- `Reference only`

Severity labels used:
- `High`
- `Medium`
- `Low`

## Findings

### 1. Backtest API and frontend contract docs still describe the wrong public interface for the shipped four-page WFO flow
Severity: `High`
Category: `doc/contract drift`

Why it matters:
- The current four-page app does have a shipped WFO path, but the docs still present an older `/backtest/wfo` contract with per-window and progress endpoints that do not match the current frontend client or backend router surface.
- This is now a documentation accuracy problem, not a missing-implementation problem.

Docs evidence:
- `docs/backtest-layer/10-api-data-flow-and-frontend-contracts.md` defines `POST /api/backtest/wfo`, `GET /api/backtest/wfo/{run_id}`, `GET /api/backtest/wfo/{run_id}/window/{idx}`, and `GET /api/backtest/wfo/{run_id}/progress`
- `docs/architecture/02-data-contracts.md:171-174` repeats the same `/backtest/wfo` inventory

Implementation evidence:
- The shipped four-page WFO router is `services/api/app/routers/strategy_backtest_runs.py:23` with prefix `/backtest/strategy-runs`
- The frontend calls `/backtest/strategy-runs` via:
  - `quant-backtesting-frontend/lib/api.ts:2584`
  - `quant-backtesting-frontend/lib/api.ts:2592`
  - `quant-backtesting-frontend/lib/api.ts:2597`
- The page uses polling hooks, not SSE:
  - `quant-backtesting-frontend/hooks/use-api.ts:734-745`
  - `quant-backtesting-frontend/app/backtest/page.tsx:400-404`

Verdict:
- WFO is `Implemented` in the four-page product.
- The documented backtest API contract is `Doc drift / inaccurate`.

Missing or incorrect doc pieces:
- update paths from `/backtest/wfo` to `/backtest/strategy-runs`
- document polling-based progress retrieval instead of SSE
- document the stock-detail endpoint shape actually used by `/backtest`

### 2. Backtest statistical-validation docs describe a different methodology than the shipped four-page WFO implementation
Severity: `High`
Category: `methodology drift`

Why it matters:
- The docs present Monte Carlo permutation testing plus a combined WFE/Monte Carlo/DSR pass-fail model.
- The shipped implementation computes WFE and DSR, then adds held-out-test block-bootstrap robustness. That is not the same statistical object as a permutation test on OOS returns.

Docs evidence:
- `docs/backtest-layer/00-INDEX.md:20,51,67,109`
- `docs/backtest-layer/01-overview-and-design-philosophy.md:97-99`
- `docs/backtest-layer/08-statistical-validation.md`
- `docs/backtest-layer/12-methodology-and-sources.md:140-168`
- `docs/architecture/01-four-stations.md:70`

Implementation evidence:
- The shipped four-page WFO path runs through:
  - `services/worker/tasks/strategy_backtest_runs.py`
  - `core/quant_core/strategy_plan/wfo.py:387-908`
- In `run_stock_walk_forward(...)`:
  - WFE is computed: `core/quant_core/strategy_plan/wfo.py:631`
  - DSR is computed: `core/quant_core/strategy_plan/wfo.py:766`
  - held-out test robustness uses `block_bootstrap_equity_paths(...)`: `core/quant_core/strategy_plan/wfo.py:342`, `core/quant_core/strategy_plan/wfo.py:748-762`
- The current per-stock result payload shown on `/backtest` exposes:
  - `statistical_validation`
  - `test_period`
  - `robustness`
  via `quant-backtesting-frontend/app/backtest/page.tsx:682-753`

What is not present in the shipped four-page path:
- no call from the four-page WFO path to `monte_carlo_permutation_test(...)`
- no combined `all_passed` verdict surfaced on `/backtest`

Verdict:
- Backtest WFO validation is `Implemented`, but the statistical-validation docs are `Doc drift / inaccurate`.

Missing or incorrect doc pieces:
- replace permutation-test language with the current held-out-test block-bootstrap robustness model
- document that DSR is shipped
- document the actual pass/fail logic that is enforced today

### 3. Cross-page navigation and query-param docs are outdated
Severity: `Medium`
Category: `doc/contract drift`

Why it matters:
- These docs describe shareable URLs and state carry between pages.
- The current four-page app uses different query-param names and does not implement the documented symbol preselection path.

Docs evidence:
- `docs/architecture/04-state-and-navigation.md`
  - Signal -> Strategy says `/strategy?symbol=IAM`
  - Strategy -> Backtest says `/backtest?strategy_id=abc123`
  - Backtest -> Strategy says `/strategy?id=abc123`

Implementation evidence:
- Strategy page only reads `strategyId`, not `symbol` or `id`:
  - `quant-backtesting-frontend/app/strategy/page.tsx:95,105`
- Strategy sends users to `/backtest?strategyId=...`:
  - `quant-backtesting-frontend/app/strategy/page.tsx:146`
- Backtest page reads `strategyId`, not `strategy_id`:
  - `quant-backtesting-frontend/app/backtest/page.tsx:381-382`
- Backtest returns to `/strategy?strategyId=...`:
  - `quant-backtesting-frontend/app/backtest/page.tsx:535`

Verdict:
- Shared navigation is `Implemented`.
- The documented query-param contract is `Doc drift / inaccurate`.

Missing or incorrect doc pieces:
- replace `strategy_id` and `id` with `strategyId`
- remove or mark deferred the `/strategy?symbol=IAM` preselection flow until implemented

### 4. Signal-layer status docs are now behind the shipped `/signals` page
Severity: `Medium`
Category: `status drift`

Why it matters:
- Several signal docs still describe the indicator explorer as deferred and the signal page as a narrower experience than what is currently shipped.
- This is the opposite of the earlier April 3 audit: the implementation moved forward, but some docs did not.

Docs evidence:
- `docs/signal-generation/00-INDEX.md:10,27` says indicator explorer is `Partial / deferred`
- `docs/signal-generation/09-api-and-frontend.md` describes only the first tab as enabled
- `docs/signal-generation/13-implementation.md` says indicator explorer is deferred from the shipped surface

Implementation evidence:
- `/signals` renders both:
  - `TechnicalAnalysisPanel`
  - `IndicatorExplorer`
  via `quant-backtesting-frontend/app/signals/page.tsx:52-96`
- The regime-aware detail flow is wired through the main technical panel:
  - `quant-backtesting-frontend/components/strategy/technical-analysis-panel.tsx:4,95,173`
  - `quant-backtesting-frontend/components/strategy/regime-detail-panel.tsx:48`
- The indicator explorer is a live component:
  - `quant-backtesting-frontend/components/strategy/indicator-explorer.tsx:48`
- The API endpoint backing it exists:
  - `services/api/app/routers/strategy_signals.py:295`

Verdict:
- The baseline signal layer is `Implemented`.
- Signal status docs in `00-INDEX`, `09-api-and-frontend`, `12-indicator-explorer`, and `13-implementation` are `Doc drift / inaccurate`.

### 5. Strategy-layer docs contain duplicated generations of contract, roadmap, and methodology files that now disagree with each other
Severity: `Medium`
Category: `documentation hygiene`

Why it matters:
- The strategy folder has duplicated numbered documents:
  - `09-api-data-flow-and-frontend-contracts.md` and `10-api-data-flow-and-frontend-contracts.md`
  - `10-implementation-roadmap.md` and `11-implementation-roadmap.md`
  - `11-methodology-and-sources.md` and `12-methodology-and-sources.md`
- The older copies describe obsolete schema shapes and stale status.

Docs evidence:
- `docs/strategy-layer/09-api-data-flow-and-frontend-contracts.md` still centers a `meta / config / snapshot` shape
- `docs/strategy-layer/10-api-data-flow-and-frontend-contracts.md` is a newer but still not fully current contract draft
- `docs/strategy-layer/10-implementation-roadmap.md` says backtest preload is not yet wired

Implementation evidence:
- The shipped strategy page uses the current v2 portfolio-plus-stocks structure:
  - `quant-backtesting-frontend/app/strategy/page.tsx`
  - `services/api/app/strategy_v2.py`
- The strategy page does have backtest navigation wired:
  - `quant-backtesting-frontend/app/strategy/page.tsx:146`
  - `quant-backtesting-frontend/components/strategy/core-strategy-header.tsx:88-94`

Verdict:
- Strategy authoring is `Implemented`.
- Several duplicated strategy docs are `Doc drift / inaccurate` or `Reference only`.

Recommended cleanup:
- pick one API contract doc, one roadmap doc, and one methodology doc as canonical
- archive or remove the older copies

### 6. Option E remains documented as part of the backtest/strategy methodology, but four-page WFO v1 still blocks it
Severity: `Medium`
Category: `documented but not wired`

Why it matters:
- The strategy and backtest docs describe full Option E auto-discovery as part of the flow.
- The current four-page review path blocks Option E from execution.

Docs evidence:
- `docs/backtest-layer/06-option-e-auto-discovery.md`
- `docs/strategy-layer/06-entry-rules-layer.md`
- `docs/strategy-layer/07-exit-rules-layer.md`

Implementation evidence:
- Strategy review explicitly blocks Option E:
  - `services/api/app/strategy_v2.py:598`
- This behavior is covered by test:
  - `services/api/tests/test_strategy_v2.py:76-121`
- `/backtest` warns that unsupported future-only constructs are blocked server-side:
  - `quant-backtesting-frontend/app/backtest/page.tsx:236-242`

Verdict:
- Option E auto-discovery is `Documented but not wired` for the current four-page product.

### 7. The “apply sizing back to strategy” loop is still more documented than shipped in the four-page UI
Severity: `Low`
Category: `partial workflow gap`

Why it matters:
- The docs describe a user-initiated feedback loop where Kelly sizing can be applied back to the strategy.
- The current strategy/backtest pages surface sizing results, but there is no visible four-page action that writes WFO Kelly output back into the saved strategy.

Docs evidence:
- `docs/architecture/02-data-contracts.md:94-95`
- `docs/architecture/04-state-and-navigation.md`
- `docs/backtest-layer/07-sizing-from-oos.md`

Implementation evidence:
- Sizing results are displayed on `/backtest` for WFO runs:
  - `core/quant_core/strategy_plan/wfo.py:765-804`
  - `quant-backtesting-frontend/app/backtest/page.tsx:744-752`
- The four-page strategy UI links to backtest, but no “apply sizing” action was found in the strategy/backtest pages.
- The sizing preview endpoint exists for strategy planning:
  - `services/api/app/routers/strategy.py:754-789`
  - `quant-backtesting-frontend/lib/api.ts:2916`
  but that is not the same as applying backtest-derived Kelly output.

Verdict:
- OOS-derived sizing is `Implemented`.
- The feedback-loop action is `Partial / deferred`.

### 8. Two verification failures remain in the currently scoped implementation
Severity: `Medium`
Category: `stability issues`

Why it matters:
- These do not necessarily contradict the docs, but they do reduce confidence in the implementation quality behind the documented behavior.

Evidence:
- `services/api/tests/test_market_holidays.py` fails because the current holiday data returns `Mawlid al-Nabi` where the test expects `Aīd Al-Mawlid Annabawi`
  - holiday loader: `services/api/app/market_holidays.py`
- `core/tests/test_pipeline_walk_forward.py::test_multi_horizon_wfo_top20_per_horizon_with_aggregate_summary` fails because `rows_by_horizon` stores all variants rather than capping at 20
  - multi-horizon aggregation: `core/quant_core/pipeline.py:1192-1307`

Verdict:
- These are `implementation gaps`, not primary doc-contract gaps.

## Layer Verdicts

### Data
Verdict: `Implemented`

The `/data` page, `market_data` router, upload/refresh flows, availability calendar, and freshness model all align well with the layer docs. The only notable issue found in the scoped checks is a holiday-name regression in the test suite, not a broad data-layer architecture mismatch.

### Signal
Verdict: `Implemented`, with `Doc drift / inaccurate` status docs

The A-G signal pipeline, variant detail, regime-aware detail flow, and indicator explorer are all present in the shipped `/signals` surface. The main problem is that several status and frontend docs still describe the explorer as deferred and the page as less complete than it is.

### Strategy
Verdict: `Implemented`, with `Partial / deferred` Option E and stale duplicate docs

The strategy page has real saved-strategy CRUD, per-stock tabs, review/gating, preview endpoints, and backtest navigation. The remaining gaps are mostly around documented Option E execution and duplicated stale documentation generations.

### Backtest
Verdict: `Implemented`, but `Partial / mixed` relative to current docs

The four-page app now ships both direct mode and a real async WFO mode. WFE, window detail, Kelly sizing, held-out test output, per-stock results, and portfolio robustness are present. The documentation problem is no longer “WFO missing”; it is that the docs still describe the wrong API surface and an older statistical-validation design.

### Shared architecture
Verdict: `Partial / mixed`

The four-station split, shared header, and forward-only product flow are real. The main architecture drift is in query params, route examples, some endpoint inventories, and a few UI-label details.

## Coverage Matrix

### Architecture

| Document | Primary subject | Verdict | Four-page evidence | Notes |
|---|---|---|---|---|
| `docs/architecture/01-four-stations.md` | Four-station mandates | `Partial / mixed` | `components/dynamic-header.tsx`, `app/data/page.tsx`, `app/signals/page.tsx`, `app/strategy/page.tsx`, `app/backtest/page.tsx` | Station split is real; backtest outputs/statistical wording is ahead of current exact implementation details. |
| `docs/architecture/02-data-contracts.md` | Inter-station contracts and endpoint inventory | `Partial / mixed` | `routers/market_data.py`, `routers/strategy_signals.py`, `routers/strategy.py`, `routers/strategy_backtest_runs.py` | Signal and strategy contracts are mostly right; backtest endpoint inventory is outdated. |
| `docs/architecture/03-methodology.md` | Theory foundations | `Reference only` | `core/quant_core/signal_engine/*`, `core/quant_core/strategy_plan/wfo.py` | Useful grounding doc; not a precise shipped-surface contract. |
| `docs/architecture/04-state-and-navigation.md` | Nav, shared state, route examples | `Doc drift / inaccurate` | `app/strategy/page.tsx`, `app/backtest/page.tsx`, `components/signals-header.tsx` | Query-param names and symbol carry are outdated. |

### Data Layer

| Document | Primary subject | Verdict | Four-page evidence | Notes |
|---|---|---|---|---|
| `docs/data-layer/00-INDEX.md` | Layer index and control-center framing | `Implemented` | `app/data/page.tsx`, `routers/market_data.py` | High-level framing matches shipped `/data`. |
| `docs/data-layer/01-overview.md` | Data architecture and lifecycle | `Implemented` | `routers/market_data.py`, `services/worker/tasks/ingest_market_data.py`, `services/worker/tasks/refresh_market_data.py` | Core lifecycle is present. |
| `docs/data-layer/02-database-models.md` | DB tables and relationships | `Implemented` | `services/api/app/models.py`, `routers/market_data.py` | No major doc-contract mismatch found. |
| `docs/data-layer/03-backend-endpoints.md` | `/market-data/*` endpoints | `Implemented` | `routers/market_data.py`, `lib/api.ts`, `hooks/use-api.ts` | This is the most accurate endpoint doc in the scope. |
| `docs/data-layer/04-worker-tasks.md` | Ingest and refresh workers | `Implemented` | `services/worker/tasks/ingest_market_data.py`, `services/worker/tasks/refresh_market_data.py` | Worker-backed behavior is real. |
| `docs/data-layer/05-format-detection-and-parsing.md` | Upload parsing and normalization | `Implemented` | `services/api/app/market_data_formats.py`, `services/api/tests/test_market_data_formats.py` | Strong test coverage. |
| `docs/data-layer/06-storage-and-keys.md` | Parquet/object key storage | `Implemented` | `core/quant_core/s3_keys.py`, `routers/market_data.py`, storage helpers | No major mismatch found in scoped review. |
| `docs/data-layer/07-frontend-architecture.md` | `/data` page frontend | `Implemented` | `app/data/page.tsx`, `components/data/*` | Upload, refresh, detail panel, freshness UI all exist. |
| `docs/data-layer/08-data-flows.md` | End-to-end data flows | `Implemented` | `app/data/page.tsx`, `routers/market_data.py`, worker tasks | Shipped flows align. |
| `docs/data-layer/09-holidays-and-scheduling.md` | Holiday calendar and scheduler | `Implemented` | `services/api/app/market_holidays.py`, `services/api/app/scheduler.py`, `services/api/tests/test_market_holidays.py` | Functionality exists; one holiday-name test currently fails. |
| `docs/data-layer/10-config-and-infra.md` | Env/config/infra | `Implemented` | `services/api/app/config.py`, `infra/*`, `docker-compose.yml` | Operational doc appears aligned. |
| `docs/data-layer/11-daily-update-and-data-page.md` | Data page as operations center | `Implemented` | `/data` page, `health`, `refresh`, `catalog`, `freshness-badge` | Accurate current-state framing. |

### Signal Generation

| Document | Primary subject | Verdict | Four-page evidence | Notes |
|---|---|---|---|---|
| `docs/signal-generation/00-INDEX.md` | Layer index and status | `Doc drift / inaccurate` | `app/signals/page.tsx`, `technical-analysis-panel.tsx`, `indicator-explorer.tsx` | Explorer is live; status bullets lag the implementation. |
| `docs/signal-generation/01-philosophy.md` | Why signals are not strategies | `Reference only` | `core/quant_core/signal_engine/*` | Good framing doc; not a shipped-surface contract. |
| `docs/signal-generation/02-candidate-universe.md` | Layer A candidate generation | `Implemented` | `core/quant_core/signal_engine/candidates.py`, `ensemble.py` | No major mismatch surfaced. |
| `docs/signal-generation/03-oos-evaluation.md` | Layer B OOS evaluation | `Implemented` | `core/quant_core/signal_engine/oos_eval.py`, `core/tests/test_signal_engine.py` | Implemented and tested. |
| `docs/signal-generation/04-robustness-scoring.md` | Layer C robustness | `Implemented` | `core/quant_core/signal_engine/robustness.py`, `core/tests/test_signal_engine.py` | Implemented and tested. |
| `docs/signal-generation/05-survivor-filtering.md` | Layer D survivor filtering | `Implemented` | `core/quant_core/signal_engine/survivor.py`, `ensemble.py` | Implemented. |
| `docs/signal-generation/06-redundancy-reduction.md` | Layer E redundancy reduction | `Implemented` | `core/quant_core/signal_engine/redundancy.py`, `core/tests/test_signal_engine.py` | Implemented. |
| `docs/signal-generation/07-current-signal-and-ensemble.md` | Layers F-G current signal and ensemble | `Implemented` | `core/quant_core/signal_engine/current_signal.py`, `ensemble.py` | Implemented. |
| `docs/signal-generation/08-variant-detail.md` | Variant detail and drilldown | `Implemented` | `app/signals/variant/[id]/page.tsx`, `routers/strategy_signals.py`, `services/api/tests/test_strategy_signals_variant_detail.py` | Implemented. |
| `docs/signal-generation/09-api-and-frontend.md` | Signal endpoints and `/signals` UX | `Partial / deferred` | `app/signals/page.tsx`, `routers/strategy_signals.py` | Endpoint coverage is strong, but tab/status description is stale. |
| `docs/signal-generation/10-methodology-and-sources.md` | Sources and justification | `Reference only` | `core/quant_core/signal_engine/*` | Reference doc. |
| `docs/signal-generation/11-regime-aware-conditioning.md` | Experimental regime conditioning | `Implemented` | `routers/strategy_signals.py:792`, `technical-analysis-panel.tsx:95,173` | Experimental but real. |
| `docs/signal-generation/12-indicator-explorer.md` | Indicator explorer | `Doc drift / inaccurate` | `app/signals/page.tsx:94-95`, `indicator-explorer.tsx:48`, `routers/strategy_signals.py:295` | Explorer is now wired into the shipped page. |
| `docs/signal-generation/13-implementation.md` | Current implementation status | `Doc drift / inaccurate` | `app/signals/page.tsx`, `technical-analysis-panel.tsx`, `indicator-explorer.tsx` | Says explorer is deferred; actual UI ships it. |

### Strategy Layer

| Document | Primary subject | Verdict | Four-page evidence | Notes |
|---|---|---|---|---|
| `docs/strategy-layer/00-INDEX.md` | Layer index | `Implemented` | `app/strategy/page.tsx`, `strategy_v2.py` | High-level section map matches the page. |
| `docs/strategy-layer/01-overview-and-design-philosophy.md` | Product philosophy and A-E options | `Partial / mixed` | `app/strategy/page.tsx`, `review-tab.tsx`, `strategy_v2.py` | Broad flow is right; Option E is still blocked in four-page WFO v1. |
| `docs/strategy-layer/02-strategy-domain-and-page-architecture.md` | Saved strategy model and page structure | `Implemented` | `app/strategy/page.tsx`, `components/strategy/core-strategy-header.tsx`, `strategy_v2.py` | Implemented. |
| `docs/strategy-layer/03-universe-layer.md` | Universe, capital, allocation | `Implemented` | `app/strategy/page.tsx`, `routers/strategy.py:/universe,/allocation` | Implemented. |
| `docs/strategy-layer/04-strategy-type-layer.md` | Trend vs mean reversion | `Implemented` | `StrategyTypeCard`, stored stock config | Implemented. |
| `docs/strategy-layer/05-signal-construction-layer.md` | Family selection, params, WFO flags | `Implemented` | `signal-construction-tab.tsx`, `useSignalConsensus`, `useSignalZoneChart`, `strategy_v2.py` | Implemented. |
| `docs/strategy-layer/06-entry-rules-layer.md` | Entry rules and options A-E | `Partial / deferred` | `entry-rules-tab.tsx`, `strategy_v2.py:598` | A-D exist; Option E remains blocked. |
| `docs/strategy-layer/07-exit-rules-layer.md` | Exit rules and options A-E | `Partial / deferred` | `exit-rules-tab.tsx`, `strategy_v2.py:598` | Same Option E limitation. |
| `docs/strategy-layer/08-risk-layer.md` | Stops, cooldown, limits | `Implemented` | `risk-tab.tsx`, `strategy_v2.py`, direct and WFO execution paths | Implemented. |
| `docs/strategy-layer/09-api-data-flow-and-frontend-contracts.md` | Older strategy contract draft | `Doc drift / inaccurate` | `strategy_v2.py`, `app/strategy/page.tsx` | Superseded by later schema work. |
| `docs/strategy-layer/09-review-and-backtest-handoff.md` | Review gate and handoff | `Partial / mixed` | `review-tab.tsx`, `strategy_v2.py:719-737`, `routers/strategy.py:1046-1068` | Review/handoff are real; apply-sizing loop is not visibly wired. |
| `docs/strategy-layer/10-api-data-flow-and-frontend-contracts.md` | Newer strategy contract draft | `Partial / mixed` | `strategy_v2.py`, `lib/api.ts`, `hooks/use-api.ts` | Better than the older copy, but still not the exact shipped shape. |
| `docs/strategy-layer/10-implementation-roadmap.md` | Older implementation roadmap | `Doc drift / inaccurate` | `app/strategy/page.tsx`, `core-strategy-header.tsx` | Claims backtest preload not yet wired. |
| `docs/strategy-layer/11-implementation-roadmap.md` | Another roadmap generation | `Reference only` | `strategy_v2.py`, `app/strategy/page.tsx` | Keep only if intentionally preserved as historical plan. |
| `docs/strategy-layer/11-methodology-and-sources.md` | Older methodology set | `Reference only` | Sources only | Historical/reference value only. |
| `docs/strategy-layer/12-methodology-and-sources.md` | Newer methodology set | `Reference only` | Sources only | Useful reference, not a precise implementation contract. |

### Backtest Layer

| Document | Primary subject | Verdict | Four-page evidence | Notes |
|---|---|---|---|---|
| `docs/backtest-layer/00-INDEX.md` | Layer index and backtest station mandate | `Partial / mixed` | `app/backtest/page.tsx`, `strategy_backtest_runs.py`, `strategy_plan/wfo.py` | WFO is real, but API and statistical-method wording drift. |
| `docs/backtest-layer/01-overview-and-design-philosophy.md` | Backtest page modes and outputs | `Partial / mixed` | `/backtest` page direct and WFO sections | Direct and WFO modes both ship; exact validation model differs from doc. |
| `docs/backtest-layer/02-wfo-methodology.md` | WFO pipeline | `Partial / mixed` | `strategy_plan/wfo.py`, `services/worker/tasks/strategy_backtest_runs.py` | Core search and rolling windows exist; some acceptance details differ from text. |
| `docs/backtest-layer/03-prom-and-objective-function.md` | PROM objective | `Implemented` | `core/quant_core/wfo/prom.py`, `strategy_plan/wfo.py` | Implemented. |
| `docs/backtest-layer/04-neighbor-averaging-and-optimization-profile.md` | Smoothing and profile checks | `Implemented` | `neighbor_avg.py`, `profile.py`, `strategy_plan/wfo.py` | Implemented. |
| `docs/backtest-layer/05-walk-forward-efficiency.md` | WFE and acceptance | `Partial / mixed` | `compute_wfe(...)`, `strategy_plan/wfo.py` | WFE is computed and shown; full documented gate logic is not fully mirrored. |
| `docs/backtest-layer/06-option-e-auto-discovery.md` | Option E WFO auto-discovery | `Documented but not wired` | `strategy_v2.py:598`, `test_strategy_v2.py` | Still blocked in four-page WFO v1. |
| `docs/backtest-layer/07-sizing-from-oos.md` | Kelly sizing from OOS | `Partial / mixed` | `compute_trade_stats`, `compute_kelly_fraction`, `/backtest` WFO detail | Sizing is produced and displayed, but not fed back into strategy via a shipped action. |
| `docs/backtest-layer/08-statistical-validation.md` | Monte Carlo and DSR | `Doc drift / inaccurate` | `strategy_plan/wfo.py`, `/backtest` WFO detail | DSR ships, but robustness is block-bootstrap on held-out test, not permutation testing. |
| `docs/backtest-layer/09-test-period-validation.md` | Held-out test period | `Implemented` | `strategy_plan/wfo.py:703-762`, `/backtest` WFO detail | Implemented. |
| `docs/backtest-layer/10-api-data-flow-and-frontend-contracts.md` | WFO API contract and UI sections | `Doc drift / inaccurate` | `strategy_backtest_runs.py`, `lib/api.ts`, `hooks/use-api.ts`, `app/backtest/page.tsx` | Main contract mismatch in the current scope. |
| `docs/backtest-layer/11-implementation-roadmap.md` | WFO roadmap | `Reference only` | historical plan | Keep only as plan/history. |
| `docs/backtest-layer/12-methodology-and-sources.md` | Sources and design choices | `Reference only` | `strategy_plan/wfo.py` | Useful reference, but not a current API/behavior contract. |

## Closing Summary

Bottom line by layer:
- `Data`: honest and well implemented
- `Signal`: well implemented, but several status/frontend docs are now stale
- `Strategy`: well implemented as an authoring and review layer; Option E and some older docs lag reality
- `Backtest`: now meaningfully implemented in the four-page app, but the docs still describe the wrong public API and an older validation model
- `Shared architecture`: structurally correct, but route examples and query-param conventions need cleanup

Most important change from the previous April 3 snapshot:
- the four-page backtest is no longer “direct-only”
- the repo now ships a real async WFO path through `/backtest/strategy-runs`
- the remaining work is mostly documentation alignment plus a few product and test cleanup items, not absence of WFO itself
