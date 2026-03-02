# Local DB + Alembic (Docker)

## 1) Start local Docker services

From repo root:

```bat
docker compose -f infra\docker-compose.yml up -d
```

This starts Postgres as container `quant_postgres` on `localhost:5555` with:

- user: `app`
- password: `app`
- database: `quant`

## 2) Run migrations using local-only scripts

Use the helper scripts at repo root:

```bat
scripts\migrate_local.bat
```

This forces:

```text
DATABASE_URL=postgresql+psycopg2://app:app@localhost:5555/quant
```

and runs:

```text
alembic -c services\api\alembic.ini upgrade head
```

To see current revision:

```bat
scripts\current_local.bat
```

## 3) Verify inside the Postgres container

Check Alembic head revision:

```bat
docker exec -it quant_postgres psql -U app -d quant -c "select * from alembic_version;"
```

List public tables:

```bat
docker exec -it quant_postgres psql -U app -d quant -c "select tablename from pg_tables where schemaname='public' order by tablename;"
```

Expected core tables include:

- `dataset`
- `run`
- `artifact`
- `run_metric`
- `fill`
- `position_ledger`
