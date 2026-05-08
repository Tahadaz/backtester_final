# Auth — Ops runbook

## Approve a pending user signup

Users register with `isActive = false`. Log into the Postgres DB and flip the flag:

```sql
-- List pending users
SELECT id, email, "isActive", "emailVerified" FROM users WHERE "isActive" = false;

-- Approve one user
UPDATE users SET "isActive" = true WHERE email = 'user@example.com';
```

Access the DB from the VM:
```bash
docker compose --env-file /etc/bt/env exec quant_postgres \
  psql -U app -d quant
```

## Create the first admin user directly (no signup form)

```sql
-- Run from psql inside the container
INSERT INTO users (id, email, "passwordHash", "isActive")
VALUES (
  gen_random_uuid()::text,
  'admin@example.com',
  -- Generate hash locally: node -e "const b=require('bcryptjs');console.log(b.hashSync('yourpassword',12))"
  '$2a$12$...',
  true
);
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
| `DATABASE_URL` | Postgres URL accessible from the frontend container |
| `INTERNAL_JWT_SECRET` | Random 32-byte hex. Used for API→backend JWT once multi-tenancy ships. |
