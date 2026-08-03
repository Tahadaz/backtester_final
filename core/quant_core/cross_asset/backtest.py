from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .costs import apply_costs
from .dataquality import DataQualityReport, data_quality_report
from .instruments import Instrument
from .portfolio import size_positions
from .returns import build_return
from .signals import carry_signal, time_series_momentum
from .strategy_spec import StrategyDefinition


STAGE_KEYS = (
    "raw",
    "tradable_returns",
    "signal",
    "position",
    "executed_position",
    "gross_return",
    "costs",
    "net_return",
    "per_instrument_attribution",
)


@dataclass(frozen=True)
class BacktestResult:
    stages: dict[str, Any]
    metrics: dict[str, float | str | None]
    warnings: tuple[str, ...]
    seed: int
    spec_hash: str


def _instruments(spec: StrategyDefinition) -> list[Instrument]:
    asset_class = {"fx_excess": "fx", "futures_excess": "commodity", "bond_duration": "rates"}[spec.returns.kind]
    return [Instrument(symbol, asset_class, spec.universe.base_currency, "return") for symbol in spec.universe.instruments]


def _field(panel: pd.DataFrame, symbol: str, name: str) -> pd.Series:
    if isinstance(panel.columns, pd.MultiIndex):
        try:
            return panel[(symbol, name)].astype(float)
        except KeyError as exc:
            raise ValueError(f"missing field {name!r} for {symbol}") from exc
    if name == "return" and symbol in panel:
        return panel[symbol].astype(float)
    candidate = f"{symbol}.{name}"
    if candidate in panel:
        return panel[candidate].astype(float)
    raise ValueError(f"missing field {name!r} for {symbol}")


def _tradable_returns(spec: StrategyDefinition, panel: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    output: dict[str, pd.Series] = {}
    warnings: list[str] = []
    params = spec.returns.parameters
    for symbol in spec.universe.instruments:
        try:
            output[symbol] = _field(panel, symbol, "return")
            warnings.append(f"{symbol}: supplied return series is proxy-based and non-tradable")
            continue
        except ValueError:
            pass
        if spec.returns.kind == "fx_excess":
            output[symbol] = build_return(
                "fx_excess",
                spot=_field(panel, symbol, "spot"),
                r_base=_field(panel, symbol, "r_base"),
                r_quote=_field(panel, symbol, "r_quote"),
                daycount=spec.returns.daycount or 1 / 12,
            )
        elif spec.returns.kind == "futures_excess":
            roll_dates = [pd.Timestamp(value).date() for value in params.get("roll_dates", {}).get(symbol, [])]
            next_prices = {
                pd.Timestamp(key).date(): float(value)
                for key, value in params.get("next_on_roll", {}).get(symbol, {}).items()
            }
            output[symbol] = build_return(
                "futures_excess",
                front=_field(panel, symbol, "front"),
                roll_dates=roll_dates,
                next_on_roll=next_prices,
                collateral_rate=_field(panel, symbol, "collateral_rate"),
                daycount=spec.returns.daycount or 1 / 252,
            )
        else:
            output[symbol] = build_return("bond_duration")
    return pd.DataFrame(output, index=panel.index), warnings


def _metrics(gross: pd.Series, net: pd.Series, turnover: pd.Series, positions: pd.DataFrame, attribution: pd.DataFrame, costs: pd.Series) -> dict[str, float | str | None]:
    clean = net.dropna()
    ann_return = float(clean.mean() * 252) if len(clean) else float("nan")
    ann_vol = float(clean.std(ddof=1) * np.sqrt(252)) if len(clean) > 1 else float("nan")
    sharpe = ann_return / ann_vol if ann_vol and np.isfinite(ann_vol) else float("nan")
    downside = clean[clean < 0].std(ddof=1) * np.sqrt(252) if (clean < 0).sum() > 1 else np.nan
    curve = (1.0 + clean).cumprod()
    drawdown = curve / curve.cummax() - 1.0
    max_drawdown = float(drawdown.min()) if len(drawdown) else float("nan")
    positive_attr = attribution.where(positions > 0).sum().sum()
    negative_attr = attribution.where(positions < 0).sum().sum()
    return {
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "sharpe": float(sharpe),
        "sortino": float(ann_return / downside) if downside and np.isfinite(downside) else None,
        "max_drawdown": max_drawdown,
        "calmar": float(ann_return / abs(max_drawdown)) if max_drawdown < 0 else None,
        "hit_rate": float((clean > 0).mean()) if len(clean) else None,
        "skew": float(clean.skew()) if len(clean) > 2 else None,
        "tail_loss_5pct": float(clean.quantile(0.05)) if len(clean) else None,
        "turnover": float(turnover.sum()),
        "gross_leverage": float(positions.abs().sum(axis=1).mean()),
        "net_exposure": float(positions.sum(axis=1).mean()),
        "total_costs": float(costs.sum()),
        "gross_total_return": float(gross.sum(skipna=True)),
        "net_total_return": float(net.sum(skipna=True)),
        "long_attr": float(positive_attr),
        "short_attr": float(negative_attr),
        "n_eff_caveat": "Daily observations are serially dependent; nominal N overstates effective N.",
    }


def run_backtest(spec: StrategyDefinition, panel: pd.DataFrame, *, seed: int = 0) -> BacktestResult:
    _ = np.random.default_rng(seed)  # reserve the deterministic seed without global RNG state
    quality: DataQualityReport = data_quality_report(panel, _instruments(spec))
    if quality.blocks_backtest:
        raise ValueError("data quality blocks backtest")
    returns, warnings = _tradable_returns(spec, panel)
    if spec.signal.kind == "time_series_momentum":
        signal = returns.apply(
            lambda item: time_series_momentum(item, spec.signal.lookback_months, lag=spec.signal.lag)
        )
    elif spec.signal.kind == "carry":
        signal = pd.DataFrame(
            {symbol: carry_signal(_field(panel, symbol, spec.signal.carry_field), lag=spec.signal.lag) for symbol in returns},
            index=panel.index,
        )
    else:
        raise ValueError(f"unsupported signal kind: {spec.signal.kind}")
    vols = returns.ewm(
        halflife=spec.position.vol_halflife,
        min_periods=spec.position.vol_halflife,
        adjust=False,
    ).std().shift(spec.signal.lag) * np.sqrt(252)
    position = size_positions(
        signal,
        vols,
        method=spec.position.method,
        target_vol_annual=spec.position.target_vol_annual,
        max_weight=spec.position.max_weight,
        max_gross=spec.position.max_gross,
    )
    executed = position.shift(spec.execution.lag)
    attribution = executed * returns
    gross = attribution.sum(axis=1, min_count=1).rename("gross_return")
    turnover, cost_series = apply_costs(
        executed,
        spec.execution.half_spread_bps,
        spec.execution.slippage_bps,
        spec.execution.commission_bps,
    )
    net = (gross - cost_series).rename("net_return")
    stages: dict[str, Any] = {
        "raw": panel.copy(),
        "tradable_returns": returns,
        "signal": signal,
        "position": position,
        "executed_position": executed,
        "gross_return": gross,
        "costs": cost_series,
        "net_return": net,
        "per_instrument_attribution": attribution,
    }
    assert tuple(stages) == STAGE_KEYS
    all_warnings = tuple(dict.fromkeys([*quality.warnings, *spec.disclosures.warnings, *warnings]))
    return BacktestResult(stages, _metrics(gross, net, turnover, executed, attribution, cost_series), all_warnings, seed, spec.spec_hash())
