#!/usr/bin/env bash
# Pings the public Caddy route from localhost so Oracle never marks the VM idle.
# Install as a systemd timer (see infra/systemd/).
set -euo pipefail
DOMAIN="${DOMAIN:-84.8.218.252.sslip.io}"
curl -fsS --max-time 10 --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}/api/health" > /dev/null
