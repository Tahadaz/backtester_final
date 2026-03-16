# Data Layer — Daily Update Mechanism & Data Page as Central Hub

---

## The Data Page Is the Control Center

The `/data` page is not just a table — it is the **single source of truth** for what market data exists, how fresh it is, and what actions are available. Every backtest run depends on data that flows through this page.

### Why it matters

```
No data → no backtests
Stale data → stale backtests → wrong decisions
Missing symbols → incomplete universe → survivorship bias
```

The data page must answer these questions at a glance:
1. **What symbols do we have?** — catalog table (market_data_store + stock_master)
2. **How fresh is each symbol?** — FreshnessBadge (green/amber/red)
3. **Which symbols are tracked for auto-refresh?** — Suivi column (checkmark)
4. **What's the overall health?** — HealthCards (up-to-date / stale / never-ingested counts)
5. **Is a refresh running right now?** — RefreshStatusBar (progress bar)
6. **Can I add new data?** — Excel upload + Bourse refresh buttons

### User workflows on the data page

| Workflow | Steps | What happens behind the scenes |
|----------|-------|-------------------------------|
| **First-time setup** | Upload BMCE Excel file | Excel → S3 → worker parses sheets → detects symbols → creates parquet → upserts market_data_store |
| **Add a new stock** | Click refresh on a row (or use AddStockDialog) | Auto-creates stock_master row + provider_symbol_map → triggers single refresh |
| **Fill metadata** | Open detail panel → "Auto-remplir depuis Bourse" | Scrapes casablanca-bourse.com → fills display_name, ISIN, sector, bourse_url |
| **Manual refresh** | Click "Mettre à jour via Bourse" (header) | Triggers bulk refresh of ALL active tracked stocks |
| **Per-stock refresh** | Click refresh icon on a row | Triggers single-symbol refresh |
| **Check freshness** | Look at Fraîcheur column | Green (≤1 day), amber (2-7 days), red (>7 days) |
| **Investigate issues** | Look at health cards + stale badges | Identify which symbols need attention |

---

## Daily Update: Current State

### What exists

The infrastructure for scheduled refresh is **partially wired**:

1. **MarketRefreshRun.trigger_source** supports `"scheduled"` (alongside `"manual"` and `"api"`)
2. **RQ Worker** runs with `with_scheduler=True` (env `WORKER_WITH_SCHEDULER=1` by default) — this enables RQ's built-in scheduler for deferred/scheduled jobs
3. **`refresh_all_tracked_symbols()`** works — it iterates all active `stock_master` rows, fetches from Bourse/Yahoo, merges parquets
4. **Incremental fetch** — the worker starts from `market_data_store.end_ts + 1 day`, so it only fetches new bars

### What is NOT implemented yet

There is **no cron job, no scheduled enqueue, no periodic trigger** that automatically calls `refresh_all_tracked_symbols()` daily. Currently, the only way to trigger a refresh is:
- User clicks "Mettre à jour via Bourse" on the data page (manual)
- Direct API call: `POST /market-data/refresh`

---

## Daily Update: What Needs to Be Built

### Option A: RQ Scheduled Job (simplest)

Use RQ's built-in scheduler to enqueue a recurring job. Add to the API startup or a management command:

```python
from rq import Queue
from rq.registry import ScheduledJobRegistry
from datetime import datetime, timedelta, timezone

def schedule_daily_refresh(queue: Queue):
    """Enqueue refresh_all_tracked_symbols to run daily at a fixed time."""
    # RQ's scheduler handles repeat via enqueue_at
    # You'd need a recurring mechanism — RQ doesn't have native cron.
    # Use rq-scheduler package or a simple cron wrapper.
    pass
```

**Limitation:** RQ doesn't have native cron. You need either `rq-scheduler` package or an external cron.

### Option B: System Cron + API Call (most reliable)

Add a cron job (in Docker or host) that hits the existing API endpoint:

```bash
# crontab or Docker healthcheck-style
# Run at 18:30 Morocco time (after Casablanca market close at 15:30)
30 18 * * 1-5 curl -X POST http://localhost:8000/market-data/refresh \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${API_KEY}" \
  -d '{"timeframe": "1D"}'
```

**Docker Compose addition:**
```yaml
quant_scheduler:
  image: curlimages/curl:latest
  depends_on:
    quant_api:
      condition: service_healthy
  entrypoint: /bin/sh
  command: |
    -c 'while true; do
      # Sleep until next 18:30 Morocco time (UTC+1)
      sleep_until_1830;
      curl -s -X POST http://quant_api:8000/market-data/refresh \
        -H "Content-Type: application/json" \
        -H "x-api-key: $$API_KEY" \
        -d "{\"timeframe\": \"1D\"}";
      sleep 86400;
    done'
```

### Option C: FastAPI Startup Scheduler (in-process)

Use `apscheduler` or `asyncio` background task in the API server:

```python
# In services/api/app/main.py or a lifespan handler
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler(timezone="Africa/Casablanca")

@scheduler.scheduled_job("cron", hour=18, minute=30, day_of_week="mon-fri")
async def daily_refresh():
    # Create a MarketRefreshRun and enqueue the worker job
    ...

@app.on_event("startup")
async def start_scheduler():
    scheduler.start()
```

