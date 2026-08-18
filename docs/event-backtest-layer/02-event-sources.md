# Event-Source Adapters — `core/quant_core/research/event_sources.py`

New flat module, `core/quant_core/research/event_sources.py`. Four functions, one per event type, each returning the canonical events DataFrame consumed by `run_event_study` (see [01-methodology.md](01-methodology.md)): columns `symbol`, `event_date`, `sign` (optional, ±1), `event_id`.

```python
def pead_events(db: Session, *, event_types: tuple[str, ...] = ("earnings", "dividend"), as_of: date | None = None) -> pd.DataFrame: ...
def macro_release_events(db: Session, *, series_ids: tuple[str, ...], min_abs_z: float = 0.5, as_of: date | None = None) -> pd.DataFrame: ...
def sentiment_shock_events(db: Session, *, subject_type: str, min_abs_shock_z: float = 2.0, min_n_items: int = 5, as_of: date | None = None) -> pd.DataFrame: ...
def geopolitical_events(db: Session, *, cameo_roots: tuple[int, ...] = (14, 15, 16, 17, 18, 19, 20), max_goldstein: float = -5.0, as_of: date | None = None) -> pd.DataFrame: ...
```

Every adapter accepts `as_of` so historical replays can be rebuilt with only the data that would have been visible at that date (research-mode PIT discipline), defaulting to "everything available now" for live use.

**Canonical output schema** (enforced by a shared `_validate_events_frame()` helper every adapter calls before returning):

| Column | Type | Semantics |
|---|---|---|
| `symbol` | str | MASI ticker the event applies to (post fan-out for non-symbol-scoped sources) |
| `event_date` | date | PIT availability date, after the 18:00 rule, **before** the trading-day snap |
| `sign` | float, nullable | `+1` / `-1`; `NaN` = unsigned/pooled |
| `event_id` | str | Stable, unique; conventions listed per adapter below |

An adapter with no available upstream data returns an **empty DataFrame with exactly these columns** — never `None`, never an exception — so downstream code (C3 runner, C4 suite) needs no per-source special-casing.

## 1. PEAD / company events

**Source table**: `FundamentalCatalyst` (`services/api/app/models.py:1061`, verified live columns):

```python
id, symbol, event_type, event_date, event_date_confidence, impact_tier,
expected_direction, title, notes, source, source_payload_json,
created_at, updated_at, is_active, superseded_by_id
```

`event_type` CHECK constraint: `'earnings','dividend','ex_dividend','agm','guidance','regulatory','product','m_and_a','split','other'`. `event_date_confidence` CHECK constraint: `'confirmed','estimated','rumour'`. `expected_direction` (nullable) CHECK: `'positive','negative','neutral'`.

**Important correction vs. the original plan sketch**: the plan assumed a *second*, independent source — "earnings-publication dates from the fundamentals PIT layer." Reading `core/quant_core/fundamentals/catalysts.py` shows this does not exist as a separate source. `catalysts.py::normalize_yfinance_calendar(symbol, calendar, dividends)` is the **only** producer of `FundamentalCatalyst` rows today, invoked by `services/worker/tasks/refresh_fundamental_catalysts.py::refresh_fundamental_catalysts()`. It emits:

- `event_type='earnings'` rows from `yfinance`'s `Ticker.calendar` — **always** `event_date_confidence='estimated'`. There is no code path that ever flips an earnings row to `'confirmed'`; `yfinance`'s calendar field is inherently forward-looking (next expected report date) and is never retroactively corrected once the date passes.
- `event_type='dividend'` rows from `Ticker.dividends` (last 8 payments) — always `event_date_confidence='confirmed'`, `expected_direction='neutral'`.

**Consequence for the adapter**: filtering to `event_date_confidence='confirmed'` only, as the plan sketch implied, would **silently drop every earnings event** and leave PEAD running on dividends alone — dividends are a much weaker post-announcement-drift candidate than earnings. `pead_events()` must instead:

1. Filter `event_type IN ('earnings', 'dividend')` and `is_active = true` (drop superseded rows — `superseded_by_id IS NULL` rows only, per the supersede idiom in `refresh_fundamental_catalysts.py::_upsert_catalyst`).
2. For `event_type='dividend'`: require `event_date_confidence='confirmed'` (this is always true given the ingestion path, but assert it — a future ingestion source could violate it).
3. For `event_type='earnings'`: **do not** filter on `event_date_confidence` (it is always `'estimated'`); instead require `event_date <= as_of` (or `<= today` for live use) so only earnings dates that have **already occurred** are used as PEAD events — a future/scheduled earnings date is not a historical event and must never enter `run_event_study`. This `event_date <= as_of` guard is the real PIT control for this source, replacing the confidence-based filter the original sketch assumed.
4. `sign`: derive from `expected_direction` where present (`'positive'` → `+1`, `'negative'` → `-1`, `'neutral'`/absent → unsigned, omit the `sign` column value i.e. `NaN`) — in practice this is populated for dividends (`'neutral'`) and essentially never for yfinance-sourced earnings rows (`expected_direction` is `NULL` there), so PEAD events are predominantly **unsigned** at v1; sign-split CAAR (pooled positive/negative) is not meaningful until a real surprise-direction signal is wired in (out of scope for C2 — flagged, not solved, here).
5. `event_id = f"pead:{symbol}:{event_type}:{event_date.isoformat()}"`.

This is documented explicitly so the C2 implementer does not spend time hunting for a second earnings-date source that does not exist — `FundamentalCatalyst` populated via `catalysts.py`/`refresh_fundamental_catalysts.py` is the complete PEAD input.

## 2. Macro release events

**Source**: `macro_release ⋈ nowcast_value` — both tables are defined in the shared PIT event store ([`../alt-data-foundation/01-pit-event-store.md`](../alt-data-foundation/01-pit-event-store.md) for DDL) and populated by macro-nowcast-layer phases B2/B3/B5. They are **not yet present in `services/api/app/models.py`** as of this writing (Plan B has not shipped); the adapter is written against the F1 schema.

**Join rule (PIT-critical)**:

- Join key `series_id`; match `macro_release.period` to `nowcast_value.target_period == period`.
- Of the matching nowcasts, take the most recent one with `nowcast_value.as_of_date < macro_release.release_time` — the nowcast used to compute the surprise must have been produced *before* the release, never using the release itself as an input.
- Only `macro_release.status = 'released'` rows qualify (never `'scheduled'`); on revisions, use the **first** vintage (`min(vintage)`) — the market reacted to the initial print, not the revised history.

**Surprise and filter**:

- `surprise = macro_release.actual_value − nowcast_value.value`.
- Standardize by the nowcast's own reported `std`; if `std` is null, fall back to an expanding std of realized surprises for that `series_id`. Result: `surprise_z`.
- Keep only `abs(surprise_z) >= min_abs_z` (0.5 default); `sign = sign(surprise_z)`.

**Universe fan-out**: macro releases are not symbol-scoped, so one release event fans out to every symbol in the configured universe — rate-sensitive baskets (banks, real estate, insurance; the same channel tags used by `FactorSignalSpec.channel_filter` in `core/quant_core/research/factors/signals.py`) plus MASI itself as an index-level event. `event_id = f"macro:{series_id}:{period}:{symbol}"`.

**Dependency**: macro-nowcast-layer **B5** (surprise engine). Before B5 lands, `nowcast_value` has no rows and this adapter returns a schema-correct empty frame (not an error) — C2/C3/C4 development is not blocked, only this source's live data is.

## 3. Sentiment shock events

