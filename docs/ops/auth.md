# Auth - Ops runbook

## Approve a pending user signup

Users register with `isActive = false`. Log into the Postgres DB and flip the flag:

```sql
-- List pending users
SELECT id, email, "isActive", "emailVerified" FROM users WHERE "isActive" = false;

-- Approve one user
UPDATE users SET "isActive" = true WHERE email = 'user@example.com';
```

Access the DB from the VM as the `deploy` user:

```bash
cd /opt/bt
docker compose --env-file /etc/bt/env -f infra/docker-compose.gcp.yml exec quant_postgres \
  psql -U app -d quant
```

Or run the approval without opening an interactive `psql` session:

```bash
cd /opt/bt
docker compose --env-file /etc/bt/env -f infra/docker-compose.gcp.yml exec -T quant_postgres \
  psql -U app -d quant -c "UPDATE users SET \"isActive\" = true WHERE email = 'user@example.com';"
```

DBeaver is not the preferred production path because Postgres is not exposed on the VM public interface. Use `docker compose exec` over SSH unless an SSH tunnel is intentionally configured.

## Create the first admin user directly (no signup form)

```sql
-- Run from psql inside the container
INSERT INTO users (id, email, "passwordHash", "isActive")
VALUES (
  gen_random_uuid()::text,
  'admin@example.com',
  -- Generate hash locally or in the frontend container:
  -- node -e "const b=require('bcryptjs');console.log(b.hashSync('yourpassword',12))"
  '$2a$12$...',
  true
);
```

Generate a bcrypt hash in the deployed frontend container:

```bash
cd /opt/bt
docker compose --env-file /etc/bt/env -f infra/docker-compose.gcp.yml exec -T quant_frontend \
  node -e "const b=require('bcryptjs'); console.log(b.hashSync(process.argv[1], 12))" 'replace-this-password'
```

## Reset a password

```sql
-- Generate a new hash first (see above), then:
UPDATE users SET "passwordHash" = '$2a$12$...' WHERE email = 'user@example.com';
```

## Revoke access

```sql
UPDATE users SET "isActive" = false WHERE email = 'user@example.com';
```

## Required secrets (set in /etc/bt/env on the VM)

| Variable | Description |
|---|---|
| `NEXTAUTH_SECRET` | Random 32-byte hex string. `openssl rand -hex 32` |
| `NEXTAUTH_URL` | Full URL of the app, e.g. `https://84.8.218.252.sslip.io` |
| `AUTH_REQUIRED` | `true` on deployed app to require login; local compose defaults to `false`. |
| `DATABASE_URL` | Postgres URL accessible from the frontend container |
| `INTERNAL_JWT_SECRET` | Random 32-byte hex. Used for API-to-backend JWT once multi-tenancy ships. |
