# Book-Grounded Four-Page Theory Audit

Date: 2026-04-04

## Executive Summary

This app is not a literal software implementation of either Marcos López de Prado or Robert Pardo. It is a four-page research product that borrows different things from each author:

- The app's overall separation into `/data`, `/signals`, `/strategy`, and `/backtest` is much closer to de Prado's chapter 1 production-chain thinking than to a single monolithic backtester. The strongest de Prado fit is architectural.
- The `/backtest` page is where Pardo is most directly operationalized. The current code genuinely implements a Pardo-style optimization and walk-forward workflow: parameter scanning, objective selection, robustness review, winning-configuration selection, Walk-Forward Efficiency, and a held-out test phase.
- The strongest direct de Prado implementation is narrower: skepticism about naive backtests, explicit attention to overfitting, and use of the deflated Sharpe ratio. The strongest direct Pardo implementation is broader: the whole strategy-development and WFO discipline.
- The `/signals` page is only partially from either book. It is more a repo-specific signal research lab built on classical TA families, then wrapped in de Prado-style "feature analysts first, strategy later" process logic.
- The app diverges materially from de Prado by not implementing his more distinctive AFML machinery in the shipped four-page flow: no triple-barrier labeling, no meta-labeling, no fractional differentiation, no purged/CPCV path in the live app flow, and no ML classifier-driven bet sizing.
- The app diverges materially from some earlier repo rhetoric by using block-bootstrap robustness in the shipped WFO path, not the permutation-test framing that appears in older docs. It also computes OOS-derived Kelly as an extension, not as a direct copy of either book.

In short: the current product is best read as a de Prado-shaped research architecture wrapped around a strongly Pardo-shaped strategy evaluation engine, with a substantial amount of app-specific engineering in the signal and execution layers.

## Sources Read

Primary local PDFs read directly:

- `c:\Users\taha\Downloads\Advances in Financial Machine Learning (López de Prado, Marcos) (z-library.sk, 1lib.sk, z-lib.sk).pdf`
- `c:\Users\taha\Downloads\evaluation and optimization of trading strategies pardo.pdf`

Targeted chapters and pages used most heavily:

- de Prado, Chapter 1, PDF pp. 32-40: production chain, meta-strategy, feature-vs-backtest epistemology.
- de Prado, Chapter 10, PDF pp. 168-169: bet sizing motivation.
- de Prado, Chapter 12, PDF pp. 188-191: walk-forward versus broader cross-validation thinking.
- de Prado, Chapter 15, PDF p. 238: strategy-risk framing.
- Pardo, Chapter 2, PDF pp. 68-73: confidence, performance profile, optimization benefits.
- Pardo, Chapter 3, PDF pp. 44-45: development process from formulation to WFO to trading.
- Pardo, Chapter 10, PDF pp. 248-254: optimization framework, parameter selection, scan ranges, trade sample and degrees of freedom.
- Pardo, Search/Judgment and optimization material, PDF pp. 238-239: PROM.

Short excerpts were extracted from the PDFs and sample-checked against the local files. Quotations below are intentionally short.

## How To Read This Report

Verdict labels:

- `Derived`: the app behavior is clearly and directly traceable to the cited book.
- `Adapted`: the book gave the app its reasoning, but the shipped implementation is a modernized or simplified translation.
- `Extension`: the behavior is useful and coherent, but it is repo-specific rather than attributable to de Prado or Pardo.
- `Divergence`: the app takes a materially different path from the cited theory.

Evidence style:

- Book citations use `Book, chapter/topic, PDF p.X`.
- Code citations use `path:line`.
- Test/build evidence reflects the current repo state on 2026-04-04.

## Verification Snapshot

Runtime checks used while preparing this report:

