from __future__ import annotations

from typing import Any

import numpy as np


def sanitize_json_compatible(value: Any) -> Any:
    """Convert NumPy containers/scalars into JSON-compatible Python values."""
    if isinstance(value, np.ndarray):
        return [sanitize_json_compatible(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, list):
        return [sanitize_json_compatible(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_json_compatible(item) for key, item in value.items()}
    return value
