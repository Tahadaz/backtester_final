# Alt-Data Foundation — Overview

## Document map

| # | Document | Contents |
|---|---|---|
| 00 | `00-overview.md` (this file) | Context, research findings, locked decisions, dependency graph, risks |
| 01 | [01-pit-event-store.md](01-pit-event-store.md) | Phase F1: table schemas, migration plan, S3 layout, the PIT join rule |
| 02 | [02-validation-policy.md](02-validation-policy.md) | Unified gating policy across all three layers, verdict-artifact convention |
| 03 | [03-api-ui.md](03-api-ui.md) | Phase U1: `sentiment_events` router + `/sentiment-events` research tab |

Sibling plan folders (each depends on this foundation):

- [`../sentiment-layer/`](../sentiment-layer/00-overview.md) — Plan A, news sentiment
- [`../macro-nowcast-layer/`](../macro-nowcast-layer/00-overview.md) — Plan B, macro nowcasting
- [`../event-backtest-layer/`](../event-backtest-layer/00-overview.md) — Plan C, event-based backtesting

This folder follows the `docs/factor-layer/` numbered-markdown convention (see `docs/factor-layer/00-INDEX.md`): each document is self-contained, cites repo-relative file paths, and states status/decisions rather than narrating exploration.

---

## Why this initiative

The platform's validated edge today is the PIT value strategy on Casablanca Bourse; a technical layer (S/R, WFO) and a macro factor layer (`docs/factor-layer/`) already exist and are production-gated. The user wants three new, currently-absent capabilities:

- **Plan A — News Sentiment**: scrape/ingest world + Moroccan news, LLM-score per subject (company, macro, geopolitics, economics, politics…), produce daily sentiment indices per topic/region and per symbol.
- **Plan B — Macro Nowcasting**: continuously-updating estimators of macro indicators — a Morocco inflation nowcast built from public high-frequency data, a Bank Al-Maghrib (BAM) rate-direction classifier, plus ingestion of ready-made US nowcasts (Cleveland Fed inflation nowcast, Atlanta Fed GDPNow, NY Fed WEI) — producing a surprise engine, a rate-direction signal, and regime flags.
- **Plan C — Event-Based Backtesting**: a generic event-study engine (AR/CAR/CAAR) plus an event-conditioned strategy runner, covering four event types: company events/PEAD, macro releases, sentiment shocks, geopolitical events.

These three plans share one PIT event store, one validation/gating policy, and one research-only UI surface — hence "alt-data **foundation**" as its own doc folder, separate from the three layer-specific plans.

## Not greenfield: what already exists

Exploration prior to this plan found substantial reusable machinery. Nothing below needs to be rebuilt:

| Capability | Existing module |
|---|---|
| Macro factor registry + DB-backed spec table | `core/quant_core/macro.py` (`MacroSeriesSpec`), `macro_factor_meta` table (`services/api/app/models.py`) |
| Factor signal spec registry | `core/quant_core/research/factors/signals.py` (`FactorSignalSpec`) |
| IC / relevance machinery | `core/quant_core/research/factors/relevance.py` (`compute_factor_relevance`, `compute_ic_series`, `compute_pair_relevance`) |
| FDR / multiple-testing | `core/quant_core/research/stats/fdr.py` (`benjamini_hochberg`, `bh_adjusted_pvalues`, `harvey_liu_sharpe_haircut`) |
| Newey-West IC stats | `core/quant_core/research/stats/ic.py` (`rank_ic`, `ic_decay_curve`, `conditional_return_tstat`, `_newey_west_var`) |
| Regime conditioning | `core/quant_core/research/factors/conditions.py`, `conditioned_variants.py` |
| PIT alignment | `core/quant_core/research/alignment.py` (`align_factor_to_target`) — see `docs/factor-layer/04-calendar-alignment.md` |
| Dated curated event calendar | `FundamentalCatalyst` table (`services/api/app/models.py:1061`) |
| Event replay backtest engine | `services/api/app/routers/analytics.py::_build_macro_backtest_replay` |
| Scheduler | `services/api/app/services/scheduler_registry.py` (`ScheduleKind`, `ScheduleSpec`), `services/worker/tasks/scheduler_dispatch.py` |
| S3 key conventions | `core/quant_core/s3_keys.py` |
| RQ ingestion patterns | `services/worker/tasks/ingest_macro_series.py`, `refresh_market_data.py` |

**What is genuinely new**: news ingestion + LLM scoring (zero NLP/LLM code exists in the repo today), macro release/nowcast persistence, and a generic event-study utility. Everything else is extension of existing registries and reuse of existing stats/alignment code.