- Frontend build passed: `quant-backtesting-frontend`, `npm run build`.
- API tests: `services/api/tests/test_strategy_signals_variant_detail.py`, `services/api/tests/test_strategy_v2.py`, and `services/api/tests/test_strategy_backtest_runs.py` passed. `services/api/tests/test_market_holidays.py` had one known holiday-name failure.
- Core tests: `core/tests/test_signal_engine.py`, `core/tests/test_strategy_plan_backtest.py`, `core/tests/test_wfo_engine.py`, `core/tests/test_wfo_statistical.py`, and `core/tests/test_test_period.py` passed. `core/tests/test_pipeline_walk_forward.py` had one known multi-horizon row-cap failure.

Known failing checks were treated as implementation issues, not as reasons to rewrite the theory mapping:

- `services/api/tests/test_market_holidays.py`: holiday naming mismatch.
- `core/tests/test_pipeline_walk_forward.py`: top-20-per-horizon row cap bug in multi-horizon aggregation.

## Page 1: Data

### What The Page Does In Code

The `/data` page is a market-data control center, not a theory page. The frontend drives three main actions:

- catalog and freshness browsing in `quant-backtesting-frontend/app/data/page.tsx:50`
- Excel ingestion and tracked-symbol management in `quant-backtesting-frontend/app/data/page.tsx:79-148`
- Bourse refresh orchestration and refresh status in `quant-backtesting-frontend/app/data/page.tsx:79-110` and `quant-backtesting-frontend/app/data/page.tsx:192`

The backend centers on `/market-data` in `services/api/app/routers/market_data.py:46`. That router owns upload formats, calendar/holiday support, OHLCV load paths, symbol maps, refresh triggers, and lightweight technical studies. The actual purpose of the page is to guarantee that the other three pages consume a canonical, inspectable market-data substrate.

### How It Applies de Prado

`Derived`, but mostly at the architectural level.

de Prado's Chapter 1 says a research factory should separate `"data curators"` from later stations and makes data collection, cleaning, storing, and delivery its own responsibility set (Chapter 1, PDF p.34). That maps cleanly to this page:

- the page exists before signal research
- the API exposes data-health and data-shape endpoints before strategy logic
- holidays, freshness, and provider mappings are handled at the data layer instead of being buried inside the backtest

This is why the page looks operational rather than analytical. The reasoning is: if data is not canonical, every downstream result becomes ambiguous.

### How It Applies Pardo

`Adapted`.

Pardo is less about data architecture, but he is explicit that historical simulation must be `"accurate, authentic, and realistic"` and that one must address the issues required to achieve that standard (Chapter 6 overview, PDF p.45). The app applies that reasoning through:

- upload-format control and preview contracts in `services/api/app/routers/market_data.py`
- holiday-aware market calendars in `services/api/app/market_holidays.py` and its tests
- freshness and catalog visibility in the data UI

This is a practical answer to Pardo's concern: before you evaluate a strategy, make the simulation substrate inspectable and correctable.

### Where It Diverges

`Divergence`.

The shipped `/data` page is far more operational and productized than either book. It is Casablanca-market specific, includes upload UX, provider maps, and Bourse refresh orchestration, and does not implement distinctive AFML data work such as:

- event-based bars or the volume clock
- fractional differentiation
- sample-uniqueness weighting

So the page is book-aligned in purpose, not in specific data-science machinery.

### Bottom-Line Reading

The `/data` page is de Prado's production-chain logic applied to an operations console, with Pardo's simulation-accuracy concern as the justification for why this page must exist at all.

## Page 2: Signals

### What The Page Does In Code

The `/signals` page is a research station for signal families before full strategy construction:

- the page shell and tab split are in `quant-backtesting-frontend/app/signals/page.tsx:12-124`
- the technical-analysis workflow uses `TechnicalAnalysisPanel` at `quant-backtesting-frontend/app/signals/page.tsx:80`
- the indicator drilldown workflow uses `IndicatorExplorer` at `quant-backtesting-frontend/app/signals/page.tsx:95`

On the backend, the page routes into `services/api/app/routers/strategy_signals.py`:

