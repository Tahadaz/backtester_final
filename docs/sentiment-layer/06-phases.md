# Phases A1–A6: Work Packages

Each phase below is a self-contained work package for an implementation
subagent: goal, files, reuse, tests, E2E verification, done-criteria. All
phases assume the shared foundation's F1 (PIT event store —
[../alt-data-foundation/01-pit-event-store.md](../alt-data-foundation/01-pit-event-store.md))
has landed: the `alt_news_item` / `alt_news_score` / `alt_sentiment_daily`
tables, `core/quant_core/newsflow/domain.py` (`NewsItemRecord`,
`normalize_content_hash()`), and `build_news_raw_object_key()` in
`core/quant_core/s3_keys.py` all exist before A1 starts.

## Dependency ordering

```
F1 ──► A1 (GDELT) ──┐
   └─► A2 (scrapers)┴─► A4 (entity map) ──► A3 (LLM scoring) ──► A5 (aggregates) ──► A6 (gates)
```

- A1 ∥ A2 — fully parallel, independent sources into one persist funnel.
- A4 needs ingested articles (either source suffices) but no scores.
- A3 needs A4 (batch priority reads `alt_news_item.symbols`) and at least
  A1's data; it does not wait for A2.
- A5 needs A3 (scores to aggregate); A6 needs A5 (series to test).

E2E verification for every phase runs on the docker compose stack
(`infra/docker-compose.yml`).

---

## A1 — GDELT connector + backfill

