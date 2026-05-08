#!/usr/bin/env bash
# Pings /health every 10 minutes from localhost so Oracle never marks the VM idle.
# Install as a systemd timer (see infra/systemd/).
set -euo pipefail
curl -fsS --max-time 5 http://localhost/api/health > /dev/null
