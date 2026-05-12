from __future__ import annotations

import json
from io import BytesIO

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.config import settings
from services.api.app.db import get_db
from services.api.app.routers import bloomberg_bridge


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover - sqlite harness
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(_type, _compiler, **_kw):  # pragma: no cover - sqlite harness
    return "CHAR(32)"


class _FakeBody:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class _FakeS3:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self._objects = objects

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, _FakeBody]:
        _ = Bucket
        return {"Body": _FakeBody(self._objects[Key])}


@pytest.fixture()
def client_and_storage(monkeypatch):
    monkeypatch.setattr(settings, "BLOOMBERG_BRIDGE_API_KEY", "secret")

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    models.BloombergIngestBatch.__table__.create(engine)
    models.BloombergSeries.__table__.create(engine)

    objects: dict[str, bytes] = {}
    monkeypatch.setattr(
        bloomberg_bridge,
        "put_bytes",
        lambda object_key, data, content_type: objects.__setitem__(object_key, data),
    )
    monkeypatch.setattr(bloomberg_bridge, "s3_client", lambda: _FakeS3(objects))

    app = FastAPI()
    app.include_router(bloomberg_bridge.bridge_router)
    app.include_router(bloomberg_bridge.app_router)

    def _override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as client:
        yield client, objects
    engine.dispose()


def _parquet_payload() -> bytes:
    frame = pd.DataFrame(
        [
            {"date": "2026-05-01", "security": "ATW MA Equity", "field": "PX_LAST", "value": 500.0},
            {"date": "2026-05-04", "security": "ATW MA Equity", "field": "PX_LAST", "value": 501.5},
        ]
    )
    buffer = BytesIO()
    frame.to_parquet(buffer, index=False)
    return buffer.getvalue()


def test_bridge_health_requires_dedicated_key(client_and_storage) -> None:
    client, _objects = client_and_storage

    assert client.get("/bridge/bloomberg/health").status_code == 401
    ok = client.get("/bridge/bloomberg/health", headers={"X-Bloomberg-Bridge-Key": "secret"})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True


def test_bridge_upload_stores_raw_batch_and_indexes_series(client_and_storage) -> None:
    client, objects = client_and_storage
    payload = _parquet_payload()
    manifest = {
        "schema_version": 1,
        "bridge_id": "bank-terminal-01",
        "request_id": "req-001",
        "bloomberg_source": "bdh",
        "kind": "time_series",
        "securities": ["ATW MA Equity"],
        "fields": ["PX_LAST"],
        "start_date": "2026-05-01",
        "end_date": "2026-05-04",
        "periodicity": "DAILY",
        "overrides": {},
        "columns": ["date", "security", "field", "value"],
        "row_count": 2,
    }

    response = client.post(
        "/bridge/bloomberg/batches",
        headers={"X-Bloomberg-Bridge-Key": "secret"},
        data={"manifest_json": json.dumps(manifest)},
        files={"file": ("sample.parquet", payload, "application/octet-stream")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["duplicate"] is False
    assert body["batch"]["row_count"] == 2
    assert body["batch"]["series_count"] == 1
    assert any(key.startswith("bloomberg/raw/") for key in objects)
    assert any(key.startswith("bloomberg/series/") for key in objects)

    duplicate = client.post(
        "/bridge/bloomberg/batches",
        headers={"X-Bloomberg-Bridge-Key": "secret"},
        data={"manifest_json": json.dumps(manifest)},
        files={"file": ("sample.parquet", payload, "application/octet-stream")},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["duplicate"] is True

    series = client.get("/bloomberg/series").json()
    assert len(series) == 1
    assert series[0]["security"] == "ATW MA Equity"
    assert series[0]["field"] == "PX_LAST"

    preview = client.get(f"/bloomberg/series/{series[0]['id']}/preview").json()
    assert preview["rows"][-1]["Value"] == 501.5

    batch_id = body["batch"]["id"]
    raw_download = client.get(f"/bloomberg/batches/{batch_id}/raw")
    assert raw_download.status_code == 200
    assert raw_download.content == payload

    series_download = client.get(f"/bloomberg/series/{series[0]['id']}/download")
    assert series_download.status_code == 200
    assert series_download.content
