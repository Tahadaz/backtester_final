# 09 — Holidays, Scheduling & MASI Registry

---

## Casablanca Exchange Holiday Calendar

**File**: `services/api/app/market_holidays.py`
**Data**: `services/api/app/data/casablanca_exchange_holidays.json`

### Why Holidays Matter

The availability calendar (see 07-frontend-architecture.md) needs to distinguish between "missing data because the exchange was closed" (expected) and "missing data because of a gap in our dataset" (a problem). Without a holiday calendar, every non-weekend gap would appear as a data quality issue.

Holidays also matter for:
- **Chart rendering**: Plotly rangebreaks remove holiday gaps so the chart doesn't show flat periods
- **Freshness calculation**: A stock's data_as_of shouldn't be considered "stale" if the exchange hasn't been open since
- **Year strip overview**: Holiday days are shown in sky-blue, distinguishing them from amber (missing) and green (present)

### Data Format

Each entry in the JSON file:

```json
{
  "date": "2026-01-01",
  "name": "Jour de l'An",
  "year": 2026,
  "certainty": "confirmed",
  "notes": "",
  "source_label": "Bourse de Casablanca officiel",
  "symbols": null
}
```

**Certainty levels**:
- `"confirmed"` — Official exchange calendar
- `"tentative"` — Predicted but not yet confirmed (e.g., Islamic holidays whose exact date depends on moon sighting)

**Symbol-specific holidays**: The `symbols` field (list or null) allows holidays that only affect certain tickers (e.g., sector-specific trading halts). When null, the holiday is global.

### Caching

The module uses mtime-aware global caches:
1. Check JSON file's modification time
2. If unchanged since last load: return cached dict
3. If changed: reload and rebuild cache

Two caches:
- `global_holidays`: `dict[date, holiday_info]` — all non-symbol-specific holidays
- `symbol_holidays`: `dict[(date, symbol), holiday_info]` — symbol-specific

### API

```python
load_casablanca_holidays() → dict[date, dict]
# Returns all global holidays

get_holiday_info(day: date, symbol: str | None = None) → dict | None
# Returns holiday info if the day is a holiday
# Priority: symbol-specific > global
```

The availability calendar endpoint calls `get_holiday_info(day, symbol)` for each day in the range.

---

## Scheduled Daily Refresh

**File**: `services/api/app/scheduler.py`

### Architecture

Uses APScheduler `BackgroundScheduler` with `CronTrigger`:
- **Schedule**: 18:00 Africa/Casablanca timezone, Monday–Friday
- **Action**: Creates a `MarketRefreshRun` and enqueues `refresh_all_tracked_symbols` via RQ

### Why 18:00?

The Casablanca Stock Exchange (Bourse de Casablanca) closes at 15:30 local time. Setting the refresh at 18:00 provides:
- 2.5 hours buffer for end-of-day data to be finalized by data providers
- Enough time before market close data is needed for next-morning analysis
- Alignment with typical after-market data publication schedules

### Configuration

| Env Var | Default | Purpose |
|---------|---------|---------|
| `MARKET_REFRESH_CRON_ENABLED` | `"1"` | Set to `"0"` to disable daily cron |

### Lifecycle

```python
# Called at API startup
start_scheduler()  # Creates BackgroundScheduler + CronTrigger

# Called at API shutdown
stop_scheduler()   # Shuts down scheduler

# Triggered by cron
_enqueue_daily_refresh()
  → Creates MarketRefreshRun(trigger_source="scheduled", scope="all")
  → Enqueues refresh_all_tracked_symbols(run_id)
```

### Monitoring

Scheduled refresh runs are visible via:
- `GET /market-data/refresh` — lists all runs, including scheduled ones
- `GET /market-data/health` — `last_refresh_run` shows the most recent run regardless of trigger

---

## MASI Ticker Registry

**File**: `services/api/app/masi_tickers.py`

### Purpose

Provides a canonical list of all 93 tickers in the Moroccan All Shares Index (MASI). Used for:
1. **Autocomplete**: The "Ajouter un titre" dialog lets users search and select from MASI tickers
2. **Auto-population**: When creating a stock, the API auto-fills display_name and sector from this registry
3. **Market classification**: The catalog endpoint marks symbols as `market: "masi"` or `market: "other"` based on this list
4. **Tab filtering**: The data page splits into "MASI" and "Autres" tabs using this classification

### Data Structure

Each ticker is a dict with:
```python
{"symbol": "ATW", "display_name": "Attijariwafa Bank", "sector": "Banques"}
```

### Sectors (11)

| Sector | Example Tickers |
|--------|-----------------|
| Banques | ATW, BCP, BOA, CIH, CDM |
| Assurances | WAA, SAH, ATL |
| BTP | CMA, JET, DH, ALM |
| Mines | CMT, MNG, SMI |
| Énergie | TQM, AFG |
| Agroalimentaire | LES, CSR, COL, OUL |
| Distribution | LBV, AUT, SNA |
| Immobilier | ADI, RDS, ALL |
| Télécommunications | IAM, IBC |
| Transport | CTM, TIM |
| Autre | NEX, MDP, M2M, REB |

### Functions

```python
is_masi_ticker(symbol: str) → bool
# Normalizes input: strip, uppercase, drop .MA/.CS suffix
# Returns True if symbol is in the registry

get_masi_info(symbol: str) → dict | None
# Returns {"display_name": "...", "sector": "..."} or None

all_masi_tickers() → list[dict]
# Returns all 93 tickers, sorted by symbol
```

### Symbol Normalization

The `is_masi_ticker()` function strips common suffixes before matching:
- `.MA` — Casablanca Bloomberg suffix
- `.CS` — Yahoo Finance Casablanca suffix

This ensures that `"ATW"`, `"ATW.CS"`, and `"ATW.MA"` all match.
