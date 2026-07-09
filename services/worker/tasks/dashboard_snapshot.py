"""Dashboard snapshot worker — Phase 1.

Materialises a ``dashboard_snapshot`` row for each horizon by calling the
shared ``build_dashboard_payload`` service. Uses a CAS upsert so a slow
worker can never overwrite a fresher row written in the meantime.

Also writes a ``pipeline_revision`` row for lineage tracking.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

HORIZONS = ("weekly", "monthly", "quarterly")


def _cas_upsert(db, horizon: str, as_of: date, payload: dict, upstream_rev: dict) -> bool:
    """Insert or conditionally update the snapshot row.

    Returns True if the row was written (new or fresher), False if skipped
    because a newer row already exists.
    """
    from sqlalchemy import text

    upstream_json = json.dumps(upstream_rev, sort_keys=True, default=str)
    result = db.execute(
        text("""
        INSERT INTO dashboard_snapshot (horizon, as_of_date, payload_jsonb, upstream_rev, computed_at)
        VALUES (:horizon, :as_of_date, CAST(:payload AS jsonb), CAST(:upstream_rev AS jsonb), now())
        ON CONFLICT (horizon, as_of_date) DO UPDATE
            SET payload_jsonb  = EXCLUDED.payload_jsonb,
                upstream_rev   = EXCLUDED.upstream_rev,
                computed_at    = EXCLUDED.computed_at
            WHERE dashboard_snapshot.upstream_rev IS DISTINCT FROM EXCLUDED.upstream_rev
              AND COALESCE(dashboard_snapshot.upstream_rev->>'revision_key', '')
                  <= COALESCE(EXCLUDED.upstream_rev->>'revision_key', '')
        RETURNING horizon
        """),
        {
            "horizon": horizon,
            "as_of_date": as_of,
            "payload": json.dumps(payload, default=str),
            "upstream_rev": upstream_json,
        },
    )
    db.commit()
    return result.rowcount > 0


def _write_pipeline_revision(db, horizon: str, upstream_rev: dict, payload: dict) -> None:
    content = json.dumps(payload, sort_keys=True, default=str).encode()
    content_hash = hashlib.sha256(content).hexdigest()[:64]
    stage = f"dashboard_snapshot:{horizon}"
    from sqlalchemy import text
    db.execute(
        text("""
        INSERT INTO pipeline_revision (stage, upstream_rev, content_hash, created_at)
        VALUES (:stage, CAST(:upstream_rev AS jsonb), :content_hash, now())
        ON CONFLICT (stage, content_hash) DO NOTHING
        """),
        {
            "stage": stage,
            "upstream_rev": json.dumps(upstream_rev, sort_keys=True, default=str),
            "content_hash": content_hash,
        },
    )
    db.commit()


def refresh_dashboard_snapshot(horizon: str | None = None) -> dict[str, bool]:
    """Build and persist dashboard snapshots.

    Args:
        horizon: specific horizon to refresh, or None to refresh all three.

    Returns:
        dict mapping horizon -> succeeded. True means the horizon completed
        without error — either a fresh row was written, or the write was
        correctly skipped because the persisted row is already current. False
        means an exception was raised while building/persisting that horizon.
        (A skip is a healthy no-op, not a failure, so callers gating on
        ``all(result.values())`` do not treat an unchanged horizon as an error.)
    """
    from services.api.app.db import _ensure_session_factory
    from services.api.app.services.dashboard_builder import (
        build_dashboard_payload,
        derive_upstream_rev,
    )

    horizons = [horizon] if horizon else list(HORIZONS)
    Session = _ensure_session_factory()
    results: dict[str, bool] = {}

    for h in horizons:
        db = Session()
        try:
            upstream_rev = derive_upstream_rev(db, h)
            payload = build_dashboard_payload(db, h, include_edge=True)
            as_of = date.today()
            wrote = _cas_upsert(db, h, as_of, payload, upstream_rev)
            if wrote:
                _write_pipeline_revision(db, h, upstream_rev, payload)
                logger.info("dashboard_snapshot: wrote %s (as_of=%s)", h, as_of)
            else:
                logger.info("dashboard_snapshot: skipped %s — existing row is fresher", h)
            # A skip (already-current row) is a healthy no-op, not a failure.
            results[h] = True
        except Exception:
            logger.exception("dashboard_snapshot: failed for horizon=%s", h)
            db.rollback()
            results[h] = False
        finally:
            db.close()

    return results


# ---------------------------------------------------------------------------
# Backward-compatible shim — called by refresh_market_data / ingest_market_data
# ---------------------------------------------------------------------------

def regenerate_dashboard_snapshot() -> bool:
    """Refresh all three horizon snapshots. Returns True if all succeeded."""
    results = refresh_dashboard_snapshot()
    return all(results.values())
