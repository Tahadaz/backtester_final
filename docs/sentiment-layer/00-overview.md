# Overview and Score Taxonomy

## Station Mandate

Ingest world and Moroccan news, score it per subject with an LLM (with a
zero-cost GDELT-tone fallback), map company-relevant items to MASI symbols,
and export daily sentiment indices that go through the same no-look-ahead,
FDR-controlled validation gate as every other factor in this repo before they
can influence a product page.

This is **Plan A** of the alt-data program. It shares one PIT event store and
one validation policy with Plan B (macro nowcasting) and Plan C (event-study
backtesting) — see [Shared Foundation](#shared-foundation) below. Nothing in
this layer touches Signal Engine, WFO, or Dashboard behavior; sentiment
series are research-only until they clear the gates in
[05-validation-gates.md](05-validation-gates.md).

---

## Why Sentiment

- The platform's only validated edge today is the PIT value strategy on
  Casablanca Bourse. Technical (S/R, WFO) and macro factor layers exist but
  no textual/news signal has ever been ingested — this is a genuinely new
  data modality, not a rebuild of something that already works.
- Two costs make this worth doing carefully rather than skipping straight to
  a backtest: Morocco has no news API (scraping only, unknown archive depth)
  and LLM-scored historical text carries **lookahead bias** — a model
  trained after 2024 scoring a 2021 headline "knows" things a contemporary
  reader didn't (arXiv 2512.23847, 2309.17322). Every score this layer
  produces therefore carries model/provenance metadata, and any score
  derived from pre-training-cutoff text is labeled `pit_grade='upper_bound'`
  and excluded from promotion — see
  [../alt-data-foundation/02-validation-policy.md](../alt-data-foundation/02-validation-policy.md).
- GDELT's own tone score (`V2Tone`) is captured at ingest time as a
  zero-cost, immediately-available fallback sentiment signal, so the layer
  produces *something* usable before the LLM scoring pipeline (A3) is even
  built or while free-tier LLM quota is exhausted.

## Goals

1. Ingest news from GDELT (world + Morocco slice), Moroccan financial
   news sites, RSS feeds, and yfinance — deduplicated, hashed, PIT-stamped,
   archived to S3 in raw form.
2. Score each article's per-subject sentiment with a provider-agnostic LLM
   client, with full provenance for lookahead-bias accounting.
3. Map company-relevant articles to MASI symbols via a curated French-alias
   table.
4. Aggregate to daily sentiment indices per subject (symbol or topic×region)
   and export them as ordinary factor series so the existing factor/IC
   machinery (`compute_factor_relevance`, `stats/fdr.py`, `stats/ic.py`)
   applies unchanged.
5. Gate every derived series through a pre-registered IC study before it is
   eligible for any product surface.

## What This Layer Does Not Do

- It does not write to Signal Engine, WFO, Dashboard, or any product table.
  `alt_sentiment_daily` and the derived `SENT_*` factor series are the only
  outputs, and they are consumed by research tooling (Analytics /
  «Sentiment & Événements» tab, Plan C event sources) — never by the trading
  signal path — until [05-validation-gates.md](05-validation-gates.md) is
  passed.
- It does not attempt company-level sentiment for non-MASI names beyond the
  yfinance-news roadmap tickers.
- It does not replace or restate the PIT event-store schema or the
  cross-layer validation policy — both live in `docs/alt-data-foundation/`
  and are linked, not duplicated, throughout this folder.

---

## Score Taxonomy

Every LLM (or GDELT-tone-fallback) score is attached to exactly one
**subject**. A subject is either a company or a topic×region pair. This
taxonomy is frozen for prompt v1 (see
[02-llm-scoring.md](02-llm-scoring.md)) — adding a topic or region is a
prompt-version bump, not a silent schema change.

### Topics

| Topic | Meaning |
|---|---|
| `company_specific` | News about one identifiable company (earnings, contracts, management, litigation) |
| `macro` | Domestic macro conditions (inflation, growth, fiscal policy, HCP/BAM releases) |
| `economics` | General economic commentary not tied to a specific release |
| `geopolitics` | Cross-border conflict, sanctions, trade disputes, regional instability |
| `politics` | Domestic/foreign political events without a direct economic release |
| `markets` | Market-structure commentary (index moves, flows, IPOs, liquidity) not tied to one company |
| `commodities` | Oil, phosphates, wheat, gold, metals |
| `other` | Does not fit the above; still scored, excluded from factor export by default |

### Regions

| Region | Meaning |
|---|---|
| `ma` | Morocco |
| `us` | United States |
| `eu` | European Union / Eurozone |
| `asia` | Asia-Pacific |
| `global` | Not region-specific, or explicitly multi-region |

### Subject Keys

Two subject types, distinguished by `subject_type` on `alt_news_score`
(schema: [../alt-data-foundation/01-pit-event-store.md](../alt-data-foundation/01-pit-event-store.md)):

- **`symbol`** — a MASI-listed company. Key format: `symbol:{TICKER}`, e.g.
  `symbol:ATW`, `symbol:IAM`. Produced by entity mapping
  ([03-entity-mapping.md](03-entity-mapping.md)) applied to
  `company_specific`-topic scores.
- **`topic_region`** — a topic×region pair, independent of any single
  company. Key format: `topic_region:{topic}:{region}`, e.g.
  `topic_region:macro:ma`, `topic_region:geopolitics:global`,
  `topic_region:commodities:global`. One article can and usually does
  produce multiple `topic_region` scores (e.g. a Brent-price story scores
  both `topic_region:commodities:global` and
  `topic_region:markets:ma` if it discusses the Casablanca energy sector).

A single article therefore fans out into 1..N rows in `alt_news_score` — one
per subject the LLM (or fallback) identified, each independently
sentiment-scored, confidence-scored, and relevance-scored. This is what lets
[04-aggregation-and-factors.md](04-aggregation-and-factors.md) build clean
per-subject daily aggregates without cross-subject contamination.

---

## Phase Map: A1–A6

| Phase | Deliverable | Doc |
|---|---|---|
| A1 | GDELT DOC 2.0 + Events 2.0 connector, 2019→present backfill | [01-data-sources.md](01-data-sources.md) |
| A2 | Morocco scrapers, RSS poller, yfinance news, archive-depth probe | [01-data-sources.md](01-data-sources.md) |
| A3 | Provider-agnostic LLM scoring pipeline | [02-llm-scoring.md](02-llm-scoring.md) |
| A4 | Entity → MASI symbol mapping (French aliases) | [03-entity-mapping.md](03-entity-mapping.md) |
| A5 | Daily aggregates, factor-series export, scheduling | [04-aggregation-and-factors.md](04-aggregation-and-factors.md) |
| A6 | Validation gates (research-only until passed) | [05-validation-gates.md](05-validation-gates.md) |

Full self-contained work packages (files to create/modify, tests, E2E
verification, done-criteria) are in [06-phases.md](06-phases.md).

### Ordering

```
      ┌─── A1 (GDELT) ───┐
      │                  ├──► A4 (entity mapping) ──► A3 (LLM scoring) ──► A5 (aggregates + factors) ──► A6 (validation)
      └─── A2 (scrapers) ┘
```

- **A1 and A2 run in parallel** — independent ingestion sources, both funnel
  through the same `_persist_items()` (see
  [01-data-sources.md](01-data-sources.md)).
- **A4 before A3**: entity mapping can run against already-ingested,
  unscored articles (it only needs title/body text), and A3's batching
  priority (`symbol-mapped > macro:ma > global`) depends on A4 having
  already tagged which articles carry a `symbol:*` candidate.
- **A3 depends on A1 ∥ A2** only for *some* data — it can start GDELT-only
  the moment A1 lands, without waiting for A2's scrapers.
- **A5 depends on A3** (needs scored subjects to aggregate) and implicitly
  on A4 (per-symbol series require the mapping to exist).
- **A6 depends on A5** (the IC study runs against exported `SENT_*` series).

---

## Shared Foundation

This layer builds on, but does not redefine, two foundation documents:

- **PIT event store** — table schemas for `alt_news_item`, `alt_news_score`,
  `alt_sentiment_daily`, the S3 raw-text layout, and the PIT join rule (18:00
  Africa/Casablanca availability cutoff, `align_factor_to_target(...,
  lag_rule="precede_open")`, `pit_grade='upper_bound'` propagation) are
  defined once in
  [../alt-data-foundation/01-pit-event-store.md](../alt-data-foundation/01-pit-event-store.md).
  Every doc in this folder assumes that schema and that join rule.
- **Validation policy** — the cross-layer FDR/multiple-testing policy,
  promotion criteria, and verdict-artifact format are defined once in
  [../alt-data-foundation/02-validation-policy.md](../alt-data-foundation/02-validation-policy.md).
  [05-validation-gates.md](05-validation-gates.md) in this folder states
  only the Plan-A-specific numeric thresholds and cites that policy for the
  shared machinery (BH-FDR, Newey-West).

---

## Document Map

| # | Document | Covers |
|---|---|---|
| 00 | [00-overview.md](00-overview.md) | This document |
| 01 | [01-data-sources.md](01-data-sources.md) | GDELT, Morocco scrapers, RSS, yfinance news, ingestion funnel |
| 02 | [02-llm-scoring.md](02-llm-scoring.md) | Provider-agnostic LLM client, quotas, prompt v1, provenance |
| 03 | [03-entity-mapping.md](03-entity-mapping.md) | French alias table, matching rules, remap task |
| 04 | [04-aggregation-and-factors.md](04-aggregation-and-factors.md) | Daily aggregate math, factor export, scheduler wiring |
| 05 | [05-validation-gates.md](05-validation-gates.md) | IC study design, numeric gates, verdict artifacts |
| 06 | [06-phases.md](06-phases.md) | A1–A6 work packages for implementation |
