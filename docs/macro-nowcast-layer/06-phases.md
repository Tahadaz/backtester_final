# Phases B1–B6: Work Packages

Each phase is a self-contained implementation work package (spec + files +
tests + verification), sized for delegation to one implementation agent.
Dependency ordering: **B1 ∥ B2 → B3 → B4 ∥ B5 → B6**. All phases depend on
the shared-foundation migration F1
([`../alt-data-foundation/01-pit-event-store.md`](../alt-data-foundation/01-pit-event-store.md))
having created `macro_release_series`, `macro_release`, `nowcast_value`, and
the `macro_factor_meta.source_kind` column.

---

## B1 — Input-series ingestion

**Goal**: every input series from [`01-data-sources.md`](01-data-sources.md)
lands in the derived-factor store, with official prints mirrored into
`macro_release`.

**Files to create**
- `core/quant_core/research/nowcast/__init__.py`
- `core/quant_core/research/nowcast/fred_client.py` — FRED+ALFRED client,
  ctor/retry pattern copied from
  `core/quant_core/fundamentals/providers/stockanalysis_provider.py`
  (`timeout_seconds`/`retries`/injectable `sleep`, `2**attempt` backoff).
- `core/quant_core/research/nowcast/csv_sources.py` — Cleveland Fed,
  GDPNow, WEI, FAO FPI, HCP CPI history fetchers.
- `scripts/probe_fuel_prices.py` — optional-input probe (non-blocking).
- Seed data change (migration or seed script): `macro_factor_meta` rows for
  `WHEAT` (`ZW=F`), `MADUSD` (`MAD=X`), `EURMAD` (direct ticker or
  `source_kind='derived'` cross — decide per `01-data-sources.md` §1).

**Files to modify**
- `services/worker/tasks/ingest_macro_series.py` — only if the F1
  skip-derived-rows guard is not already merged (it is an F1 deliverable;
  verify before touching).

**Code to reuse**: `core/quant_core/s3_keys.py::build_market_store_object_key`,
the `_merge`/`_save_parquet`/`_upsert_market_data_store` pattern inside
`ingest_macro_series.py` (extract-and-share or mirror; do not fork
semantics), `core/quant_core/macro.py::get_macro_series()`.

**Tests** (`core/tests/`)
- `test_nowcast_fred_client.py` — retry/backoff with injected `sleep`,
  vintage (`realtime_start/end`) query construction, `FRED_API_KEY`-missing
  ctor failure; JSON fixtures, no network.
- `test_nowcast_csv_sources.py` — parse fixtures for each source →
  normalized `(period, value, published_at)` rows; malformed-file handling.
- Regression: derived/new seeds never hit yfinance (extends F1's
  `test_macro_meta_source_kind.py`).

**E2E (docker compose)**: seed rows → trigger ingestion → confirm parquet
objects in MinIO under `market_data/symbols/{WHEAT,MADUSD,EURMAD}/ohlcv.parquet`,
`market_data_store` rows with `asset_class='factor'`, and `macro_release`
rows for at least one FRED series with non-null `vintage`.

**Done when**: all series listed in `01-data-sources.md` §1–3 are queryable
via the standard factor loader; US CPI has vintaged `macro_release` rows.

---

## B2 — Release calendar + actuals (parallel with B1)

**Goal**: `macro_release` holds the full 2019→present Morocco calendar
(HCP CPI monthly, BAM quarterly) with `scheduled`→`released` lifecycle.

**Files to create**
- `core/quant_core/research/nowcast/data/ma_release_calendar.yaml` —
  hand-seeded per `01-data-sources.md` §4 (one-time manual collection from
  HCP/BAM archives, plus forward entries).
- `services/worker/tasks/refresh_macro_releases.py` — YAML seed + HCP/BAM
  press-page scrape + FRED fill for US series; upsert mirrors the
  `_upsert_catalyst()` supersede idiom in
  `services/worker/tasks/refresh_fundamental_catalysts.py`; vintage bump on
  revision.

**Files to modify**
- `services/api/app/services/scheduler_registry.py` — extend the
  `ScheduleKind` Literal with `"macro_release_refresh"` and add a
  `ScheduleSpec` (cron `0 9-18/3 * * mon-fri`, timezone
  `Africa/Casablanca`, queue `market_refresh`).
- `services/worker/tasks/scheduler_dispatch.py` — dispatch branch for the
  new kind.

