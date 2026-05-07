from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import math
from typing import Any

import numpy as np


def sanitize_json_compatible(value: Any) -> Any:
    """Convert common scientific/python containers into JSON-compatible values."""
    if value is None:
        return None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, np.ndarray):
        return [sanitize_json_compatible(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return sanitize_json_compatible(value.item())
    # Handle pandas/third-party timestamp-like objects without importing pandas here.
    if value.__class__.__name__ in {"Timestamp", "Timedelta"} and hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if value.__class__.__name__ in {"NAType", "NaTType"}:
        return None
    if isinstance(value, tuple):
        return [sanitize_json_compatible(item) for item in value]
    if isinstance(value, set):
        return [sanitize_json_compatible(item) for item in sorted(value, key=lambda item: str(item))]
    if isinstance(value, list):
        return [sanitize_json_compatible(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_json_compatible(item) for key, item in value.items()}
    return value
