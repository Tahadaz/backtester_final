# Application Map

This map reflects the current deployable application.

## Runtime Topology

Production on Oracle VM is a Docker Compose stack defined by `infra/docker-compose.prod.yml`.

Request path:

```text
Browser
  -> Caddy edge proxy (`edge_proxy`, ports 80/443)
  -> Next.js app (`quant_frontend`, port 3000 inside compose)
  -> Next.js `/api/[...path]` proxy
  -> FastAPI (`quant_api`, port 8000 inside compose)
  -> Postgres / Redis / MinIO
  -> RQ workers for long-running jobs
```

Core services:

| Service | Purpose | Persistent state |
| --- | --- | --- |
| `edge_proxy` | TLS, IP allowlist, reverse proxy to frontend | `caddy_data`, `caddy_config` |
| `quant_frontend` | Next.js dashboard, auth pages, API proxy | Uses Postgres auth tables |
| `quant_api` | FastAPI routers, auth checks, queue producers, metadata APIs | Postgres, Redis, MinIO |
| `quant_worker` | General RQ worker for runs, market refresh, signal engine, signal backtest, score history | Postgres, Redis, MinIO |
| `quant_worker_defaults` | Dedicated defaults discovery queue worker | Postgres, Redis, MinIO |
| `quant_worker_wfo` | Dedicated WFO signal queue worker | Postgres, Redis, MinIO |
| `quant_postgres` | Main relational database | `pgdata` |
| `quant_redis` | RQ queues, cache, rate-limit buckets | `redisdata` |
| `quant_minio` | S3-compatible artifact and market data object store | `miniodata` |
| `quant_minio_init` | One-shot bucket creation for `quant-artifacts` and `bt-backups` | None |

Local development uses `infra/docker-compose.yml`, which builds images from the working tree and bind-mounts source directories.

## Source Layout

| Path | Role |
| --- | --- |
| `frontend/` | Current Next.js app used by the VM image and compose stack. |
| `services/api/` | FastAPI app, routers, Pydantic schemas, SQLAlchemy models, Alembic migrations. |
| `services/worker/` | RQ worker entrypoint and long-running task implementations. |
| `core/quant_core/` | Quant, signal, WFO, strategy, research, and portfolio logic shared by API and workers. |
| `infra/` | Oracle Cloud VM Docker Compose, Caddy, systemd timer, and backup scripts. |
| `.github/workflows/` | CI, image build, VM deploy, and static dashboard Pages deploy. |
| `docs/ops/` | Existing auth and restore operational notes. |
| `latex/`, `report-pfe-mis3/`, `docs/presentations/` | Academic report and presentation deliverables; not used by runtime containers. |

`frontend/` is the only active UI tree. The older duplicate frontend tree has been removed from the handoff.

## API Surface

FastAPI starts in `services/api/app/main.py` and registers these router groups:

| Router group | Typical use |
| --- | --- |
| `/health` | Container and smoke-test health check. |
| `/runs`, `/results`, `/datasets`, `/defaults` | Backtest/optimization lifecycle, artifacts, datasets, defaults discovery. Protected when `API_KEY` is set. |
| `/market-data`, `/market-data-indices` | Upload, refresh, inspect market and index data. Protected when `API_KEY` is set. |
| `/analytics` | Predictive history, leaderboard, bucket matrix, edge metrics, edge warmup. |
| `/data`, `/dashboard`, `/leaderboard`, `/snapshots` | Public/read dashboard and data surfaces. `/dashboard/portfolio-ticket` turns a selected basket into next-session trade sizing; `/dashboard/daily-blotter` compares that ticket with manual positions to produce buy/hold/reduce/exit/watch actions. |
| `/strategy`, `/strategy-signals`, `/strategy-backtest-runs`, `/wfo-signals` | Strategy builder, signal computation, WFO signal views, strategy backtest jobs. |

The Next.js catch-all proxy in `frontend/app/api/[...path]/route.ts` injects `X-API-Key` from the frontend container env when `API_KEY` is set. Browser code should normally call `/api/...`, not the API container directly.

## Auth And Access

Access has three layers:

1. Caddy allowlist in `infra/Caddyfile.prod`: only local VM traffic, Docker bridge traffic, and `ALLOWED_REMOTE_IPS` can reach the frontend.
2. NextAuth credentials auth in `frontend/auth/index.ts`: users can sign up, but `isActive` defaults to false.
3. API auth in `services/api/app/auth.py`: protected FastAPI routers accept `X-API-Key`; admin operations accept `X-Admin-Api-Key` or an admin-scoped JWT.

Operational auth notes:

- Approve users with SQL from `docs/ops/auth.md`.
- Set `NEXTAUTH_SECRET` and `NEXTAUTH_URL` for production.
- Set `API_KEY` in both frontend and API containers through compose.
- Set `ADMIN_API_KEY` for admin-only warmup/recompute endpoints.

## Data And Artifacts

Primary state:

- Postgres stores run metadata, metrics, folds, auth users/sessions, market metadata, signal results, score history, snapshots, and job status rows.
- MinIO stores datasets, parquet market data, generated artifacts, and backups.
- Redis stores RQ queues, scheduled jobs, edge cache entries, and trigger rate-limit counters.

