#!/usr/bin/env bash
# Daily Postgres backup → MinIO bt-backups bucket.
# Runs as a cron job on the Oracle VM. Requires mc (MinIO client) in PATH.
set -euo pipefail

TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_FILE="/tmp/quant_${TIMESTAMP}.dump"
CONTAINER="quant_postgres"
DB_USER="app"
DB_NAME="quant"
MINIO_ALIAS="local"
MINIO_BUCKET="bt-backups"
RETENTION_DAYS=30

# Dump inside the postgres container
docker exec "${CONTAINER}" \
  pg_dump -U "${DB_USER}" -Fc "${DB_NAME}" > "${BACKUP_FILE}"

gzip "${BACKUP_FILE}"
BACKUP_FILE="${BACKUP_FILE}.gz"

# Upload to MinIO
mc cp "${BACKUP_FILE}" "${MINIO_ALIAS}/${MINIO_BUCKET}/daily/${TIMESTAMP}.dump.gz"

# Remove local file
rm -f "${BACKUP_FILE}"

echo "[pg_backup] ${TIMESTAMP} uploaded to ${MINIO_ALIAS}/${MINIO_BUCKET}/daily/"

# Enforce retention: delete objects older than RETENTION_DAYS days
mc find "${MINIO_ALIAS}/${MINIO_BUCKET}/daily/" \
  --older-than "${RETENTION_DAYS}d" \
  --exec "mc rm {}"
