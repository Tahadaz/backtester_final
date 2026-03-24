# 10 — Configuration & Infrastructure

---

## Environment Variables

### S3 / MinIO
| Variable | Default | Purpose |
|----------|---------|---------|
| `S3_ENDPOINT_URL` | — | MinIO URL (e.g., `http://localhost:9000`) |
| `S3_ACCESS_KEY_ID` | — | Access key |
| `S3_SECRET_ACCESS_KEY` | — | Secret key |
| `S3_BUCKET` | `quant-artifacts` | Bucket name |

### Database
| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | — | PostgreSQL connection string |

### API
| Variable | Default | Purpose |
|----------|---------|---------|
| `API_KEY` | — | x-api-key header value for auth |
| `DATASET_MAX_UPLOAD_BYTES` | — | Max Excel upload size |

### Market Data
| Variable | Default | Purpose |
|----------|---------|---------|
| `BOURSE_STOCK_PAGE_URL` | `https://www.casablanca-bourse.com/bourseweb/Detail-Valeur.aspx?Cat=3&valeur={symbol}` | Template for Bourse lookup |
| `BOURSE_DIRECT_URL_TEMPLATE` | — | If set, uses BourseDirectAdapter; else BDCSessionAdapter |
| `MARKET_REFRESH_CRON_ENABLED` | `"1"` | Set to `"0"` to disable daily cron |

### Redis / RQ
| Variable | Default | Purpose |
|----------|---------|---------|
| `REDIS_URL` | — | Redis connection for RQ job queue |

---

## Docker Compose (`infra/docker-compose.yml`)

Key services:
- **postgres**: PostgreSQL database
- **redis**: RQ job queue backend
- **minio**: S3-compatible object storage
- **api**: FastAPI application (with scheduler)
- **worker**: RQ worker processing ingest + refresh tasks

---

## Queue Configuration

- **Queue name**: default RQ queue
- **Job types**: `ingest_excel_to_store`, `refresh_all_tracked_symbols`, `refresh_single_symbol`
- **Timeout**: default RQ timeout (configurable per job)
- **Retry**: no automatic retry; errors logged to market_refresh_error

---

## Frontend Proxy

Next.js API routes proxy all `/api/*` requests to the FastAPI backend:
- Adds `x-api-key` header automatically
- Base URL configured via `NEXT_PUBLIC_API_URL` or defaults to `http://localhost:8000`
