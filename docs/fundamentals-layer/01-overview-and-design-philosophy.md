# Overview and design philosophy

## What this layer is

A fundamental analysis subsystem that converts company financial statements into:
- A six-pillar **quality score** (value, quality, growth, risk, cash flow, health)
- A seven-model **intrinsic valuation** (FCFF DCF, FCFE DCF, DDM, residual income, justified multiples, relative multiples, reverse DCF)
- An **ensemble fair-value band** from the median of eligible, non-outlier model values
- Three **accounting-quality diagnostics** (Piotroski-lite, DuPont bridge, accrual quality)

The layer is built on top of an Excel workbook ingestion pipeline. Each upload produces normalized snapshots and annual metric rows, scored against the current cohort, then valuated with peer-aware multiples. The whole engine is offered as a workspace page at `/fundamentals` with import / universe / detail / assumption-editing surfaces.

## Design philosophy

### 1. Run eligible models, publish the robust survivor median

Every applicable model runs for every eligible symbol. Models that don't have the inputs they need are explicitly marked `unavailable`. Models that have inputs but at lower quality (e.g. FCFE built from FCF proxy) carry lower confidence and explicit warnings.

The blend is **not** "pick the best model" or "average them". The current Brief 34 methodology is:

```
eligible_values = observed_or_derived_model_values - cross_model_outliers
fair_value_base = median(eligible_values)
model_weights = 1 / N for included models, 0 for excluded models
```

This keeps a single fragile model from pulling the headline. Confidence is computed separately from coverage, cross-model agreement, and input quality, and is surfaced to the UI.

### 2. Sector-relative multiples, universe-relative percentiles

The valuation engine **does** bucket peers by sector when computing relative multiples (`_peer_stats` in `valuation.py:191`), with a fallback to whole-universe medians when the sector group is too small (`peer_min_count=3` default).

The scoring engine mirrors this pattern: percentiles are sector-bucketed when a sector has enough peers, with market fallback for thin cohorts.

### 3. Honest about proxies

When a workbook lacks debt-flow detail, the FCFE DCF uses raw FCF as a proxy only when that proxy is positive and observable, emits `fcfe_proxy_from_free_cash_flow`, and caps model confidence through `is_proxy=True`. The ensemble inclusion weight remains equal for surviving models; proxy status affects confidence and warnings, not a hidden hand-tuned weight.

This pattern repeats across the engine: missing inputs produce structured warnings, not silent zeros. The FCFF net-debt bridge now reports whether net debt was reported, computed from debt minus cash, debt-only, or unavailable.

### 4. Diagnostics over single scores

The `quality` pillar is not just a percentile rank of ROE/ROA/margins. It's:

```
quality_adjusted = mean(quality_raw_percentile, accounting_discipline, accrual_quality_score)
where:
  accounting_discipline = mean(piotroski_lite_score, dupont_bridge_score)
  health_score      = sector-aware percentile rank of leverage, coverage, and liquidity
  accrual_quality   = f(net_income, free_cash_flow)
  dupont_bridge     = ROE consistency between reported and net margin x asset turnover x equity multiplier
  piotroski_lite    = 9-check accounting-trend score
```

Three weak signals together carry more information than one strong one. The 21 individual checks behind `quality_adjusted` are stored in `snapshot.diagnostics` for the UI to expand.

### 5. Tuned for the Moroccan equity market

Default assumptions reflect Casablanca / MAD market conditions:

| Parameter | Default | Rationale |
|---|---|---|
| Risk-free rate | 3.5% | Approx. 10y MAD government yield |
| Equity risk premium | 6.0% | Moroccan broker consensus, country risk included |
| Country risk premium | 0.0% | Avoids double-counting country risk already embedded in ERP |
| Cost of equity | 9.5% | rf + ERP for typical beta=1 |
| Tax rate | 35% | Current effective large-company IS convention |
| Terminal growth | 2.5% | Moroccan IB long-run nominal convention |
| Stable payout | 55% | Median observed for Casablanca dividend payers |
| Peer minimum count | 3 | Sector → market fallback threshold |
| Ensemble outlier k | 3.0 | Robust MAD rejection threshold |

The `FundamentalAssumptionSet` schema allows per-symbol and per-sector overrides — global defaults are starting points.

### 6. Financial-sector handling is explicit

