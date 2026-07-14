# Data Sources

Four source classes, in ascending order of new code required: Yahoo-covered
series (zero code), FRED/ALFRED (one new client, reuses an existing retry
pattern), static CSV/XLSX downloads (one small client per source, no auth),
and the Morocco release calendar (no API at all — hand-seeded + scraped
confirmation). This is phase **B1** (series ingestion) and **B2** (calendar).

---

## 1. Yahoo-covered inputs — zero new code

`core/quant_core/macro.py` already has a DB-backed `MacroSeriesSpec` registry
(`macro_factor_meta` table, read with a 60s cache via `get_macro_series()`).
Confirmed present in the current static fallback list (`_STATIC_FALLBACK` in
`core/quant_core/macro.py`, lines 49–162) and therefore already flowing
through `services/worker/tasks/ingest_macro_series.py`:

| canonical_id | Yahoo ticker | Already registered |
|---|---|---|
| `BRENT` | `BZ=F` | Yes |
| `EURUSD` | `EURUSD=X` | Yes |
| `US10Y` | `^TNX` | Yes |

**Not present** and needed for the inflation-nowcast feature set
(`02-inflation-nowcast.md`) — new `macro_factor_meta` rows only, no new
ingestion code:

| canonical_id | Yahoo ticker | Purpose |
|---|---|---|
| `WHEAT` | `ZW=F` | Morocco is a large wheat importer; wheat futures feed the food-inflation channel. |
| `MADUSD` | `MAD=X` | Direct MAD/USD leg (the existing `EURUSD` series only gives the USD/EUR cross). |
| `EURMAD` | *derive from `EURUSD` × `MADUSD`, or confirm a direct Yahoo cross exists at implementation* | MAD peg is quoted against a EUR/USD basket; Brent-in-MAD and wheat-in-MAD features need this cross directly. |

Seeding is a migration/seed-script data change (`INSERT INTO
macro_factor_meta …`), not new Python. `MacroSeriesSpec.channel_tags` for
these three should be `["all"]` per the existing convention (channel
gating for macro-derived series happens later, at the `FactorSignalSpec`
level — see [`04-surprise-and-regimes.md`](04-surprise-and-regimes.md)).

If `EURMAD` has no direct Yahoo cross ticker, compute it as a **derived**
series (`source_kind='derived'`, per the shared-foundation `macro_factor_meta`
extension — [`../alt-data-foundation/01-pit-event-store.md`](../alt-data-foundation/01-pit-event-store.md))
rather than adding a synthetic Yahoo ticker.

---

## 2. FRED + ALFRED client

New file: `core/quant_core/research/nowcast/fred_client.py`.

**FRED** (Federal Reserve Economic Data) serves current-vintage series.
**ALFRED** (ArchivaL FRED) serves the *as-first-published* vintage of the
same series — i.e., what a forecaster actually knew on a given date, before
later data revisions. Both are served by the same FRED REST API; ALFRED
vintages are obtained by passing `realtime_start`/`realtime_end` parameters
to `fred/series/observations` instead of omitting them. This client must
default to vintage-aware calls — every US series ingested here needs a true
point-in-time value, not today's revised number, or the whole PIT guarantee
of the layer is violated for US inputs.

- **Auth**: free API key, request at
  `https://fred.stlouisfed.org/docs/api/api_key.html`. Env var
  `FRED_API_KEY`; ctor raises early (not on first call) if unset.
- **Endpoint**: `https://api.stlouisfed.org/fred/series/observations`
  (documented at `https://fred.stlouisfed.org/docs/api/fred/series_observations.html`).
  Vintage query adds `realtime_start=<as_of>&realtime_end=<as_of>` so the
  response is exactly the value as published/known on that date.
- **Retry/ctor pattern** — copy the shape of
  `StockAnalysisFundamentalProvider` in
  `core/quant_core/fundamentals/providers/stockanalysis_provider.py`
  (lines 199–229): constructor takes `timeout_seconds: int = 30`,
  `retries: int = 3`, `sleep: Any = time.sleep` (injectable for tests); the
  public fetch method loops `for attempt in range(self.retries)`, catches
  the request exception, sleeps `2**attempt` (exponential backoff) between
  attempts, and raises a domain-specific `ProviderUnavailableError`-style
  exception (mirror `core/quant_core/fundamentals/providers/__init__.py`'s
  `ProviderUnavailableError`, or a local equivalent) after exhausting
  retries with the last exception chained (`raise … from last_exc`). No new
  HTTP dependency — `urllib.request` as in the source pattern, or `requests`
  if already a project dependency; confirm at implementation which is
  already vendored for this module's import path.
- **Series to pull**: `CPIAUCSL` / `CPILFESL` (US CPI headline/core, for
  `US_CPI_YOY` release rows), plus any additional series the rate classifier
  needs for the Fed-decision feature (`03-rate-classifier.md`) — confirm
  exact series IDs at implementation against the classifier's final feature
  list.
- **Persistence**: each pulled point both (a) upserts into the derived-factor
  parquet/DB pattern (`core/quant_core/s3_keys.py::build_market_store_object_key`,
  same convention `ingest_macro_series.py` already uses) and (b) inserts a
  `macro_release` row with `vintage` set from the ALFRED `realtime_start` of
  that observation, per the shared-foundation schema.

---

## 3. CSV/XLSX sources (no auth, static download URLs)

New file: `core/quant_core/research/nowcast/csv_sources.py`. One fetch
function per source, all following the same shape: HTTP GET → parse
(pandas `read_csv`/`read_excel` on the response bytes) → normalize to
`(period, value, published_at)` rows → persist via the derived-factor
pattern + a `macro_release` row per official print.

