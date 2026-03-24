# 11 — Data Page as Control Center & Freshness Monitoring

---

## The Data Page Is the Control Center

The `/data` page is the operational hub for the entire platform's data pipeline. It serves three audiences:

1. **Operators**: Need to know what data exists, what's missing, and what's stale — at a glance
2. **Analysts**: Need to verify data quality before trusting backtest or signal results
3. **The signal engine**: Depends on fresh, complete OHLCV to produce meaningful signals

Without this page, data quality issues would be invisible until they produced wrong results downstream.

---

## Dual Freshness Model

The system uses two different freshness calculations, each correct for its context:

### Backend Freshness (Business Days)

**File**: `routers/market_data.py` → `_is_stale(data_as_of)`

```python
def _is_stale(data_as_of: datetime | None) -> bool:
    if data_as_of is None:
        return True
    return data_as_of.date() < _business_days_ago(_today_utc(), 2)
```

- Uses business days (Mon–Fri only)
- Threshold: 2 business days
- Used in: `StockMasterOut.is_stale`, `MarketHealthOut.stale`/`up_to_date`

**Why business days?** The exchange doesn't operate on weekends or holidays. Data from Friday is not "stale" on Saturday — it's the most recent available. Business-day calculation prevents false staleness alerts.

### Frontend Freshness (Calendar Days)

**File**: `components/data/freshness-badge.tsx`

```typescript
const daysSince = Math.floor((now - parseDate(dataAsOf)) / 86400000)
```

| Days | Badge | Color |
|------|-------|-------|
| ≤1 | "À jour" | Green |
| 2–7 | "{n}j" | Yellow |
| >7 | "{n}j — obsolète" | Red |

**Why calendar days?** The badge is a visual signal for quick scanning. Calendar days are intuitive for humans — "3 days ago" is immediately understood. The yellow zone (2–7 days) accounts for weekends without requiring holiday-calendar logic in the frontend.

### Reconciliation

Both models agree on the important cases:
- Data from today/yesterday: both say "fresh"
- Data from 2+ weeks ago: both say "stale"
- Weekend gap: backend says "fresh" (correct), frontend says 2j yellow (conservative but not alarming)

The slight conservatism of the frontend model is acceptable — a yellow badge for Saturday data on Sunday is not a problem.

---

## Monitoring Capabilities

### 1. Catalog Table
- **What it shows**: Every symbol in the system, whether tracked, whether it has data, data range, source, freshness
- **Key insight**: Rows without data (has_canonical_data=false) appear in the table but with empty Début/Fin/Barres columns

### 2. Freshness Badges
- Per-row in the catalog table
- Immediate visual: green = good, yellow = attention, red = action needed

### 3. Refresh Status Bar
- Appears only during active refresh operations
- Real-time: "Mise à jour en cours… {done}/{total}"
- Progress bar visualization
- Disappears when complete

### 4. Availability Calendar
- Per-day data coverage for any symbol
- Holiday-aware: sky blue for confirmed holidays, fuchsia for tentative
- Missing-day detection: amber for expected trading days without data
- Partial-day detection: yellow for bars with missing OHLCV fields

### 5. Year Strip Overview
- Quick annual summary: which months have gaps?
- Color-coded: emerald (complete), amber (gaps), sky (holidays)
- Click to navigate to specific month in calendar

### 6. Data Quality Report
- Expandable diagnostics section
- Lists partial days (which fields missing, on which dates)
- Lists missing expected days
- "Aucun problème détecté" when clean

### 7. Health Endpoint
- `GET /market-data/health` for programmatic monitoring
- Counts: up_to_date, stale, very_stale, never_ingested
- Last refresh timestamp

---

## Data-Signal Pipeline Dependency

```
Data Page (controls data freshness)
  │
  ├─ market_data_store/{symbol}/1D  (parquet, canonical OHLCV)
  │
  ▼
Signal Engine (consumes OHLCV)
  │
  ├─ load_close_for_symbol(db, symbol)  → numpy array
  ├─ load_ohlcv_for_symbol(db, symbol)  → DataFrame with Volume
  │
  ▼
Signal Page (displays ensemble results)
```

The signal engine calls `load_close_for_symbol()` and `load_ohlcv_for_symbol()` from `market_data_loader.py`. These functions read the same parquet files managed by the data page. If a symbol's data is stale or missing, the signal engine will:
- Produce signals based on outdated data (stale)
- Return an error or neutral signal (missing)
- Show fewer OOS windows if history is short

This is why the data page is not optional — it is the foundation that the signal engine builds on.