- family ensemble entry point: `_get_or_compute` at `services/api/app/routers/strategy_signals.py:151`
- family endpoint: `family_ensemble` at `services/api/app/routers/strategy_signals.py:199`
- variant detail endpoint: `variant_detail` at `services/api/app/routers/strategy_signals.py:375`
- variant backtest endpoint: `variant_backtest` at `services/api/app/routers/strategy_signals.py:639`
- regime endpoint: `regime_consensus` at `services/api/app/routers/strategy_signals.py:793`

The core engine implements a layered pipeline:

- candidate generation: `core/quant_core/signal_engine/candidates.py`
- walk-forward OOS scoring: `core/quant_core/signal_engine/oos_eval.py:216`
- robustness scoring: `core/quant_core/signal_engine/robustness.py:18`
- redundancy pruning: `core/quant_core/signal_engine/redundancy.py:14`
- family ensemble orchestration: `core/quant_core/signal_engine/ensemble.py:378`
- regime validation and weighting: `core/quant_core/signal_engine/regime.py:113` and `core/quant_core/signal_engine/regime.py:315`
- variant drilldown: `core/quant_core/signal_engine/variant_detail.py:123` and `core/quant_core/signal_engine/variant_detail.py:150`

### How It Applies de Prado

`Derived` in process, `Adapted` in implementation.

The strongest fit is Chapter 1's `"Feature Analysts"` station and the statement that such analysts are `"transforming raw data into informative signals"` and that those findings are `"not an investment strategy on [their] own"` (Chapter 1, PDF p.34). That is almost exactly what `/signals` is:

- it studies signal families before strategy assembly
- it exposes per-family and per-variant evidence rather than a full portfolio result
- it treats signals as reusable building blocks that can later feed strategy construction

de Prado also contrasts `"research through backtesting"` with `"feature importance analysis"` (Table 1.2, PDF p.40). The app does not literally implement chapter-8 feature importance methods, but it operationalizes the same warning by separating signal research from full strategy backtesting. In practical terms, the signal station asks:

- which variants survive OOS scrutiny?
- which variants are redundant?
- what does the current signal mean right now?

That is de Prado's epistemology even when the formulas are repo-specific.

### How It Applies Pardo

`Adapted`.

Pardo's process expects preliminary testing and disciplined optimization before live deployment. The signal engine inherits that discipline through rolling OOS windows and comparative variant evaluation. The candidate set is not accepted because it "looks good" on one chart; it must survive repeated OOS windows in `core/quant_core/signal_engine/oos_eval.py:216` and receive robustness scores in `core/quant_core/signal_engine/robustness.py:18`.

This is Pardo-like in spirit:

- evaluate many variants rather than bless the first plausible one
- compare parameterized versions systematically
- prefer robust survivors over isolated winners

### Why The Page Is Built This Way

The app deliberately keeps signal research separate from strategy design because the repo treats signal families as a pre-strategy research inventory. That reasoning comes straight from de Prado's separation between findings and investment strategies, and it prevents the user from conflating "interesting indicator behavior" with "ready-to-trade system."

The ensemble layer in `core/quant_core/signal_engine/ensemble.py` then turns surviving variants into a family score rather than a single best-variant dictatorship. That is a sensible extension of de Prado's ensemble thinking, but it is not copied from a single AFML recipe.

### Ensemble And Redundancy Logic

This is one of the most important `Adapted` and `Extension` areas in the whole app.

What the code does:

- candidate variants are generated family by family
- each variant gets rolling OOS evaluation
- robustness is scored
- highly correlated survivors are pruned by greedy correlation clustering in `core/quant_core/signal_engine/redundancy.py:14-90`
- remaining representatives are reliability-weighted into a family score in `core/quant_core/signal_engine/ensemble.py:48-80`

Why that fits the books:

- de Prado explicitly cares about ensembles and about avoiding naive feature/backtest habits, but the exact greedy redundancy reducer here is repo-specific.
- Pardo cares about robust parameter behavior, but he does not give this family-ensemble architecture.

So the right reading is:

- `Derived` from de Prado: the idea that research should produce reusable, testable findings rather than one lucky backtest.
- `Extension`: the exact representative-selection and weighted-family-combination algorithm.

### Regime Logic

`Extension`, with partial theoretical support.

