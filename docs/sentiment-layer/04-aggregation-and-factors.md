# Aggregation and Factor Export (A5)

Turns per-article, per-subject scores (`alt_news_score`) into daily
per-subject indices (`alt_sentiment_daily`), then exports selected indices
as ordinary factor series so every existing IC/relevance/WFO tool in this
repo consumes them unchanged.

## Daily aggregate math

`core/quant_core/research/sentiment/aggregate.py::aggregate_subject_day(subject_type, subject_key, date) -> DailyAggregate`.

### PIT cutoff

An article's `published_at` is assigned to calendar day **D** if
`published_at < 18:00 Africa/Casablanca` on D, else assigned to **D+1**.
This is the same 18:00 cutoff rule used for every alt-data source in this
program — defined once in
[../alt-data-foundation/01-pit-event-store.md](../alt-data-foundation/01-pit-event-store.md)
(section: PIT join rule) and not restated here beyond this one-line
reminder, since every aggregate computed in this file depends on it.

### Per (date, subject) fields

For all `alt_news_score` rows whose parent `alt_news_item.published_at`
PIT-maps to date D and whose `(subject_type, subject_key)` matches:

| Field | Formula |
|---|---|
| `n_items` | count of distinct articles contributing at least one score row for this subject on D |
| `sent_mean` | unweighted mean of `sentiment` across contributing scores |
| `sent_weighted` | `Σ(sentiment_i · relevance_i · confidence_i) / Σ(relevance_i · confidence_i)` — a low-relevance or low-confidence score contributes little to the index even though it's still counted in `n_items` |
| `pos_share` | fraction of contributing scores with `sentiment > 0.1` |
| `neg_share` | fraction of contributing scores with `sentiment < -0.1` |
| `shock_z` | `(sent_weighted_D - mean(sent_weighted, trailing 60 sessions)) / std(sent_weighted, trailing 60 sessions)`, i.e. today's weighted sentiment expressed as a z-score against its own trailing 60-day distribution; `NaN` when fewer than 20 of the trailing 60 days have `n_items ≥ 1` (insufficient history to estimate a stable mean/std) |

The `0.1` pos/neg thresholds are a deadband around zero — scores near-zero
are "neutral," not weakly positive/negative, matching the deadband
convention already used elsewhere in this repo's regime/signal code (e.g.
avoids `pos_share + neg_share` summing to ~1.0 on genuinely mixed-neutral
days, which would misrepresent a quiet news day as split-decision).

`sent_weighted`, not `sent_mean`, is the series that gets exported as a
factor (below) — it's the one that down-weights noise by construction.
`sent_mean`, `pos_share`, `neg_share`, and `n_items` are retained in
`alt_sentiment_daily` for diagnostics/UI (Phase U1, out of scope here) but
are not independently exported as factor series.

### Recomputability

`alt_sentiment_daily` is a derived/recomputable table (per its schema note
in [../alt-data-foundation/01-pit-event-store.md](../alt-data-foundation/01-pit-event-store.md)):
`aggregate_subject_day` can always be re-run for any historical date from
`alt_news_score`, and does an `INSERT ... ON CONFLICT (date, subject_type,
subject_key) DO UPDATE` — a remap ([03-entity-mapping.md](03-entity-mapping.md))
or a re-scoring pass naturally propagates by simply re-running aggregation
over the affected date range, with no separate migration/backfill logic
needed for the aggregate layer itself.

## Derived factor-series export

Not every subject becomes a tradable-looking factor series — only subjects
with enough sustained coverage to produce a non-degenerate daily series.

### Canonical series

| Canonical ID | Subject | Coverage gate |
|---|---|---|
| `SENT_MA_MACRO` | `topic_region:macro:ma` | always exported (core Morocco macro sentiment index) |
| `SENT_MA_MARKETS` | `topic_region:markets:ma` | always exported |
| `SENT_GLOBAL_GEOPOL` | `topic_region:geopolitics:global` | always exported |
| `SENT_COMMODITIES` | `topic_region:commodities:global` | always exported |
| `SENT_SYM_{TICKER}` | `symbol:{TICKER}` | **only** where median weekly `n_items ≥ 3` over the trailing 26 weeks — most MASI tickers simply don't get 3 articles/week of coverage, and a sparse per-symbol series is noise, not signal; the coverage check re-evaluates on each export run so a symbol can gain or lose its series as coverage changes |

