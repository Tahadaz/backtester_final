# Phase U1 — API & Research-Tab UI

Thin, French-language, research-only surface for all three alt-data layers. Starts only after **A5 + B3 + C1** (see [00-overview.md](00-overview.md#cross-plan-dependency-graph)) — the minimum needed for the three headline panels (sentiment indices, one nowcast series, one event-study result) to have real data to render. Not linked from Signal or Dashboard navigation, per the hard rule in [02-validation-policy.md](02-validation-policy.md#nothing-reaches-signaldashboard-before-gates).

## Router: `services/api/app/routers/sentiment_events.py`

Mirrors the structure of `services/api/app/routers/factor_signals.py`, verified (first ~80 lines):

```python
"""API endpoints for Phase 2/3 Factor×TA signal configuration and results.

Routes:
    GET  /factor-signals/{symbol}/config                   — per-stock factor enable state
    PUT  /factor-signals/{symbol}/config                   — update per-stock factor enables
    GET  /factor-signals/{symbol}/{horizon}                — Factor×TA family results (engine + wfo)
    POST /factor-signals/{symbol}/{horizon}/run            — enqueue both engine AND wfo jobs
    POST /factor-signals/{symbol}/{horizon}/wfo/run        — enqueue wfo job only
    GET  /factor-signals/{symbol}/{horizon}/detail         — full detail for one family (click-to-expand)
    GET  /factor-signals/{symbol}/{horizon}/factor-state   — current macro factor values + condition outcomes
"""
from __future__ import annotations
...
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from services.api.app.db import get_db
from services.api.app.models import SignalEngineFamilyResult, WfoSignalSummary
from core.quant_core.macro import get_macro_series, get_macro_series_by_symbol
from core.quant_core.research.alignment import align_factor_to_target
...

router = APIRouter(prefix="/factor-signals", tags=["factor-signals"])
```

The pattern to reuse: (1) a module docstring listing every route with its HTTP verb and one-line purpose, (2) a single `router = APIRouter(prefix=..., tags=[...])` at module scope, (3) small private helper functions above the Pydantic schemas (`_factor_specs()`, `_factor_tickers()` in `factor_signals.py`), (4) Pydantic response models defined immediately below the router before the route functions, (5) imports of domain logic from `core.quant_core.*` rather than reimplementing it in the router. `sentiment_events.py` follows the same five conventions:

```python
"""API endpoints for the alt-data research surface (Plan A/B/C, Phase U1).

Research-only: nothing here is read by Signal Engine, WFO, or Dashboard code paths.
See docs/alt-data-foundation/02-validation-policy.md for the promotion-gate rule this
router exists to respect.

Routes:
    GET  /sentiment-events/ingest-health                   — per-source freshness, scoring backlog, LLM quota state
    GET  /sentiment-events/indices                          — sentiment index time series (per topic/region/symbol)
    GET  /sentiment-events/nowcast/{series_id}               — nowcast-vs-actual history + next-release countdown + OOS verdict
    GET  /sentiment-events/rate-probability                  — BAM P(hike)/P(hold)/P(cut) current + history
    GET  /sentiment-events/event-studies                     — CAAR curves + significance + promotion status per grid cell
    POST /sentiment-events/refresh/{kind}                    — manually trigger an ingestion/scoring/aggregation task (ops use)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from services.api.app.db import get_db
from services.api.app.models import (
    AltNewsItem, AltNewsScore, AltSentimentDaily,
    MacroReleaseSeries, MacroRelease, NowcastValue,
)
from core.quant_core.newsflow.domain import Topic, Region

router = APIRouter(prefix="/sentiment-events", tags=["sentiment-events"])
```

### Endpoint sketches

**`GET /sentiment-events/ingest-health`**

Per-source freshness (latest `observed_at` per news source, latest `release_time` per macro series), LLM scoring backlog depth (count of `alt_news_item` rows with no corresponding `alt_news_score` at the current `prompt_version`), and current LLM provider quota state (read from the Redis quota counters described in `../sentiment-layer/02-llm-scoring.md`).

```jsonc
// Response
{
  "sources": [
    {"source": "gdelt_doc", "last_observed_at": "2026-07-13T14:02:00Z", "items_last_24h": 214, "status": "ok"},
    {"source": "medias24", "last_observed_at": "2026-07-12T09:15:00Z", "items_last_24h": 3, "status": "stale"}
  ],
  "scoring_backlog": {"unscored_items": 128, "oldest_unscored_published_at": "2026-07-12T22:00:00Z"},
  "llm_quota": [
    {"provider": "openrouter", "used_today": 480, "limit_today": 500, "status": "near_limit"},
    {"provider": "groq", "used_today": 12, "limit_today": 1000, "status": "ok"},
    {"provider": "ollama", "used_today": 0, "limit_today": null, "status": "ok"}
  ]
}
```

**`GET /sentiment-events/indices`**

Query params: `subject_type: 'symbol'|'topic_region'`, `subject_key: str`, `start: date`, `end: date`. Returns the daily aggregate series straight from `alt_sentiment_daily`, plus the latest [Gate 1](02-validation-policy.md#gate-1--sentiment-ic-gate-plan-a-phase-a6) verdict for that subject.

```jsonc
{
  "subject_type": "topic_region",
  "subject_key": "macro:ma",
  "series": [
    {"date": "2026-07-10", "n_items": 12, "sent_mean": 0.18, "sent_weighted": 0.21, "shock_z": 0.4, "pit_grade": "live"}
  ],
  "gate": {"promotable": false, "reason": "failed: ic_tstat_ge_2_0", "run_date": "2026-07-13"}
}
```

**`GET /sentiment-events/nowcast/{series_id}`**

Nowcast-vs-realized history (joins `nowcast_value` against `macro_release` on `target_period`), next scheduled release countdown (from `macro_release` rows with `status='scheduled'`), and the latest [Gate 2](02-validation-policy.md#gate-2--nowcast-gate-plan-b-phase-b3) OOS verdict.

```jsonc
{
  "series_id": "MA_CPI_YOY",
  "history": [
    {"target_period": "2026-06", "nowcast_value": 2.1, "nowcast_std": 0.3, "actual_value": 2.3, "model_version": "ridge_bridge_v1"}
  ],
  "next_release": {"period": "2026-07", "expected_release_time": "2026-08-22T09:00:00+01:00"},
  "gate": {"promotable": false, "rmse_ratio": 0.97, "dm_pvalue": 0.14, "oos_months": 41}
}
```

**`GET /sentiment-events/rate-probability`**

Current BAM P(hike)/P(hold)/P(cut) from the latest `nowcast_value` row for `series_id='BAM_POLICY_RATE'`, plus meeting-by-meeting history and the latest [Gate 3](02-validation-policy.md#gate-3--bam-rate-direction-classifier-gate-plan-b-phase-b4) verdict.

```jsonc
{
  "current": {"meeting_date": "2026-09-24", "p_hike": 0.05, "p_hold": 0.82, "p_cut": 0.13},
  "history": [
    {"meeting_date": "2026-06-18", "p_hike": 0.03, "p_hold": 0.90, "p_cut": 0.07, "actual": "hold"}
  ],
  "gate": {"promotable": false, "loo_log_loss": 0.61, "climatology_log_loss": 0.58, "hit_rate_non_hold": 0.55}
}
```

**`GET /sentiment-events/event-studies`**

Query params: `event_type`, `window`, `benchmark` (all optional; omitted = full pre-registered grid). Returns CAAR curves and the [Gate 4](02-validation-policy.md#gate-4--event-study-promotion-gates-plan-c-phase-c4) verdict per cell, always including raw p, BH q (both tiers), and n_events per the two-tier FDR display rule.

```jsonc
{
  "cells": [
    {
      "event_type": "macro_release", "window": "[0,+10]", "benchmark": "market_adjusted",
      "n_events": 34,
      "caar_curve": [{"day": 0, "caar": 0.001}, {"day": 10, "caar": 0.014}],
      "raw_pvalue": 0.031, "bh_q_family": 0.08, "bh_q_full_grid": 0.12,
      "bootstrap_ci": [-0.002, 0.029],
      "wfo_oos_sharpe_net": 0.4,
      "sign_stable_both_halves": true,
      "promotable": false,
      "reason": "failed: bh_q_le_0_05_full_grid"
    }
  ]
}
```

**`POST /sentiment-events/refresh/{kind}`**

`kind` is one of the `ScheduleKind` values added by Plan A/B/C (`news_ingest`, `news_sentiment_scoring`, `sentiment_daily_aggregate`, `refresh_macro_releases`, `refresh_nowcasts`, `event_study_refresh` — see the phase docs in each sibling folder for the exact `ScheduleKind` additions). Enqueues the corresponding RQ task immediately, same pattern as any existing manual-trigger ops endpoint in this repo. Response is `{"enqueued": true, "job_id": "..."}`.

## Frontend: `frontend/app/sentiment-events/page.tsx`

New Next.js page. French section labels, per the locked decision in [00-overview.md](00-overview.md#locked-user-decisions) (one French research tab, gated).

**Page title**: « Sentiment & Événements »

**Sections** (in page order):

1. **« Santé de l'ingestion »** — renders `GET /sentiment-events/ingest-health`: a status table (source, dernière mise à jour, statut) plus the LLM quota strip. A source with `status: "stale"` renders with a warning tint; this section never blocks the rest of the page from rendering (see [Degradation](#degradation-rule) below).
2. **« Indices de sentiment »** — line chart per selected subject (topic/region/symbol picker), reading `GET /sentiment-events/indices`. Any day whose contributing scores are not all `live` renders with the « borne supérieure (pré-cutoff LLM) » badge next to it, sourced from `pit_grade` on the returned series points.
3. **« Nowcast vs Réalisé »** — dual-line chart (nowcast vs actual) plus **« Prochaine publication »** sub-panel (countdown to `next_release.expected_release_time`), reading `GET /sentiment-events/nowcast/{series_id}`.
4. **« Probabilité de décision BAM »** — reuses the existing gauge/meter component, `Speedometer`, exported from `frontend/components/strategy/speedometer.tsx` (verified: `export function Speedometer({ ... })`, five-zone French-labeled wedge gauge already used elsewhere in the strategy UI — its existing zone labels "Vente forte/Vente/Neutre/Achat/Achat fort" are replaced for this panel with a three-way P(hike)/P(hold)/P(cut) reading, since the component takes a needle value + zone config as props rather than a fixed zone set). Reads `GET /sentiment-events/rate-probability`.
5. **« Études d'événements »** — a filterable table (event_type / window / benchmark) of grid cells from `GET /sentiment-events/event-studies`, each row showing the CAAR curve (small sparkline), n_events, raw p / BH q (both tiers), and a promotion-status badge (« Promu » / « Non promu » with the failing-gate reason on hover, matching `reason` from the verdict artifact).

Every promotion-status badge and every `upper_bound`-tainted number on the page uses the same two badge components: a green/grey "Promu / Recherche uniquement" badge (from `promotable`) and an amber "borne supérieure (pré-cutoff LLM)" badge (from `pit_grade`) — these are the only two trust signals the page needs to communicate, and they appear consistently across all five sections rather than being reinvented per-panel.

### Degradation rule

Each of the five sections calls its own endpoint independently and renders a skeleton/empty state ("Pas encore de données" / "Étude non disponible") if its endpoint 404s or returns an empty payload — this is required, not optional, because U1 ships after only **A5 + B3 + C1** land, meaning at ship time the nowcast section has real data but the BAM classifier (B4) and most of the event-study grid (C2/C3/C4) may not yet. **No section's failure blocks any other section from rendering.** This is implemented the same way the rest of the frontend handles partial backend availability: each section is its own client component with its own `fetch`/error boundary, not one page-level `Promise.all`.

### Frontend wiring

- `frontend/lib/api.ts` — add typed client functions for the six endpoints (`getIngestHealth`, `getSentimentIndices`, `getNowcast`, `getRateProbability`, `getEventStudies`, `postRefresh`), following the existing typed-fetch pattern already used for `factor-signals` endpoints in this file.
- Nav registry (wherever the app's top-level route list lives, alongside the existing Dashboard/Signal/Strategy/Data entries) — add a `/sentiment-events` entry labeled "Sentiment & Événements", but **not** surfaced inside the Dashboard or Signal navigation groupings, keeping it visually and structurally separate as a research-only surface per [02-validation-policy.md](02-validation-policy.md#nothing-reaches-signaldashboard-before-gates).

## U1 work package

**Files to create:**
- `services/api/app/routers/sentiment_events.py` — router + Pydantic schemas as sketched above.
- `frontend/app/sentiment-events/page.tsx` — page shell composing the five sections.
- `frontend/app/sentiment-events/*` section components (one file per section, e.g. `ingest-health-panel.tsx`, `sentiment-indices-panel.tsx`, `nowcast-panel.tsx`, `rate-probability-panel.tsx`, `event-studies-panel.tsx`) — kept as separate components specifically to satisfy the [Degradation rule](#degradation-rule).

**Files to modify:**
- `services/api/app/main.py` (or wherever routers are registered) — include `sentiment_events.router`.
- `frontend/lib/api.ts` — add the six typed client functions.
- Frontend nav registry — add the `/sentiment-events` route entry.

**Tests:**
- `services/api/tests/test_sentiment_events_router.py` — one test per endpoint against a seeded test DB (empty-state responses for endpoints with no data yet, populated-state responses once fixture rows exist for `alt_sentiment_daily` / `nowcast_value` / `macro_release`), mirroring the test structure used for `services/api/tests/test_macro_factor_replay.py`.
- Frontend: component-level render tests for each of the five panels covering both the populated and the empty/degraded state.

**E2E verification steps:**
1. On the docker-compose stack, with F1 migrated and A5+B3+C1 (at minimum) implemented and their scheduled tasks run at least once, hit each of the six endpoints directly and confirm non-error JSON responses shaped as sketched above.
2. Load `/sentiment-events` in a browser (or via `mcp__claude-in-chrome`/Playwright in CI) and confirm all five sections render — the ones backed by implemented phases show real data, the ones not yet implemented (e.g. B4/C4 before those phases ship) show the degraded empty state without breaking the rest of the page.
3. Confirm the « borne supérieure (pré-cutoff LLM) » badge appears on any sentiment-index datapoint whose backing `alt_sentiment_daily.pit_grade='upper_bound'`, and does **not** appear on `pit_grade='live'` datapoints.
4. Confirm `/sentiment-events` is reachable from its own nav entry but does not appear inside the Dashboard or Signal page navigation groupings.
5. Trigger `POST /sentiment-events/refresh/{kind}` for one `kind` and confirm the corresponding RQ job is enqueued (visible in the worker logs / RQ dashboard) and that the relevant table updates after the job completes.