The regime path in `core/quant_core/signal_engine/regime.py:113-366` validates whether family weighting improves OOS behavior under a Kaufman-efficiency-ratio regime split. That is consistent with both authors' interest in robustness under varying market conditions, but the precise regime-weighting implementation is a repo invention rather than a direct de Prado or Pardo transplant.

### Where It Diverges

This page diverges from both books in four important ways:

- It is mostly a classical TA engine, not an ML feature pipeline. The families are SMA, RSI, MACD, and OBV, not AFML labels, classifiers, or microstructure features.
- It does not implement de Prado's hallmark supervised-learning tools: triple barrier, meta-labeling, purged K-fold, CPCV, or feature-importance methods.
- It uses rolling OOS windows and robustness scoring, but not the more formal Pardo optimization framework that appears in `/backtest`.
- The UI includes interpretability features such as charts, indicator overlays, and variant drilldowns that are product choices, not book prescriptions.

### Bottom-Line Reading

`/signals` is best understood as a de Prado-style signal-research station implemented with classical TA families and app-specific robustness heuristics. It is theory-aligned in workflow much more than in literal formulas.

## Page 3: Strategy

### What The Page Does In Code

The `/strategy` page is where the app turns signal ideas into explicit, saved, reviewable strategy objects:

- search-param loading and saved-strategy focus are in `quant-backtesting-frontend/app/strategy/page.tsx:105-123`
- the handoff link into `/backtest` is in `quant-backtesting-frontend/app/strategy/page.tsx:146`
- direct-vs-WFO compatibility warnings are in `quant-backtesting-frontend/app/strategy/page.tsx:60-68`

The API side performs three jobs:

- review and readiness checking: `services/api/app/strategy_v2.py:670-716`
- strategy handoff serialization: `services/api/app/strategy_v2.py:719-740`
- persistence and handoff routing: `services/api/app/routers/strategy.py:829-1068`

The review layer explicitly blocks unsupported WFO constructs, including Option E and WFO-driven rule sizing, in `services/api/app/strategy_v2.py:596-604`. It also exposes a Pardo-flavored complexity warning through `pardo_df_ok` and `pardo_df_message` in `services/api/app/strategy_v2.py:700-710`.

### How It Applies Pardo

`Derived`.

Pardo says strategy development should proceed from `"formulation and precise specification"` through testing, optimization, WFO, and then trading (Chapter 3 overview, PDF p.44). That is the clearest description of what this page is doing. The page exists to force the user to produce:

- explicit signals
- explicit entry rules
- explicit exit rules
- explicit risk logic
- an explicit basket and capital structure

Only after that does the app allow the object to flow into backtesting via handoff.

This is why the review layer matters so much. The page is not just a UI editor. It is the formal-specification gate that Pardo insists on before meaningful evaluation.

### How It Applies de Prado

`Derived` at the architectural level.

de Prado's production-chain argument is that strategy formation should not collapse data handling, feature research, backtesting, and deployment into one person or one step. The strategy page plays the role of a synthesis station between signal research and backtest evaluation:

- it consumes signals and rules
- it serializes a canonical strategy object
- it does not itself claim performance validity

That separation is very de Prado even though the strategy schema is repo-specific.

### Why The Review Layer Exists

This is the most important reasoning step on the page.

Pardo's optimization chapters repeatedly emphasize limiting parameter freedom, choosing meaningful ranges, and avoiding excess degrees of freedom. The review layer turns that into operational constraints:

- count WFO parameters before launch: `services/api/app/strategy_v2.py:675-710`
- warn when the search space becomes too complex
- block constructs that the clean-slice WFO executor cannot faithfully test

The strongest direct book fit is Pardo's claim that one should keep the `"smallest number of optimizable parameters possible"` and that more parameters make overfitting more likely (Optimization chapter, PDF p.249). The app's `pardo_df_ok` flag is not a quoted Pardo formula, but it is a clear translation of his reasoning into a UI review signal.

### Strategy Handoff And Saved Objects

`Adapted`.

