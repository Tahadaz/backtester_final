from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class TradingHorizon(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


@dataclass(frozen=True)
class HorizonConfig:
    name: TradingHorizon
    train_window: int
    test_window: int
    step_size: int
    use_test_window: bool = True
    label: str = ""


PRESETS: dict[TradingHorizon, HorizonConfig] = {
    TradingHorizon.SHORT: HorizonConfig(
        name=TradingHorizon.SHORT,
        train_window=252,   # ~1 an
        test_window=63,     # ~3 mois
        step_size=63,       # ~1 mois
        use_test_window=True,
        label="Court terme (~1 an train, 5 ans)",
    ),
    TradingHorizon.MEDIUM: HorizonConfig(
        name=TradingHorizon.MEDIUM,
        train_window=504,   # ~2 ans
        test_window=126,    # ~6 mois
        step_size=126,       # ~1 mois
        use_test_window=True,
        label="Moyen terme (~2 ans train, 10 ans)",
    ),
    TradingHorizon.LONG: HorizonConfig(
        name=TradingHorizon.LONG,
        train_window=756,   # ~3 ans
        test_window=252,    # ~1 an
        step_size=252,       # ~1 mois
        use_test_window=True,
        label="Long terme (~3 ans train, 20 ans)",
    ),
}


def _coerce_positive_int(raw: Any, *, field_name: str) -> int:
    try:
        out = int(raw)
    except Exception as exc:
        raise ValueError(f"{field_name} must be a positive integer.") from exc
    if out <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return out


def _coerce_horizon(value: str | TradingHorizon | None) -> TradingHorizon:
    if value is None:
        return TradingHorizon.MEDIUM
    if isinstance(value, TradingHorizon):
        return value
    token = str(value).strip().lower()
    for item in TradingHorizon:
        if token == item.value:
            return item
    raise ValueError("horizon must be one of: short, medium, long.")


def get_horizon_config(
    horizon: str | TradingHorizon | None,
    overrides: Mapping[str, Any] | None = None,
) -> HorizonConfig:
    h = _coerce_horizon(horizon)
    base = PRESETS[h]
    data = dict(overrides or {})

    train_window = (
        _coerce_positive_int(data["train_window"], field_name="horizon_overrides.train_window")
        if data.get("train_window") is not None
        else int(base.train_window)
    )
    test_window = (
        _coerce_positive_int(data["test_window"], field_name="horizon_overrides.test_window")
        if data.get("test_window") is not None
        else int(base.test_window)
    )
    step_size = (
        _coerce_positive_int(data["step_size"], field_name="horizon_overrides.step_size")
        if data.get("step_size") is not None
        else int(base.step_size)
    )
    use_test_window = bool(data["use_test_window"]) if data.get("use_test_window") is not None else bool(base.use_test_window)
    label = str(data["label"]).strip() if data.get("label") is not None else str(base.label)

    return HorizonConfig(
        name=h,
        train_window=int(train_window),
        test_window=int(test_window),
        step_size=int(step_size),
        use_test_window=bool(use_test_window),
        label=label,
    )