### Recommended: Option B (cron + API call)

- No new dependencies
- Uses the existing, tested `/market-data/refresh` endpoint
- Creates a proper `MarketRefreshRun` row with `trigger_source="scheduled"`
- Frontend shows progress in RefreshStatusBar
- Easy to monitor: check `market_refresh_run` table for daily runs

---

## Daily Update: Timing Considerations

### Casablanca Stock Exchange Hours
- **Trading session:** 09:30 – 15:30 (Morocco time, UTC+1)
- **After-hours data availability:** varies by provider
  - Bourse de Casablanca website: usually updated by 16:00–17:00
  - Yahoo Finance: may lag 30-60 minutes after close

### Recommended Schedule
```
18:30 UTC+1 (Morocco time), Monday–Friday
= 17:30 UTC in winter, 17:30 UTC in summer (Morocco doesn't observe DST consistently)
```

### What the daily refresh does
1. Creates `MarketRefreshRun` (trigger_source="scheduled", scope="all")
2. Queries all `stock_master WHERE is_active=TRUE`
3. For each symbol (sequential):
   - Resolves provider symbol (e.g. ATW → ATW.CS for Yahoo)
   - Fetches OHLCV from `end_ts + 1 day` to today (incremental)
   - Validates bars (integrity checks)
   - Merges with existing parquet (overwrite-if-different strategy)
   - Saves updated parquet to S3
   - Upserts `market_data_store` row
4. Final status: "succeeded" / "partial" / "failed"

### What can go wrong
| Issue | Symptom | Fix |
|-------|---------|-----|
| Bourse website down | All symbols fail, status="failed" | Retry next day; add Yahoo fallback |
| Rate limiting | Some symbols timeout | Increase delay in BourseDirectAdapter (default 0.5s) |
| New listing | Symbol not in stock_master | Manual add via data page; or add auto-discovery |
| Weekend/holiday | No new data available | Worker detects 0 new bars, skips gracefully |
| Worker not running | Jobs stuck in "queued" | Check `WORKER_QUEUES` includes `"market_refresh"` |
| Queue not listened | Jobs enqueued but never processed | Verify worker config: `WORKER_QUEUES` |

---

## Data Freshness Monitoring

### Backend staleness check

```python
# In market_data.py — _is_stale() helper
def _is_stale(data_as_of: date | None, threshold_biz_days: int = 2) -> bool:
    """A stock is stale if data_as_of is older than N business days."""
    if data_as_of is None:
        return True  # never ingested = stale
    # Count only Mon–Fri between data_as_of and today
    biz_days = np.busday_count(data_as_of, date.today())
    return biz_days >= threshold_biz_days
```

### Frontend freshness display

| Staleness | FreshnessBadge | HealthCards bucket |
|-----------|---------------|-------------------|
| 0–1 calendar days | Green "À jour · J-0" | `up_to_date` |
| 2–7 calendar days | Amber "Périmé · J-3" | `stale` |
| 8+ calendar days | Red "Très périmé · J-15" | `very_stale` |
| Never ingested | Gray "Jamais ingéré" | `never_ingested` |

**Note:** Backend uses **business days** (Mon–Fri), frontend badge uses **calendar days**. They can disagree on weekends: a Friday update shows green on Monday (1 calendar day) but backend says stale (2+ business days).

### Ideal monitoring loop

```
Daily at 18:30 → scheduled refresh runs
Daily at 19:00 → check /market-data/health
  If very_stale > 0 or failed refresh → alert (Slack, email, etc.)
  If up_to_date == total_tracked → all good
```

---

## Prompt Context: Implement Daily Scheduled Refresh

```
### Task: Implement daily automatic refresh of market data

Architecture context:
- Worker file: services/worker/tasks/refresh_market_data.py
- Entry point: refresh_all_tracked_symbols(refresh_run_id, timeframe="1D", source_override=None, include_unverified=False)
- API trigger: POST /market-data/refresh → creates MarketRefreshRun row, enqueues job on "market_refresh" queue
- API file: services/api/app/routers/market_data.py
- Queue helper: services/api/app/queue.py → get_market_refresh_queue()
- Worker: services/worker/worker.py → runs with with_scheduler=True (RQ scheduler enabled)
- Model: MarketRefreshRun.trigger_source supports "scheduled" value
- Docker: infra/docker-compose.yml

Casablanca market closes at 15:30 Morocco time (UTC+1).
Data typically available on Bourse website by 16:00–17:00.
Recommended trigger time: 18:30 UTC+1, Monday–Friday.

The simplest approach: add a cron container to docker-compose.yml that POSTs to /market-data/refresh daily.
Alternative: use apscheduler in the API server's lifespan handler.

Requirements:
1. Create MarketRefreshRun with trigger_source="scheduled"
2. Use the existing refresh_all_tracked_symbols worker task
3. Frontend should see the refresh progress in RefreshStatusBar automatically
4. Log success/failure for monitoring
5. Handle weekends/holidays gracefully (worker skips if no new bars)
```