The handoff payload in `services/api/app/strategy_v2.py:719-740` exists because the app treats a strategy as a transportable contract between stations. That is much closer to de Prado's production-chain worldview than to the simpler "run one model and see" mentality both authors criticize.

The saved-strategy list and handoff endpoint in `services/api/app/routers/strategy.py:829-1068` mean the backtest station is not backtesting arbitrary page state; it is backtesting a persisted specification. That is exactly the kind of procedural rigor both books want, even if they do not describe it in REST terms.

### Sizing On The Strategy Page

`Adapted` and `Extension`.

The strategy API exposes Kelly-based sizing in `services/api/app/routers/strategy.py:754-795`, backed by `core/quant_core/strategy_plan/sizing.py`. This fits the broad spirit of both books:

- de Prado: sizing matters and bad sizing can ruin a good signal (Bet Sizing chapter, PDF p.168).
- Pardo: proper capitalization and performance profile matter (Chapter 2, PDF pp. 68-70).

But the shipped strategy-page sizing is not a direct implementation of de Prado's probabilistic sizing formulas. It is a more classical win-rate / win-loss-ratio Kelly ceiling plus portfolio-allocation logic. That makes it an app extension justified by the books, not copied from them.

### Where It Diverges

- The page's `pardo_df_ok <= 15 params` logic is a house rule, not a canonical Pardo threshold.
- Option E blocking in `services/api/app/strategy_v2.py:598` is an executor limitation, not a theoretical claim from either book.
- The page offers a `kelly_wfo` concept in the schema, but the fully closed feedback loop from WFO sizing back into the editable strategy object is still only partially surfaced in the four-page UX.

### Bottom-Line Reading

`/strategy` is the page where Pardo's demand for explicit formulation becomes product behavior. It is also the bridge that lets de Prado's separated stations communicate through a canonical object instead of ad hoc page state.

## Page 4: Backtest

### What The Page Does In Code

The `/backtest` page supports two distinct evaluation modes:

- direct backtest for a fixed parameterization
- async WFO run for optimization plus rolling OOS plus held-out test

Relevant frontend behavior:

- strategy preselection via `strategyId`: `quant-backtesting-frontend/app/backtest/page.tsx:382-412`
- run polling hooks: `quant-backtesting-frontend/hooks/use-api.ts:734-746`
- server-side WFO warning copy: `quant-backtesting-frontend/app/backtest/page.tsx:233`
- WFO run launch button and mode switch: `quant-backtesting-frontend/app/backtest/page.tsx:542-653`
- per-stock WFO result panels with WFE, robustness, winning config, final params, windows, and held-out test: `quant-backtesting-frontend/app/backtest/page.tsx:664-760`

Relevant backend/core path:

- run creation: `services/api/app/routers/strategy_backtest_runs.py:57-134`
- worker orchestration: `services/worker/tasks/strategy_backtest_runs.py:107-331`
- direct path: `core/quant_core/strategy_plan/backtest.py`
- WFO path: `core/quant_core/strategy_plan/wfo.py:387-833`
- portfolio aggregation over held-out tests: `core/quant_core/strategy_plan/wfo.py:859-910`

### Why There Are Two Modes

This split is theoretically correct.

Pardo treats historical simulation and optimization/WFO as related but distinct stages. The app reflects that distinction directly:

- direct mode = fixed specification historical simulation
- WFO mode = parameter search plus rolling out-of-sample validation

That is also why the strategy page warns that direct mode uses current seed values for WFO-marked fields (`quant-backtesting-frontend/app/strategy/page.tsx:60-68`). In other words: direct mode is intentionally not pretending to be the optimization engine.

### How It Applies Pardo

`Strongly Derived`.

This is the page where Pardo is most concretely implemented.

#### 1. Optimization framework

Pardo's optimization framework calls for:

- selecting parameters
- selecting scan ranges
- selecting data sample
- selecting objective functions
- evaluating optimization behavior

The code does exactly that:

