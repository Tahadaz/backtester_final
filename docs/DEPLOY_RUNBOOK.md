# Oracle VM Deploy Runbook

This is the source-of-truth deploy runbook for the Oracle VM path.

## Current Deploy Assets

| Asset | Status |
| --- | --- |
| `infra/docker-compose.prod.yml` | Production VM compose stack. Uses GHCR images for API, worker, and frontend. |
| `infra/Caddyfile.prod` | TLS reverse proxy with IP allowlist. |
| `.github/workflows/build-images.yml` | Builds `linux/arm64` images on pushes to `main`. |
| `.github/workflows/deploy-vm.yml` | SSH deploy to Oracle VM after image builds complete. |
| `services/api/Dockerfile` | FastAPI image. |
| `services/worker/Dockerfile` | RQ worker image. |
| `frontend/Dockerfile` | Next.js standalone image. |
| `services/api/alembic/` | DB migrations. Current audit: one Alembic head, `f7a8b9c1d2e3`. |

## Known Current Oracle VM

These values describe the current OCI test VM, not a reusable default for every deployment:

| Item | Value |
| --- | --- |
| Public IP | `84.8.218.252` |
| Current temporary domain | `84.8.218.252.sslip.io` |
| Requested free domain | `taha-signal.is-a.dev` via `is-a-dev/register` |
| Cloud-image sudo user | `opc` |
| Application/docker user | `deploy` |
| Local private key path on the Windows workstation | `C:\Users\taha\Downloads\ssh-key-2026-05-07.key` |

Operational rule: use `opc` for sudo work such as editing `/etc/bt/env`, firewalld, or systemd. Use `deploy` for Docker Compose. Running `sudo docker compose` as `opc/root` can fail with `unauthorized` against GHCR because Docker registry credentials are user-scoped.

## Fixed During This Audit

- VM workers now use `ghcr.io/tahadaz/bt-worker:${IMAGE_TAG}` instead of building on the VM.
- VM compose now creates both MinIO buckets: `quant-artifacts` and `bt-backups`.
- `ADMIN_API_KEY` and worker concurrency env vars now pass through compose.
- VM API defaults to `API_WORKERS=1` so FastAPI scheduler jobs are not duplicated across Uvicorn workers.
- Caddy allowlist now includes local VM and Docker bridge traffic for health checks.
- GitHub deploy smoke test now runs on the VM with `curl --resolve`, avoiding false failure from the public IP allowlist.
- The systemd heartbeat now probes the real Caddy HTTPS route locally.
- Frontend artifact downloads now go through `/api/artifacts/fetch`, a server-side proxy that only allows MinIO artifact hosts.
- MinIO is bound to `127.0.0.1:9000` on the VM so host cron can upload Postgres backups without exposing MinIO publicly.
- Oracle Linux `firewalld` must allow `http` and `https`; the OCI subnet/security-list must also allow inbound `80/tcp` and `443/tcp`.

## Remaining Deployment Risks

| Risk | Severity | Action |
| --- | --- | --- |
| `NEXTAUTH_SECRET` unset | High | Must be set in `/etc/bt/env` before starting frontend. |
| Oracle VM architecture mismatch | High | Current image workflow builds `linux/arm64`. Use an Ampere ARM VM or change workflow platforms. |
| GHCR image access | High if packages are private | Log in to GHCR on the VM with a PAT that can read packages. |
| Caddy IP allowlist blocks supervisor | High for demo | Add supervisor CIDRs to `ALLOWED_REMOTE_IPS`. |
| Corporate firewall blocks dynamic DNS | High for bank network access | Replace `sslip.io` with a normal domain or ask IT for a whitelist/internal DNS record. |
| Free domain review delay | Medium | `is-a.dev` requires maintainer/code-owner review; approval can take hours or days. |
| No active user | High for demo | Create or approve a user before the demo. |
| Empty DB or stale data | High for demo | Restore a known-good backup or run refresh/warmup jobs. |
| Hardcoded Postgres password `app` | Medium | Accept for private VM or plan coordinated secret rotation. |

## Required VM Env File

Create `/etc/bt/env` on the VM. Values below are examples; replace secrets.

