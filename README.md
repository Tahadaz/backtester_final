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
| `academic/` | Academic report and presentation deliverables (PFE report, slide generators). Kept locally under `academic/` and gitignored — not part of the runtime. |

The active frontend is `frontend/`. Older duplicate frontend trees were removed to avoid ambiguity.

## Local Runtime

Start the backend, workers, and local infrastructure from the repository root:

```bash
docker compose -f infra/docker-compose.yml up --build
```

Start the single local frontend separately:

```bash
cd frontend
npm run dev
```

Main local endpoints:

| Service | URL |
| --- | --- |
| Frontend | `http://localhost:3000` |
| API health | `http://localhost:8000/health` |
| MinIO console | `http://localhost:9001` |
| Postgres forwarded port | `localhost:5555` |

The frontend should call backend routes through its `/api/...` proxy. Local `next dev` uses `UPSTREAM_API_BASE=http://127.0.0.1:8000` from `frontend/.env.local` when present, otherwise it falls back to the same URL in code.

For a production-container smoke test of the frontend, run it explicitly on the same local port:

```bash
docker compose -f infra/docker-compose.yml --profile frontend-container up --build quant_frontend
```

The Docker frontend also binds `http://localhost:3000`; if local `next dev` is already running, it should fail instead of creating another frontend on a different port.

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

Production deployment is documented in `docs/DEPLOY_RUNBOOK.md`. The VM stack uses `infra/docker-compose.prod.yml`, GHCR images, Caddy, Postgres, Redis, MinIO, FastAPI, workers, and the Next.js frontend.

Operational auth and restore notes live under `docs/ops/`.