- collect WFO dimensions from the strategy config: `core/quant_core/strategy_plan/wfo.py:104-131`
- build parameter tuples from scan ranges: `core/quant_core/strategy_plan/wfo.py:141-146`
- cap candidate explosion: `core/quant_core/strategy_plan/wfo.py:43-44`
- build WFO window configurations from IS/OOS ratios and minimum walk-forward counts: `core/quant_core/strategy_plan/wfo.py:275-302`

Pardo's point that optimization requires attention to parameter count, scan ranges, and representative data is directly recognizable here.

#### 2. PROM

This is one of the clearest direct implementations in the repo.

Pardo explicitly names `"Pessimistic return on margin"` and gives its pessimistic win/loss adjustment formula (Search/Judgment material, PDF pp. 238-239). The app's `compute_prom` in `core/quant_core/wfo/prom.py:25-44` reproduces that logic:

- reduce wins by `sqrt(n_wt)`
- increase losses by `sqrt(n_lt)`
- scale by capital

Then the WFO engine applies it to candidate selection inside the IS loop at `core/quant_core/strategy_plan/wfo.py:507`.

That is not just inspiration. It is a direct operational translation.

#### 3. Neighbor averaging and optimization profile

`Adapted`, but still Pardo-heavy.

The WFO engine smooths raw candidate scores with neighbor averaging and then evaluates optimization profile shape:

- one-dimensional smoothing: `core/quant_core/strategy_plan/wfo.py:527`
- n-dimensional smoothing: `core/quant_core/strategy_plan/wfo.py:533`
- profile evaluation: `core/quant_core/strategy_plan/wfo.py:536`

This matches Pardo's insistence that optimization should assess robustness, not merely pick the sharpest local winner. The code's exact smoothing/profile formulas are repo-specific, but the reason they exist is unmistakably Pardo-like: reward stable plateaus over brittle spikes.

#### 4. Walk-Forward Efficiency and robustness

This is another direct Pardo area.

Pardo's walk-forward chapters revolve around robustness and WFE. The app computes:

- WFE: `core/quant_core/strategy_plan/wfo.py:631`
- robustness ratio: `core/quant_core/strategy_plan/wfo.py:632`
- viability gate using WFE and profile checks: `core/quant_core/strategy_plan/wfo.py:639-644`

The UI then surfaces these metrics per stock in `quant-backtesting-frontend/app/backtest/page.tsx:724-740`.

This is the strongest example of the current four-page app taking Pardo's methodology and turning it into first-class product state.

#### 5. Held-out test period after WFO

`Derived` from Pardo's confidence/real-time-likelihood reasoning, with de Prado reinforcement.

After choosing the winning WFO configuration, the engine creates a final test slice from either an explicit `test_period_start` or the post-WFO remainder:

- test-period slice logic: `core/quant_core/strategy_plan/wfo.py:314-325`
- explicit config input: `core/quant_core/strategy_plan/wfo.py:414`
- winning configuration and final params: `core/quant_core/strategy_plan/wfo.py:700-708`
- final held-out result stored in the returned payload: `core/quant_core/strategy_plan/wfo.py:812`

This is consistent with Pardo's repeated focus on confidence, robustness, and likelihood of real-time performance, and also with de Prado's insistence that one historical path is not enough.

### How It Applies de Prado

`Derived`, but in narrower and more selective ways.

#### 1. Overfitting skepticism

de Prado attacks naive walk-forward complacency and stresses the `"probability of backtest overfitting"` (Chapter 1, PDF p.35) as well as the limitations of single historical paths (Chapter 12, PDF pp. 188-191). The app reflects this skepticism by:

- not stopping at one direct backtest
- exposing candidate count and WFO parameter count
- adding DSR to the final WFO result
- adding robustness overlays on held-out returns

#### 2. Deflated Sharpe ratio

This is the most direct de Prado implementation in the shipped backtest flow.

The WFO result computes DSR in:

- `core/quant_core/strategy_plan/wfo.py:766-768`
- using `core/quant_core/wfo/statistical.py:260-304`

That is a concrete response to de Prado's warning about backtest overfitting and multiple testing.

