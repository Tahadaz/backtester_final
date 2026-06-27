from __future__ import annotations

from functools import cache
from typing import Any


def disable_broken_narwhals_optional_plugins() -> None:
    """Keep Plotly/Narwhals from importing optional plugins with missing native SDKs."""

    try:
        import narwhals.plugins as plugins
    except Exception:
        return

    try:
        discovered = tuple(plugins._discover_entrypoints())
    except Exception:
        return

    filtered = tuple(entry for entry in discovered if not _is_known_broken_plugin(entry))
    if len(filtered) == len(discovered):
        return

    @cache
    def _filtered_entrypoints() -> tuple[Any, ...]:
        return filtered

    plugins._discover_entrypoints = _filtered_entrypoints


def _is_known_broken_plugin(entry: Any) -> bool:
    value = str(getattr(entry, "value", ""))
    return value.startswith("xbbg.")
