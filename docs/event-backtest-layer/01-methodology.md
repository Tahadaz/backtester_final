# Event-Study Methodology — `core/quant_core/research/event_study.py`

New module, flat under `core/quant_core/research/` alongside the existing `alignment.py`, `cross_sectional.py`, `edge.py` (no subpackage — matches the existing convention; `research/factors/` is reserved for the macro-factor registry, not event studies).

## `EventStudyConfig`

```python
@dataclass(frozen=True)
class EventStudyConfig:
    estimation_window: int = 120       # trading sessions used to fit the benchmark model
    estimation_gap: int = 10           # sessions between estimation-window end and event day 0
    event_window: tuple[int, int] = (-5, 10)   # relative-day bounds, inclusive
    benchmark: str = "market_adjusted"  # "market_adjusted" | "market_model" | "mean_adjusted"
    min_estimation_obs: int = 60        # below this, market_model falls back to market_adjusted
    max_stale_fraction: float = 0.3     # fraction of stale bars in [estimation ∪ event] window that drops the event
    bootstrap_iters: int = 2000
```

All fields have defaults reflecting the numbers pre-registered in [04-multiple-testing.md](04-multiple-testing.md); callers must not silently override them per-run — any deviation from the frozen config is itself a new pre-registration entry, not a runtime knob.

**Timeline for one event** (session-index space, not calendar-day space — see the thin-trading section below for how session index 0 is chosen):

```
estimation window                    gap        event window
[-(gap+estimation_window), -gap) -> [-gap, 0) -> [event_window[0], event_window[1]]
                                                   ^ day 0 = event day (or its PIT-snapped session)
```

With defaults: estimation spans sessions `[-130, -10)` relative to day 0, a 10-session gap avoids event-window contamination of the benchmark fit, and the event window itself is `[-5, +10]`.

## `run_event_study`

```python
def run_event_study(
    events_df: pd.DataFrame,   # columns: symbol, event_date, sign? (±1, optional), event_id
    prices: dict[str, pd.DataFrame],   # symbol -> OHLCV (Close, Volume at minimum; Open if available)
    market: pd.Series,          # MASI index close, same calendar as `prices`
    config: EventStudyConfig = EventStudyConfig(),
) -> EventStudyResult:
    ...
```

- `events_df` is the canonical schema every adapter in [02-event-sources.md](02-event-sources.md) must produce: `symbol`, `event_date` (the PIT availability date, pre-snap), optional `sign` (±1; absent = unsigned/pooled), `event_id` (stable string, `f"{event_type}:{symbol}:{event_date.isoformat()}"` convention).
- `prices` is loaded once per symbol via the existing OHLCV loader (`load_ohlcv_for_symbol`, already used by `analytics.py`), not re-fetched per event.
- `market` is the MASI index series used by `market_adjusted` and `market_model` benchmarks.

### `EventStudyResult`

```python
@dataclass(frozen=True)
class EventStudyResult:
    ar: pd.DataFrame            # rows = event_id, columns = relative day (event_window[0]..event_window[1]), values = abnormal return
    car: pd.Series               # per-event cumulative abnormal return over the full event window, indexed by event_id
    caar: pd.Series              # mean AR at each relative day, indexed by relative day
    caar_cumulative: pd.Series   # cumulative sum of caar, indexed by relative day
    bmp_t: pd.Series             # BMP standardized t-stat per relative day (and one for the full-window CAR)
    bmp_p: pd.Series             # two-sided p-value from bmp_t
    bootstrap_ci: dict[str, tuple[float, float]]   # {"car_full_window": (lo, hi), ...} — block-bootstrap 95% CI
    n_used: int
    n_dropped: int
    drop_reasons: dict[str, int]  # {"insufficient_estimation_obs": k1, "stale_fraction_exceeded": k2, "no_price_history": k3, ...}
    sign_split_caar: dict[str, pd.Series]  # {"positive": caar_series, "negative": caar_series} when events_df has a sign column
```

### Benchmark models

| Benchmark | Formula | When used |
|---|---|---|
| `market_adjusted` (**default**) | `AR_t = r_i,t − r_MASI,t` (no estimation, no parameters) | Always safe; the default because MASI single-name estimation samples are frequently short or gappy (thin trading — see below), which makes OLS beta estimates unstable. No estimation window is even needed for this benchmark, but `estimation_window`/`gap` are still honored for reporting comparability across benchmarks. |
| `market_model` | OLS `r_i,t = α + β·r_MASI,t + ε_t` fit on the estimation window; `AR_t = r_i,t − (α̂ + β̂·r_MASI,t)` | Only when the estimation window yields `≥ min_estimation_obs` (60) **non-stale** return observations for that symbol. Below that, silently fall back to `market_adjusted` for that event and record it in `drop_reasons` only if the event itself is later dropped for a different reason — the benchmark fallback itself is not a drop, it is logged as `benchmark_used='market_adjusted_fallback'` per event in a diagnostics column. |
| `mean_adjusted` | `AR_t = r_i,t − mean(r_i, estimation window)` | Opt-in only (config override), for cases where no reliable market index alignment exists for the event's universe (e.g., a rate-sensitive basket rather than a single symbol); not used by default because it ignores market-wide moves that coincide with the event window. |

### Why BMP (Boehmer-Musumeci-Poulsen 1991) instead of a plain cross-sectional t-test