**Goal**: GDELT DOC 2.0 articles (Morocco + global slices) and Events 2.0
geopolitical events ingested live and backfilled 2019→present, with V2Tone
captured. Full spec: [01-data-sources.md](01-data-sources.md#a1--gdelt).

**Files to create**
- `core/quant_core/newsflow/gdelt_client.py`
- `scripts/probe_gdelt_volume.py` (run its report before finalizing filters)
- `services/worker/tasks/ingest_news_gdelt.py`
- `core/quant_core/newsflow/persist.py` (`persist_items()` funnel — created
  here in A1 since it's the first writer; A2 reuses it)
- `core/tests/test_gdelt_client.py`, `core/tests/fixtures/news/gdelt_*.json`

**Files to modify** — none (F1 already added the tables/models/keys).

**Existing code to reuse**
- Constructor/retry pattern from
  `core/quant_core/fundamentals/providers/stockanalysis_provider.py`
  (`timeout_seconds`/`retries`/`sleep` ctor, `sleep(2**attempt)` backoff).
- `core/quant_core/newsflow/domain.py` (F1) for `NewsItemRecord` +
  `normalize_content_hash()`.
- `core/quant_core/s3_keys.py::build_news_raw_object_key` (F1).
- `services/worker/storage.py` (`s3_client`, `ensure_bucket`) and
  `services/worker/db.py::SessionLocal`, as used by every existing worker
  task.

**Tests**: fixture-driven client parsing (both slices + Events CSV),
`persist_items` dedup (`ON CONFLICT` no-op on duplicate hash), S3 raw-text
upload for new items only.

**E2E verify**: compose up (db, minio, redis, worker) → enqueue
`backfill_gdelt_month("morocco", 2024, 6)` → assert `alt_news_item` rows
with `payload_json.v2tone` populated, S3 objects under
`alt_data/news/raw/gdelt/...`, re-run is a zero-insert no-op.

**Done when**: probe script output recorded; one full backfill month
ingested E2E; live-poll entry points return `PersistSummary` counts; tests
green.

---

## A2 — Morocco scrapers + RSS + yfinance news

**Goal**: Moroccan news sites, RSS feeds, and yfinance news flowing through
the same funnel — **archive-depth probe first**. Full spec:
[01-data-sources.md](01-data-sources.md#a2--morocco-scrapers-rss-yfinance-news).

**Sequencing inside the phase**: `scripts/probe_news_archives.py` is
written and run first; its generated report
(`docs/sentiment-layer/07-archive-depth-report.md`) fixes each site's
backfill scope before any scraper class is written.

**Files to create**
- `scripts/probe_news_archives.py` → generated report doc (above)
- `core/quant_core/newsflow/morocco_scrapers.py` (one class per site:
  Medias24, Boursenews, FNH, casablanca-bourse announcements, AMMC)
- `core/quant_core/newsflow/rss_client.py` (+ etag/last-modified state)
- `core/quant_core/newsflow/yfinance_news.py`
- `data/news_feed_registry.json`
- `services/worker/tasks/ingest_news_feeds.py`
- `core/tests/test_morocco_scrapers.py`, `core/tests/test_rss_client.py`,
  HTML/XML fixtures under `core/tests/fixtures/news/`

**Files to modify** — none.

**Existing code to reuse**
- `BourseDirectAdapter` (`core/quant_core/data.py:853`) as the structural
  template: shared `requests.Session`, `rate_limit_delay_s` sleep between
  requests, per-item try/except-continue, env-var URL config with ctor
  override.
- `persist.py::persist_items()` from A1 — scrapers produce
  `NewsItemRecord`s only, never touch persistence.

**Tests**: per-site HTML fixture parsing; RSS 304-short-circuit behavior;
robots.txt disallow honored; registry JSON schema round-trip.

**E2E verify**: compose up → enqueue `ingest_news_feeds` → assert rows per
source in `alt_news_item`, feed-state rows updated, second run inserts only
newer items.

**Done when**: archive report committed; all five site scrapers + RSS +
yfinance ingest E2E within measured coverage windows; tests green.

---

## A4 — Entity → MASI symbol mapping

**Goal**: French-alias matching populates `alt_news_item.symbols` at ingest
and via a re-runnable remap task. Full spec:
[03-entity-mapping.md](03-entity-mapping.md).

**Files to create**
- `data/masi_aliases.json` (seeded then human-curated)
- `scripts/seed_masi_aliases.py`
- `core/quant_core/newsflow/entity_map.py`
- `services/worker/tasks/remap_news_entities.py`
- `core/tests/test_entity_map.py` +
  `core/tests/fixtures/news/masi_aliases_test.json`

**Files to modify**
- `core/quant_core/newsflow/persist.py` — call `map_entities()` on
  title+lead at ingest, write `symbols` JSONB.

**Existing code to reuse**
- `StockMaster` model (`services/api/app/models.py:447` — `symbol`,
  `display_name`, `isin`, `is_active`, `market_region`) for seeding.

**Tests**: accent-strip/case-fold matching, word-boundary false-positive
guards, ISIN exact match, confidence tiers (1.0/0.9/0.6), multi-match
articles, seed script never clobbering curated aliases.

**E2E verify**: compose up → run seed script → curate 10 example names →
re-ingest a fixture batch → assert `symbols` populated → edit an alias →
run `remap_news_entities` → assert updated tags without re-scoring.

**Done when**: every active MASI symbol has an alias entry; ingest-time and
remap paths both populate `symbols` E2E; tests green.

---

## A3 — LLM scoring pipeline

**Goal**: provider-agnostic, quota-rotating LLM scoring writing
`alt_news_score` rows with full lookahead provenance. Full spec:
[02-llm-scoring.md](02-llm-scoring.md).

**Files to create**
- `core/quant_core/research/sentiment/__init__.py`
- `core/quant_core/research/sentiment/llm_client.py`
- `core/quant_core/research/sentiment/prompts.py`
- `core/quant_core/research/sentiment/schema.py`
- `core/quant_core/research/sentiment/scoring.py`
- `services/worker/tasks/score_news_sentiment.py`
- `core/tests/test_sentiment_scoring.py` +
  `core/tests/fixtures/news/llm_responses/`

**Files to modify** — none (parking-table DDL, if chosen over payload
metadata, extends the F1 migration family; see
[02-llm-scoring.md](02-llm-scoring.md#malformed-json-repair-retry-then-park)).

**Existing code to reuse**
- Raw-`urllib` HTTP style from `stockanalysis_provider.py` — **no new SDK
  deps**.
- Redis connection via `services/worker/redis_utils.py::
  connect_redis_with_fallback` (as `scheduler_dispatch.py` does) for the
  `sent_llm:{provider}:{yyyymmdd}` counters.
- RQ delayed retry via `queue.enqueue_in(timedelta(minutes=30), ...)`.

**Tests**: schema validate/clip/repair/park paths; provider rotation on
quota; all-exhausted → delayed re-enqueue; provenance columns persisted;
anonymization flag recorded. All against a fake `chat_completion`.

**E2E verify**: compose up with `SENTIMENT_LLM_PROVIDERS` pointing at a
local Ollama (or a stub server) → enqueue scoring batch → assert
`alt_news_score` rows with `model_id`/`provider`/`prompt_version`/
`anonymized`/`scored_at` set, priority order respected (symbol-mapped
articles scored first), quota counters incrementing in Redis.

**Done when**: a batch of 50 real ingested articles scores end-to-end
against at least one live free-tier provider and the Ollama fallback; tests
green.

---

## A5 — Aggregates + factor export + scheduling

**Goal**: daily per-subject aggregates, `SENT_*` derived factor series in
the standard parquet layout, three new schedules. Full spec:
[04-aggregation-and-factors.md](04-aggregation-and-factors.md).

**Files to create**
- `core/quant_core/research/sentiment/aggregate.py`
- `services/worker/tasks/aggregate_sentiment_daily.py`
- `services/worker/tasks/export_sentiment_factors.py`
- `core/tests/test_sentiment_aggregate.py`
- `services/worker/tests/test_export_sentiment_factors.py`

**Files to modify**
- `services/api/app/services/scheduler_registry.py` — extend `ScheduleKind`
  (lines 13–28) with `news_ingest`, `news_sentiment_scoring`,
  `sentiment_daily_aggregate`; append three `ScheduleSpec` entries (crons:
  `*/30 * * * *`, `0 */2 * * *`, `10 18 * * mon-fri`; all
  `Africa/Casablanca`, queue `market_refresh`).
- `services/worker/tasks/scheduler_dispatch.py` — three new branches in
  `dispatch_schedule()`'s kind chain (lines 105–136) + `_dispatch_*`
  helpers per the `_dispatch_factor_monitor` /`_dispatch_stale_wfo`
  patterns.

**Existing code to reuse**
- `services/worker/tasks/ingest_macro_series.py` helpers:
  `_try_load_existing_parquet`, `_merge`, `_save_parquet`,
  `_upsert_market_data_store` (with `source_provider='derived'`).
- `core/quant_core/s3_keys.py::build_market_store_object_key`.
- `macro_factor_meta` with `source_kind='derived'`,
  `yahoo_ticker=canonical_id` (F1 convention; see the `MacroSeriesSpec.source`
  vs `source_kind` distinction flagged in
  [04-aggregation-and-factors.md](04-aggregation-and-factors.md#macro_factor_meta-registration)).

**Tests**: `sent_weighted` and `shock_z` math; 18:00-cutoff boundary;
`SENT_SYM_*` coverage gate (median weekly `n_items ≥ 3`); regression test
that derived `macro_factor_meta` rows never reach yfinance.

**E2E verify**: compose up → trigger `sentiment_daily_aggregate` via the
ops schedule endpoint → assert `alt_sentiment_daily` rows,
`market_data/symbols/SENT_MA_MACRO/ohlcv.parquet` in MinIO with `Close`
holding `sent_weighted`, `market_data_store` + `macro_factor_meta` rows
present, and an existing factor reader (e.g. the analytics factor loader)
loading `SENT_MA_MACRO` unchanged.

**Done when**: all three schedules dispatch E2E and appear in scheduler-run
audit rows; the four topic series export and reload through existing factor
readers; tests green.

---

## A6 — Validation gates

**Goal**: pre-registered IC study over all exported `SENT_*` series with
the four numeric gates and upper-bound/live sample separation. Full spec:
[05-validation-gates.md](05-validation-gates.md).

**Files to create**
- `core/quant_core/research/sentiment/ic_study.py`
- `services/worker/tasks/sentiment_ic_study.py`
- `core/tests/test_sentiment_ic_study.py`

**Files to modify** — none.

**Existing code to reuse**
- `core/quant_core/research/factors/relevance.py::compute_factor_relevance`
  (horizons {1,5,21}, `lag_rule="precede_open"`).
- `core/quant_core/research/stats/fdr.py::benjamini_hochberg`,
  `bh_adjusted_pvalues` (q=0.10 over the full pre-registered grid).
- `core/quant_core/research/stats/ic.py` (`_newey_west_var`,
  `ic_decay_curve` for diagnostics).
- S3 write conventions from existing study/verdict artifact writers.

**Tests**: gate arithmetic on synthetic series with injected IC; coverage
and sign-stability gates on constructed `alt_sentiment_daily` fixtures;
live vs upper-bound sample split on provenance columns; verdict JSON
schema.

**E2E verify**: compose up → run `sentiment_ic_study` against the
backfilled (upper-bound) history → assert
`alt_data/studies/sentiment_ic/{as_of}_upper_bound.json` in MinIO with
per-claim gate results and `pit_grade='upper_bound'`; confirm no live
verdict is emitted while the live sample is below coverage minimums.

**Done when**: study runs E2E producing a verdict artifact; the grid is
pre-registered in the artifact before results are read; nothing in the
product surface consumes `SENT_*` series (grep-verifiable: no
Signal/Dashboard import of sentiment modules); tests green.
