from __future__ import annotations

import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


BloombergSource = Literal["bdh", "bdp", "bds", "bql"]
BloombergKind = Literal["time_series", "reference", "bulk_table", "bql_table"]


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
