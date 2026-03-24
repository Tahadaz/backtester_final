from __future__ import annotations

from dataclasses import dataclass
import math
import re
import unicodedata
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


CANONICAL_OHLCV_FIELDS = ("Date", "Open", "High", "Low", "Close", "Volume")
CASABLANCA_TZ = ZoneInfo("Africa/Casablanca")
NUMERIC_PLACEHOLDERS = frozenset({"", "-", "nan", "none", "null", "n/a", "n\\a"})
VOLUME_SUFFIX_MULTIPLIERS = {
    "k": 1_000.0,
    "m": 1_000_000.0,
    "b": 1_000_000_000.0,
}


@dataclass(frozen=True)
class UploadFormatSpec:
    format_id: str
    label: str
    aliases: dict[str, tuple[str, ...]]
    number_style: str
    day_first: bool
    numeric_examples: tuple[str, ...]
    volume_suffixes: tuple[str, ...] = ("K", "M", "B")
    notes: tuple[str, ...] = ()


def _deaccent(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_header_key(value: str) -> str:
    text = str(value or "")
    text = text.replace("\u00a0", " ")
    text = text.replace("’", "'").replace("`", "'")
    text = " ".join(text.strip().split())
    text = _deaccent(text)
    return text.casefold()


UPLOAD_FORMAT_SPECS: tuple[UploadFormatSpec, ...] = (
    UploadFormatSpec(
        format_id="bmce_new",
        label="BMCE / Bourse de Casablanca (new)",
        aliases={
            "Date": ("Date", "date", "Seance", "Séance", "SÃ©ance", "SÃ£Â©ance"),
            "Open": ("Open", "open", "Ouverture"),
            "High": ("High", "high", "+haut du jour"),
            "Low": ("Low", "low", "+bas du jour"),
            "Close": ("Close", "close", "Dernier Cours", "Price", "price"),
            "Volume": (
                "Volume",
                "volume",
                "Nombre de titres echanges",
                "Nombre de titres échangés",
                "Nombre de titres Ã©changÃ©s",
                "Nombre de titres Ã£Â©changÃ£Â©s",
            ),
        },
        number_style="french",
        day_first=True,
        numeric_examples=("1 052,00", "5 249", "982"),
        notes=("Extra columns are ignored.",),
    ),
    UploadFormatSpec(
        format_id="investing",
        label="Investing / English-style export",
        aliases={
            "Date": ("Date", "date", "Timestamp", "timestamp", "Datetime", "datetime"),
            "Open": ("Open", "open", "Ouv.", "Ouverture"),
            "High": ("High", "high", "Plus Haut"),
            "Low": ("Low", "low", "Plus Bas"),
            "Close": ("Close", "close", "Dernier", "Dernier Cours", "Price", "price"),
            "Volume": ("Volume", "volume", "Vol", "Vol."),
        },
        number_style="english",
        day_first=False,
        numeric_examples=("1,745.00", "2,100.00", "980.00", "5.60K"),
        notes=("Extra columns like Change % are ignored.",),
    ),
    UploadFormatSpec(
        format_id="bmce_old",
        label="BMCE / Bourse de Casablanca (old)",
        aliases={
            "Date": ("Date", "date", "Timestamp", "timestamp", "Datetime", "datetime"),
            "Open": ("Open", "open", "Ouvt"),
            "High": ("High", "high", "'+Haut", "+Haut"),
            "Low": ("Low", "low", "'+Bas", "+Bas"),
            "Close": (
                "Close",
                "close",
                "Cloture",
                "Clôture",
                "ClÃ´ture",
                "ClÃ£Â´ture",
                "Price",
                "price",
            ),
            "Volume": ("Volume", "volume"),
        },
        number_style="french",
        day_first=True,
        numeric_examples=("1 052,00", "5 249", "982"),
        notes=("Extra columns are ignored.",),
    ),
)


_NORM_ALIAS_MAP: dict[str, dict[str, list[str]]] = {
    spec.format_id: {
        field: [normalize_header_key(alias) for alias in aliases]
        for field, aliases in spec.aliases.items()
    }
    for spec in UPLOAD_FORMAT_SPECS
}


def _field_match_count(spec: UploadFormatSpec, normalized_columns: set[str]) -> int:
    matched = 0
    for field in CANONICAL_OHLCV_FIELDS:
        aliases = _NORM_ALIAS_MAP[spec.format_id].get(field, [])
        if any(alias in normalized_columns for alias in aliases):
            matched += 1
    return matched


def detect_upload_format(columns: list[str]) -> UploadFormatSpec | None:
    normalized_columns = {normalize_header_key(col) for col in columns}
    best: UploadFormatSpec | None = None
    best_score = -1
    for spec in UPLOAD_FORMAT_SPECS:
        score = _field_match_count(spec, normalized_columns)
        if score > best_score:
            best = spec
            best_score = score
    if best is None or best_score < 3:
        return None
    return best


def rename_columns_for_upload(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, str, dict[str, dict[str, str]]]:
    normalized_to_original: dict[str, str] = {}
    for column in df.columns:
        normalized_to_original.setdefault(normalize_header_key(column), str(column))

    spec = detect_upload_format([str(col) for col in df.columns])
    if spec is None:
        return df, "unknown", {}

    rename_map: dict[str, str] = {}
    matched_aliases: dict[str, dict[str, str]] = {}
    for field in CANONICAL_OHLCV_FIELDS:
        for alias in spec.aliases.get(field, ()):
            norm_alias = normalize_header_key(alias)
            if norm_alias in normalized_to_original:
                original = normalized_to_original[norm_alias]
                rename_map[original] = field
                matched_aliases[field] = {
                    "input_column": original,
                    "matched_alias": alias,
                }
                break

    return df.rename(columns=rename_map), spec.format_id, matched_aliases


def _swap_month_day_datetime(value: datetime | date) -> datetime:
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time())
    if value.month <= 12 and value.day <= 12:
        return value.replace(month=value.day, day=value.month)
    return value