#### 3. Broader-than-historical stress logic

de Prado distinguishes the narrow walk-forward sense of backtesting from broader OOS scenario analysis (Chapter 12, PDF p.188). The shipped app partly follows that logic through block-bootstrap robustness bands over held-out returns:

- bootstrap entry point: `core/quant_core/strategy_plan/wfo.py:327-384`
- bootstrap engine: `core/quant_core/wfo/statistical.py:164-241`

This is not CPCV, but it does move beyond "one historical equity line."

### OOS-Derived Kelly Sizing

`Extension` with some book support.

The WFO engine computes trade stats from winning OOS windows and then computes Kelly:

- OOS trade stats: `core/quant_core/strategy_plan/wfo.py:764`
- Kelly estimate: `core/quant_core/strategy_plan/wfo.py:765`

The theoretical support is indirect:

- de Prado: sizing matters and belongs in the backtesting conversation.
- Pardo: capitalization and performance profile matter.

But the exact choice to derive Kelly from WFO OOS trades in this way is a repo-level extension. It is sensible, but it is not a direct book formula.

### Where It Diverges

This page has the most important divergences in the entire app.

#### 1. It does not implement de Prado's preferred CPCV path

de Prado explicitly argues that ordinary walk-forward is limited and promotes broader cross-validation approaches (Chapter 12, PDF pp. 188-191). The shipped four-page backtest flow still centers on WFO plus a held-out test, not purged/CPCV.

#### 2. The shipped robustness path is block bootstrap, not permutation

`core/quant_core/wfo/statistical.py:80-131` still contains `monte_carlo_permutation_test`, but the shipped WFO runner imports and uses `block_bootstrap_equity_paths` instead:

- import and use: `core/quant_core/strategy_plan/wfo.py:27`, `core/quant_core/strategy_plan/wfo.py:342`

So the live app has already diverged from some older documentation and from any interpretation that the current WFO validation is primarily permutation-based.

#### 3. The direct mode remains intentionally simpler

The direct path routes through legacy-config conversion and `run_strategy_plan_backtest`:

- legacy conversion: `services/api/app/strategy_v2.py:766-840`
- direct execution in worker: `services/worker/tasks/strategy_backtest_runs.py:258-279`

That means direct mode is useful for fixed-rule simulation, but it is not the place where the app claims to have performed full optimization-theory discipline.

### Bottom-Line Reading

`/backtest` is the app's clearest Pardo implementation and its clearest de Prado-overfitting checkpoint. If someone asked which page is most faithful to the books in operational terms, this is the answer.

## Cross-Cutting Theory Map

| App concept | Best source | Status in app | Why |
| --- | --- | --- | --- |
| Four-station separation | de Prado Chapter 1, PDF pp. 33-35 | `Derived` | Data, signals, strategy, backtest are separated as stations. |
| Strategy-development sequence | Pardo Chapter 3, PDF pp. 44-45 | `Derived` | Formulate, specify, test, WFO, then decide on use. |
| Signal research before strategy | de Prado Chapter 1, PDF p. 34 | `Derived` | `/signals` studies reusable findings before strategy packaging. |
| Fixed historical simulation | Pardo Chapter 6 framing, PDF p. 45 | `Derived` | Direct mode and direct executor. |
| Optimization framework | Pardo Chapter 10, PDF pp. 248-254 | `Derived` | Param collection, scan ranges, candidate loops, objective selection. |
| PROM | Pardo, PDF pp. 238-239 | `Derived` | `core/quant_core/wfo/prom.py`. |
| WFE and robustness | Pardo WFO chapters | `Derived` | `core/quant_core/strategy_plan/wfo.py:631-644`. |
| DSR / multiple-testing caution | de Prado Part 3 and Chapter 14 framing | `Derived` | `core/quant_core/wfo/statistical.py:260-304`. |
| Ensemble and redundancy reduction | de Prado ensemble mindset + repo invention | `Adapted` | Good theoretical fit, repo-specific mechanics. |
| Held-out test after WFO | Pardo confidence logic + de Prado OOS skepticism | `Adapted` | Practical extra confirmation stage. |
| OOS-derived Kelly | Both books justify sizing/capitalization concerns | `Extension` | Exact implementation is repo-specific. |

