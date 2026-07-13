# Multi-Market Port — Exploration Findings & Plan

**Status: planned 2026-07-12, not yet implemented.** Question: run the app's
technical + fundamental analysis on a non-Moroccan market (FR/US/DE/JP) —
which is easiest, and how?

## Port-readiness findings (explored 2026-07-12)

The app is **already partially multi-market**:

- `stock_master` / `index_master` carry `market_region` (`masi|us|european|asian`)
  and `asset_type` (migration `o5p6q7r8s9t0`); the dashboard already has
  region tabs (`lib/dashboard-preferences.ts`), and `market_universe.py` emits
  region-grouped catalogs.
- **Price ingestion via yahoo is generic**: `YFinanceMoroccoAdapter`
  (`core/quant_core/data.py:987`) works for any ticker via
  `provider_symbol_map`; only the `.CS` suffix fallback in
  `_resolve_provider_symbol` needs generalizing. Store/merge/parquet plumbing is
  market-agnostic.
- **yfinance fundamentals path is generic and already wired** for
  `source_universe="non_masi"` (`fundamentals/providers/yfinance_provider.py`,
  `refresh_yfinance_fundamentals.py`) — bypasses the CGNC French mapping
  entirely, produces canonical `AnnualMetricRow` (Revenue, EBITDA,
  Operating_Cash_Flow, Shares_Outstanding…).
- **The quant core is fully market-agnostic**: zero Morocco references in
  `signal_engine/*`, `wfo/*`; `build_pit_panel`/`pit_ic_backtest` are
  schema-generic (only tie: `UNIVERSE_PATH` → `bvc_pit_universe.csv`).
- **Deep coupling is confined to**: Casablanca scrapers (`BourseDirectAdapter`
  etc.), BMCE Excel format maps, `cgnc_mapping.py` (French accounting), MASI
  benchmark/float-share/holiday/session constants — all bypassable or
  config-swappable. Light constants to parameterize per market: cost bps
  (33/side is Morocco; US large caps ≈ 2-5bps + slippage), `MASI_PERIODS`
  regimes, `TRUSTED_UNIVERSE_EXCLUSIONS`, benchmark proxy in
  `cost_of_capital.py`.

## The data-reality constraint that decides the market

| Leg | FR / DE / JP | US |
|---|---|---|
| Prices (yahoo) | ✅ fine (`MC.PA`, `SAP.DE`, `7203.T`) | ✅ best quality |
| Fundamentals for DASHBOARDS | ⚠️ yfinance snapshots (~4-5y, restated) — acceptable for display | ✅ same, plus EDGAR |
| Fundamentals for BACKTESTS (PIT) | ❌ no free point-in-time source | ✅ SEC EDGAR companyfacts XBRL: free, unlimited, filing-dated = true PIT |

A value backtest on restated snapshot fundamentals is survivorship/restatement-
biased — we do not run those. Therefore: **US first**. France/Germany/Japan get
the technical leg + fundamental dashboards only, until a PIT source appears.

## Plan

### Track 1 — Technical leg on US large caps (pure config, ~1 session)

1. **Universe seeding script**: ~30 liquid US large caps (start small — weekly
   WFO full recompute is expensive; scale after observing worker load) into
   `stock_master` with `market_region='us'`, `track_source='yahoo'`,
   `provider_symbol_map` rows; `^GSPC` (and `^NDX`) into `index_master`.
2. **Generalize `_resolve_provider_symbol`**: fallback suffix per
   `market_region` (masi→`.CS`, us→none) instead of hardcoded `.CS`.
3. **Per-market calendar/session config**: refactor `market_refresh_window.py`
   constants + `market_holidays.py` JSON into a per-market registry
   (`America/New_York`, 09:30-16:00, US holiday JSON). Refresh gating and
   scheduler crons read the market's window.
4. **Cost + benchmark config**: per-market `cost_bps` default (US: 5) and
   benchmark proxy symbol; thread through `EDGE_COST_BPS_PER_SIDE` usage and
   `cost_of_capital.py` proxy.
5. Let `daily_market_refresh` + `weekly_wfo_dispatch` pick the new symbols up
   (they iterate `stock_master.is_active`); verify WFO summaries/opportunities
   appear under the existing US region tab.

Deliverable: live technical signals (WFO, S/R, best-evidence) on US names in
the existing UI. Same caveat as MASI: per-symbol WFO edges are research-grade
until portfolio-level validation.

### Track 2 — Fundamental value replication on US (the real research, 2-3 sessions)

Purpose is explicitly a **platform validation**, not an alpha hunt: US value is
the most-studied factor in finance, so running the six-vintage B/M engine on
US data and comparing against published Fama-French HML behavior (weak
post-2010, deep 2018-2020 drawdown, 2021-22 rebound) is a ground-truth test of
the entire pipeline (PIT panel, vintage engine, cost handling). If our engine
reproduces the known shape, every Moroccan result gains credibility; if not,
we have a bug to find. (Interview-grade artifact, too.)

1. **EDGAR ingestion**: new provider `edgar_provider.py` — companyfacts XBRL →
   canonical `AnnualMetricRow` with `availability_date = filing date` (true
   PIT; the CGNC layer is NOT involved). Bulk `companyfacts.zip` for backfill,
   API for refresh. Map us-gaap tags → canonical metrics (Revenues,
   StockholdersEquity, NetCashProvidedByUsedInOperatingActivities,
   CommonStockSharesOutstanding…), with the same quality-issue logging the
   Moroccan ingestion uses.
2. **PIT universe with survivorship handling**: build
   `data/universe/us_pit_universe.csv` from a public historical S&P 500
   constituents dataset (document the source + its imperfections in the file
   header). This is the weakest link of any free US backtest — disclose it in
   every artifact; restrict claims accordingly.
3. **Pre-registered replication study** (same harness discipline as the three
   2026-07 studies): six-vintage B/M top-tercile on US large caps 2010→present,
   cost 5bps; acceptance = *qualitative agreement with published HML shape*
   (sign of long-leg premium, drawdown window location), NOT beating SPY.
   Explicitly pre-register that beating SPY is not expected.
4. Frontend: fundamentals dashboards work via the existing non-MASI path;
   value-strategy panel gets a market selector only if Track 2 validates.

### Non-goals (explicit)

- No CSE-style alpha claims on US/EU/JP — those markets are efficient where
  this app's edge (hand-built PIT data on a neglected frontier market) doesn't
  exist. The Moroccan edge IS the moat; the port is for platform validation,
  scale practice, and interview material.
- No FR/DE/JP fundamental backtests until a PIT source exists.
- No new Casablanca-style scrapers for foreign exchanges — yahoo only.

## Sequencing vs the paper-trading desk

The desk (docs/plans/paper-trading-desk.md) outranks the port: it
operationalizes the one validated edge. Suggested order: desk phases 1-4 →
port Track 1 (cheap win) → desk observation period runs in parallel with port
Track 2.
