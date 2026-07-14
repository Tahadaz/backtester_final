# Multiple-Testing Policy — `core/quant_core/research/event_study_registry.py`

New flat module, `core/quant_core/research/event_study_registry.py`. Owns the **pre-registered, frozen grid** of event studies this layer is allowed to run, and the FDR/promotion policy applied to their results.

## Why pre-registration matters here specifically

Several of this layer's event types are structurally tiny samples: roughly 48 BAM policy meetings per decade (macro release events on `BAM_POLICY_RATE`), a bounded number of Morocco-relevant geopolitical shocks passing the Goldstein ≤ −5 filter, and PEAD events limited to whatever subset of MASI names has reliable earnings-date coverage. With `event_type × window × benchmark` combinations multiplying out, an unconstrained researcher testing many window/benchmark choices against a handful of dozens of events will find a "significant" CAAR somewhere by chance alone with high probability — this is the exact failure mode the rest of the repo already defends against for macro factors (`docs/factor-layer/11-pre-registration.md`) and is documented as risk #4 in [`../alt-data-foundation/00-overview.md`](../alt-data-foundation/00-overview.md#top-5-risks--mitigations). The discipline is identical here: decide the full grid once, before looking at results, hash it so it cannot be quietly edited after an unfavorable run, and apply FDR control across the whole grid rather than picking the best-looking cell.

## The frozen grid

Enumerated once as a module-level constant, hashed at import time (`hashlib.sha256` over the sorted tuple representation) so any accidental edit is detectable in a diff review and any code that reads the registry can assert the hash it expects:

```python
EVENT_STUDY_WINDOWS: tuple[tuple[int, int], ...] = ((-1, 1), (0, 3), (0, 10), (0, 20))
EVENT_STUDY_BENCHMARKS: tuple[str, ...] = ("market_adjusted", "market_model", "mean_adjusted")
EVENT_STUDY_TYPES: tuple[str, ...] = ("pead_earnings", "pead_dividend", "macro_release", "sentiment_shock", "geopolitical")

REGISTERED_GRID: tuple[EventStudyCell, ...] = tuple(
    EventStudyCell(event_type=t, window=w, benchmark=b)
    for t in EVENT_STUDY_TYPES for w in EVENT_STUDY_WINDOWS for b in EVENT_STUDY_BENCHMARKS
)  # 5 * 4 * 3 = 60 cells

REGISTERED_GRID_HASH: str = _hash_grid(REGISTERED_GRID)
```

`pead_earnings` and `pead_dividend` are separate grid entries (not pooled) because they are economically distinct hypotheses (post-earnings-announcement drift vs. ex-dividend price behavior) with different expected effect sizes and directions — pooling them would itself be a form of undisclosed researcher discretion.

Extending the grid (new event type, new window, new benchmark) is a deliberate, reviewed change to this file, not a runtime parameter — any such change is a new pre-registration and must be called out in the PR/commit description, exactly as `docs/factor-layer/11-pre-registration.md` requires for factor-layer changes.

## FDR policy

Two BH-FDR passes, using the existing `core/quant_core/research/stats/fdr.py::benjamini_hochberg(p_values, q)` and `bh_adjusted_pvalues(p_values)` (both verified present, signatures unchanged — no new FDR math needed, this layer is pure reuse):

1. **Within event-type family, q = 0.10** (research display): for each `event_type`, gather the p-values of its `4 windows × 3 benchmarks = 12` cells, run `benjamini_hochberg(p_values, q=0.10)`. This is the looser, exploratory threshold shown on the `/sentiment-events` "Études d'événements" panel for every event type, including ones not yet promotion-eligible — it lets a researcher see "this looks directionally interesting" without claiming it clears the bar to trade.
2. **Across the full grid, q = 0.05** (promotion candidates): run `benjamini_hochberg(p_values, q=0.05)` once over all 60 cells' p-values together. Only cells rejected at this stricter, grid-wide level are eligible to proceed to the promotion gate below. This is deliberately stricter than the per-family pass — a cell can look "significant" within its own family's looser correction and still fail the grid-wide one, and only the grid-wide pass has any bearing on promotion.