Object buckets created by deploy compose:

- `quant-artifacts`: application data and generated artifacts.
- `bt-backups`: database backups written by `infra/scripts/pg_backup.sh`.

## Worker Queues

| Queue | Producers | Consumers in VM compose |
| --- | --- | --- |
| `runs` | Backtest/optimization APIs, factor monitor/recalibration aliases | `quant_worker` |
| `market_refresh` | Market-data refresh API and scheduler, dashboard snapshot jobs | `quant_worker` |
| `signal_engine` | Signal engine triggers and weekly schedules | `quant_worker` |
| `signal_backtest` | Signal backtest triggers | `quant_worker` |
| `score_history` | Analytics predictive-history triggers | `quant_worker` |
| `defaults_discovery` | Defaults discovery APIs | `quant_worker_defaults` |
| `wfo_signals` | WFO signal APIs and weekly schedules | `quant_worker_wfo` |

`services/worker/worker.py` also registers weekly RQ schedules for signal engine, WFO signals, and signal backtests when workers start.

## Scheduled Jobs

FastAPI starts `services/api/app/scheduler.py` on app lifespan unless `MARKET_REFRESH_CRON_ENABLED=0`.

Default schedule in `Africa/Casablanca`:

| Time | Job |
| --- | --- |
| Mon-Fri 20:00 | Daily market refresh |
| Mon-Fri 23:30 | Dashboard snapshot maintenance refresh |
| Mon-Fri 22:00 | Factor monitor |
| Jan/Apr/Jul/Oct 1 at 02:00 | Quarterly factor recalibration |

The VM compose sets `API_WORKERS=1` by default so this scheduler is not duplicated across multiple API worker processes.

## Migrations

Alembic lives under `services/api/alembic`. The deploy workflow runs:

```bash
docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml run --rm quant_api \
  alembic -c services/api/alembic.ini upgrade head
```

Current local audit result: Alembic reports one head, `b2c3d4e5f6a8`.

## Cache And Warmup

Important warmup/cache paths:

- Redis edge metrics cache: `POST /api/analytics/edge/warm` with `X-Admin-Api-Key`.
- Score history population: `POST /api/analytics/predictive-history/trigger-all` with admin auth.
- Dashboard snapshots: queued by scheduler, and refresh tasks live in `services/worker/tasks/dashboard_snapshot.py`.
- Signal engine/WFO batches: queued by strategy signal and WFO signal endpoints; workers persist results into Postgres.
- Dashboard portfolio tickets depend on current dashboard rows, OHLCV history, Edge metrics, and support/resistance calculations.
- Daily blotters depend on portfolio tickets plus manual desk positions in `desk_portfolio_position`; they are advisory next-session instructions, not broker orders.

## Layer Documentation

Detailed per-layer docs live in `docs/<layer-name>/`. Each layer has a `00-INDEX.md` entry point.

| Layer | Index | Covers |
| --- | --- | --- |
| Data | [`docs/data-layer/00-INDEX.md`](data-layer/00-INDEX.md) | OHLCV ingestion, dataset object keys, daily refresh |
| Factor | [`docs/factor-layer/00-INDEX.md`](factor-layer/00-INDEX.md) | Factor universe, statistical battery, factor×TA conditioning |
| Signal generation | [`docs/signal-generation/00-INDEX.md`](signal-generation/00-INDEX.md) | Candidate universe, OOS evaluation, ensembling, indicator catalog |
| Strategy | [`docs/strategy-layer/00-INDEX.md`](strategy-layer/00-INDEX.md) | Strategy builder, entry/exit/risk layers, backtest handoff |
| Backtest | [`docs/backtest-layer/00-INDEX.md`](backtest-layer/00-INDEX.md) | WFO methodology, PROM objective, sizing from OOS |
| Dashboard | [`docs/dashboard-layer/00-INDEX.md`](dashboard-layer/00-INDEX.md) | Snapshot export, navigation, dashboard types |
| Analytics | [`docs/analytics-layer/00-INDEX.md`](analytics-layer/00-INDEX.md) | Predictive history, edge metrics, leaderboard |
| **Fundamentals** | [`docs/fundamentals-layer/00-INDEX.md`](fundamentals-layer/00-INDEX.md) | **6-pillar scoring + 7-model valuation engine, Excel ingestion, known issues** |

## Known Deployment Risks

| Risk | Status | Minimal action |
| --- | --- | --- |
| Missing `NEXTAUTH_SECRET` | Compose warns and frontend auth is unsafe/broken if unset. | Set it in `/etc/bt/env`. |
| Caddy allowlist can block supervisor access | Expected by design. | Add supervisor/public CIDRs to `ALLOWED_REMOTE_IPS`. |
| DB password is hardcoded as `app` in compose URLs and Postgres env. | Existing deploy debt. | Accept for a private VM or schedule a coordinated secret rotation. |
| Artifact fetch proxy route appears unresolved in current `frontend/` tree. | App-level risk, not changed here. | Verify run artifact downloads before supervisor demo. |
| Initial database has no active users. | Operational requirement. | Create/approve at least one user before demo. |
| Initial database may have no market data/signals. | Presentation risk. | Restore a known-good backup or run refresh/warmup jobs. |
