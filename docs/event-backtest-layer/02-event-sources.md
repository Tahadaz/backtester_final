# Event-Source Adapters — `core/quant_core/research/event_sources.py`

New flat module, `core/quant_core/research/event_sources.py`. Four functions, one per event type, each returning the canonical events DataFrame consumed by `run_event_study` (see [01-methodology.md](01-methodology.md)): columns `symbol`, `event_date`, `sign` (optional, ±1), `event_id`.

```python
def pead_events(db: Session, *, event_types: tuple[str, ...] = ("earnings", "dividend"), as_of: date | None = None) -> pd.DataFrame: ...
def macro_release_events(db: Session, *, series_ids: tuple[str, ...], min_abs_z: float = 0.5, as_of: date | None = None) -> pd.DataFrame: ...
def sentiment_shock_events(db: Session, *, subject_type: str, min_abs_shock_z: float = 2.0, min_n_items: int = 5, as_of: date | None = None) -> pd.DataFrame: ...
def geopolitical_events(db: Session, *, cameo_roots: tuple[int, ...] = (14, 15, 16, 17, 18, 19, 20), max_goldstein: float = -5.0, as_of: date | None = None) -> pd.DataFrame: ...
```

Every adapter accepts `as_of` so historical replays can be rebuilt with only the data that would have been visible at that date (research-mode PIT discipline), defaulting to "everything available now" for live use.

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

**Source**: `macro_release ⋈ nowcast_value` (both tables defined in macro-nowcast-layer's Phase B / the shared PIT event store — see [`../alt-data-foundation/01-pit-event-store.md`](../alt-data-foundation/01-pit-event-store.md) for DDL; not yet present in `models.py` as of this writing, since Plan B has not shipped). Join key: `series_id`, matching `macro_release.period` to the most recent `nowcast_value.target_period == period` with `nowcast_value.as_of_date < macro_release.release_time` (PIT — the nowcast used to compute the surprise must have been made *before* the release, never using the release itself as an input).

- `surprise = macro_release.actual_value − nowcast_value.value`; standardize by the nowcast's own reported `std` (or an expanding realized-surprise std if `std` is null) to get `surprise_z`.
- Filter `abs(surprise_z) >= min_abs_z` (0.5 default).
- `sign = sign(surprise_z)`.
- **Universe**: this adapter does not take a `symbol` from the release itself (macro releases are not symbol-scoped) — it fans one release event out to every symbol in the configured universe: rate-sensitive baskets (banks, real estate, insurance — the same channel tags used by `FactorSignalSpec.channel_filter` in `core/quant_core/research/factors/signals.py`) plus MASI itself as an index-level event. `event_id = f"macro:{series_id}:{period}:{symbol}"`.
- Depends on macro-nowcast-layer **B5** (surprise engine) existing — before that, `nowcast_value` has no rows and this adapter returns an empty frame (not an error), so C2/C3/C4 development is not blocked, only this one source's live data is.

## 3. Sentiment shock events

**Source**: `alt_sentiment_daily` (shared PIT event store; not yet present as of this writing, ships with sentiment-layer **A5**). Filter `abs(shock_z) >= min_abs_shock_z` (2.0 default) **and** `n_items >= min_n_items` (5 default) — the `n_items` floor exists because `shock_z` on a 1–2 article day is noise, not a shock, regardless of its magnitude.

- `subject_type IN ('symbol', 'topic_region')`. When `subject_type='symbol'`, `subject_key` is the MASI ticker directly (per-symbol shock). When `subject_type='topic_region'` (e.g. `subject_key='macro:ma'`), the adapter fans the event out to the same rate-sensitive-basket + MASI universe used by the macro-release adapter, since an index-level sentiment shock is not symbol-specific.
- `sign = sign(shock_z)`.
- `event_id = f"sentiment:{subject_type}:{subject_key}:{date.isoformat()}"`.
- Depends on sentiment-layer **A5**; empty frame until then.

## 4. Geopolitical events

**Source**: GDELT Events 2.0 (`fetch_gdelt_events_window()`, delivered by sentiment-layer **A1** for Plan C's use — see `../sentiment-layer/01-data-sources.md`), not the GDELT DOC/news API used elsewhere in Plan A.

- Filter: CAMEO event root code `IN (14, 15, 16, 17, 18, 19, 20)` (Protest, Coerce, Assault, Fight, Use unconventional mass violence, and the two "engage in..." roots bordering conflict — i.e. the CAMEO "conflict" quad, roots 14–20 per the standard CAMEO/Goldstein taxonomy) **and** `Goldstein <= -5.0` (materially escalatory on the Goldstein scale, which runs roughly −10..+10). `GEO = 'MO'` (Morocco-located events) **or** a curated global-systemic actor list (major-power conflict, oil-chokepoint disruption — the same list used to scope the GDELT global slice in `../sentiment-layer/01-data-sources.md`).
- **Dedup**: at most 1 event per calendar day per bucket (Morocco-local vs. global-systemic are separate buckets) — GDELT emits many near-duplicate rows for the same real-world event across sources; keep the most-negative-Goldstein row of the day as the representative.
- **Sign**: always `-1` (unsigned risk-off assumption — this event type has no notion of a "positive" geopolitical shock at these CAMEO/Goldstein thresholds by construction).
- **Universe fan-out**: same rate-sensitive/MASI pattern as macro and sentiment adapters for Morocco-local events; MASI-only for global-systemic events (no plausible single-sector channel).
- `event_id = f"geo:{bucket}:{date.isoformat()}"`.
- Depends on sentiment-layer **A1** (GDELT connector must exist and expose the Events export, not just the DOC API); empty frame until then.

## PIT snapping — tested per adapter

Every adapter's `event_date` is the **availability** timestamp before the 18:00 Africa/Casablanca snap rule, exactly as for the shared PIT store: `published_at`/`release_time`/`as_of_date`/GDELT event date `< 18:00` → assigned to that day, else day+1. The snap-to-day-0 (first *traded* session on/after this date) happens inside `run_event_study`, not in the adapters — adapters emit the raw availability date, `event_study.py` owns the thin-trading-aware snap (see [01-methodology.md](01-methodology.md)). Each adapter's test suite (`core/tests/test_event_sources.py`) includes a fixture asserting the pre-snap `event_date` is computed correctly from a raw timestamp straddling 18:00, independent of whatever `run_event_study` later does with it — this keeps the PIT-cutoff logic and the thin-trading snap logic independently testable and not conflated.