def market_today_local() -> date:
    return datetime.now(CASABLANCA_TZ).date()


def _dedupe_candidates(values: list[pd.Timestamp]) -> list[pd.Timestamp]:
    out: list[pd.Timestamp] = []
    seen: set[pd.Timestamp] = set()
    for value in values:
        if pd.isna(value):
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _investing_candidates_for_value(value: Any) -> list[pd.Timestamp]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []

    if isinstance(value, pd.Timestamp):
        base = value.normalize()
        if base.month <= 12 and base.day <= 12:
            return _dedupe_candidates([base, pd.Timestamp(_swap_month_day_datetime(base.to_pydatetime()))])
        return [base]

    if isinstance(value, (datetime, date)):
        base = pd.Timestamp(value).normalize()
        if base.month <= 12 and base.day <= 12:
            return _dedupe_candidates([base, pd.Timestamp(_swap_month_day_datetime(base.to_pydatetime()))])
        return [base]

    text = str(value).strip()
    if not text:
        return []

    mmdd_match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if mmdd_match:
        month = int(mmdd_match.group(1))
        day = int(mmdd_match.group(2))
        year = int(mmdd_match.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return [pd.Timestamp(year=year, month=month, day=day)]
        return []

    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return []
    return [pd.Timestamp(parsed).normalize()]


def _infer_series_direction(candidate_lists: list[list[pd.Timestamp]]) -> str:
    resolved = [candidates[0] for candidates in candidate_lists if len(candidates) == 1]
    if len(resolved) < 2:
        return "descending"

    descending = 0
    ascending = 0
    for prev, curr in zip(resolved, resolved[1:]):
        if curr <= prev:
            descending += 1
        if curr >= prev:
            ascending += 1
    return "descending" if descending >= ascending else "ascending"


def _transition_cost(
    prev: pd.Timestamp | None,
    curr: pd.Timestamp,
    *,
    direction: str,
    market_today: date,
) -> float:
    cost = 0.0

    if curr.date() > market_today:
        cost += 10_000 + float((curr.date() - market_today).days)

    if prev is None:
        return cost

    delta_days = float(abs((prev - curr).days))
    monotonic_ok = curr <= prev if direction == "descending" else curr >= prev
    if not monotonic_ok:
        cost += 1_000 + delta_days
    else:
        cost += delta_days / 365.0
        if delta_days > 45:
            cost += (delta_days - 45.0) * 0.5
    return cost


def _resolve_investing_candidate_sequence(values: pd.Series) -> pd.Series:
    candidate_lists = [_investing_candidates_for_value(item) for item in values]
    direction = _infer_series_direction(candidate_lists)
    today = market_today_local()

    states: list[dict[pd.Timestamp, tuple[float, pd.Timestamp | None]]] = []
    prev_state: dict[pd.Timestamp, tuple[float, pd.Timestamp | None]] = {}

    for candidates in candidate_lists:
        if not candidates:
            states.append({})
            prev_state = {}
            continue

        current_state: dict[pd.Timestamp, tuple[float, pd.Timestamp | None]] = {}
        if not prev_state:
            for candidate in candidates:
                current_state[candidate] = (_transition_cost(None, candidate, direction=direction, market_today=today), None)
        else:
            for candidate in candidates:
                best_cost = float("inf")
                best_prev: pd.Timestamp | None = None
                for prev_candidate, (prev_cost, _backptr) in prev_state.items():
                    total = prev_cost + _transition_cost(
                        prev_candidate,
                        candidate,
                        direction=direction,
                        market_today=today,
                    )
                    if total < best_cost:
                        best_cost = total
                        best_prev = prev_candidate
                current_state[candidate] = (best_cost, best_prev)

        states.append(current_state)
        prev_state = current_state

    chosen: list[pd.Timestamp | None] = [None] * len(candidate_lists)
    last_idx = None
    last_candidate: pd.Timestamp | None = None
    for idx in range(len(states) - 1, -1, -1):
        if states[idx]:
            last_idx = idx
            last_candidate = min(states[idx].items(), key=lambda item: item[1][0])[0]
            break

    if last_idx is None or last_candidate is None:
        return pd.Series([pd.NaT] * len(values), index=values.index)

    idx = last_idx
    candidate = last_candidate
    while idx >= 0 and candidate is not None:
        chosen[idx] = candidate
        _cost, backptr = states[idx][candidate]
        candidate = backptr
        idx -= 1

    for i, candidates in enumerate(candidate_lists):
        if chosen[i] is None:
            valid = [item for item in candidates if item.date() <= today]
            chosen[i] = valid[0] if valid else (candidates[0] if candidates else None)

    return pd.Series([value if value is not None else pd.NaT for value in chosen], index=values.index)


def parse_datetime_series(
    values: pd.Series,
    *,
    day_first: bool,
    format_id: str | None = None,
) -> pd.Series:
    if format_id == "investing":
        resolved = _resolve_investing_candidate_sequence(values)
        today = market_today_local()
        return resolved.where(resolved.dt.date <= today, pd.NaT)

    if pd.api.types.is_datetime64_any_dtype(values):
        return pd.to_datetime(values, errors="coerce")
    return pd.to_datetime(values, errors="coerce", dayfirst=day_first)


def _parse_scalar_number(
    value: Any,
    *,
    number_style: str,
    allow_suffixes: bool = True,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isnan(float(value)):
            return None
        return float(value)

    text = str(value).strip()
    if not text:
        return None
    if text.casefold() in NUMERIC_PLACEHOLDERS:
        return None

    text = text.replace("\u00a0", " ").replace("−", "-")
    multiplier = 1.0
    if allow_suffixes:
        suffix_match = re.fullmatch(r"([+-]?[0-9][0-9\s,\.]*)([KMBkmb])", text)
        if suffix_match:
            text = suffix_match.group(1).strip()
            multiplier = VOLUME_SUFFIX_MULTIPLIERS[suffix_match.group(2).casefold()]

    if number_style == "french":
        text = text.replace(" ", "").replace(".", "")
        text = text.replace(",", ".")
    else:
        text = text.replace(" ", "").replace(",", "")

    if text.casefold() in NUMERIC_PLACEHOLDERS:
        return None

    try:
        return float(text) * multiplier
    except ValueError:
        return None


def parse_numeric_series(
    values: pd.Series,
    *,
    number_style: str,
    allow_suffixes: bool = True,
) -> pd.Series:
    return values.apply(
        lambda item: _parse_scalar_number(
            item,
            number_style=number_style,
            allow_suffixes=allow_suffixes,
        )
    )


def build_upload_format_reference() -> dict[str, Any]:
    formats: list[dict[str, Any]] = []
    for spec in UPLOAD_FORMAT_SPECS:
        formats.append(
            {
                "format_id": spec.format_id,
                "label": spec.label,
                "aliases": {field: list(spec.aliases[field]) for field in CANONICAL_OHLCV_FIELDS},
                "numeric_examples": list(spec.numeric_examples),
                "volume_suffixes": list(spec.volume_suffixes),
                "notes": list(spec.notes),
            }
        )

    return {
        "canonical_fields": list(CANONICAL_OHLCV_FIELDS),
        "formats": formats,
        "validation": {
            "required_fields": list(CANONICAL_OHLCV_FIELDS),
            "note": "A valid bar requires Date, Open, High, Low, Close, and Volume. Extra columns are ignored.",
        },
    }