**Source**: `alt_sentiment_daily` (shared PIT event store; not yet present in `models.py` as of this writing — ships with sentiment-layer **A5**, which computes `shock_z` as the z-score of the day's weighted sentiment vs. its trailing 60-day window, see `../sentiment-layer/04-aggregation-and-factors.md`).

**Filters** (conjunctive):

- `abs(shock_z) >= min_abs_shock_z` (2.0 default) — a genuine two-sigma sentiment day, not routine flow;
- `n_items >= min_n_items` (5 default) — the floor exists because `shock_z` on a 1–2 article day is noise, not a shock, regardless of magnitude.

**Subject handling**:

- `subject_type='symbol'`: `subject_key` is the MASI ticker directly — a per-symbol shock, no fan-out.
- `subject_type='topic_region'` (e.g. `subject_key='macro:ma'`): index-level shock, fanned out to the same rate-sensitive-basket + MASI universe as the macro-release adapter.
- `sign = sign(shock_z)`; `event_id = f"sentiment:{subject_type}:{subject_key}:{date.isoformat()}"`.

**PIT grade caveat**: sentiment aggregates built from LLM scores over pre-training-cutoff text carry `pit_grade='upper_bound'` (see [`../alt-data-foundation/00-overview.md`](../alt-data-foundation/00-overview.md#research-findings-baked-into-the-design)). The adapter propagates the worst `pit_grade` among contributing rows into the events frame as a diagnostic column, and the C4 verdict artifact labels any cell whose events are majority-upper-bound accordingly — such cells can never clear promotion, matching Plan A's rule that only live-collected scores are promotion-eligible.

**Dependency**: sentiment-layer **A5**; schema-correct empty frame until then.

## 4. Geopolitical events

**Source**: GDELT Events 2.0 via `fetch_gdelt_events_window()`, delivered by sentiment-layer **A1** for Plan C's use (see `../sentiment-layer/01-data-sources.md`). Note this is the Events **CSV export**, not the GDELT DOC/news API used elsewhere in Plan A — the DOC API has no CAMEO/Goldstein fields.

**Filters** (all conjunctive):

| Filter | Value | Rationale |
|---|---|---|
| CAMEO event root code | `IN (14, 15, 16, 17, 18, 19, 20)` | The conflict end of the CAMEO taxonomy: Protest (14), Exhibit force posture (15), Reduce relations (16), Coerce (17), Assault (18), Fight (19), Use unconventional mass violence (20) |
| Goldstein score | `<= -5.0` | Materially escalatory on the −10..+10 Goldstein scale; screens out routine diplomatic friction |
| Geography | `GEO = 'MO'` (Morocco-located) **or** curated global-systemic actor list | Global-systemic = major-power conflict, oil-chokepoint disruption — the same list scoping the GDELT global slice in `../sentiment-layer/01-data-sources.md` |

**Dedup**: at most 1 event per calendar day per bucket (Morocco-local vs. global-systemic are separate buckets). GDELT emits many near-duplicate rows for the same real-world event across news sources; keep the most-negative-Goldstein row of the day as the representative.

**Sign**: always `-1` — unsigned risk-off assumption. By construction there is no "positive geopolitical shock" at these CAMEO/Goldstein thresholds.

**Universe fan-out**: Morocco-local events fan out to the rate-sensitive baskets + MASI (same pattern as adapters 2–3); global-systemic events map to MASI only (no plausible single-sector channel). `event_id = f"geo:{bucket}:{date.isoformat()}"`.

**Dependency**: sentiment-layer **A1** — the GDELT connector must exist and expose the Events export, not just the DOC API. Schema-correct empty frame until then.

## PIT snapping — tested per adapter

Division of responsibility between adapters and the engine:

- **Adapters own the 18:00 rule**: each adapter's `event_date` is the availability date after applying the 18:00 Africa/Casablanca cutoff, exactly as for the shared PIT store — availability timestamp (`published_at` / `release_time` / `as_of_date` / GDELT event date) before 18:00 → assigned to that day, at/after 18:00 → next day.
- **`event_study.py` owns the trading snap**: the snap of day 0 to the first *traded* (non-stale) session on/after `event_date` happens inside `run_event_study`, never in the adapters (see [01-methodology.md](01-methodology.md)). Adapters emit calendar dates; the engine maps them to session indices.

Each adapter's test suite (`core/tests/test_event_sources.py`) includes a fixture asserting the pre-snap `event_date` is computed correctly from a raw timestamp straddling 18:00 — one case at 17:59, one at 18:00 — independent of whatever `run_event_study` later does with it. This keeps the PIT-cutoff logic and the thin-trading snap logic independently testable and never conflated.
