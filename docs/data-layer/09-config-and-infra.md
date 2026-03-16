# Data Layer — Configuration & Infrastructure

---

## Environment Variables

### API Server (`services/api/app/config.py`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `postgresql+psycopg2://app:app@127.0.0.1:5555/quant` | PostgreSQL connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection for RQ |
| `S3_ENDPOINT_URL` / `S3_ENDPOINT` | `http://localhost:9000` | MinIO / S3 endpoint |
| `S3_ACCESS_KEY_ID` / `S3_ACCESS_KEY` | `minio` | S3 access key |
| `S3_SECRET_ACCESS_KEY` / `S3_SECRET_KEY` | `minio12345` | S3 secret key |
| `S3_BUCKET` | `quant-artifacts` | Default S3 bucket |
| `S3_REGION` | `us-east-1` | AWS region (ignored by MinIO) |
| `S3_USE_SSL` | `false` | HTTPS for S3 |
| `DATASET_MAX_UPLOAD_BYTES` | `104857600` (100 MiB) | Max Excel upload size |
| `DATASET_METADATA_MAX_BYTES` | `32768` | Max metadata_json size |
| `BOURSE_STOCK_PAGE_URL` | `https://www.casablanca-bourse.com/bourseweb/Detail-Valeur.aspx?Cat=3&valeur={symbol}` | Bourse lookup template |
| `BOURSE_DIRECT_URL_TEMPLATE` | *(not set)* | Bourse OHLCV download URL template |
| `BOURSE_DIRECT_RESPONSE_FORMAT` | `excel` | Response format (excel/csv) |
| `RUNS_QUEUE_NAME` | `runs` | RQ queue for backtest + ingestion jobs |
| `MARKET_REFRESH_QUEUE_NAME` | `market_refresh` | RQ queue for refresh jobs |
| `MARKET_REFRESH_JOB_TIMEOUT_SECONDS` | `3600` | Refresh job timeout (1 hour) |

### Worker (`services/worker/config.py`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `WORKER_QUEUES` | `("runs", "defaults_discovery", "market_refresh")` | Queues the worker listens on |
| `RUN_HEARTBEAT_INTERVAL_SECONDS` | `15` | Heartbeat frequency for long jobs |
| `RUN_ORPHAN_STALE_SECONDS` | `600` | Mark orphan if no heartbeat for 10 min |

### Frontend (`quant-backtesting-frontend`)

| Variable | Used in | Default | Purpose |
|----------|---------|---------|---------|
| `UPSTREAM_API_BASE` / `API_URL` | `app/api/[...path]/route.ts` | `http://127.0.0.1:8000` | FastAPI upstream |
| `API_KEY` | `app/api/[...path]/route.ts` | `""` | Injected as `x-api-key` header |

---

## Queue Architecture

```
                    ┌─────────────────────────┐
                    │       Redis (RQ)         │
                    │                          │
                    │  Queue: "runs"           │ ← backtest jobs + Excel ingestion
                    │  Queue: "defaults_       │ ← defaults discovery
                    │          discovery"      │
                    │  Queue: "market_refresh" │ ← stock refresh jobs
                    └──────┬──────┬──────┬─────┘
                           │      │      │
                    ┌──────┘      │      └──────┐
                    ▼             ▼              ▼
            ┌───────────┐ ┌───────────┐ ┌───────────────┐
            │  Worker   │ │  Worker   │ │  Worker       │
            │  (runs +  │ │ (defaults)│ │ (all queues)  │
            │  market_  │ │           │ │               │
            │  refresh) │ │           │ │               │
            └───────────┘ └───────────┘ └───────────────┘
```

### Queue Functions (`services/api/app/queue.py`)

```python
def get_queue() -> Queue:
    # Redis URL from settings
    # Queue name: settings.RUNS_QUEUE_NAME ("runs")
    # Default timeout: settings.RUN_JOB_TIMEOUT_SECONDS (21600s = 6h)

def get_market_refresh_queue() -> Queue:
    # Same Redis connection
    # Queue name: settings.MARKET_REFRESH_QUEUE_NAME ("market_refresh")
    # Default timeout: settings.MARKET_REFRESH_JOB_TIMEOUT_SECONDS (3600s = 1h)
```

**Critical:** if `"market_refresh"` is not in `WORKER_QUEUES`, refresh jobs are enqueued but never processed. Verify:
```bash
python -c "from services.worker.config import settings; print(settings.WORKER_QUEUES)"
# Must include 'market_refresh'
```

---

## Docker Compose (`infra/docker-compose.yml`)

### Services

| Service | Image | Port(s) | Purpose |
|---------|-------|---------|---------|
| `quant_postgres` | `postgres:16` | `5555:5432` | Primary database |
| `quant_redis` | `redis:7` | `6379:6379` | RQ queue backend |
| `quant_minio` | `minio/minio` | `9000:9000`, `9001:9001` | S3-compatible storage (API + console) |
| `quant_minio_init` | `minio/mc` | — | One-time bucket creation |
| `quant_db_migrate` | custom | — | `alembic upgrade head` (one-time) |
| `quant_worker` | custom | — | RQ worker: `runs` + `market_refresh` |
| `quant_worker_defaults` | custom | — | RQ worker: `defaults_discovery` |

### Worker Environment

```yaml
environment:
  REDIS_URL: redis://quant_redis:6379/0
  DATABASE_URL: postgresql+psycopg2://app:app@quant_postgres:5432/quant
  S3_ENDPOINT: http://quant_minio:9000
  S3_ACCESS_KEY: minio
  S3_SECRET_KEY: minio12345
  S3_BUCKET: quant-artifacts
  WORKER_CONCURRENCY: 2
  OMP_NUM_THREADS: 1
  MKL_NUM_THREADS: 1
  OPENBLAS_NUM_THREADS: 1
```

### Startup Order

1. `quant_postgres` + `quant_redis` + `quant_minio` start in parallel
2. `quant_minio_init` creates the bucket (depends_on: minio healthy)
3. `quant_db_migrate` runs alembic (depends_on: postgres healthy)
4. `quant_worker` + `quant_worker_defaults` start (depends_on: migrate + redis + minio healthy)

---

## Database Migrations

Run migrations:
```bash
cd services/api
alembic upgrade head
```

Migration chain (data layer relevant):
```
c788e94f3062  ← add market_data_store (base table)
      │
a1b2c3d4e5f6  ← add Morocco market data tables (stock_master, provider_symbol_map, refresh tables)
      │
b2c3d4e5f6a7  ← add bourse_url to stock_master
```