## Research findings baked into the design

### Lookahead-bias literature (LLM sentiment scoring)

Two findings drive the provenance requirements in [01-pit-event-store.md](01-pit-event-store.md):

- **arXiv 2512.23847** and **arXiv 2309.17322** document that LLMs trained on data through a knowledge cutoff can "recall" post-event outcomes when scoring historical news text, inflating backtested sentiment-return correlations relative to what a live, real-time scoring pipeline would have produced. This is a structural bias, not a bug — it cannot be fixed by prompting alone.
- **Mitigations adopted**: optional name-anonymization at scoring time (entity → `SOCIETE_A` placeholder, recorded per score); mandatory per-score model/provenance metadata (`model_id`, `provider`, `prompt_version`, `anonymized`, `scored_at`); a `pit_grade='upper_bound'` label attached to any score whose source text predates the scoring model's training cutoff, propagated through every downstream aggregate, backtest artifact, and UI badge. Only **live-collected** scores (scored at or near publication time, going forward) are promotion-eligible for Signal/Dashboard surfaces — historical LLM-scored backfill is permanently capped at "upper bound / research only".

### Morocco data reality

- Morocco has no news API. Ingestion is scraping-based: Medias24/LeBoursier, Boursenews, FNH, casablanca-bourse.com, AMMC. **Archive depth is unknown up front** — sitemap pagination and RSS availability vary by site and were not verified before this plan was written.
- World/macro news is covered via **GDELT 2.0 DOC API** (free, includes V2Tone, `sourcecountry:MO` filter for Morocco slice, 2019+ backfill available) plus `yfinance` news and general RSS feeds.
- **Design consequence**: Plan A's first work package (A2) is a probe script, not a scraper — see `../sentiment-layer/01-data-sources.md`. Coverage windows discovered by the probe become the validation sample boundary; they are not assumed.

### Thin-sample warnings

Morocco macro series are structurally low-frequency: roughly 120 CPI prints and roughly 48 BAM policy meetings per decade. This is small-sample statistics territory where naive backtesting produces false discoveries with high probability. **Every layer therefore carries an explicit numeric kill-switch gate and a multiple-testing control**, detailed in full in [02-validation-policy.md](02-validation-policy.md). Nothing from any of the three plans reaches a Signal or Dashboard page until it clears its layer's gate — until then it is visible only on the research-only `/sentiment-events` tab (see [03-api-ui.md](03-api-ui.md)).

## Locked user decisions

These were confirmed with the user and are not open questions for implementers:

| Decision | Value |
|---|---|
| Data sourcing | All-free sources only (GDELT, yfinance, FRED/ALFRED, Cleveland Fed/Atlanta Fed/NY Fed CSV feeds, FAO FPI, HCP/BAM public pages) |
| LLM scoring | Free API tiers first: OpenRouter `:free` Kimi/GLM → Groq → Gemini Flash compat; Ollama + Qwen3-8B on the OCI free ARM VM as last-resort fallback. Client is a provider-agnostic OpenAI-compatible chat-completions caller — no new SDK dependency. |
| Sentiment taxonomy | Per-subject scoring (company symbol, or `topic:region` key such as `macro:ma`), not a single document-level score |
| Macro build/ingest split | **Build** Morocco (inflation nowcast, BAM classifier) from scratch; **ingest** ready-made US nowcasts (Cleveland Fed, GDPNow, WEI) rather than rebuilding them |
| Backfill horizon | 2019 → present, wherever source coverage allows |
| UI surface | One French-language research tab, `/sentiment-events` ("Sentiment & Événements"), gated off Signal/Dashboard until each sub-capability passes its numeric gate |
| Event types (Plan C) | All four in scope: company/PEAD, macro releases, sentiment shocks, geopolitical |

## Cross-plan dependency graph

```
F1 (PIT event store — blocks everything)
├─ A1 ∥ A2 ∥ B1 ∥ B2 ∥ C1     ← up to 5 parallel work packages, each a self-contained delegation unit
├─ A4 → A3 → A5 → A6            (sentiment-layer, see ../sentiment-layer/06-phases.md)
├─ B3 → B4 ∥ B5 → B6            (macro-nowcast-layer, see ../macro-nowcast-layer/06-phases.md)
├─ C2 → C3 → C4                 (event-backtest-layer, see ../event-backtest-layer/05-phases.md)
└─ U1 (after A5 + B3 + C1)      (this folder, 03-api-ui.md)
```

Notes on the graph:

- **F1 is a hard prerequisite** for every other work package — no table, no ingestion.
- **A1 (GDELT), A2 (Morocco scrapers/RSS), B1 (input-series ingestion), B2 (release calendar), C1 (event-study utility)** have no dependencies on each other and can be delegated as parallel Sonnet work packages once F1 lands.
- **C2 (event-source adapters)** has partial dependencies: source 1 (PEAD) is available immediately (reuses `FundamentalCatalyst`), source 2 (macro releases) needs B5 (surprise engine), source 3 (sentiment shocks) needs A5 (daily aggregates), source 4 (geopolitical) needs A1 (GDELT Events).
- **U1 (API/UI)** intentionally starts only after A5 + B3 + C1 — the minimum needed for the three headline panels (sentiment indices, one nowcast series, one event-study result) to render with real data; panels for not-yet-ready sub-capabilities degrade gracefully (see [03-api-ui.md](03-api-ui.md)).

## Top 5 risks & mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | Free-LLM quota exhaustion stalls sentiment scoring | GDELT `V2Tone` is stored at ingest time as a zero-cost fallback sentiment signal, independent of LLM availability; provider registry does quota-aware rotation across OpenRouter/Groq/Gemini/Ollama; on total exhaustion, RQ jobs delay-retry (30 min) rather than fail; backlog depth is surfaced on `/ingest-health` |
| 2 | Morocco news archives shallower than assumed (2019+) | Archive-depth probe (`scripts/probe_news_archives.py`) is Plan A's first deliverable, run **before** any scraper is written; it re-scopes per-source backfill depth; GDELT's Morocco slice (`sourcecountry:MO`) guarantees a 2019+ floor independent of site archive depth; discovered coverage windows are recorded and validation is restricted to them |
| 3 | LLM lookahead contamination inflates historical backtests | Per-score provenance columns (`model_id`, `scored_at`, `anonymized`, `prompt_version`) on every `alt_news_score` row; `pit_grade='upper_bound'` propagated to every derived aggregate, backtest artifact, and UI badge; only live-collected (post-deployment) scores are promotion-eligible for product surfaces |
| 4 | Tiny macro samples (~120 CPI prints, ~48 BAM meetings/decade) × a large parameter grid ⇒ false discoveries | Pre-registered frozen grids (documented per layer, see [02-validation-policy.md](02-validation-policy.md)); BH-FDR via `core/quant_core/research/stats/fdr.py::benjamini_hochberg`; explicit n-minimums per gate; leave-one-out CV + climatology baseline for the BAM classifier; Diebold-Mariano-vs-naive-AR gate for the CPI nowcast; default posture is "park, don't promote" |
| 5 | Derived (non-Yahoo) factor series break the existing yfinance ingestion path | `macro_factor_meta.yahoo_ticker` is `NOT NULL UNIQUE` (verified live at `services/api/app/models.py:503`) — derived rows cannot simply leave it null. New `source_kind` column (`'yahoo'` default, `'derived'` for computed series) plus a mandatory `yahoo_ticker = canonical_id` placeholder for derived rows plus a skip-guard in `services/worker/tasks/ingest_macro_series.py`, backed by a dedicated regression test. Full detail in [01-pit-event-store.md](01-pit-event-store.md#macro_factor_meta-extension). |

## Verification model

- Every phase across all four plan folders ships pytest units before merge, colocated with existing test suites (`core/tests/`, `services/api/tests/`, `services/worker/tests/`).
- End-to-end checks run on the docker-compose stack after F1, A5, B3, C3, and U1: apply migrations, trigger the relevant `ScheduleKind` via the ops endpoint, and verify DB rows / MinIO (S3) objects / `/sentiment-events` rendering.
- Final acceptance for the whole initiative: `/sentiment-events` renders all panels from live-ingested data; the sentiment IC study, the nowcast OOS report, and the event-study suite each produce a verdict artifact in S3 (`alt_data/studies/...`); `graphify update .` is run after each implementation session per this repo's `CLAUDE.md` convention.

## Execution model

Per the user's standing rule (implementation via Sonnet subagents, spec-and-review by the orchestrator), each phase in each plan folder is written as a self-contained work package: files to create/modify, reuse targets, tests, and an E2E verification recipe. See `06-phases.md` in `../sentiment-layer/`, `../macro-nowcast-layer/`, and `05-phases.md` in `../event-backtest-layer/` for the phase-by-phase breakdown; F1's work package is in [01-pit-event-store.md](01-pit-event-store.md#f1-work-package) and U1's in [03-api-ui.md](03-api-ui.md#u1-work-package).