**Tests**
- `services/api/tests/` — scheduler registry includes the new kind/spec
  (follow the existing registry test file's pattern).
- `services/worker/tests/test_refresh_macro_releases.py` — YAML→scheduled
  rows idempotency; scrape fixture flips scheduled→released with
  actual/observed_at; revision bumps vintage without deleting the prior row.

**E2E**: compose up → `alembic upgrade head` → trigger the schedule kind via
the ops endpoint → inspect `macro_release` rows for HCP/BAM 2019→present,
statuses correct for past vs future periods.

**Done when**: every historical HCP print and BAM meeting since 2019 exists
as a `released` row with actuals; next upcoming entries exist as
`scheduled`.

---

## B3 — CPI nowcast + OOS harness (needs B1 + B2)

**Goal**: [`02-inflation-nowcast.md`](02-inflation-nowcast.md) implemented:
PIT feature assembly, two pure-function models (<200 LOC combined),
expanding-window OOS harness, gate, daily refresh.

**Files to create**
- `core/quant_core/research/nowcast/features.py` — monthly PIT feature
  assembly; every row carries `available_at`; assembly asserts
  `available_at ≤ as_of_date`.
- `core/quant_core/research/nowcast/models.py` — `naive_ar_benchmark`,
  `ridge_bridge_nowcast`; both `(history_df, target_period) → (point, std)`.
- `core/quant_core/research/nowcast/evaluate.py` —
  `expanding_window_oos()`: re-estimate after each print, one-step-ahead,
  RMSE ratio + Diebold–Mariano.
- `services/worker/tasks/refresh_nowcasts.py` — daily 18:30 Mon–Fri
  Casablanca; writes `nowcast_value` rows + derived series
  `NOWCAST_MA_CPI`; re-checks the gate each run and stamps
  `model_version` accordingly.

**Files to modify**: `scheduler_registry.py` + `scheduler_dispatch.py`
(kind `"nowcast_refresh"`, cron `30 18 * * mon-fri`, Africa/Casablanca).

**Code to reuse**: derived-factor export pattern from B1;
`macro_release` reads from B2; scikit-learn/statsmodels ridge — whichever
is already a dependency (confirm; do not add a new package for a ridge
regression — closed-form ridge in numpy is acceptable within the LOC
budget).

**Tests** (`core/tests/`)
- `test_nowcast_features.py` — PIT assertion fires on a deliberately
  leaked feature; `available_at` propagation; missing-optional-feature
  degradation.
- `test_nowcast_models.py` — pure-function determinism; synthetic data with
  known AR structure recovered; `(point, std)` shape.
- `test_nowcast_evaluate.py` — expanding window never sees future rows
  (assert via `available_at` bookkeeping); DM test against a known-worse
  model rejects; RMSE-ratio arithmetic.

**E2E**: with B1+B2 data present, trigger `nowcast_refresh` → `nowcast_value`
rows exist with today's `as_of_date`; `NOWCAST_MA_CPI` parquet in MinIO;
`model_version` reflects gate state.

**Done when**: OOS harness runs over the full historical window and emits a
verdict (RMSE ratio, DM p, months count); daily refresh green in compose.

---

## B4 — BAM rate classifier (needs B3; parallel with B5)

**Goal**: [`03-rate-classifier.md`](03-rate-classifier.md) implemented.

**Files to create**
- `core/quant_core/research/nowcast/rate_classifier.py` — per-meeting PIT
  feature assembly (nowcast gap, Fed/ECB 60/40 basket feature, Brent 3m
  trend, optional credit proxy), `OrderedModel` fit, `hand_rule_rate_direction()`
  fallback, LOO CV runner, profile-likelihood CIs, gate evaluation.

**Files to modify**
- `services/worker/tasks/refresh_nowcasts.py` — extend the daily task to
  also refresh `BAM_POLICY_RATE` `nowcast_value` rows ahead of the next
  scheduled meeting (no separate schedule kind needed).

**Code to reuse**: B2's `macro_release` meeting calendar; B3's published
nowcast series; statsmodels (`OrderedModel` — verify version exposes it).

**Tests** (`core/tests/test_rate_classifier.py`)
- Hand-rule decision table exactness on constructed feature rows.
- LOO harness: each fold's training set excludes the held-out meeting.
- Gate logic: log-loss vs climatology computation; non-hold hit-rate
  computation; fallback selection when either gate fails.
- Degenerate-sample guards (all-hold history → climatology output, no
  crash).

**E2E**: trigger refresh → `nowcast_value` rows with
`series_id='BAM_POLICY_RATE'`, `model_version ∈ {'ordered_logit','hand_rule'}`,
`target_period` = next scheduled meeting from `macro_release`.

**Done when**: LOO report (log-loss, hit-rate, CIs) is produced as an
artifact and the published P(hike)−P(cut) respects the gate.

---

## B5 — Surprise engine, regimes, registry wiring (needs B3; parallel with B4)

**Goal**: [`04-surprise-and-regimes.md`](04-surprise-and-regimes.md)
implemented.

**Files to create**
- `core/quant_core/research/nowcast/surprise.py` — release-triggered
  surprise computation, expanding-std standardization, event-shaped
  `SURPR_*` + ffill `*_LAST` exports.
- `core/quant_core/research/nowcast/regimes.py` — the three {0,1} daily
  flag series, definitions frozen at pre-registration.

**Files to modify**
- `core/quant_core/research/factors/signals.py` — append the
  `BAM_RATE_DIR` `FactorSignalSpec` (exact entry in
  `04-surprise-and-regimes.md` §3) + `bam_rate_dir_signal()` function;
  extend the `compute_factor_signal()` dispatcher only if needed (it is a
  single-factor signal, so `spec.fn` suffices).
- **Sector-slug helper** (explicit work item, see the caveat in
  `04-surprise-and-regimes.md` §3): add `sector_slug(label) -> str`
  translating French `stock_master.sector` labels to the English slugs in
  `services/worker/research/channel_tags.yaml` `sectors:`, and apply it in
  the path that feeds `is_applicable()` / `_filter_conditions_by_channel()`
  for this spec — otherwise `channel_filter=("banks","insurance","real_estate")`
  never matches `"banques"`.
- `services/worker/research/channel_tags.yaml` — entries for
  `BAM_RATE_DIR` (tags `[banks, insurance, real_estate]`) and the regime
  flags (tags `[all]`).
- `services/worker/tasks/refresh_nowcasts.py` — emit surprise + regime
  series on each run; recompute surprises when `refresh_macro_releases`
  flips a row to `released`.

**Tests** (`core/tests/`)
- `test_nowcast_surprise.py` — nowcast lookup is strictly pre-release;
  expanding-std min-observation behavior; event-shaped vs `_LAST`
  series shapes.
- `test_nowcast_regimes.py` — flag definitions on synthetic nowcast paths;
  {0,1} + NaN-before-coverage output.
- `test_factor_signals.py` (extend) — `BAM_RATE_DIR` spec registered;
  `bam_rate_dir_signal` threshold mapping; `is_applicable` passes for
  slugged bank/insurance/real-estate sectors and fails for others;
  sector-slug helper round-trips the YAML mapping.

**E2E**: flip a fixture release → surprise rows appear; regime parquets in
MinIO; `compute_factor_relevance` runs end-to-end on `BAM_RATE_DIR` without
code changes.

**Done when**: all six derived series exist and are consumable by
`evaluate_condition`/`conditioned_variants` and the factor-signal registry
with no changes beyond those listed above.

---

## B6 — Validation gates (needs B4 + B5)

**Goal**: [`05-validation-gates.md`](05-validation-gates.md) executed and
artifacted.

**Files to create**
- `core/quant_core/research/nowcast/validation.py` (or a
  `scripts/run_nowcast_validation.py` runner if the study is batch-style
  like the factor layer's Phase 0.9 study — match whichever idiom the
  sentiment layer's A6 lands first; do not build two idioms) — frozen grid,
  `compute_factor_relevance` + `benjamini_hochberg` over the six series ×
  {banks, real-estate, MASI} targets, NW t ≥ 2.0 / BH q = 0.10 gates,
  WFO promotion path for `BAM_RATE_DIR` via `run_wfo_engine`.

**Code to reuse**: `core/quant_core/research/factors/relevance.py`,
`core/quant_core/research/stats/fdr.py`, `core/quant_core/wfo/engine.py`,
S3 artifact-writing pattern from the sentiment layer's verdict artifacts.

**Tests** (`core/tests/test_nowcast_validation.py`)
- Grid is exactly the pre-registered set (freeze-check against a constant).
- Gate arithmetic on synthetic IC tables (pass, fail, boundary).
- Artifact schema completeness (grid, ICs, q-values, verdicts, coverage,
  hashes).

**E2E**: run the study on compose against live-ingested data → verdict
artifact lands in MinIO under `alt_data/studies/nowcast_validation/`;
research tab's promotion-status panel reads it.

**Done when**: a complete verdict artifact exists (pass or fail — a
well-documented null is a valid completion), and `BAM_RATE_DIR` is either
promoted through the standard WFO/cost path or explicitly parked with
reasons recorded in the artifact.
