from __future__ import annotations

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
    ValidationSpec,
)

FX_UNIVERSE = ("EURUSD", "USDJPY", "GBPUSD", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "USDNOK", "USDSEK")


def _base(name: str, signal: SignalSpec) -> StrategyDefinition:
    return StrategyDefinition(
        identity=Identity(name=name, version=1, description="G10 currencies versus USD"),
        universe=Universe(instruments=FX_UNIVERSE, base_currency="USD"),
        research_source=ResearchSource(
            title="Moskowitz, Ooi & Pedersen / Koijen et al.",
            citation="Adapted systematic FX replication",
            replication_fidelity="adapted",
        ),
        data=DataRequirements(fields=("spot", "r_base", "r_quote", "carry"), source="yfinance+fred", frequency="daily"),
        signal=signal,
        position=PositionSpec(method="vol_target", target_vol_annual=0.10, vol_halflife=20, max_weight=0.30, max_gross=2.0),
        execution=ExecutionSpec(lag=1, rebalance="monthly", half_spread_bps=1.0, slippage_bps=0.5),
        returns=ReturnSpec(kind="fx_excess", daycount=1 / 12),
        validation=ValidationSpec(n_variants=4),
        disclosures=Disclosures(
            assumptions=("Rates are decimal annualized policy-rate proxies.", "Positions rebalance monthly."),
            warnings=("Proxy short rates are not tradable forward points.", "Adapted monthly rebalance styling."),
        ),
    )


FX_TSM = _base("G10 FX Time-Series Momentum", SignalSpec(kind="time_series_momentum", lookback_months=12, lag=1))
FX_CARRY = _base("G10 FX Carry", SignalSpec(kind="carry", lookback_months=12, lag=1, carry_field="carry"))


def fx_reference_strategies() -> tuple[StrategyDefinition, StrategyDefinition]:
    return FX_TSM, FX_CARRY
