# Data Sources (A1, A2)

Five ingestion sources, all funneling through one dedup/persist path. Each
source writes `alt_news_item` rows and raw text to S3 — schema and S3 layout
are defined once in
[../alt-data-foundation/01-pit-event-store.md](../alt-data-foundation/01-pit-event-store.md);
this document covers only source-specific fetch/filter/backfill logic.

---

## A1 — GDELT

GDELT is free, requires no API key, and already tags tone, themes, and
source country per article — it is the highest-signal-per-dollar source and
lands first.

### Why the DOC 2.0 API, not bulk GKG files

GDELT publishes two products: the **DOC 2.0 API** (query-filtered JSON over
HTTP, returns matching articles with metadata including `V2Tone`) and the
raw **GKG (Global Knowledge Graph) bulk export** (15-minute CSV/TSV dumps of
*all* GDELT-indexed articles worldwide, 100+ GB/year uncompressed). The OCI
Always-Free ARM VM this stack runs LLM fallback on has no room for a
100+ GB/year ingest-and-filter pipeline, and a filtered API query is exactly
what a curated Morocco/macro/geopolitics slice needs. **Decision: DOC 2.0
API for articles, bulk files never touched.**

### DOC 2.0 API spec

- **Endpoint**: `https://api.gdeltproject.org/api/v2/doc/doc`
- **Method**: `GET`
- **Key query params**:
  | Param | Value | Notes |
  |---|---|---|
  | `query` | boolean query string, see slices below | GDELT query syntax: `AND`/`OR`/`-` exclude, `sourcecountry:XX`, `theme:XXX`, quoted phrases |
  | `mode` | `artlist` | returns article list (not timeline/tone-chart modes) |
  | `format` | `json` | |
  | `maxrecords` | `250` | API hard cap per call; page via `startdatetime`/`enddatetime` windows for more |
  | `startdatetime` / `enddatetime` | `YYYYMMDDHHMMSS` | UTC, used for backfill windowing |
  | `sort` | `datedesc` | for live polling; unset (relevance) not used — we want exhaustive within window |