The four always-exported topic_region series are exported regardless of
volume because they're macro/market-wide indices aggregating across many
articles by construction (unlike a single-symbol series, which lives or
dies on that one company's press coverage).

### Export mechanics — reusing the `ingest_macro_series.py` pattern

`services/worker/tasks/export_sentiment_factors.py` calls
`aggregate.py` to build each eligible series as a `pd.Series` (date-indexed,
one value per session day using `sent_weighted`, forward-filled over
non-trading days only — never over missing-coverage trading days, which
stay `NaN`), then persists it through the **same three-step flow**
`services/worker/tasks/ingest_macro_series.py` already uses for yfinance
factors, reusing its helpers directly rather than re-implementing them:

1. `_merge(old, incoming)` — loads the existing parquet (if any) via
   `_try_load_existing_parquet(object_key)`, diffs overlap, appends new
   index entries, returns `(merged_df, summary)`. Applied unchanged: a
   sentiment series re-export is just another `_merge` call.
2. `_save_parquet(object_key, df)` — writes the merged frame back to S3.
   `object_key` is built with the existing
   `build_market_store_object_key(canonical_id, "1D")` from
   `core/quant_core/s3_keys.py` — sentiment series live in the exact same
   `market_data/symbols/{canonical_id}/ohlcv.parquet` layout as any other
   factor, with `Close` holding the `sent_weighted` value (matching the
   plan's convention that "derived daily series reuse the parquet
   convention so existing factor readers work unchanged" — no separate
   reader code path for sentiment factors anywhere downstream).
3. `_upsert_market_data_store(db, canonical_id, object_key, merged)` — same
   `market_data_store` upsert, with `source_provider` set to `'derived'`
   instead of `'yahoo'` for these rows (the one required literal change to
   that helper's call site — the SQL itself does not need to change since
   `source_provider` is already a bound parameter, not hardcoded).

### `macro_factor_meta` registration

Each canonical ID above gets one `macro_factor_meta` row with
`source_kind='derived'` and `yahoo_ticker=canonical_id` (satisfying the
`NOT NULL UNIQUE` constraint on that column —
`services/api/app/models.py:503` — without a real yfinance ticker existing;
this is the same self-referential placeholder convention the shared
foundation's F1 phase establishes for the macro-nowcast layer's derived
series). **`ingest_macro_series.py` itself must skip these rows** — the
foundation's F1 phase is responsible for adding the `source_kind` guard to
`ingest_all_macro_series()` (skip any row with `source_kind='derived'`
before calling `fetch_macro_series`, which would otherwise try to pull
`SENT_MA_MACRO` from yfinance and fail); this document assumes that guard
exists per
[../alt-data-foundation/01-pit-event-store.md](../alt-data-foundation/01-pit-event-store.md)
and does not re-specify it.

**Note for the implementer**: `core/quant_core/macro.py`'s existing
`MacroSeriesSpec` dataclass already has a `source: str = "yahoo"` field
(line ~42) — this is the *provider name* used elsewhere in `macro.py`, not
the DB-level `source_kind` fetch-routing flag described above and in the
plan. They are two different fields with similar names; do not conflate
them or overload the existing `source` field for this purpose. Add a
distinct `source_kind: str = "yahoo"` field to `MacroSeriesSpec` if
in-process specs (as opposed to the DB-backed `macro_factor_meta` table)
ever need the same skip-guard — most of A5's export path only touches the
DB table, so this is only relevant if a static-fallback `MacroSeriesSpec`
list entry is ever added for a derived series.

## Scheduler additions

Three new `ScheduleKind` values, extending the `Literal` in
`services/api/app/services/scheduler_registry.py:13-28` (currently ending
at `"pit_opportunity_materialization"`):

```python
ScheduleKind = Literal[
    ...,
    "pit_opportunity_materialization",
    "news_ingest",
    "news_sentiment_scoring",
    "sentiment_daily_aggregate",
]
```

New `ScheduleSpec` entries appended to the `SCHEDULE_SPECS` tuple
(`scheduler_registry.py:49-182`), following the existing
`id`/`label`/`kind`/`queue`/`cron`/`timezone`/`description` shape:

| id | kind | queue | cron | timezone | description |
|---|---|---|---|---|---|
| `news_ingest` | `news_ingest` | `market_refresh` | `*/30 * * * *` | `Africa/Casablanca` | Poll GDELT slices, Morocco scrapers, RSS feeds, and yfinance news for new items every 30 minutes. |
| `news_sentiment_scoring` | `news_sentiment_scoring` | `market_refresh` | `0 */2 * * *` | `Africa/Casablanca` | Score the next priority-ordered batch of unscored articles against the LLM provider registry. |
| `sentiment_daily_aggregate` | `sentiment_daily_aggregate` | `market_refresh` | `10 18 * * mon-fri` | `Africa/Casablanca` | Recompute daily sentiment aggregates and re-export SENT_* factor series after the 18:00 PIT cutoff. |

All three reuse the existing `market_refresh` queue — this ingestion/
scoring/aggregation workload does not warrant a dedicated RQ queue or a
deploy/infra change, matching every other addition in this program.

### Dispatch wiring

`services/worker/tasks/scheduler_dispatch.py::dispatch_schedule()`
(the `if/elif` chain at lines 105–136) gets three new branches, following
the exact shape of the existing `elif spec.kind == "factor_monitor":
result = _dispatch_factor_monitor()` entries:

```python
elif spec.kind == "news_ingest":
    result = _dispatch_news_ingest()
elif spec.kind == "news_sentiment_scoring":
    result = _dispatch_news_sentiment_scoring()
elif spec.kind == "sentiment_daily_aggregate":
    result = _dispatch_sentiment_daily_aggregate()
```

Each `_dispatch_*` helper follows the simplest existing pattern in that
file — `_dispatch_factor_monitor()` (`scheduler_dispatch.py:254-259`):
enqueue one job onto `_queue(settings.MARKET_REFRESH_QUEUE_NAME)` calling
the relevant task function with a `job_timeout`, return
`{"enqueued_jobs": 1, "rq_job_id": str(job.id)}`. `_dispatch_news_ingest()`
enqueues all configured GDELT/scraper/RSS/yfinance entry points as separate
jobs (one per source, so one slow/failing source doesn't block the others)
and sums `enqueued_jobs` across them, closer in shape to
`_dispatch_stale_wfo`'s multi-job-per-dispatch pattern
(`scheduler_dispatch.py:439-483`) than to the single-job helpers.

## Files

- `core/quant_core/research/sentiment/aggregate.py`
- `services/worker/tasks/aggregate_sentiment_daily.py` (writes
  `alt_sentiment_daily` rows)
- `services/worker/tasks/export_sentiment_factors.py` (writes the
  `SENT_*` parquet series + `macro_factor_meta` rows)
- Modified: `services/api/app/services/scheduler_registry.py` (three new
  `ScheduleKind` values + three new `ScheduleSpec` entries)
- Modified: `services/worker/tasks/scheduler_dispatch.py` (three new
  dispatch branches + three `_dispatch_*` helpers)

## Tests

`core/tests/test_sentiment_aggregate.py` — aggregate math (`sent_weighted`
formula, `shock_z` with/without sufficient trailing history, PIT-cutoff
day-assignment edge case at exactly 18:00). `services/worker/tests/test_export_sentiment_factors.py`
— coverage-gate logic for `SENT_SYM_*` series (median weekly `n_items ≥ 3`
threshold, series appearing/disappearing as coverage crosses the
threshold), and a regression test asserting `ingest_all_macro_series()`
never calls `fetch_macro_series` for a `source_kind='derived'` row (mirrors
the `test_macro_meta_source_kind.py` regression test already specified by
the shared foundation's F1 phase).
