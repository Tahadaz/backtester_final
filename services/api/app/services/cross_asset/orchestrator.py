from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import uuid
from typing import Any

import pandas as pd
from sqlalchemy import Column, DateTime, Float, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from ...db import Base


class CrossAssetInstrument(Base):
    __tablename__ = "cross_asset_instrument"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String, nullable=False, unique=True)
    asset_class = Column(String, nullable=False)
    currency = Column(String, nullable=False)
    quote_convention = Column(String, nullable=False)
    point_value = Column(Float, nullable=False, default=1.0)
    expiry = Column(String, nullable=True)
    roll_rule = Column(String, nullable=True)
    metadata_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CrossAssetStrategy(Base):
    __tablename__ = "cross_asset_strategy"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    spec_json = Column(JSONB, nullable=False)
    spec_hash = Column(String(64), nullable=False)
    replication_fidelity = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("name", "version", name="uq_cross_asset_strategy_name_version"),)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def dataset_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def panel_from_payload(value: list[dict[str, Any]] | dict[str, Any]) -> pd.DataFrame:
    if isinstance(value, list):
        if not value:
            from .datasources import assemble_fx_panel

            live = assemble_fx_panel()
            flattened = live.panel.copy()
            flattened.columns = [f"{symbol}__{field}" for symbol, field in flattened.columns]
            records = frame_to_records(flattened)
            value.extend(records)
        frame = pd.DataFrame(value)
        if "date" not in frame:
            raise ValueError("fixture data requires a date field")
        frame["date"] = pd.to_datetime(frame["date"], errors="raise")
        frame = frame.set_index("date").sort_index()
        encoded = [column for column in frame.columns if "__" in str(column)]
        if encoded and len(encoded) == len(frame.columns):
            frame.columns = pd.MultiIndex.from_tuples([tuple(str(column).split("__", 1)) for column in frame.columns])
        return frame
    frame = pd.DataFrame.from_dict(value, orient="index")
    frame.index = pd.to_datetime(frame.index, errors="raise")
    return frame.sort_index()


def frame_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    output = frame.reset_index(names="date")
    output["date"] = output["date"].map(lambda item: pd.Timestamp(item).isoformat())
    return output.where(pd.notna(output), None).to_dict(orient="records")


def serialize_strategy(row: CrossAssetStrategy) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "version": row.version,
        "spec": row.spec_json,
        "spec_hash": row.spec_hash,
        "replication_fidelity": row.replication_fidelity,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def envelope(
    *,
    inputs: dict[str, Any],
    methodology: dict[str, Any],
    warnings: list[str] | tuple[str, ...],
    results: Any,
    interpretation: str,
    assumptions: list[str] | tuple[str, ...] = (),
    units: dict[str, str] | None = None,
    data_source: str = "fixture",
) -> dict[str, Any]:
    return {
        "inputs": inputs,
        "methodology": methodology,
        "data_source": data_source,
        "calculation_date": date.today().isoformat(),
        "assumptions": list(assumptions),
        "units": units or {},
        "warnings": list(warnings),
        "results": results,
        "interpretation": interpretation,
    }