```bash
DOMAIN=84.8.218.252.sslip.io
NEXTAUTH_URL=https://84.8.218.252.sslip.io
NEXTAUTH_SECRET=replace_with_openssl_rand_hex_32

API_KEY=replace_with_openssl_rand_hex_32
ADMIN_API_KEY=replace_with_openssl_rand_hex_32
INTERNAL_JWT_SECRET=replace_with_openssl_rand_hex_32
BLOOMBERG_BRIDGE_API_KEY=replace_with_openssl_rand_hex_32
BLOOMBERG_BRIDGE_MAX_UPLOAD_BYTES=268435456

MINIO_ROOT_USER=btminio
MINIO_ROOT_PASSWORD=replace_with_long_random_secret

ALLOWED_REMOTE_IPS="197.230.23.178/32 196.127.81.67/32 196.70.253.81/32"
API_WORKERS=1
WORKER_CONCURRENCY=1
OMP_NUM_THREADS=1
MKL_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1

SENTRY_DSN=
```

Notes:

- Add the supervisor office public egress IP as another CIDR in `ALLOWED_REMOTE_IPS`, separated by a space. For a single IP, use `/32`.
- Use the public IP shown by `curl https://api.ipify.org` from the client network, not the workstation's private `10.x` or `172.x` intranet address.
- `API_KEY` protects API routes. The Next.js server injects it when browser code calls `/api/...`.
- `ADMIN_API_KEY` is required for admin-only snapshot, batch, and edge warmup endpoints.
- `BLOOMBERG_BRIDGE_API_KEY` only authorizes `/bridge/bloomberg/*` ingestion calls from the Bloomberg bridge.
- `NEXTAUTH_SECRET`, `API_KEY`, `ADMIN_API_KEY`, `INTERNAL_JWT_SECRET`, `BLOOMBERG_BRIDGE_API_KEY`, and `MINIO_ROOT_PASSWORD` can be generated with `openssl rand -hex 32`.

## Oracle VM Checklist

1. Provision an Oracle Linux or Ubuntu VM. Prefer `VM.Standard.A1.Flex` ARM64 because CI builds ARM64 images.
2. In the OCI network security list, allow inbound `22/tcp` from admin IPs and `80/tcp`, `443/tcp` as needed. For OCI ingress rules, use source type `CIDR`. Use `x.x.x.x/32` for a single admin/company public IP, or `0.0.0.0/0` temporarily for public web access. Caddy still enforces the app allowlist.
3. Point `DOMAIN` to the public VM IP. `84.8.218.252.sslip.io` works only while the VM public IP is `84.8.218.252`, but some corporate firewalls classify `sslip.io` as dynamic DNS and block it.
4. Bootstrap with the cloud-image user, then create the Actions deploy user:

```bash
ssh -i ~/Downloads/ssh-key-2026-05-07.key opc@84.8.218.252
```

From Windows PowerShell, use:

```powershell
ssh -i C:\Users\taha\Downloads\ssh-key-2026-05-07.key -o IdentitiesOnly=yes opc@84.8.218.252
```

The current Oracle VM uses the `opc` user. GitHub Actions deploys as `deploy`, so install the same public key for `deploy` before relying on `.github/workflows/deploy-vm.yml`.

5. Install Docker, Git, and the MinIO client:

```bash
if command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y ca-certificates curl git tar gzip
else
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl git tar gzip
fi
curl -fsSL https://get.docker.com | sudo sh
sudo useradd -m -s /bin/bash deploy || true
sudo usermod -aG docker deploy
sudo mkdir -p /opt/bt /etc/bt
sudo chown -R deploy:deploy /opt/bt

ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) MC_ARCH=arm64 ;;
  x86_64|amd64) MC_ARCH=amd64 ;;
  *) echo "Unsupported mc architecture: $ARCH" >&2; exit 1 ;;
esac
curl -fsSL "https://dl.min.io/client/mc/release/linux-${MC_ARCH}/mc" -o /tmp/mc
sudo install -m 0755 /tmp/mc /usr/local/bin/mc

if command -v firewall-cmd >/dev/null 2>&1 && sudo firewall-cmd --state >/dev/null 2>&1; then
  sudo firewall-cmd --permanent --add-service=http
  sudo firewall-cmd --permanent --add-service=https
  sudo firewall-cmd --reload
fi
```

6. Install the env file:

```bash
sudo tee /etc/bt/env >/dev/null <<'EOF'
DOMAIN=84.8.218.252.sslip.io
NEXTAUTH_URL=https://84.8.218.252.sslip.io
NEXTAUTH_SECRET=replace_me
API_KEY=replace_me
ADMIN_API_KEY=replace_me
INTERNAL_JWT_SECRET=replace_me
BLOOMBERG_BRIDGE_API_KEY=replace_me
BLOOMBERG_BRIDGE_MAX_UPLOAD_BYTES=268435456
MINIO_ROOT_USER=btminio
MINIO_ROOT_PASSWORD=replace_me
ALLOWED_REMOTE_IPS="197.230.23.178/32 196.127.81.67/32 196.70.253.81/32"
API_WORKERS=1
WORKER_CONCURRENCY=1
OMP_NUM_THREADS=1
MKL_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
SENTRY_DSN=
EOF
sudo chown root:docker /etc/bt/env
sudo chmod 640 /etc/bt/env
```

7. Clone the repo:

```bash
sudo -iu deploy
git clone https://github.com/Tahadaz/backtester_final.git /opt/bt
cd /opt/bt
```

8. If GHCR packages are private, log in once:

```bash
echo '<ghcr_pat_with_read_packages>' | docker login ghcr.io -u Tahadaz --password-stdin
```

Run this as `deploy`. If it is run only as `deploy`, later `sudo docker compose ... pull` as `root` can still fail with `unauthorized`.

9. First deploy manually:

```bash
cd /opt/bt
git fetch --quiet
git reset --hard origin/main

IMAGE_TAG=latest docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml pull

IMAGE_TAG=latest docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml run --rm quant_api \
  alembic -c services/api/alembic.ini upgrade head

IMAGE_TAG=latest docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml up -d --remove-orphans
IMAGE_TAG=latest docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml ps
```

10. Install heartbeat timer:

```bash
sudo cp /opt/bt/infra/systemd/bt-heartbeat.service /etc/systemd/system/
sudo cp /opt/bt/infra/systemd/bt-heartbeat.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bt-heartbeat.timer
sudo systemctl list-timers bt-heartbeat.timer
```

Install the safe Docker housekeeping timer at the same time. It retains active
images plus one rollback release, and never prunes named volumes or backups:

```bash
sudo cp /opt/bt/infra/systemd/bt-docker-housekeeping.service /etc/systemd/system/
sudo cp /opt/bt/infra/systemd/bt-docker-housekeeping.timer /etc/systemd/system/
sudo chmod 0755 /opt/bt/infra/scripts/docker_housekeeping.sh
sudo systemctl daemon-reload
sudo systemctl enable --now bt-docker-housekeeping.timer
```

11. Configure backups:

```bash
sudo cp /opt/bt/infra/scripts/pg_backup.sh /usr/local/bin/pg_backup.sh
sudo chmod +x /usr/local/bin/pg_backup.sh

sudo -iu deploy bash -lc 'set -a; source /etc/bt/env; set +a; /usr/local/bin/mc alias set local http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"; /usr/local/bin/mc mb --ignore-existing local/bt-backups; /usr/local/bin/mc ilm add --expiry-days 30 local/bt-backups || true'

echo "0 1 * * * /usr/local/bin/pg_backup.sh >> /var/log/bt-backup.log 2>&1" | sudo crontab -u deploy -
```

## GitHub Actions Setup

Required repository secrets:

| Secret | Purpose |
| --- | --- |
| `ORACLE_HOST` | VM public IP or DNS name for SSH. |
| `ORACLE_SSH_KEY` | Private SSH key for the `deploy` user. |
| `DOMAIN` | Public app domain, for smoke tests. |

Deploy flow:

1. Push to `main`.
2. `build-images.yml` builds and pushes `bt-api`, `bt-worker`, and `bt-frontend` images tagged by commit SHA and `latest`.
3. `deploy-vm.yml` SSHes to `/opt/bt`, resets to `origin/main`, pulls images with `IMAGE_TAG=<sha>`, runs Alembic, starts compose, prunes old images, then smokes the app locally through Caddy.

## Domain And Corporate Network Notes

What the current rollout proved:

- `84.8.218.252.sslip.io` resolves correctly to `84.8.218.252` and Caddy can issue a valid certificate for it.
- Bank/corporate filtering can still block `sslip.io` because it is categorized as dynamic DNS. DNS success does not mean HTTPS access will be allowed.
- Cloudflare Worker proxy hostnames can also be blocked by corporate filtering and are not a reliable replacement for a normal domain in this environment.
- The pending free-domain route is `taha-signal.is-a.dev`; `is-a.dev` requires code-owner review before DNS is active.
- For same-day reliable access from a filtered bank network, use a normal paid domain or ask company IT to create/whitelist a DNS name.

When a normal domain is ready, point it to the VM with an `A` record:

```text
Type: A
Name: @
Value: 84.8.218.252
TTL: Auto
```

Optional `www`:

```text
Type: CNAME
Name: www
Value: <domain>
TTL: Auto
```

Then update the VM env as `opc`. Set `NEW_DOMAIN` to the approved free domain or paid domain:

```bash
NEW_DOMAIN=taha-signal.is-a.dev
sudo cp /etc/bt/env /etc/bt/env.bak.$(date -u +%Y%m%dT%H%M%SZ)
sudo sed -i -E "s|^DOMAIN=.*|DOMAIN=${NEW_DOMAIN}|; s|^NEXTAUTH_URL=.*|NEXTAUTH_URL=https://${NEW_DOMAIN}|" /etc/bt/env
sudo grep -E '^(DOMAIN|NEXTAUTH_URL)=' /etc/bt/env
```

Recreate the frontend and Caddy as `deploy` so `NEXTAUTH_URL` and the Caddy site name are refreshed:

```bash
cd /opt/bt
TAG=$(docker inspect -f '{{.Config.Image}}' quant_frontend | sed 's|^ghcr.io/tahadaz/bt-frontend:||')
IMAGE_TAG="$TAG" docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml up -d --no-deps --force-recreate quant_frontend edge_proxy
```

## Allowlist Updates

To add a client/company public IP to the Caddy allowlist, run these as `opc`:

```bash
NEW_IP=196.70.253.81
sudo cp /etc/bt/env /etc/bt/env.bak.$(date -u +%Y%m%dT%H%M%SZ)
sudo sed -i -E "s|^ALLOWED_REMOTE_IPS=\"([^\"]*)\"|ALLOWED_REMOTE_IPS=\"\1 ${NEW_IP}/32\"|" /etc/bt/env
sudo grep '^ALLOWED_REMOTE_IPS=' /etc/bt/env
```

Then recreate only Caddy as `deploy`:

```bash
cd /opt/bt
TAG=$(docker inspect -f '{{.Config.Image}}' quant_frontend | sed 's|^ghcr.io/tahadaz/bt-frontend:||')
IMAGE_TAG="$TAG" docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml up -d --no-deps --force-recreate edge_proxy
```

Avoid heredocs and pasted multi-line Python in a remote terminal for simple env changes; indentation and line wrapping caused avoidable failures during the rollout.

## Troubleshooting Client Access

Run these from the client network that cannot reach the app:

```powershell
curl.exe -s https://api.ipify.org
nslookup 84.8.218.252.sslip.io
Test-NetConnection 84.8.218.252 -Port 443
curl.exe -4 -I https://84.8.218.252.sslip.io/login
```

Interpretation:

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| DNS resolves but `Test-NetConnection` to `443` fails | OCI security list, route table, host firewall, or Caddy container is not reachable | Check OCI ingress, Oracle Linux `firewalld`, and `docker compose ps edge_proxy`. |
| TCP connects but FortiGuard says dynamic DNS/intrusion prevention | Corporate filter blocks `sslip.io` category | Use a normal domain, wait for `is-a.dev`, or ask IT to whitelist/create DNS. |
| HTTPS returns Caddy `403 Forbidden` | Client public IP is missing from `ALLOWED_REMOTE_IPS` | Add the public egress IP with `/32` and recreate `edge_proxy`. |
| `docker compose` reports `unauthorized` pulling GHCR images | Running Docker as a user that is not logged in to GHCR | Run Docker as `deploy` or log in to GHCR for the same Linux user running Compose. |
| Shell says `no such service: edge_proxysudo` or splits a compose filename | Two commands were pasted without a newline, or the terminal line-wrapped in the middle of a token | Re-run one complete command at a time. |

## Migrations

Check heads locally:

```bash
python -m alembic -c services/api/alembic.ini heads
```

Apply on VM:

```bash
IMAGE_TAG=latest docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml run --rm quant_api \
  alembic -c services/api/alembic.ini upgrade head
```

Expected current head:

```text
f7a8b9c1d2e3 (head)
```

## Smoke Tests

Set common shell variables on the VM:

```bash
source /etc/bt/env
BASE="https://${DOMAIN}"
RESOLVE="${DOMAIN}:443:127.0.0.1"
```

Container health:

```bash
docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml ps
docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml exec -T quant_api \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read().decode())"
```

Caddy/API health through the public route from localhost:

```bash
curl -fsS --resolve "$RESOLVE" "$BASE/api/health"
```

Frontend login page:

```bash
curl -fsS --resolve "$RESOLVE" "$BASE/login" | grep -q "Connexion"
```

Market data health:

```bash
curl -fsS --resolve "$RESOLVE" -H "X-API-Key: $API_KEY" "$BASE/api/market-data/health"
```

Dashboard data:

```bash
curl -fsS --resolve "$RESOLVE" "$BASE/api/dashboard/data/weekly" | head -c 300
```

Redis queues:

```bash
docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml exec -T quant_redis \
  redis-cli llen runs
docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml exec -T quant_redis \
  redis-cli llen market_refresh
docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml exec -T quant_redis \
  redis-cli llen signal_engine
```

Logs:

```bash
docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml logs --tail=100 quant_api
docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml logs --tail=100 quant_worker
docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml logs --tail=100 edge_proxy
```

## Warmup Commands

Run these after first deploy or after restoring a DB. Use admin headers for admin-only endpoints.

Trigger dashboard snapshot backfill:

```bash
curl -fsS --resolve "$RESOLVE" -X POST "$BASE/api/dashboard/snapshot/backfill" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Admin-Api-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Trigger predictive history for all available symbols:

```bash
curl -fsS --resolve "$RESOLVE" -X POST "$BASE/api/analytics/predictive-history/trigger-all" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Admin-Api-Key: $ADMIN_API_KEY"
```

Warm edge cache after score history exists:

```bash
curl -fsS --resolve "$RESOLVE" -X POST "$BASE/api/analytics/edge/warm?cost_bps=33" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Admin-Api-Key: $ADMIN_API_KEY"
```

Trigger a market data refresh:

```bash
curl -fsS --resolve "$RESOLVE" -X POST "$BASE/api/market-data/refresh" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"timeframe":"1D","include_unverified":false}'
```

Check refresh status:

```bash
curl -fsS --resolve "$RESOLVE" -H "X-API-Key: $API_KEY" "$BASE/api/market-data/refresh?limit=5"
```

## User Setup For Demo

Fast path:

1. Open `/signup`.
2. Create the supervisor/demo account.
3. Approve it in Postgres:

```bash
docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml exec -T quant_postgres \
  psql -U app -d quant -c "UPDATE users SET \"isActive\" = true WHERE email = 'demo@example.com';"
```

List pending users:

```bash
docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml exec -T quant_postgres \
  psql -U app -d quant -c "SELECT id, email, \"isActive\" FROM users ORDER BY email;"
```

## Rollback

Use the previous image tag or `latest` known-good tag:

```bash
cd /opt/bt
IMAGE_TAG=<previous_sha> docker compose --env-file /etc/bt/env -f infra/docker-compose.prod.yml up -d --remove-orphans
```

If migrations are not backward-compatible, restore Postgres using `docs/ops/restore.md`.

## Local Validation Commands

These were run during the audit:

```bash
docker compose -f infra/docker-compose.yml config --quiet
docker compose -f infra/docker-compose.prod.yml config --quiet
docker run --rm -e DOMAIN=84.8.218.252.sslip.io -e ALLOWED_REMOTE_IPS=197.230.23.178/32 \
  -v "${PWD}/infra/Caddyfile.prod:/etc/caddy/Caddyfile:ro" \
  caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile
python -m alembic -c services/api/alembic.ini heads
```

Validation notes:

- Compose validation passes.
- Caddy validation passes, with only a formatting warning from Caddy.
- Alembic reports one head: `f7a8b9c1d2e3`.
- `docker compose -f infra/docker-compose.prod.yml config --quiet` warns if `NEXTAUTH_SECRET` is not supplied in the current shell; the VM env file must supply it.