| Source | Series | URL | Status |
|---|---|---|---|
| Cleveland Fed Inflation Nowcasting | US CPI/PCE nowcast | `https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting` (page hosts a downloadable data file) | confirm exact CSV/XLSX asset URL at implementation — page layout and filename are not fixed |
| Atlanta Fed GDPNow | US real GDP growth nowcast | `https://www.atlantafed.org/cqer/research/gdpnow` (historical tracking dataset linked from this page) | confirm exact XLSX asset URL at implementation |
| NY Fed Weekly Economic Index (WEI) | US weekly activity index | `https://www.newyorkfed.org/research/policy/weekly-economic-index` (data file linked from this page) | confirm exact CSV/XLSX asset URL at implementation |
| FAO Food Price Index | Global food commodity index (monthly) | `https://www.fao.org/worldfoodsituation/foodpricesindex/en/` (monthly CSV/XLSX linked from this page, filename changes per release) | confirm exact asset URL at implementation |
| HCP CPI history | Morocco CPI (y/y, m/m, subindices) | `https://www.hcp.ma` — Indice des Prix à la Consommation section | confirm exact download endpoint/format at implementation; HCP publishes bulletins as PDF/XLSX, not a stable CSV API |

All five are **optional-degrade** for the inflation nowcast except HCP CPI
itself (the target variable): if Cleveland Fed / GDPNow / WEI / FAO FPI are
unreachable on a given refresh, the corresponding regime flags
(`REGIME_GLOBAL_TIGHTENING`, etc. — [`04-surprise-and-regimes.md`](04-surprise-and-regimes.md))
simply go stale rather than blocking the Morocco nowcast pipeline, because
Morocco's own nowcast only requires Brent, wheat, FAO FPI, and FX (see
feature list in [`02-inflation-nowcast.md`](02-inflation-nowcast.md)) — even
FAO FPI unavailability degrades gracefully via the assembly's
`available_at`-gated feature set (a missing feature is dropped from that
month's row, not treated as a hard failure).

**Fuel-price probe** (optional, do not block on this): a standalone probe
script, e.g. `scripts/probe_fuel_prices.py`, checks whether a Moroccan pump
fuel-price feed (candidate: `https://www.mtpnet.gov.ma` or a
sectoral/distributor bulletin — confirm at implementation, no known stable
public API today) is scrapeable with a usable history depth. This is an
**optional** nowcast input (imported fuel costs are a component of the CPI
transport/energy subindex) — the inflation-nowcast models (`02-inflation-nowcast.md`)
must work with the feature entirely absent; do not gate B3 on this probe
succeeding.

---

## 4. HCP/BAM release calendar — realistic scrape-or-seed

Neither HCP (Haut-Commissariat au Plan, publishes CPI) nor BAM (Bank
Al-Maghrib, sets the policy rate) exposes a machine-readable release
calendar or API. The realistic approach is **hand-seed once, scrape to
confirm**, matching how the platform already handles unstable calendar
sources for `FundamentalCatalyst` (`services/worker/tasks/refresh_fundamental_catalysts.py`).

New file: `core/quant_core/research/nowcast/data/ma_release_calendar.yaml`,
collected once by hand from public HCP/BAM historical bulletins and BAM's
monetary-policy-decision press-release archive, then extended forward as new
dates are announced:

```yaml
# illustrative shape — exact 2019→present dates collected once at
# implementation time from hcp.ma bulletin archive and bkam.ma press
# releases; both sources publish month/quarter-ahead schedules a few
# months in advance, so "forward entries" beyond the collection date are
# provisional until confirmed released.
hcp_cpi:
  - period: "2024-01"
    scheduled_date: "2024-02-22"   # HCP CPI publishes ~day 20-25 of month+1
  - period: "2024-02"
    scheduled_date: "2024-03-21"
  # ... 2019-01 → present, one row per month

bam_meetings:
  - period: "2024Q1"
    scheduled_date: "2024-03-19"   # quarterly BAM Conseil de la Banque decision
  - period: "2024Q2"
    scheduled_date: "2024-06-25"
  # ... 2019Q1 → present, one row per quarter
```

`services/worker/tasks/refresh_macro_releases.py` (new task, see
[`06-phases.md`](06-phases.md)) does two things on a 3-hour business-hours
schedule:

1. **Seed**: load the YAML, upsert `macro_release` rows with
   `status='scheduled'` for any `(series_id, period)` not yet present.
2. **Confirm**: scrape the HCP CPI bulletin page and BAM's Conseil de la
   Banque press-release page for the latest published figures; when a
   scheduled row's period has an actual figure available, flip
   `status='released'`, set `actual_value` and `observed_at`, and bump
   `vintage` (mirroring the exact-match / near-match / supersede idiom
   already used in `_upsert_catalyst()` in
   `services/worker/tasks/refresh_fundamental_catalysts.py`, lines 33–80,
   for `FundamentalCatalyst` upserts — same three-way branch: exact-date
   match updates in place, near-date match (±14d window there; Morocco
   calendar precision may differ, confirm tolerance at implementation)
   updates the date, otherwise insert new and supersede the prior row on
   revision).

US series (`CPIAUCSL` via FRED/ALFRED) get their `macro_release` rows
directly from the FRED client (§2) — FRED publishes reliable release-date
metadata via its own API, no calendar-seeding needed for the US leg.

## What This Phase Does Not Do

- Does not require BAM/HCP API access — none exists publicly.
- Does not treat fuel-price data as required — it is a probed, optional
  input only.
- Does not backfill Morocco CPI/BAM history further back than what HCP/BAM
  bulletin archives make reachable; probe archive depth before assuming
  2019 coverage (same caution as Plan A's Morocco news-archive probe).