## Where The App Diverges

### Major Divergences From de Prado

- No triple-barrier labeling in the shipped four-page flow.
- No meta-labeling in the shipped four-page flow.
- No purged or combinatorial purged cross-validation in the live four-page path.
- No ML classifier stack driving signal generation or bet sizing.
- No fractional differentiation or event-bar pipeline behind the visible pages.

### Major Divergences From Pardo

- The signal page is a richer research workbench than Pardo's book directly describes.
- The app uses a modern API-worker-frontend architecture rather than a single platform script mentality.
- Neighbor smoothing, regime overlays, and some robustness heuristics are implementation inventions rather than canonical Pardo formulas.

### Internal Repo Uses Of The Books That Are More Rhetorical Than Literal

- `pardo_df_ok` is an interpretation of parameter-discipline, not a verbatim Pardo rule.
- "Kelly from WFO" is directionally consistent with both books, but the exact end-to-end product loop is still partly aspirational in the four-page UX.
- Some old docs implied a different robustness method than the current shipped block-bootstrap implementation.

## Book-To-App Appendix

### de Prado

Chapter 1, production chain, PDF pp. 33-35:

- `"data curators"` -> `/data`
- `"Feature Analysts"` -> `/signals`
- `"Backtesters"` -> `/backtest`
- meta-strategy factory logic -> the four-page architecture itself

Chapter 10, bet sizing, PDF pp. 168-169:

- sizing belongs after signal quality, not before it
- the app reflects this by keeping sizing in strategy/backtest rather than signal discovery

Chapter 12, backtesting through CV, PDF pp. 188-191:

- direct historical walk-forward is not enough on its own
- app response: WFO plus held-out test plus DSR plus bootstrap robustness
- divergence: no CPCV in shipped flow

Chapter 15, strategy risk, PDF p. 238:

- strategy evaluation must think in payout, hit-rate, and vulnerability terms
- app response: risk rules, drawdown, WFE, robustness, and OOS-derived Kelly

### Pardo

Chapter 3, development process, PDF pp. 44-45:

- formulate -> specify -> test -> WFO -> trade
- app mapping: `/signals` -> `/strategy` -> `/backtest`

Chapter 10, optimization, PDF pp. 248-254:

- choose parameters carefully
- keep scan ranges sensible
- avoid too many degrees of freedom
- use representative data with adequate trade samples
- app mapping: WFO param manifest, readiness checks, candidate-grid construction, configuration review

PROM material, PDF pp. 238-239:

- directly implemented in `core/quant_core/wfo/prom.py`

Confidence / performance-profile material, PDF pp. 68-73:

- strategy evaluation should lead to justified confidence, not hope
- app mapping: held-out summaries, stock-level window tables, robustness displays, and saved strategy review

## Limitations And Confidence

What I am confident about:

- The four-page architecture is genuinely more de Prado-shaped than most of the older docs suggest.
- The current WFO engine is genuinely more Pardo-faithful than the older direct-only narrative implied.
- PROM and WFE are not superficial references. They are real, active parts of the current WFO path.
- DSR is genuinely wired into the shipped WFO result.

What I am less confident about:

- Neither book is the sole intellectual source of the signal page. The classical TA literature is doing a lot of work there.
- Some strategy-page semantics around future `kelly_wfo` feedback are only partially visible in the current four-page UX.
- Because the request focused on the shipped four pages, this report does not attempt to audit every legacy or auxiliary module outside that product surface.

Final judgment:

- If you ask "Which book most explains the app architecture?", the answer is de Prado.
- If you ask "Which book most explains the backtest engine's actual workflow?", the answer is Pardo.
- If you ask "Does the current app literally implement AFML?", the answer is no.
- If you ask "Does the current app genuinely apply both authors in meaningful ways?", the answer is yes, but asymmetrically and with substantial repo-specific adaptation.
