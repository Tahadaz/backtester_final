from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


DATA_PATH = Path(__file__).resolve().parent / "data" / "casablanca_exchange_holidays.json"
_HOLIDAY_CACHE: tuple[
    int | None,
    dict[dt.date, dict[str, Any]],
    dict[str, dict[dt.date, dict[str, Any]]],
] | None = None


def _normalize_symbols(raw_symbols: Any) -> list[str]:
    if isinstance(raw_symbols, str):
        raw_values = [raw_symbols]
    elif isinstance(raw_symbols, list):
        raw_values = raw_symbols
    else:
        raw_values = []

    out: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        symbol = str(value or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def _ensure_holiday_cache() -> tuple[
    dict[dt.date, dict[str, Any]],
    dict[str, dict[dt.date, dict[str, Any]]],
]:
    global _HOLIDAY_CACHE
    if not DATA_PATH.exists():
        return {}, {}

    mtime_ns = DATA_PATH.stat().st_mtime_ns
    if _HOLIDAY_CACHE is not None and _HOLIDAY_CACHE[0] == mtime_ns:
        return _HOLIDAY_CACHE[1], _HOLIDAY_CACHE[2]

    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    global_holidays: dict[dt.date, dict[str, Any]] = {}
    symbol_holidays: dict[str, dict[dt.date, dict[str, Any]]] = {}

    for row in payload:
        try:
            day = dt.date.fromisoformat(str(row["date"]))
        except Exception:
            continue

        symbols = _normalize_symbols(row.get("symbols", row.get("symbol")))
        holiday = {
            "date": day,
            "name": str(row.get("name") or ""),
            "year": int(row.get("year") or day.year),
            "certainty": str(row.get("certainty") or "tentative"),
            "notes": str(row.get("notes") or ""),
            "source_label": str(row.get("source_label") or "local_file"),
        }
        if symbols:
            holiday["symbols"] = list(symbols)
            for symbol in symbols:
                symbol_holidays.setdefault(symbol, {})[day] = dict(holiday)
            continue

        global_holidays[day] = holiday

    _HOLIDAY_CACHE = (mtime_ns, global_holidays, symbol_holidays)
    return global_holidays, symbol_holidays


def load_casablanca_holidays() -> dict[dt.date, dict[str, Any]]:
    holidays, _ = _ensure_holiday_cache()
    return holidays


def get_holiday_info(day: dt.date, symbol: str | None = None) -> dict[str, Any] | None:
    global_holidays, symbol_holidays = _ensure_holiday_cache()
    normalized_symbol = str(symbol or "").strip().upper()
    if normalized_symbol:
        symbol_holiday = symbol_holidays.get(normalized_symbol, {}).get(day)
        if symbol_holiday is not None:
            return symbol_holiday
    return global_holidays.get(day)
