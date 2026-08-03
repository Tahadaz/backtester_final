from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID

import numpy as np
import pandas as pd

from core.quant_core.cross_asset.backtest import run_backtest
from core.quant_core.cross_asset.strategy_spec import StrategyDefinition
from core.quant_core.research.stats.robustness import deflated_sharpe_ratio
from services.api.app import models
from services.api.app.db import _ensure_session_factory
from services.api.app.services.cross_asset.orchestrator import panel_from_payload
from services.worker.config import settings
from services.worker.storage import ensure_bucket, s3_client


def _jsonable(value):
    if isinstance(value, pd.DataFrame):
        frame = value.copy()
        frame.index = frame.index.map(str)
        return {"index": list(frame.index), "columns": [str(item) for item in frame.columns], "data": frame.where(pd.notna(frame), None).values.tolist()}
    if isinstance(value, pd.Series):
        return {str(key): (None if pd.isna(item) else float(item)) for key, item in value.items()}
    return value


def _store(run_id: UUID, name: str, payload) -> models.Artifact:
    body = json.dumps(_jsonable(payload), allow_nan=False, default=str, separators=(",", ":")).encode("utf-8")
    key = f"runs/{run_id}/cross_asset/{name}.json"
    ensure_bucket()
    s3_client().put_object(Bucket=settings.S3_BUCKET, Key=key, Body=body, ContentType="application/json")
    return models.Artifact(run_id=run_id, artifact_type="table_json", name=name, object_key=key, bucket=settings.S3_BUCKET, content_type="application/json", size_bytes=len(body), sha256=hashlib.sha256(body).hexdigest())


def execute_cross_asset_backtest(run_id: str) -> None:
    db = _ensure_session_factory()()
    run_key = UUID(str(run_id))
    row = db.get(models.Run, run_key)
    if row is None or row.run_type != "cross_asset_strategy":
        db.close()
        return
    try:
        row.status = "running"
        row.started_at = datetime.now(timezone.utc)
        db.commit()
        spec = StrategyDefinition.from_dict(row.spec_json["strategy"])
        panel = panel_from_payload(row.spec_json["fixture_data"])
        result = run_backtest(spec, panel, seed=int(row.seed or 0))
        for name, payload in result.stages.items():
            db.add(_store(run_key, name, payload))
        current = {"latest_signal": None, "intended_position": None, "previous_position": None}
        signal = result.stages["signal"].dropna(how="all")
        position = result.stages["position"].dropna(how="all")
        if not signal.empty:
            current["latest_signal"] = signal.iloc[-1].to_dict()
        if not position.empty:
            current["intended_position"] = position.iloc[-1].to_dict()
            current["previous_position"] = position.iloc[-2].to_dict() if len(position) > 1 else None
        db.add(_store(run_key, "current_signal", current))
        for name, value in result.metrics.items():
            if isinstance(value, (int, float)) and np.isfinite(value):
                db.add(models.RunMetric(run_id=run_key, symbol="PORTFOLIO", metric_name=name, metric_value=float(value)))
        if spec.validation.n_variants > 1:
            net = result.stages["net_return"].dropna().to_numpy()
            db.add(models.RunMetric(run_id=run_key, symbol="PORTFOLIO", metric_name="deflated_sharpe", metric_value=float(deflated_sharpe_ratio(net, n_variants=spec.validation.n_variants))))
            db.add(models.RunMetric(run_id=run_key, symbol="PORTFOLIO", metric_name="variant_count", metric_value=float(spec.validation.n_variants)))
        row.status = "succeeded"
        row.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        row = db.get(models.Run, run_key)
        if row is not None:
            row.status = "failed"
            row.error_message = str(exc)
            row.finished_at = datetime.now(timezone.utc)
            db.commit()
        raise
    finally:
        db.close()
