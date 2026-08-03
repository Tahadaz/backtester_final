from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import hashlib
import json
from typing import Any, Literal, TypeVar


@dataclass(frozen=True)
class Identity:
    name: str
    version: int = 1
    description: str = ""


@dataclass(frozen=True)
class ResearchSource:
    title: str = ""
    citation: str = ""
    replication_fidelity: Literal["faithful", "adapted", "simplified", "extension"] = "adapted"


@dataclass(frozen=True)
class Universe:
    instruments: tuple[str, ...]
    base_currency: str = "USD"


@dataclass(frozen=True)
class DataRequirements:
    fields: tuple[str, ...] = ("return",)
    source: str = "fixture"
    frequency: str = "daily"


@dataclass(frozen=True)
class SignalSpec:
    kind: str = "time_series_momentum"
    lookback_months: int = 12
    lag: int = 1
    carry_field: str = "carry"


@dataclass(frozen=True)
class PositionSpec:
    method: Literal["unit", "inverse_vol", "vol_target"] = "vol_target"
    target_vol_annual: float | None = 0.10
    vol_halflife: int = 20
    max_weight: float = 1.0
    max_gross: float = 3.0


@dataclass(frozen=True)
class ExecutionSpec:
    lag: int = 1
    rebalance: str = "daily"
    half_spread_bps: float = 0.0
    slippage_bps: float = 0.0
    commission_bps: float = 0.0


@dataclass(frozen=True)
class ReturnSpec:
    kind: Literal["fx_excess", "futures_excess", "bond_duration"] = "fx_excess"
    daycount: float | None = None
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationSpec:
    n_variants: int = 1
    bootstrap_samples: int = 1000


@dataclass(frozen=True)
class Disclosures:
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategyDefinition:
    identity: Identity
    universe: Universe
    research_source: ResearchSource
    data: DataRequirements = field(default_factory=DataRequirements)
    signal: SignalSpec = field(default_factory=SignalSpec)
    position: PositionSpec = field(default_factory=PositionSpec)
    execution: ExecutionSpec = field(default_factory=ExecutionSpec)
    returns: ReturnSpec = field(default_factory=ReturnSpec)
    validation: ValidationSpec = field(default_factory=ValidationSpec)
    disclosures: Disclosures = field(default_factory=Disclosures)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "StrategyDefinition":
        return cls(
            identity=_construct(Identity, value["identity"]),
            universe=_construct(Universe, value["universe"]),
            research_source=_construct(ResearchSource, value["research_source"]),
            data=_construct(DataRequirements, value.get("data", {})),
            signal=_construct(SignalSpec, value.get("signal", {})),
            position=_construct(PositionSpec, value.get("position", {})),
            execution=_construct(ExecutionSpec, value.get("execution", {})),
            returns=_construct(ReturnSpec, value.get("returns", {})),
            validation=_construct(ValidationSpec, value.get("validation", {})),
            disclosures=_construct(Disclosures, value.get("disclosures", {})),
        )

    def spec_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


T = TypeVar("T")


def _construct(kind: type[T], value: dict[str, Any]) -> T:
    normalized = dict(value)
    tuple_fields = {item.name for item in fields(kind) if "tuple" in str(item.type).lower()}
    for name in tuple_fields:
        if name in normalized and isinstance(normalized[name], list):
            normalized[name] = tuple(normalized[name])
    return kind(**normalized)
