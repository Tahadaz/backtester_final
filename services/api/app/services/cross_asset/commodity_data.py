from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, IO

import pandas as pd

from core.quant_core.cross_asset.curve import curve_carry, curve_snapshot
from core.quant_core.cross_asset.importer import import_canonical_csv
from core.quant_core.cross_asset.strategy_spec import (
    DataRequirements,
    Disclosures,
    ExecutionSpec,
    Identity,
    PositionSpec,
    ResearchSource,
    ReturnSpec,
    SignalSpec,
    StrategyDefinition,
    Universe,
)


@dataclass(frozen=True)
class CommodityDataResult:
    panel: pd.DataFrame
    data_source: str
    warnings: tuple[str, ...]


def load_commodity_csv(source: str | Path | IO[str], *, data_tier: str = "fixture") -> CommodityDataResult:
    if data_tier not in {"fixture", "proxy", "validated"}:
        raise ValueError("data_tier must be fixture, proxy or validated")
    panel, report = import_canonical_csv(source)
    warnings = list(report.warnings)
    if data_tier in {"fixture", "proxy"}:
        warnings.append(f"{data_tier} contract data — non-tradable research result; upgrade to validated per-contract data")
    return CommodityDataResult(panel, data_tier, tuple(dict.fromkeys(warnings)))


def commodity_reference_strategy(symbols: tuple[str, ...] = ("GC",)) -> StrategyDefinition:
    return StrategyDefinition(
        identity=Identity("Commodity TSM and Curve Carry", 1, "Preliminary explicit-contract commodity sleeve"),
        universe=Universe(symbols, "USD"),
        research_source=ResearchSource("Commodity systematic strategies", "Internal MVP", "simplified"),
        data=DataRequirements(("front", "collateral_rate", "carry"), "fixture", "daily"),
        signal=SignalSpec("time_series_momentum", 1, 1, "carry"),
        position=PositionSpec("vol_target", 0.10, 20, 0.50, 2.0),
        execution=ExecutionSpec(1, "monthly", 2.0, 1.0, 0.5),
        returns=ReturnSpec("futures_excess", 1 / 252, {"roll_dates": {}, "next_on_roll": {}}),
        disclosures=Disclosures(
            assumptions=("Collateral earns the supplied lagged cash rate.", "Curve carry is a feature, never realized P&L."),
            warnings=("Fixture contract data — non-tradable result.", "Validated exchange/vendor contract history is the upgrade path."),
        ),
    )


def commodity_curve_payload(records: list[dict[str, Any]], *, as_of: date, data_tier: str = "fixture") -> dict[str, Any]:
    frame = pd.DataFrame(records)
    required = {"date", "contract_expiry", "value", "field"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"commodity curve missing fields: {', '.join(missing)}")
    settle = frame.loc[frame["field"] == "settle"].rename(columns={"value": "settle"})
    snapshot = curve_snapshot(settle, as_of)
    carry = curve_carry(snapshot)
    warnings = []
    if data_tier in {"fixture", "proxy"}:
        warnings.append(f"{data_tier} curve is exploratory and non-tradable")
    return {
        "as_of": as_of.isoformat(),
        "data_tier": data_tier,
        "contracts": snapshot.where(pd.notna(snapshot), None).to_dict(orient="records"),
        "carry": asdict(carry),
        "warnings": warnings,
    }
