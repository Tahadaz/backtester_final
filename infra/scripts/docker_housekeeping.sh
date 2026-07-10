#!/usr/bin/env bash
# Safely reclaim Docker deployment residue on the production VM.
#
# This script intentionally never prunes volumes, networks, databases, MinIO,
# or backups. It keeps every image used by a running container plus the image
# IDs captured by deploy-vm.yml as the one-release rollback set.
set -euo pipefail

ROLLBACK_FILE="${BT_ROLLBACK_IMAGE_FILE:-/opt/bt/.rollback-image-ids}"
KEEP_IDS="$(docker ps -aq | xargs -r docker inspect -f '{{.Image}}' | sort -u)"
if [[ -f "$ROLLBACK_FILE" ]]; then
  KEEP_IDS+=$'\n'"$(grep -E '^[a-f0-9]{12,64}$' "$ROLLBACK_FILE" || true)"
fi
KEEP_IDS="$(printf '%s\n' "$KEEP_IDS" | sed '/^$/d' | sort -u)"

while IFS= read -r image_id; do
  [[ -z "$image_id" ]] && continue
  if grep -qx "$image_id" <<<"$KEEP_IDS"; then
    continue
  fi
  docker image rm "$image_id" >/dev/null 2>&1 || true
done < <(
  docker image ls --no-trunc --format '{{.Repository}} {{.ID}}' \
    | awk '$1 ~ /^ghcr\.io\/tahadaz\/bt-(api|worker|frontend)$/ {print $2}' \
    | sort -u
)

# Safe residue only: stopped containers and dangling layers. No `--volumes`.
docker container prune -f --filter 'until=24h' >/dev/null
docker image prune -f >/dev/null
docker builder prune -f --filter 'until=168h' >/dev/null

echo "docker housekeeping completed; protected images: $(printf '%s\n' "$KEEP_IDS" | wc -l)"
