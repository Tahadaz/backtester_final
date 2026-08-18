"""Canonical Revision 5 source-generation serialization."""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
import unicodedata
from typing import Any, Iterable, Mapping, Sequence


DOMAIN_PREFIX = b"pit-v5-source-watermark-v1\n"
SourceRecord = tuple[str, Sequence[Any], Any]


def _text(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value))


def normalize_source_value(value: Any) -> Any:
    if value is None:
        return {"$null": True}
    if isinstance(value, bool):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        return {"$datetime": value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, float):
        if math.isnan(value):
            token = "nan"
        elif math.isinf(value):
            token = "+inf" if value > 0 else "-inf"
        else:
            token = value.hex()
        return {"$float": token}
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return _text(value)
    if hasattr(value, "item"):
        try:
            return normalize_source_value(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, Mapping):
        pairs = sorted(((_text(key), item) for key, item in value.items()), key=lambda pair: pair[0])
        return {key: normalize_source_value(item) for key, item in pairs}
    if isinstance(value, (list, tuple)):
        return [normalize_source_value(item) for item in value]
    raise TypeError(f"unsupported canonical source value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        normalize_source_value(value), separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    )


def source_watermark_v1(records: Iterable[SourceRecord]) -> str:
    normalized: list[tuple[str, list[Any], Any]] = []
    for family, natural_key, payload in records:
        normalized.append((_text(family), list(natural_key), payload))
    normalized.sort(key=lambda row: (canonical_json(row[0]), canonical_json(row[1])))
    digest = hashlib.sha256()
    digest.update(DOMAIN_PREFIX)
    for family, natural_key, payload in normalized:
        digest.update(canonical_json([family, natural_key, payload]).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()