- A plain t-test on AR/CAR across events implicitly assumes each event's abnormal-return variance equals its (typically calm) estimation-window variance.
- Real events — earnings surprises, macro releases, geopolitical shocks — usually **increase** return variance around the event itself ("event-induced variance"). Using calm-period variance in the t-test denominator understates the true standard error and inflates significance (false positives).
- BMP fixes this in two steps:
  1. Standardize each event's AR by *that event's own* estimation-window standard deviation before cross-sectional averaging (so a noisy name cannot dominate the mean).
  2. Divide the cross-sectional mean of standardized residuals by their **cross-sectional** standard deviation on the event day itself — so any event-induced variance shows up in the denominator instead of being ignored.
- This is standard event-study practice precisely because it defends against the scenario this repo is in: thin MASI names, heteroskedastic returns, tiny event counts.
- The BMP t-stat is computed both per relative day (for the AAR curve) and for the full-window CAR (input to the promotion gate in [04-multiple-testing.md](04-multiple-testing.md)).

### Block bootstrap

In addition to the BMP asymptotic test, `run_event_study` computes a block-bootstrap CI on the full-window CAR:

1. Sort events by `event_date`; form contiguous blocks of consecutive events. Blocks — not individual events — are the resampling unit, to preserve residual cross-event correlation (macro/geopolitical events cluster in time far more than PEAD events).
2. Resample blocks with replacement until the original event count is matched; recompute the mean CAR. Repeat `bootstrap_iters` (2000) times.
3. Report the empirical 2.5/97.5 percentiles as `bootstrap_ci["car_full_window"]`.

This CI backs the promotion gate ("bootstrap CI excludes 0") independently of the BMP test's asymptotic assumptions — with n_events in the 30–60 range, agreement between the two is itself informative and disagreement is a red flag reported in the verdict artifact.

## Thin-trading handling (MASI-critical)

MASI names, especially outside the top-liquidity tier, trade thinly: many sessions have zero volume, and the closing price is mechanically carried forward unchanged by the exchange feed. Naive daily-return event studies on this market silently compute near-zero "abnormal returns" that are actually just missing trades, not evidence of no reaction.

**Stale bar** — a session is stale when either condition holds (each alone is sufficient):

- `Volume == 0`, or
- the close is unchanged for ≥ 3 consecutive bars (the whole unchanged run is stale, i.e. bars 2..k of a k-bar unchanged run with k ≥ 3).

**Trade-to-trade returns** — returns are computed only between consecutive *non-stale* bars:

- A return spanning a run of stale bars compounds across the gap: `r = close_t / close_{t-k} − 1`, where `t-k` is the last non-stale bar before `t` — **not** `close_t / close_{t-1}`.
- Rationale: naive daily returns manufacture a sequence of exact zeros during the stale run followed by one artificially large return when trading resumes; both distort AR estimates and the estimation-window variance that BMP divides by.
- Relative-day columns in the AR matrix are indexed by **traded sessions**, so a symbol's day +3 may be further away in calendar time than another symbol's — this is intended and is what makes CAAR comparable across liquidity tiers.

**Event-day snap** — day 0 is *not* the raw event/availability date:

1. Per the PIT 18:00 Africa/Casablanca rule ([`../alt-data-foundation/01-pit-event-store.md`](../alt-data-foundation/01-pit-event-store.md)), the availability timestamp resolves to calendar date D (or D+1 if at/after 18:00).
2. Day 0 then snaps forward to the **first traded (non-stale) session on or after D** — the first session where the stock has a real print.
3. This anchors the event window to when the market could plausibly have reacted, not to a stale carry-forward print. The snap distance (in sessions) is recorded per event for diagnostics.

**Drop rule**:

- For each event, compute the stale-bar fraction over `estimation_window ∪ event_window` (session-index space, post-snap).
- If the fraction `≥ max_stale_fraction` (0.3 default), the event is **dropped** and counted under `drop_reasons["stale_fraction_exceeded"]`.
- This is a hard cutoff, not a down-weighting: mixing heavily-stale and liquid events in one CAAR biases the pooled estimate toward whichever thin-trading artifact dominates the small sample.

## Test plan

- **Synthetic prices with injected known CAAR**: generate a market series plus N synthetic stock series where a known constant abnormal return is injected at day 0 (e.g., +2% for half the events, 0% for the control half); assert `run_event_study` recovers the injected CAAR within bootstrap CI and that BMP t-stat rejects the null for the treated half but not the control half.
- **Thin-trading fixtures**: synthetic price series with engineered runs of zero-volume/unchanged-close bars spanning the event window; assert (a) the day-0 snap lands on the correct first-traded session, (b) trade-to-trade returns compound correctly across the stale run instead of producing artificial zero-then-spike sequences, (c) events exceeding `max_stale_fraction` are dropped and appear in `drop_reasons`, not silently included.
- **Benchmark-equivalence checks**: with `market == stock` (degenerate case), `market_adjusted` AR must be ~0 at every relative day; with a flat/zero-variance market series, `market_model` OLS beta must be well-defined (or the estimator must fall back to `market_adjusted` without raising); `mean_adjusted` must reduce to `market_adjusted` when the estimation-window mean return equals the market return exactly (constructed fixture).
- Location: `core/tests/test_event_study.py`, mirroring the fixture style of existing `core/tests/test_wfo_engine.py` (synthetic arrays, no DB).