- Response JSON: `{"articles": [{"url", "title", "seendate", "domain", "sourcecountry", "language", "tone", ...}]}`.
  `tone` is GDELT's `V2Tone` composite score (roughly −10..+10); stored
  verbatim into `alt_news_item.payload_json.v2tone` — this is the zero-cost
  fallback sentiment referenced in
  [00-overview.md](00-overview.md#why-sentiment).

### Query slices

1. **Morocco slice**: `sourcecountry:MO (theme:ECON_STOCKMARKET OR theme:ECON_INFLATION OR theme:ECON_MACRO OR theme:ECON_TRADE OR theme:ECON_BANKRUPTCY OR theme:TAX_FNCACT_BANK)`.
   Expected volume ~50–300 articles/day (confirmed by the volume-probe
   script, not assumed). No article cap — Morocco volume is naturally low
   enough that GDELT's own theme/country filter is sufficient.
2. **Global finance/macro slice**: curated theme list —
   `ECON_INFLATION`, `ECON_STOCKMARKET`, `ECON_CENTRALBANK`,
   `ECON_INTERESTRATES`, `ECON_UNEMPLOYMENT`, `ECON_CURRENCY_EXCHANGE_RATE`,
   `ECON_DEBT`, `ECON_TRADE`, `WB_678_FINANCIAL_SECTOR_DEVELOPMENT` —
   OR-joined, **no country filter**. Global volume is huge; **cap at 500
   articles/day**, selecting the top-500 by `abs(tone)` (highest-magnitude
   tone first, since the LLM scoring queue in A3 is quota-limited and
   high-magnitude-tone articles are both more likely to move markets and
   more informative to score first). The cap is applied client-side after
   fetch, not via the API (GDELT has no magnitude-sort mode).
3. **Geopolitics slice — GDELT Events 2.0, not DOC API**: geopolitical
   *events* (not articles) come from GDELT's separate **Events 2.0** CSV
   exports (`http://data.gdeltproject.org/gdeltv2/{yyyymmddhhmmss}.export.CSV.zip`,
   15-minute cadence, or the daily-summarized `events` table via BigQuery —
   this layer uses the CSV export path to stay free-tier). Filter to CAMEO
   root event codes **14–20** (protest, coerce, assault, fight, mass
   violence) with **`GoldsteinScale` ≤ −5** (materially destabilizing).
   Implemented as `fetch_gdelt_events_window(start, end) -> DataFrame` in
   `gdelt_client.py`. This feed is consumed directly by Plan C's
   geopolitical event-source adapter — Plan A only ingests it into
   `alt_news_item`-adjacent storage (payload_json) so it also has a
   sentiment-shock angle available if the LLM later scores CAMEO-derived
   headlines; the two GDELT paths (DOC articles vs. Events CSV) are
   deliberately kept separate because their schemas do not overlap
   (articles vs. structured event tuples).

### Volume-probe script

**Deliverable**: `scripts/probe_gdelt_volume.py` — runs each of the three
queries above over a rolling 30-day window, prints daily article/event
counts per query, and flags queries that blow past expected volume (Morocco
slice > 500/day, global slice near the 250-per-call pagination ceiling
requiring more aggressive sub-windowing). Run once before A1 implementation
is finalized; its output determines whether the Morocco slice needs its own
tone-magnitude cap and whether the global slice needs finer than
1-day pagination windows during backfill.

### 2019→present backfill strategy

- Backfill window: **2019-01-01 → today**, matching the platform's other
  alt-data backfills (`docs/alt-data-foundation/00-overview.md` decision
  log).
- **Month-chunked RQ jobs**: one job per (slice, calendar month), enqueued
  onto the existing `market_refresh` queue (no new queue — this ingestion
  volume does not need dedicated infra). Each job calls the DOC API with
  `startdatetime`/`enddatetime` bounding that month, paginating in
  sub-windows if the 250-record cap is hit mid-month (detect via
  `len(articles) == 250` and halve the window, retry).
- Idempotent: every insert is `ON CONFLICT (content_hash) DO NOTHING`
  (content-hash defined in
  [../alt-data-foundation/01-pit-event-store.md](../alt-data-foundation/01-pit-event-store.md)),
  so a re-run of any month-chunk is a safe no-op for already-ingested
  articles.
- Live/incremental polling after backfill catches up: same query set, no
  `startdatetime` bound (defaults to "recent"), on the `news_ingest`
  schedule (every 30 min — see
  [04-aggregation-and-factors.md](04-aggregation-and-factors.md)).

### Files

- `core/quant_core/newsflow/gdelt_client.py` — patterned on
  `core/quant_core/fundamentals/providers/stockanalysis_provider.py`'s
  `StockAnalysisFundamentalProvider` constructor shape
  (`__init__(self, *, timeout_seconds: int = 30, retries: int = 3, sleep:
  Any = time.sleep)`, exponential backoff `sleep(2**attempt)` between
  retries). Exposes `fetch_gdelt_articles(query, start, end, cap=None,
  sort_by_tone_magnitude=False) -> list[dict]` and
  `fetch_gdelt_events_window(start, end) -> pd.DataFrame`.
- `scripts/probe_gdelt_volume.py`
- `services/worker/tasks/ingest_news_gdelt.py` — three entry points:
  `ingest_gdelt_morocco_slice()`, `ingest_gdelt_global_slice()`,
  `backfill_gdelt_month(slice_name, year, month)`; all three call
  `core.quant_core.newsflow.persist.persist_items()` (below) after fetch.
- Tests: `core/tests/test_gdelt_client.py` with saved JSON response fixtures
  under `core/tests/fixtures/news/gdelt_*.json` (no live network calls in
  tests).

---

## A2 — Morocco scrapers, RSS, yfinance news

### Archive-depth probe — first deliverable

Morocco's financial news sites have no published archive-depth guarantee.
Building scrapers before knowing how far back each site's history reaches
risks building a 2019-backfill pipeline against a site that only keeps 6
months of articles. **The probe runs before any scraper is written.**

**Deliverable**: `scripts/probe_news_archives.py`. For each target site it:

1. Checks for a sitemap (`/sitemap.xml`, `/sitemap_index.xml`) and, if
   present, parses the oldest `<lastmod>`/URL date found.
2. Checks for an RSS/Atom feed (`<link rel="alternate" type="application/rss+xml">`
   in the homepage `<head>`, or well-known paths `/feed`, `/rss`) and
   inspects the feed's article-date range.
3. Falls back to paginating the site's article-listing/archive pages
   (`/category/economie/page/N` or equivalent) until either a 404/empty page
   or a rate-limit response is hit, recording the oldest date reached and
   the page count required.
4. Emits one row per site to a report table: site, oldest reachable article
   date, mechanism used (sitemap / RSS / pagination), pages probed, any
   robots.txt disallow paths that block the standard approach.

**Output**: `docs/sentiment-layer/07-archive-depth-report.md` (generated by
running the probe script against live sites — not authored as part of this
planning pass, since its content is real measured data, not a design
decision). Each target site's **actual backfill scope for A2 is whatever
this report measures**, not an assumption baked into this document. If a
site's reachable history is shallower than 2019, that site's coverage window
is recorded in the report and the sentiment IC study
([05-validation-gates.md](05-validation-gates.md)) restricts any analysis
touching that site to its measured window. The GDELT Morocco slice
(A1) already guarantees a 2019+ minimum regardless of scraper depth, so no
site being shallow blocks the layer — it only narrows that one source's
contribution.

### Target sites

| Site | Notes |
|---|---|
| Medias24 | French-language, one of the most active MASI-relevant outlets; also aliased historically as "LeBoursier" content |
| Boursenews.ma | Casablanca-Bourse-focused financial news |
| fnh.ma (Finances News Hebdo) | Weekly + daily financial news |
| casablanca-bourse.com (announcements section) | Official exchange announcements — company disclosures, index changes |
| AMMC filings (ammc.ma) | Regulator filings — prospectuses, disclosure notices; lower frequency, high relevance |

### Scraper pattern — copy `BourseDirectAdapter`

`core/quant_core/data.py:853` (`BourseDirectAdapter(BaseDataSource)`) is the
existing HTTP-scrape-with-rate-limit pattern in this codebase and is what
`morocco_scrapers.py` copies structurally:

- One `requests.Session()` reused across all fetches for a given run (not
  re-created per request).
- Constructor takes `rate_limit_delay_s: float = 0.5` and the fetch loop
  does `time.sleep(self.rate_limit_delay_s)` **before** every request except
  the first (`if i > 0: time.sleep(...)`).
- Per-item HTTP/parse errors are caught and logged, not raised — one bad
  page does not abort a bulk run; `BourseDirectAdapter._load_impl` returns
  an empty result for the failed symbol and continues the loop. The news
  scrapers apply the same per-article-page try/except-continue discipline.
- Configuration (URL templates, format) comes from environment variables
  with a constructor-arg override, e.g. `BOURSE_DIRECT_URL_TEMPLATE` — the
  Morocco scrapers follow the same "env var with explicit override
  parameter" shape rather than hardcoding URLs, since site markup/URL
  structure is exactly the kind of thing that breaks silently and needs a
  fast fix without a code deploy.

**Difference from `BourseDirectAdapter`**: that adapter fetches one
structured Excel/CSV download per symbol; the news scrapers parse HTML
listing pages into article stubs (title, URL, published date) then fetch
each article page for full text — one class per site in
`morocco_scrapers.py`, each implementing a shared
`MoroccoScraper.fetch_since(cutoff_date) -> list[NewsItemRecord]` interface
so `ingest_news_feeds.py` can iterate all sites uniformly.

### Rate-limiting / robots etiquette

- Every scraper class respects `robots.txt` (fetched once per run via
  `urllib.robotparser`, cached for the run's duration); a `Disallow` on a
  target path is honored (site is skipped for that path, run continues).
- Default `rate_limit_delay_s = 1.0` for these sites (more conservative than
  `BourseDirectAdapter`'s 0.5s, since these are lower-capacity content sites
  rather than the exchange's own download endpoint).
- A single custom `User-Agent` string identifying the ingestion bot is set
  on every request (no user-agent spoofing).
- AMMC filings scraper additionally caps to **1 request per 2 seconds** —
  it's a public regulator and the lowest-frequency source; there is no
  throughput reason to go faster.

### RSS poller

`core/quant_core/newsflow/rss_client.py`:

- Standard-library `xml.etree.ElementTree` RSS/Atom parsing (no new feed
  parser dependency).
- **ETag / Last-Modified caching**: each feed's last-seen `ETag` and
  `Last-Modified` response headers are persisted (one row per feed URL,
  keyed table `alt_news_feed_state` — extension to the F1 migration, or a
  small Redis hash if a DB migration for this is overkill; DB table is
  preferred for restart-durability) and sent as `If-None-Match` /
  `If-Modified-Since` on the next poll — a `304 Not Modified` response short
  circuits without reparsing.
- **Feed registry**: `data/news_feed_registry.json` — a flat list of `{name,
  url, source_country, default_topics}` entries, one per polled feed,
  human-editable (adding a feed is a JSON edit, not a code change). Mirrors
  the `data/masi_aliases.json` convention used in A4
  ([03-entity-mapping.md](03-entity-mapping.md)).

### yfinance news

`core/quant_core/newsflow/yfinance_news.py` — thin wrapper around
`yfinance.Ticker(sym).news` for the roadmap's US/international tickers
(not MASI names, which have no yfinance news coverage). Read-only, low
volume, feeds the same `_persist_items()` funnel with `source='yfinance'`.
Scoped to whatever ticker list the roadmap's multi-market port plan defines;
this layer does not itself expand the tracked-ticker universe.

### The persistence funnel

Every writer above — GDELT, each Morocco scraper, the RSS poller, and
yfinance news — funnels through one function:
`core/quant_core/newsflow/persist.py::persist_items(db, items:
list[NewsItemRecord]) -> PersistSummary`. Responsibilities:

1. Compute `content_hash` (defined in
   [../alt-data-foundation/01-pit-event-store.md](../alt-data-foundation/01-pit-event-store.md))
   for each item and `INSERT ... ON CONFLICT (content_hash) DO NOTHING` into
   `alt_news_item`.
2. For newly-inserted items only, upload the raw article text to S3 under
   `build_news_raw_object_key(source, published_date, content_hash)`
   (defined alongside the other key builders in `core/quant_core/s3_keys.py`,
   next to the existing `build_market_store_object_key` /
   `build_dataset_object_key`) and set `alt_news_item.s3_text_key`.
3. Returns a `PersistSummary(inserted, duplicates, errors)` count that every
   ingestion task logs and returns as its RQ job result — this is what the
   `/ingest-health` endpoint (Phase U1, out of scope here) reads.

Having one funnel means content-hash dedup and S3 raw-text storage are
implemented exactly once; a new source (a sixth scraper, a new RSS feed) is
just a producer of `NewsItemRecord`s and never touches persistence logic
directly.

### Tests

`core/tests/fixtures/news/` holds saved HTML fixtures (one file per site,
captured from a real listing + article page) so `morocco_scrapers.py` tests
run offline and deterministically. RSS tests use saved XML fixtures under
the same directory. GDELT tests use the JSON fixtures noted above.