The UI **always** shows all three of: raw p-value, BH-adjusted q-value (both passes, labeled separately), and `n_events` for every cell — never just a pass/fail badge — so a viewer can see how thin a "significant" result's underlying sample actually is (this mirrors the existing factor-layer convention of never hiding `n_obs` behind a significance star).

## Promotion gates (all required)

A `(event_type, window, benchmark)` cell is promotion-eligible only if **every** condition holds:

1. `n_events >= 30` — matches the factor-layer's existing minimum-sample convention; below this, BMP asymptotics and the block-bootstrap CI are both unreliable regardless of how small the p-value looks.
2. Post-FDR **grid-wide** `q <= 0.05` (from the across-grid BH pass above — the within-family q=0.10 pass alone is never sufficient for promotion).
3. Block-bootstrap CI (`EventStudyResult.bootstrap_ci["car_full_window"]`) **excludes 0**.
4. Event-conditioned WFO OOS Sharpe `> 0`, net of **25 bps/side** transaction cost (`EngineResult` from the WFO path in [03-strategy-runner.md](03-strategy-runner.md), with `cost_bps` fixed at the promotion-gate value regardless of whatever `cost_bps` a research UI run used — the promotion check re-runs, or reads a cached run tagged, at exactly 25 bps/side so the gate is not gameable by cost-parameter selection).
5. CAAR **same sign** in both halves of the sample (split events chronologically at the median event date; recompute CAAR on each half independently; both halves' full-window CAR must agree in sign — this is a crude but robust regime-stability check that a result is not driven entirely by one cluster of events, e.g. a single crisis period for geopolitical events).

Failing any gate keeps the cell at "research only" on `/sentiment-events`, per the shared validation policy in [`../alt-data-foundation/02-validation-policy.md`](../alt-data-foundation/02-validation-policy.md). Nothing from this layer reaches the Signal/Dashboard pages regardless of gate status — Plan C's promotion ceiling is the research tab, matching the Plan A/B posture; wiring a promoted event-conditioned signal into the production Signal Engine is explicitly out of scope for C1–C4 and would be a separate, later initiative.

## Weekly scheduled suite

New `ScheduleKind` literal `"event_study_refresh"` added to the `Literal[...]` list in `services/api/app/services/scheduler_registry.py` (currently: `market_refresh`, `live_quote_refresh`, `dashboard_snapshot`, `factor_monitor`, `factor_recalibration`, `fundamental_beta_refresh`, `fundamental_cross_section`, `fundamental_refresh`, `value_strategy_refresh`, `wfo_dispatch`, `signal_backtest_dispatch`, `signal_best_evidence_snapshot`, `signal_history_dispatch`, `pit_opportunity_materialization` — verified live), plus a new `ScheduleSpec` entry:

```python
ScheduleSpec(
    id="weekly_event_study_refresh",
    label="Weekly event-study suite",
    kind="event_study_refresh",
    queue="market_refresh",   # reuse existing queue, no new deploy/worker-topology change
    cron="0 6 * * sat",       # Saturdays, no trading-session pressure
    timezone="Africa/Casablanca",
    description="Re-run the full pre-registered event-study grid and refresh promotion verdicts.",
)
```

Dispatch branch added to `services/worker/tasks/scheduler_dispatch.py` alongside the existing per-kind branches. The task re-runs `run_event_study` for every `REGISTERED_GRID` cell against current data, recomputes both FDR passes, re-evaluates promotion gates, and writes a verdict artifact to S3 (`alt_data/studies/event_studies/{grid_hash}/{run_date}.json`, following the same `alt_data/studies/...` convention used by the sentiment IC study and nowcast OOS report — see [`../alt-data-foundation/00-overview.md`](../alt-data-foundation/00-overview.md#verification-model)). Saturday (no trading session, all week's events already settled) avoids competing with weekday market-hours/close-of-day jobs already on the `market_refresh` queue.
