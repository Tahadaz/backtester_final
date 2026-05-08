# Restore runbook

## Postgres — restore from MinIO backup

```bash
# 1. List available backups
mc ls local/bt-backups/daily/ | sort

# 2. Download the target backup
mc cp local/bt-backups/daily/20260101T200000Z.dump.gz /tmp/restore.dump.gz

# 3. Decompress
gunzip /tmp/restore.dump.gz

# 4. Drop and recreate the database (takes the app offline)
docker exec -i quant_postgres psql -U app postgres <<'SQL'
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'quant' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS quant;
CREATE DATABASE quant OWNER app;
SQL

# 5. Restore
docker exec -i quant_postgres pg_restore -U app -d quant < /tmp/restore.dump

# 6. Bring services back up
docker compose --env-file /etc/bt/env -f infra/docker-compose.gcp.yml up -d

# 7. Verify
curl -fsS http://localhost/api/health
```

## MinIO — configure lifecycle retention

Run once after initial deploy to set 30-day auto-expiry on the backup bucket:

```bash
# Create the bucket if it doesn't exist
mc mb local/bt-backups || true

# Set lifecycle: delete objects in daily/ older than 30 days
mc ilm add --expiry-days 30 local/bt-backups
```

## Setup mc alias on the VM

```bash
mc alias set local http://localhost:9000 "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"
```

## Setting up the cron job

```bash
# Copy the script
cp /opt/bt/infra/scripts/pg_backup.sh /usr/local/bin/pg_backup.sh
chmod +x /usr/local/bin/pg_backup.sh

# Add cron entry (runs daily at 02:00 Africa/Casablanca = 01:00 UTC)
echo "0 1 * * * deploy /usr/local/bin/pg_backup.sh >> /var/log/bt-backup.log 2>&1" \
  | crontab -u deploy -

# Verify
crontab -u deploy -l
```

## Setting up the idle heartbeat

```bash
cp /opt/bt/infra/systemd/bt-heartbeat.service /etc/systemd/system/
cp /opt/bt/infra/systemd/bt-heartbeat.timer  /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now bt-heartbeat.timer
systemctl list-timers bt-heartbeat.timer
```
