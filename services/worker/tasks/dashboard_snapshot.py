from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path


logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPORT_SCRIPT = REPO_ROOT / "frontend" / "scripts" / "export-scores.py"


def regenerate_dashboard_snapshot() -> bool:
    """
    Refresh the static dashboard/signal JSON snapshots used by the frontend.

    This is intentionally best-effort: market-data refresh should not be marked
    failed just because snapshot materialization failed afterward.
    """
    if not EXPORT_SCRIPT.exists():
        logger.warning("dashboard snapshot export script not found: %s", EXPORT_SCRIPT)
        return False

    try:
        completed = subprocess.run(
            [sys.executable, str(EXPORT_SCRIPT)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stdout = (exc.stdout or "").strip()
        stderr = (exc.stderr or "").strip()
        logger.warning(
            "dashboard snapshot regeneration failed with exit code %s\nstdout:\n%s\nstderr:\n%s",
            exc.returncode,
            stdout,
            stderr,
        )
        return False

    stdout = (completed.stdout or "").strip()
    if stdout:
        logger.info("dashboard snapshot regeneration output:\n%s", stdout)
    return True
