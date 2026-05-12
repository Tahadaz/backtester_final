# Moroccan Market Signal Backtester

End-of-studies engineering project for a Moroccan investment-bank context. The application ingests market data, computes technical/factor signals, runs backtests and walk-forward analysis, and exposes the results through a FastAPI backend, RQ workers, and a Next.js frontend.

## Repository Map

| Path | Purpose |
| --- | --- |
| `frontend/` | Active Next.js application, auth pages, dashboard, signals, strategy, and API proxy. |
| `services/api/` | FastAPI service, routers, schemas, SQLAlchemy models, and Alembic migrations. |
| `services/worker/` | RQ worker entrypoint and long-running jobs for data refresh, signals, backtests, and analytics. |
| `core/quant_core/` | Shared quant, signal-engine, WFO, research, and strategy logic. |
| `infra/` | Docker Compose stacks, Caddy config, backup scripts, and VM deployment support. |
| `docs/` | Architecture, methodology, deployment, and operational documentation. |
| `latex/`, `report-pfe-mis3/`, `docs/presentations/` | Academic report and presentation deliverables. These are not required by the runtime. |

The active frontend is `frontend/`. Older duplicate frontend trees were removed to avoid ambiguity.

## Local Runtime

Start the full local stack from the repository root:

```bash
docker compose -f infra/docker-compose.yml up --build
```

Main local endpoints:

| Service | URL |
| --- | --- |
| Frontend (Docker Compose) | `http://localhost:3001` |
| Frontend (local `next dev`) | `http://localhost:3000` |
| API health | `http://localhost:8000/health` |
| MinIO console | `http://localhost:9001` |
| Postgres forwarded port | `localhost:5555` |

The frontend should call backend routes through its `/api/...` proxy. Docker Compose sets `UPSTREAM_API_BASE=http://quant_api:8000` for the frontend container.

## Static Public Samples

`frontend/public/data/` intentionally contains tiny synthetic JSON fixtures. They preserve the public static-dashboard/signals file contract without committing real market snapshots.

To regenerate full public snapshots from a populated database:

```bash
python frontend/scripts/export-scores.py
```

Do not commit full exports, Excel market dumps, parquet files, database backups, or private generated artifacts.

## Checks

Python core tests:

```bash
python -m pytest core/tests -q --tb=short
```

Frontend install and type check:

```bash
cd frontend
npm ci --legacy-peer-deps
npx tsc --noEmit
```

Frontend app build:

```bash
cd frontend
npm run build
```

Static public build:

```bash
cd frontend
npm run build:pages
npm run prune:pages
```

Compose validation:

```bash
docker compose -f infra/docker-compose.yml config
```

## Deployment Notes

Production deployment is documented in `docs/DEPLOY_RUNBOOK.md`. The VM stack uses `infra/docker-compose.gcp.yml`, GHCR images, Caddy, Postgres, Redis, MinIO, FastAPI, workers, and the Next.js frontend.

Operational auth and restore notes live under `docs/ops/`.