Banks and insurers get different model gates:
- FCFF/FCFE DCF: **excluded** (cash flows don't translate to enterprise value)
- Residual income: **eligible when book and ROE inputs are observable**
- Justified multiples (P/B): **eligible when book/ROE or P/E inputs are observable**

Detection is token-based: `FINANCIAL_SECTOR_TOKENS = ("banque", "bank", "assurance", "insurance", "financement", "leasing", "credit")` (see `valuation.py:31`).

### 7. Reverse DCF as a sanity check

The reverse DCF doesn't produce a fair value — it produces an **implied perpetual growth rate** given current price and WACC. This is the question "what does the market believe?" rather than "what do we believe?". A reverse-DCF implied growth > sustainable growth flags overvaluation; implied growth < sustainable flags undervaluation. The model is intentionally excluded from the ensemble (`family="diagnostic"`, weight=0).

## System diagram

```
                  ┌─────────────────────────────────┐
                  │   Excel workbook (MASI)         │
                  │   uploaded via UI / API         │
                  └────────────┬────────────────────┘
                               ▼
        ┌─────────────────────────────────────────────────┐
        │  parse_fundamental_workbook                     │
        │  (core/quant_core/fundamentals/workbook.py)     │
        │  → FundamentalWorkbook                          │
        │    ├ company mappings                           │
        │    ├ annual metric rows                         │
        │    ├ latest snapshots (per symbol)              │
        │    └ quality issues                             │
        └────────────┬────────────────────────────────────┘
                     ▼
        ┌─────────────────────────────────────────────────┐
        │  score_fundamental_snapshots                    │
        │  (core/quant_core/fundamentals/scoring.py:232)  │
        │  → percentile ranks across cohort               │
        │    × DuPont + Piotroski + accrual diagnostics   │
        │    → 6-pillar scores + overall                  │
        └────────────┬────────────────────────────────────┘
                     ▼
        ┌─────────────────────────────────────────────────┐
        │  compute_symbol_valuations (per symbol)         │
        │  (core/quant_core/fundamentals/valuation.py:601)│
        │  → 7 valuation models, eligibility-gated        │
        │  → peer multiples (sector → market fallback)    │
        └────────────┬────────────────────────────────────┘
                     ▼
        ┌─────────────────────────────────────────────────┐
        │  compute_valuation_ensemble                     │
        │  (core/quant_core/fundamentals/valuation.py:555)│
        │  → weighted-mean fair value                     │
        │  → Q1/Q3 model-dispersion band                  │
        │  → ensemble confidence_score                    │
        └────────────┬────────────────────────────────────┘
                     ▼
        ┌─────────────────────────────────────────────────┐
        │  execute_import_run                             │
        │  (services/api/app/services/fundamentals.py)    │
        │  → persists into 8 fundamental_* tables         │
        │    in PostgreSQL                                │
        └────────────┬────────────────────────────────────┘
                     ▼
        ┌─────────────────────────────────────────────────┐
        │  REST API + Frontend                            │
        │  GET /fundamentals/universe                     │
        │  GET /fundamentals/stocks/{symbol}              │
        │  PUT /fundamentals/stocks/{symbol}/assumptions  │
        │  Page: /fundamentals (frontend/app/...)         │
        └─────────────────────────────────────────────────┘
```

## What this layer is NOT

- It is **not** an automated trading signal. Fundamental scores inform discretion; signal-engine integration is a planned but unshipped follow-up (see `14-implementation-roadmap.md` and the parallel signal-generation layer).
- It is **not** a real-time data feed. Snapshots are point-in-time, refreshed on workbook upload (weekly cadence at best).
- It is **not** a forecast model. The DCF projections use observed growth rates with a linear fade to terminal growth — they don't ingest analyst estimates or scenario macros.
- It is **not** asset-class general. The current calibration is for listed equities. Bonds, commodities, and forex go through the data layer but skip this engine entirely.
- It is **not** an FX conversion engine. Valuations are currency-tagged and mismatches are blocked, but no USD/EUR/MAD conversion is attempted.

## Where to go next

- New to the layer? Read [02-data-flow.md](02-data-flow.md), then [04-pillars-and-scoring.md](04-pillars-and-scoring.md), then [06-valuation-models.md](06-valuation-models.md).
- Reviewing the v3 fix history? Start at [12-known-issues-and-limitations.md](12-known-issues-and-limitations.md).
- Analyst running the engine day-to-day? Read [10-modelling-playbooks.md](10-modelling-playbooks.md) and [11-prompts-for-claude.md](11-prompts-for-claude.md).
