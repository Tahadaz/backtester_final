# Phase F1 — PIT Event Store

Blocks every other phase in every plan folder (see [00-overview.md](00-overview.md#cross-plan-dependency-graph)). Nothing in Plan A/B/C can be implemented before this migration lands.

## Decision: new tables, not an extension of `FundamentalCatalyst`

`services/api/app/models.py:1061` defines `FundamentalCatalyst` — verified:

```python
class FundamentalCatalyst(Base):
    __tablename__ = "fundamental_catalyst"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    event_type = Column(String(32), nullable=False)
    event_date = Column(Date, nullable=False)
    event_date_confidence = Column(String(20), nullable=False)
    impact_tier = Column(String(20), nullable=False)
    expected_direction = Column(String(20), nullable=True)
    title = Column(Text, nullable=False)
    ...
    superseded_by_id = Column(BigInteger, ForeignKey("fundamental_catalyst.id", ondelete="SET NULL"), nullable=True)
    __table_args__ = (
        CheckConstraint("event_type in ('earnings','dividend','ex_dividend','agm','guidance','regulatory','product','m_and_a','split','other')", ...),
        ...
    )
```

**Do not extend this table.** Reasons:

1. **Volume mismatch.** `FundamentalCatalyst` is a low-volume, hand-curated calendar (earnings dates, dividends, AGMs — order of magnitude: tens of rows per symbol per year). News items are high-volume, append-only observations (hundreds per day across sources). Cramming both into one table means every index and CHECK constraint on the curated calendar now has to scale to news volume, and vice versa.
2. **Scope mismatch.** `FundamentalCatalyst` is symbol-scoped (`symbol` is `NOT NULL`, one row = one company event). News items and macro releases are frequently **multi-subject** (one article mentions three companies plus a macro topic) or **not symbol-scoped at all** (a BAM policy decision, a global geopolitical event). Forcing multi-subject rows through a symbol-scoped schema means either denormalizing to one row per (article, symbol) pair — which breaks `content_hash` dedup semantics — or leaving `symbol` null and losing the `NOT NULL` guarantee that the rest of the codebase (and its CHECK constraints) relies on.
3. **CHECK-constrained event taxonomy.** `event_type` is a closed enum (`earnings`, `dividend`, `ex_dividend`, `agm`, `guidance`, `regulatory`, `product`, `m_and_a`, `split`, `other`) tuned for confirmed corporate actions. News/sentiment subjects and macro release series need an open, growing taxonomy (topics, regions, per-symbol sentiment subjects) that doesn't fit a CHECK enum without constant migrations.
4. **Vintage requirement.** Macro releases need revision tracking (`vintage`, `status`, `superseded` chains keyed by `(series_id, period)`) — a different versioning shape than `FundamentalCatalyst`'s single `superseded_by_id` self-FK, which supersedes whole rows rather than tracking value revisions of the same period.

**`FundamentalCatalyst` is reused unchanged** as Plan C's PEAD/company event source (see `../event-backtest-layer/02-event-sources.md`, adapter 1). No schema change to it in this migration.

## Table schemas

All six tables are created in one Alembic migration (see [Migration plan](#migration-plan) below). DDL is written Postgres-flavored to match the rest of `services/api/app/models.py` (JSONB, `BigInteger().with_variant(Integer, "sqlite")` for cross-dialect PK compatibility, `server_default=func.now()`).

### `alt_news_item`

Append-only. One row per unique article/press item, regardless of how many subjects it mentions.

```sql
CREATE TABLE alt_news_item (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source          VARCHAR(64)  NOT NULL,   -- 'gdelt_doc' | 'medias24' | 'boursenews' | 'fnh' |
                                              -- 'casablanca_bourse' | 'ammc' | 'yfinance' | 'rss:<feed_id>'
    url             TEXT         NOT NULL,   -- original article URL (not unique alone — mirrors/AMP dupes)
    title           TEXT         NOT NULL,
    language        VARCHAR(8)   NOT NULL,   -- 'fr' | 'en' | 'ar'
    event_time      TIMESTAMPTZ,             -- dateline time if distinct from published_at (nullable; rare)
    published_at    TIMESTAMPTZ  NOT NULL,   -- PIT anchor #1: source-claimed publish time (UTC)
    observed_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),  -- PIT anchor #2: when OUR pipeline fetched it
    content_hash    VARCHAR(64)  NOT NULL,   -- sha256(normalize(title) || netloc(url) || date(published_at))
    symbols         JSONB        NOT NULL DEFAULT '[]',   -- e.g. ["ATW","IAM"] — MASI symbols mapped at ingest/remap time
    topics          JSONB        NOT NULL DEFAULT '[]',   -- e.g. ["macro","banks"]
    regions         JSONB        NOT NULL DEFAULT '[]',   -- e.g. ["ma","global"]
    payload_json    JSONB,                   -- raw provider payload: GDELT V2Tone, GKG themes, CAMEO codes, etc.
    s3_text_key     TEXT,                    -- pointer to full raw text/HTML in S3 (see S3 layout below); NULL if inline-only
    raw_excerpt     TEXT,                    -- short snippet stored inline for list views without an S3 round-trip
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT uq_alt_news_item_content_hash UNIQUE (content_hash)
);

CREATE INDEX ix_alt_news_item_published_at   ON alt_news_item (published_at);
CREATE INDEX ix_alt_news_item_source_pubdate ON alt_news_item (source, published_at);
CREATE INDEX ix_alt_news_item_symbols_gin    ON alt_news_item USING GIN (symbols);
CREATE INDEX ix_alt_news_item_topics_gin     ON alt_news_item USING GIN (topics);
```

Dedup key is `content_hash`, not `url`, because the same article is frequently republished at a different URL (syndication, AMP variants, GDELT re-crawls). Ingestion always upserts with `ON CONFLICT (content_hash) DO NOTHING`.

### `alt_news_score`

One row per `(article, subject, prompt_version)`. Re-scoring with a new prompt version adds new rows rather than overwriting — this is what makes prompt iteration auditable and keeps old backtests reproducible.

```sql
CREATE TABLE alt_news_score (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    news_item_id    BIGINT       NOT NULL REFERENCES alt_news_item(id) ON DELETE CASCADE,
    subject_type    VARCHAR(16)  NOT NULL,   -- 'symbol' | 'topic_region'
    subject_key     VARCHAR(64)  NOT NULL,   -- 'ATW' | 'macro:ma' | 'geopolitics:global' | ...
    sentiment       REAL         NOT NULL,   -- [-1, +1]
    confidence      REAL         NOT NULL,   -- [0, 1] — model's stated confidence
    relevance       REAL         NOT NULL,   -- [0, 1] — how relevant this subject is to this article
    direction       VARCHAR(16),             -- 'positive' | 'negative' | 'neutral' | 'mixed' (categorical read, may
                                              -- diverge from sign(sentiment) on genuinely mixed articles)
    model_id        VARCHAR(64)  NOT NULL,   -- e.g. 'kimi-k2:free', 'qwen3:8b'
    provider        VARCHAR(32)  NOT NULL,   -- 'openrouter' | 'groq' | 'gemini' | 'ollama'
    prompt_version  VARCHAR(16)  NOT NULL,   -- 'v1', 'v2', ...
    anonymized      BOOLEAN      NOT NULL DEFAULT FALSE,   -- entity names replaced with SOCIETE_A/B/... before scoring
    scored_at       TIMESTAMPTZ  NOT NULL,   -- when the LLM call happened (lookahead-bias provenance)
    pit_grade       VARCHAR(16)  NOT NULL,   -- 'live' | 'upper_bound' — see PIT JOIN RULE #3 below
    error_tag       VARCHAR(32),             -- non-null only for parked/malformed rows (schema repair failed)
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT ck_alt_news_score_subject_type CHECK (subject_type IN ('symbol','topic_region')),
    CONSTRAINT ck_alt_news_score_pit_grade    CHECK (pit_grade IN ('live','upper_bound')),
    CONSTRAINT ck_alt_news_score_sentiment    CHECK (sentiment  BETWEEN -1 AND 1),
    CONSTRAINT ck_alt_news_score_confidence   CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_alt_news_score_relevance    CHECK (relevance  BETWEEN 0 AND 1),
    CONSTRAINT uq_alt_news_score_item_subject_prompt
        UNIQUE (news_item_id, subject_type, subject_key, prompt_version)
);

CREATE INDEX ix_alt_news_score_subject       ON alt_news_score (subject_type, subject_key);
CREATE INDEX ix_alt_news_score_scored_at     ON alt_news_score (scored_at);
```

`pit_grade` is set at scoring time by comparing `scored_at` against the scoring model's known training-data cutoff (a small static table/constant per `model_id`, maintained in `core/quant_core/research/sentiment/prompts.py` — see `../sentiment-layer/02-llm-scoring.md`): if the article's `published_at` predates that cutoff, the score is `'upper_bound'` regardless of when the scoring call itself ran, because the model may have seen the outcome during training. `'live'` is reserved for articles published **after** the scoring model's cutoff — i.e., genuinely out-of-training-sample text.

### `alt_sentiment_daily`

Recomputable aggregate — always safe to `TRUNCATE` and rebuild from `alt_news_score` + `alt_news_item`. Not a source of truth.

```sql
CREATE TABLE alt_sentiment_daily (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date            DATE         NOT NULL,   -- Casablanca trading-day bucket (see PIT JOIN RULE #1)
    subject_type    VARCHAR(16)  NOT NULL,
    subject_key     VARCHAR(64)  NOT NULL,
    n_items         INTEGER      NOT NULL,   -- distinct articles contributing
    sent_mean       REAL         NOT NULL,   -- unweighted mean sentiment
    sent_weighted   REAL         NOT NULL,   -- relevance · confidence weighted mean sentiment
    pos_share       REAL         NOT NULL,   -- fraction of items with sentiment > 0
    neg_share       REAL         NOT NULL,   -- fraction of items with sentiment < 0
    shock_z         REAL,                    -- z-score of sent_weighted vs trailing 60-session mean/std; NULL until warm
    pit_grade       VARCHAR(16)  NOT NULL,   -- 'live' if ALL contributing scores are 'live', else 'upper_bound'
    computed_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT ck_alt_sentiment_daily_subject_type CHECK (subject_type IN ('symbol','topic_region')),
    CONSTRAINT ck_alt_sentiment_daily_pit_grade     CHECK (pit_grade IN ('live','upper_bound')),
    CONSTRAINT uq_alt_sentiment_daily_date_subject
        UNIQUE (date, subject_type, subject_key)
);

CREATE INDEX ix_alt_sentiment_daily_subject_date ON alt_sentiment_daily (subject_type, subject_key, date);
```

`pit_grade` aggregation is deliberately conservative (worst-case, not majority-vote): a single `upper_bound` contributor taints the whole daily bucket, because a downstream IC study that mixes live and upper-bound days without labeling would silently inherit the contamination.

### `macro_release_series`

Registry of macro series that have a release/vintage structure (distinct from `macro_factor_meta`, which is Yahoo-sourced continuous price/level series — see [`macro_factor_meta` extension](#macro_factor_meta-extension) below).

```sql
CREATE TABLE macro_release_series (
    series_id                    VARCHAR(64) PRIMARY KEY,   -- 'MA_CPI_YOY' | 'BAM_POLICY_RATE' | 'US_CPI_YOY' | 'US_GDPNOW' | ...
    country                      VARCHAR(8)  NOT NULL,      -- 'MA' | 'US' | 'GLOBAL'
    frequency                    VARCHAR(16) NOT NULL,      -- 'monthly' | 'quarterly' | 'weekly' | 'daily'
    display_name                 TEXT        NOT NULL,
    unit                         VARCHAR(32) NOT NULL,      -- '%' | 'index' | 'bps'
    source                       VARCHAR(32) NOT NULL,      -- 'HCP' | 'BAM' | 'FRED' | 'ALFRED' | 'ClevelandFed' | 'AtlantaFed' | 'NYFed' | 'FAO'
    typical_release_lag_days     INTEGER,                   -- e.g. CPI ~20-25 days after period end
    typical_release_time_local   VARCHAR(8),                -- e.g. '09:00' (source-local time, for calendar display only)
    active                       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_macro_release_series_frequency CHECK (frequency IN ('monthly','quarterly','weekly','daily'))
);
```

### `macro_release`

Vintaged actuals + calendar. One row per `(series_id, period, vintage)` — a revision inserts a new row rather than mutating the prior vintage, so any nowcast/backtest that fixed its `as_of_date` in the past can still reconstruct exactly what was known then.

```sql
CREATE TABLE macro_release (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    series_id           VARCHAR(64)  NOT NULL REFERENCES macro_release_series(series_id),
    period              VARCHAR(16)  NOT NULL,   -- period the release covers, e.g. '2026-06' (monthly) or '2026-Q2'
    release_time        TIMESTAMPTZ  NOT NULL,   -- PIT anchor: when this vintage became public
    status               VARCHAR(16)  NOT NULL,   -- 'scheduled' | 'released' | 'revised'
    actual_value         DOUBLE PRECISION,        -- NULL while status='scheduled'
    vintage              INTEGER      NOT NULL DEFAULT 1,   -- 1 = first print, 2 = first revision, ...
    observed_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),  -- when OUR pipeline recorded this vintage
    source_payload_json  JSONB,                   -- raw scrape/API payload for audit
    superseded_by_id     BIGINT REFERENCES macro_release(id) ON DELETE SET NULL,  -- mirrors FundamentalCatalyst idiom
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT ck_macro_release_status CHECK (status IN ('scheduled','released','revised')),
    CONSTRAINT uq_macro_release_series_period_vintage UNIQUE (series_id, period, vintage)
);

CREATE INDEX ix_macro_release_series_release_time ON macro_release (series_id, release_time);
CREATE INDEX ix_macro_release_status               ON macro_release (status, release_time);
```

### `nowcast_value`

Model outputs. `as_of_date` is the PIT contract: a nowcast row must only have used data available on or before that date, enforced by the feature-assembly layer (`../macro-nowcast-layer/02-inflation-nowcast.md`), not by the DB.

```sql
CREATE TABLE nowcast_value (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    series_id       VARCHAR(64)  NOT NULL REFERENCES macro_release_series(series_id),
    as_of_date      DATE         NOT NULL,   -- PIT cutoff: only data ≤ this date was used to produce `value`
    target_period   VARCHAR(16)  NOT NULL,   -- period being forecast, e.g. '2026-07'
    value            DOUBLE PRECISION NOT NULL,
    std              DOUBLE PRECISION,       -- model uncertainty estimate; NULL if point-estimate only
    model_version    VARCHAR(32)  NOT NULL,  -- 'ridge_bridge_v1' | 'ar_benchmark' | 'ordered_logit_v1' | 'rule_fallback_v1'
    inputs_hash      VARCHAR(64)  NOT NULL,  -- sha256 of the assembled feature vector, for reproducibility audits
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT uq_nowcast_value_series_asof_target_model
        UNIQUE (series_id, as_of_date, target_period, model_version)
);

CREATE INDEX ix_nowcast_value_series_asof ON nowcast_value (series_id, as_of_date);
```

## `macro_factor_meta` extension

`macro_factor_meta` (`services/api/app/models.py:495-510`) is the DB-backed registry of Yahoo-sourced macro factor series. Verified live column definition:

```python
__tablename__ = "macro_factor_meta"
canonical_id  = Column(String, primary_key=True)
yahoo_ticker  = Column(String, nullable=False, unique=True)   # services/api/app/models.py:503
display_name  = Column(String, nullable=False)
asset_type    = Column(String, nullable=False)
market_region = Column(String, nullable=True)
active        = Column(Boolean, nullable=False, default=True)
added_via     = Column(String, nullable=False, default="system")
created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
notes         = Column(Text, nullable=True)
```

`yahoo_ticker` is confirmed `NOT NULL UNIQUE`. This is the constraint that Risk #5 in [00-overview.md](00-overview.md#top-5-risks--mitigations) is about: any row inserted for a derived series (a sentiment index, a surprise series, a regime flag — none of which have a Yahoo ticker) must still populate `yahoo_ticker` with *something* unique, or the insert fails outright.

**Migration adds one column**:

```sql
ALTER TABLE macro_factor_meta
    ADD COLUMN source_kind VARCHAR(16) NOT NULL DEFAULT 'yahoo';

ALTER TABLE macro_factor_meta
    ADD CONSTRAINT ck_macro_factor_meta_source_kind CHECK (source_kind IN ('yahoo','derived'));
```

**Convention for derived rows** (sentiment indices, surprise series, regime flags, `BAM_RATE_DIR`, etc.): `source_kind='derived'` and `yahoo_ticker = canonical_id` (i.e., the placeholder satisfies the `UNIQUE` constraint by construction, since `canonical_id` is itself the primary key and therefore already unique). This is a documented placeholder, not a real ticker — every consumer must branch on `source_kind` before treating `yahoo_ticker` as fetchable.

**Skip-guard requirement**: `services/worker/tasks/ingest_macro_series.py` currently reads `macro_factor_meta` via `core/quant_core/macro.py::get_macro_series()` and, for every row returned, calls the Yahoo Finance data source unconditionally (verified: `ingest_macro_series.py` imports `MACRO_SERIES_BY_ID` / `MacroSeriesSpec` / `fetch_macro_series` from `core/quant_core/macro.py` and has no existing branch on source). The task **must be modified** to skip any row with `source_kind='derived'` before it reaches the yfinance fetch call — those series are written by their own producer tasks (`aggregate_sentiment_daily.py`, `refresh_nowcasts.py`, `surprise.py`, etc., per the sibling plans), not by this task.

**`core/quant_core/macro.py::MacroSeriesSpec`** (currently, verified):

```python
@dataclass
class MacroSeriesSpec:
    symbol: str
    canonical_id: str
    description: str
    timezone: str = "UTC"
    close_time_utc: str = "21:00"
    channel_tags: list[str] = field(default_factory=list)
    source: str = "yahoo"
```

Note it already has a `source: str = "yahoo"` field, but this is a free-text description field, not the same as the new DB `source_kind` enum column — the migration plan adds a **matching** `source_kind: Literal["yahoo","derived"] = "yahoo"` field to this dataclass so the DB row and the in-process spec stay in sync (`get_macro_series()` reads DB rows into this dataclass; the field must exist on both sides or the derived flag is silently dropped when the DB row is deserialized).

**Regression test**: `services/worker/tests/test_macro_meta_source_kind.py` — asserts that a `macro_factor_meta` row with `source_kind='derived'` is filtered out before `ingest_macro_series`'s yfinance call path, using a mock/spy on the Yahoo fetch function to assert zero calls for derived rows.

## S3 layout

`core/quant_core/s3_keys.py` is the single source of truth for object-key construction (both API and worker import from it — verified, docstring: "the key format can never silently diverge between writer and reader"). Two existing helpers, verified:

```python
def build_dataset_object_key(data_hash: str, filename: str) -> str:
    return f"datasets/{data_hash}/{filename}"

def build_market_store_object_key(symbol: str, timeframe: str) -> str:
    return f"market_data/symbols/{symbol}/ohlcv.parquet"
```

**New helper added in this migration's companion code change** (F1 work package, below):

```python
def build_news_raw_object_key(source: str, published_date: str, content_hash: str) -> str:
    """Return the canonical S3 key for a raw news article's full text/HTML.

    Format: ``alt_data/news/raw/{source}/{yyyy}/{mm}/{hash}.json.gz``
    """
    yyyy, mm = published_date[:4], published_date[5:7]
    return f"alt_data/news/raw/{source}/{yyyy}/{mm}/{content_hash}.json.gz"
```

`alt_news_item.s3_text_key` stores this key. `published_date` is `published_at` truncated to `YYYY-MM-DD`.

**Derived daily series** (sentiment indices, surprise series, regime flags — anything landing in `macro_factor_meta(source_kind='derived')`) **reuse `build_market_store_object_key`** unchanged: they are written as a two-column `Close`-only parquet (`Close = value`, indexed by date) at `market_data/symbols/{canonical_id}/ohlcv.parquet`, identical in shape to a real OHLCV series. This is a deliberate reuse decision — it means every existing factor reader (`get_macro_series`, `align_factor_to_target`, the Factor×TA runtime, the Data-page loaders) works on derived series with **zero code changes**, because from their point of view a derived series is indistinguishable from a Yahoo-sourced one except for the `source_kind` flag.

## THE PIT JOIN RULE

This is the single rule every consumer of alt-data (sentiment, macro releases, nowcasts) must follow. It extends the existing macro-factor alignment contract documented in `docs/factor-layer/04-calendar-alignment.md` — read that document first; this section only adds the alt-data-specific availability-timestamp mapping.

### 1. Availability timestamp → trading-day bucket

Every alt-data record has exactly one **availability timestamp**:

| Record type | Availability timestamp field |
|---|---|
| News article | `alt_news_item.published_at` |
| Macro release | `macro_release.release_time` |
| Nowcast value | `nowcast_value.as_of_date` (treated as 18:00 Casablanca on that date, i.e. end-of-day availability) |

**Cutoff rule**: convert the availability timestamp to `Africa/Casablanca` local time.
- If local time `< 18:00` on day D → the record is assigned to day **D**.
- If local time `≥ 18:00` on day D (including anything after MASI close but before midnight, and anything overnight) → the record is assigned to day **D+1**.

Rationale for 18:00: MASI closes at 17:35 local (`docs/factor-layer/04-calendar-alignment.md`); the 18:00 cutoff gives a 25-minute buffer past close so same-day late-afternoon news/releases are not misclassified as "available before close" by a few minutes of clock skew, while still capturing same-day after-close news for next-day use. This mirrors the existing `sentiment_daily_aggregate` scheduler slot, which the design deliberately times at **18:10** Casablanca (see `../sentiment-layer/04-aggregation-and-factors.md`) — 10 minutes after this cutoff, so the aggregation job never races an in-flight ingestion.

### 2. All joins go through `align_factor_to_target`

Every backtest, IC study, or UI series that combines an alt-data series with equity returns **must** call:

```python
core.quant_core.research.alignment.align_factor_to_target(
    factor, target,
    lag_rule="precede_open",
    max_staleness=...,
)
```

exactly as documented in `docs/factor-layer/04-calendar-alignment.md`. `lag_rule="contemporaneous"` is **forbidden** for every alt-data series — sentiment indices, macro releases, nowcasts, surprise series, regime flags — with no exceptions, because rule #1 above already assigns same-day-but-after-cutoff records to D+1; treating a D-bucketed record as usable for a D-return would double-count availability that the bucketing already accounted for, reintroducing the exact look-ahead bias the bucketing exists to prevent. Any PR that passes `lag_rule="contemporaneous"` on an alt-data series should be rejected in review.

`max_staleness` is set per-series in the calling code (sentiment IC study, nowcast evaluation harness, event-study alignment) following the same reasoning as the existing macro factors (`docs/factor-layer/04-calendar-alignment.md` — 3-day default, wider for lower-frequency macro releases).

### 3. `pit_grade='upper_bound'` propagation

Any LLM sentiment score whose source article predates the scoring model's training cutoff is `pit_grade='upper_bound'` (set in `alt_news_score`, defined precisely in [`alt_news_score`](#alt_news_score) above). This label propagates forward through every derived artifact:

- `alt_sentiment_daily.pit_grade` — worst-case aggregation (any contributing `upper_bound` score taints the day).
- Every IC-study / verdict JSON artifact written to S3 (`alt_data/studies/...`, see [02-validation-policy.md](02-validation-policy.md#verdict-artifact-convention)) reports pre-cutoff and post-cutoff results **separately** — an upper-bound history is never blended into a promotion-eligible statistic.
- The UI: any panel or number derived even partially from `upper_bound` data carries the « borne supérieure (pré-cutoff LLM) » badge (see [03-api-ui.md](03-api-ui.md)).
- **Promotion gate**: only `pit_grade='live'` data is eligible for Signal/Dashboard promotion (see [02-validation-policy.md](02-validation-policy.md)). `upper_bound` results are permanently research-tab-only, regardless of how strong they look statistically — the label does not "expire" as more live data accumulates; each individual score keeps the grade it was assigned at scoring time.

## Migration plan

**Single Alembic migration**: `services/api/alembic/versions/<rev>_add_alt_event_store.py`. Creates, in order (respecting FK dependencies):

1. `macro_release_series`
2. `alt_news_item`
3. `alt_news_score` (FK → `alt_news_item`)
4. `alt_sentiment_daily`
5. `macro_release` (FK → `macro_release_series`, self-FK `superseded_by_id`)
6. `nowcast_value` (FK → `macro_release_series`)
7. `ALTER TABLE macro_factor_meta ADD COLUMN source_kind ...` + CHECK constraint

All in one migration file (not six) so the whole alt-data foundation lands atomically and there is exactly one new head to reconcile — this repo's Alembic history must stay single-headed, enforced by `services/api/tests/test_alembic_single_head.py` (verified present at that path). The migration's `down_revision` must point at the current head at merge time; if another migration lands first, this one is rebased onto the new head before merge, not stacked as a second head.

Both `upgrade()` and `downgrade()` are implemented (downgrade drops all seven changes in reverse order). No data migration/backfill logic belongs in this migration — it only creates empty structure; ingestion tasks populate it afterward.

## `core/quant_core/newsflow` domain module

New package, no DB/network dependency (pure domain logic, testable in isolation):

- `core/quant_core/newsflow/__init__.py`
- `core/quant_core/newsflow/domain.py`:
  - `NewsItemRecord` — frozen dataclass mirroring `alt_news_item` columns, used as the ingestion-layer's in-memory representation before it's persisted (same pattern as other `*Record` frozen dataclasses elsewhere in `core/quant_core`).
  - `normalize_content_hash(title: str, url: str, published_at: datetime) -> str` — implements the `content_hash` formula (`sha256(normalize(title) || netloc(url) || date(published_at))`) as one canonical function so every ingestion path (GDELT, scrapers, RSS, yfinance) produces byte-identical hashes for the same logical article.
  - Topic/region literal types (`Topic = Literal["macro","banks","insurance",...]`, `Region = Literal["ma","global",...]`) shared by the entity-mapping and scoring modules in Plan A.

## F1 work package

**Files to create:**
- `services/api/alembic/versions/<rev>_add_alt_event_store.py` — the migration described above.
- `services/api/app/models.py` — add ORM classes: `AltNewsItem`, `AltNewsScore`, `AltSentimentDaily`, `MacroReleaseSeries`, `MacroRelease`, `NowcastValue`, and the `source_kind` column + `MacroFactorSourceKind`-style CHECK on the existing `MacroFactorMeta` class.
- `core/quant_core/newsflow/__init__.py`, `core/quant_core/newsflow/domain.py`.
- `docs/alt-data-foundation/01-pit-event-store.md` — this document (already created).

**Files to modify:**
- `core/quant_core/s3_keys.py` — add `build_news_raw_object_key()`.
- `core/quant_core/macro.py` — add `source_kind: Literal["yahoo","derived"] = "yahoo"` to `MacroSeriesSpec`; thread it through `get_macro_series()`'s DB-row deserialization.
- `services/worker/tasks/ingest_macro_series.py` — add the `source_kind == "derived"` skip-guard before the yfinance fetch call.

**Tests:**
- `services/api/tests/test_alt_event_store.py` — table creation smoke test (migration applies cleanly against a fresh test DB), CHECK/UNIQUE constraint tests for each new table (e.g. duplicate `content_hash` rejected, `pit_grade` outside enum rejected, `(series_id, period, vintage)` uniqueness enforced).
- `services/api/tests/test_alembic_single_head.py` — must still pass unmodified (asserts exactly one Alembic head); this is the existing test, not a new one — it is the acceptance check for "did this migration fork the history."
- `core/tests/test_newsflow_domain.py` — `normalize_content_hash()` determinism/collision tests (same article via two sources → same hash; different articles → different hash with high probability), `NewsItemRecord` frozen/immutability check.
- `services/worker/tests/test_macro_meta_source_kind.py` — asserts `ingest_macro_series` never calls the Yahoo fetch path for a `source_kind='derived'` row (mock/spy assertion).

**E2E verification steps:**
1. `docker compose up -d db` (or the project's standard compose invocation).
2. `alembic upgrade head` from `services/api/` — must succeed with no errors, must leave exactly one head (`alembic heads` prints one line).
3. Connect (`psql` or the project's DB inspection tool) and verify all six new tables exist with the expected columns, and that `macro_factor_meta` has the new `source_kind` column defaulting existing rows to `'yahoo'`.
4. Insert one manual test row into `alt_news_item`, then one `alt_news_score` referencing it, then one `alt_sentiment_daily` row — confirm FKs and CHECK constraints behave as specified (e.g. an out-of-range `sentiment` value is rejected).
5. Insert one `macro_factor_meta` row with `source_kind='derived'` and `yahoo_ticker` equal to its own `canonical_id`; run `ingest_macro_series` against it in a dry-run/test invocation and confirm (via logs or the spy test) that no yfinance HTTP call is attempted.
6. `alembic downgrade -1` — must cleanly drop everything added, leaving the schema identical to pre-migration state (diff against a pre-migration schema dump).
