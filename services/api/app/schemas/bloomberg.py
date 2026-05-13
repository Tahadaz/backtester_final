from __future__ import annotations

import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


BloombergSource = Literal["bdh", "bdp", "bds", "bql", "bdib"]
BloombergKind = Literal["time_series", "reference", "bulk_table", "bql_table"]
BloombergJobType = Literal["preflight", "discovery", "backfill", "refresh"]
BloombergJobStatus = Literal["queued", "leased", "running", "succeeded", "failed", "cancelled", "expired"]
BloombergFrequency = Literal["daily", "hourly", "minute"]
BloombergUniverse = Literal["masi", "selected", "custom", "bonds"]
BloombergMode = Literal["discovery_only", "discover_then_backfill", "backfill_missing", "refresh_latest"]


class BloombergBridgeManifest(BaseModel):
    schema_version: int = Field(default=1)
    bridge_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=160)
    bloomberg_source: BloombergSource
    kind: BloombergKind
    securities: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
    periodicity: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
    columns: list[str] = Field(default_factory=list)
    row_count: int | None = Field(default=None, ge=0)
    data_sha256: str | None = None
    created_at: datetime.datetime | None = None


class BloombergBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    bridge_id: str
    request_id: str
    bloomberg_source: str
    kind: str
    status: str
    raw_object_key: str
    manifest_object_key: str
    normalized_object_key: str | None = None
    filename: str | None = None
    content_type: str | None = None
    size_bytes: int
    data_sha256: str
    row_count: int
    series_count: int
    manifest_json: dict[str, Any]
    error_message: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class BloombergBatchCreateOut(BaseModel):
    batch: BloombergBatchOut
    duplicate: bool = False
    indexed_series: list[UUID] = Field(default_factory=list)


class BloombergSeriesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    series_key: str
    last_batch_id: UUID
    security: str
    field: str
    periodicity: str | None = None
    overrides_hash: str
    kind: str
    object_key: str
    start_ts: datetime.datetime | None = None
    end_ts: datetime.datetime | None = None
    row_count: int
    metadata_json: dict[str, Any]
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class BloombergSeriesPreviewOut(BaseModel):
    series: BloombergSeriesOut
    columns: list[str]
    rows: list[dict[str, Any]]


class BloombergJobCreateIn(BaseModel):
    job_type: BloombergJobType = "discovery"
    universe: BloombergUniverse = "masi"
    mode: BloombergMode = "discover_then_backfill"
    frequency: BloombergFrequency = "daily"
    symbols: list[str] = Field(default_factory=list, max_length=500)
    securities: list[str] = Field(default_factory=list, max_length=500)
    fields: list[str] = Field(default_factory=lambda: ["PX_LAST", "VOLUME"], max_length=64)
    start_date: str | None = None
    end_date: str | None = None
    apply_to_market_data: bool = False
    options: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = Field(default=None, max_length=128)

    @field_validator("symbols", "fields")
    @classmethod
    def _clean_upper_list(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value).strip().upper()
            if not text:
                continue
            if text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned

    @field_validator("securities")
    @classmethod
    def _clean_security_list(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value).strip()
            if not text:
                continue
            key = text.upper()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
        return cleaned


class BloombergJobUpdateIn(BaseModel):
    status: BloombergJobStatus | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    message: str | None = Field(default=None, max_length=2000)
    error_message: str | None = Field(default=None, max_length=4000)


class BloombergHeartbeatIn(BaseModel):
    bridge_id: str = Field(min_length=1, max_length=128)
    status: str = Field(default="online", max_length=32)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    preflight: dict[str, Any] = Field(default_factory=dict)
    active_job_id: UUID | None = None
    error_message: str | None = Field(default=None, max_length=4000)


class BloombergBridgeStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bridge_id: str
    status: str
    capabilities_json: dict[str, Any]
    preflight_json: dict[str, Any]
    active_job_id: UUID | None = None
    error_message: str | None = None
    last_seen_at: datetime.datetime
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None
    is_stale: bool = False


class BloombergJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: str
    status: str
    requested_by: str | None = None
    bridge_id: str | None = None
    spec_json: dict[str, Any]
    progress_json: dict[str, Any]
    result_json: dict[str, Any]
    error_message: str | None = None
    lease_expires_at: datetime.datetime | None = None
    started_at: datetime.datetime | None = None
    completed_at: datetime.datetime | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class BloombergJobEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    bridge_id: str | None = None
    status: str | None = None
    message: str | None = None
    payload_json: dict[str, Any]
    created_at: datetime.datetime


class BloombergJobClaimOut(BaseModel):
    job: BloombergJobOut | None = None
    server_time: datetime.datetime
