"""Cross-asset time-series momentum: return construction, portfolio, metrics.

Pure pandas/numpy. Every estimate that feeds a position is lagged at least one
bar, and the shift discipline is asserted by `core/tests/test_ca_tsmom_study.py`.

Method is fixed by `docs/global-desk/02-tsmom-preregistration.md`; this module
implements it and must not acquire tunable knobs beyond what that document
declares.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd


TRADING_DAYS = 252

# Modified duration by Treasury tenor, used to turn a yield series into an
# approximate total return. Coupon-bond durations, not maturities.
DURATION_BY_INSTRUMENT: dict[str, float] = {"TU": 1.9, "FV": 4.6, "TY": 8.3, "US": 17.5}

# Pessimistic per-side costs in bps on |change in position|, per the
# pre-registration §3. Deliberately 2-4x typical institutional fills.
COST_BPS_BY_ASSET_CLASS: dict[str, float] = {
    "fx": 1.5,
    "rates": 2.0,
    "equity_index": 2.0,
    "commodity": 5.0,
    "credit": 10.0,
}


@dataclass(frozen=True)
class StudyConfig:
    lookback_months: int = 12
    instrument_vol_target: float = 0.10
    instrument_vol_halflife: int = 60
    portfolio_vol_target: float = 0.10
    portfolio_vol_halflife: int = 60
    rebalance_rule: str = "W-FRI"
    no_trade_band: float = 0.10
    execution_lag: int = 1
    cost_multiplier: float = 1.0
    max_instrument_leverage: float = 5.0
    max_portfolio_leverage: float = 3.0
    min_instruments: int = 5

    def __post_init__(self) -> None:
        if self.execution_lag < 1:
            raise ValueError("execution_lag must be at least one bar")
        if self.lookback_months not in {1, 3, 6, 12}:
            raise ValueError("lookback_months must be one of 1, 3, 6, 12")
        if self.instrument_vol_target <= 0 or self.portfolio_vol_target <= 0:
            raise ValueError("vol targets must be positive")
        if not 0.0 <= self.no_trade_band < 1.0:
            raise ValueError("no_trade_band must be in [0, 1)")


@dataclass(frozen=True)
class StudyResult:
    net_returns: pd.Series
    gross_returns: pd.Series
    costs: pd.Series
    positions: pd.DataFrame
    turnover: pd.Series
    metrics: dict[str, float]
    instruments: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Return construction
# ---------------------------------------------------------------------------


def price_returns(prices: pd.Series) -> pd.Series:
    """Simple returns from a price-like series.

    Percentage returns are undefined across a non-positive price -- WTI settled
    at -$37.63 on 2020-04-20, and ``pct_change`` turns that into -306% followed
    by +127%, which corrupts every vol estimate and trailing sum that touches
    it. Those transitions are marked missing rather than propagated; the caller
    is expected to surface them (see :func:`data_quality_report`).
    """
    clean = pd.to_numeric(prices, errors="coerce").astype(float)
    # fill_method=None: a gap stays a gap. Filling is done explicitly and
    # disclosed by align_on_common_calendar, never implicitly here.
    returns = clean.pct_change(fill_method=None)
    invalid = (clean.shift(1) <= 0) | (clean <= 0)
    return returns.where(~invalid).replace([np.inf, -np.inf], np.nan)


def align_on_common_calendar(
    series_by_instrument: dict[str, pd.Series],
) -> tuple[dict[str, pd.Series], dict[str, int]]:
    """Put every instrument on one business-day calendar.

    Instruments trade on different holiday calendars, so a naive union index
    leaves a NaN in each column on every day some *other* market was open. A
    252-day rolling window then never fills, the signal is silently NaN forever,
    and the instrument contributes nothing while appearing present.

    A closed market genuinely has an unchanged price, so prices are
    forward-filled -- but only *within* each instrument's own first/last
    observation, never extrapolated beyond its life. Returns computed from the
    filled prices are therefore 0 on that instrument's holidays, which is
    correct rather than merely convenient.

    Returns the aligned prices and the per-instrument count of filled bars, so
    the fill is disclosed instead of silent.
    """
    if not series_by_instrument:
        return {}, {}

    starts = [s.index.min() for s in series_by_instrument.values() if not s.empty]
    ends = [s.index.max() for s in series_by_instrument.values() if not s.empty]
    if not starts:
        return {}, {}
    calendar = pd.bdate_range(min(starts), max(ends))

    aligned: dict[str, pd.Series] = {}
    filled_counts: dict[str, int] = {}
    for instrument, series in series_by_instrument.items():
        if series.empty:
            continue
        clean = series[~series.index.duplicated(keep="last")].sort_index()
        reindexed = clean.reindex(calendar)
        live = (calendar >= clean.index.min()) & (calendar <= clean.index.max())
        filled = reindexed.ffill().where(live)
        filled_counts[instrument] = int((filled.notna() & reindexed.isna()).sum())
        aligned[instrument] = filled
    return aligned, filled_counts


def data_quality_report(
    prices_by_instrument: dict[str, pd.Series],
    filled_counts: dict[str, int],
) -> dict[str, dict[str, float]]:
    """Per-instrument defects that must be disclosed, never silently dropped."""
    report: dict[str, dict[str, float]] = {}
    for instrument, series in prices_by_instrument.items():
        observed = series.dropna()
        non_positive = int((observed <= 0).sum())
        report[instrument] = {
            "observations": int(observed.size),
            "filled_bars": int(filled_counts.get(instrument, 0)),
            "filled_share": float(filled_counts.get(instrument, 0) / observed.size) if observed.size else 0.0,
            "non_positive_prices": non_positive,
        }
    return report


def yield_to_bond_return(yields: pd.Series, duration: float) -> pd.Series:
    """Duration-approximated total return of a constant-maturity bond.

    ``r[t] ~= y[t-1]/252 - D * (y[t] - y[t-1])``: carry from yesterday's yield
    plus the price move implied by today's yield change. Uses ``y[t-1]`` for
    carry so no same-bar information leaks into the return.
    """
    if duration <= 0:
        raise ValueError("duration must be positive")
    # No dropna: the caller's calendar must survive, or the panel de-aligns.
    clean = pd.to_numeric(yields, errors="coerce").astype(float)
    carry = clean.shift(1) / TRADING_DAYS
    price_move = -duration * clean.diff()
    return (carry + price_move).replace([np.inf, -np.inf], np.nan)


def build_return_panel(
    series_by_instrument: dict[str, pd.Series],
    asset_class_by_instrument: dict[str, str],
    align: bool = True,
) -> pd.DataFrame:
    """Per-instrument return series on one common business-day calendar.

    ``align=True`` is the correct behaviour and the default; it exists as a flag
    only so tests can demonstrate what the unaligned version breaks.
    """
    if align:
        series_by_instrument, _ = align_on_common_calendar(series_by_instrument)
    columns: dict[str, pd.Series] = {}
    for instrument, series in series_by_instrument.items():
        asset_class = asset_class_by_instrument.get(instrument)
        if asset_class == "rates":
            duration = DURATION_BY_INSTRUMENT.get(instrument)
            if duration is None:
                raise KeyError(f"no duration mapping for rates instrument {instrument!r}")
            columns[instrument] = yield_to_bond_return(series, duration)
        else:
            columns[instrument] = price_returns(series)
    if not columns:
        raise ValueError("no instruments supplied")
    panel = pd.DataFrame(columns).sort_index()
    panel.index = pd.to_datetime(panel.index)
    return panel


# ---------------------------------------------------------------------------
# Signal and sizing -- everything here is lagged
# ---------------------------------------------------------------------------


def tsmom_signal(returns: pd.DataFrame, lookback_months: int, lag: int = 1) -> pd.DataFrame:
    """sign(trailing lookback-month return), lagged."""
    window = 21 * lookback_months
    trailing = returns.rolling(window, min_periods=window).sum()
    return np.sign(trailing).shift(lag)


def inverse_vol_scale(
    returns: pd.DataFrame,
    target_vol_annual: float,
    halflife: int,
    lag: int = 1,
    max_leverage: float = 5.0,
) -> pd.DataFrame:
    """Per-instrument scaler bringing each to the target vol, lagged."""
    realized = returns.ewm(halflife=halflife, min_periods=halflife, adjust=False).std() * np.sqrt(TRADING_DAYS)
    scale = target_vol_annual / realized.replace(0.0, np.nan)
    return scale.clip(upper=max_leverage).shift(lag)


def apply_rebalance_schedule(
    targets: pd.DataFrame,
    rebalance_rule: str,
    no_trade_band: float,
) -> pd.DataFrame:
    """Hold positions between rebalance dates; trade only outside the band.

    Walks forward one row at a time because each decision depends on the
    position actually carried into that bar.
    """
    if targets.empty:
        return targets.copy()

    rebalance_dates = set(targets.resample(rebalance_rule).last().index)
    # resample labels the period end, which may not be a trading day; snap each
    # label to the last available bar at or before it.
    index = targets.index
    snapped: set[pd.Timestamp] = set()
    for label in rebalance_dates:
        candidates = index[index <= label]
        if len(candidates):
            snapped.add(candidates[-1])

    held = pd.DataFrame(0.0, index=targets.index, columns=targets.columns)
    current = pd.Series(0.0, index=targets.columns, dtype=float)
    for timestamp, row in targets.iterrows():
        if timestamp in snapped:
            desired = row.fillna(0.0)
            drift = (desired - current).abs()
            reference = desired.abs().where(desired.abs() > 0, 1.0)
            trade = drift > (no_trade_band * reference)
            current = current.where(~trade, desired)
        held.loc[timestamp] = current.to_numpy()
    return held


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


def _annualized_sharpe(returns: pd.Series) -> float:
    clean = returns.dropna()
    if clean.empty or clean.std(ddof=1) == 0 or not np.isfinite(clean.std(ddof=1)):
        return float("nan")
    return float(clean.mean() / clean.std(ddof=1) * np.sqrt(TRADING_DAYS))


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return float("nan")
    return float((equity / equity.cummax() - 1.0).min())


def compute_metrics(net: pd.Series, gross: pd.Series, turnover: pd.Series) -> dict[str, float]:
    net_clean = net.dropna()
    if net_clean.empty:
        return {"net_sharpe": float("nan"), "n_obs": 0}
    equity = (1.0 + net_clean).cumprod()
    years = len(net_clean) / TRADING_DAYS
    drawdown = equity / equity.cummax() - 1.0
    underwater = (drawdown < 0).astype(int)
    longest = 0
    running = 0
    for value in underwater:
        running = running + 1 if value else 0
        longest = max(longest, running)
    return {
        "net_sharpe": _annualized_sharpe(net_clean),
        "gross_sharpe": _annualized_sharpe(gross.dropna()),
        "net_cagr": float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else float("nan"),
        "net_vol": float(net_clean.std(ddof=1) * np.sqrt(TRADING_DAYS)),
        "max_drawdown": _max_drawdown(equity),
        "longest_drawdown_days": float(longest),
        "hit_rate": float((net_clean > 0).mean()),
        "avg_annual_turnover": float(turnover.dropna().mean() * TRADING_DAYS),
        "cost_drag_annual": float((gross.dropna().mean() - net_clean.mean()) * TRADING_DAYS),
        "n_obs": int(len(net_clean)),
        "years": float(years),
    }


def run_tsmom(
    returns: pd.DataFrame,
    asset_class_by_instrument: dict[str, str],
    config: StudyConfig | None = None,
) -> StudyResult:
    """Run the pre-registered TSMOM sleeve over a return panel."""
    config = config or StudyConfig()
    panel = returns.sort_index()
    signal = tsmom_signal(panel, config.lookback_months, lag=config.execution_lag)
    return run_signal_portfolio(panel, signal, asset_class_by_instrument, config)


def run_signal_portfolio(
    returns: pd.DataFrame,
    signal: pd.DataFrame,
    asset_class_by_instrument: dict[str, str],
    config: StudyConfig | None = None,
) -> StudyResult:
    """Size, rebalance, cost and measure an already-computed signal.

    Everything downstream of the signal -- vol targeting, equal risk weighting,
    the weekly rebalance band, execution lag, costs and metrics -- lives here so
    that every strategy in this program is measured by identical machinery and
    the resulting Sharpes are comparable rather than merely similar-looking.

    ``signal`` must already be lagged; this function does not shift it.
    """
    config = config or StudyConfig()
    warnings: list[str] = []

    panel = returns.sort_index()
    signal = signal.reindex(index=panel.index, columns=panel.columns)
    scale = inverse_vol_scale(
        panel,
        config.instrument_vol_target,
        config.instrument_vol_halflife,
        lag=config.execution_lag,
        max_leverage=config.max_instrument_leverage,
    )

    raw_target = (signal * scale).replace([np.inf, -np.inf], np.nan)
    # Equal risk weight across whatever is live on that bar.
    active = raw_target.notna().sum(axis=1)
    if (active >= config.min_instruments).sum() == 0:
        raise ValueError("no bar has the minimum number of active instruments")
    equal_weight = raw_target.div(active.where(active > 0, np.nan), axis=0).fillna(0.0)

    held = apply_rebalance_schedule(equal_weight, config.rebalance_rule, config.no_trade_band)

    # Portfolio vol targeting off the UNSCALED portfolio's trailing vol, lagged,
    # so the scaler never sees the bar it sizes.
    unscaled_pnl = (held.shift(config.execution_lag) * panel).sum(axis=1, min_count=1)
    trailing_vol = unscaled_pnl.ewm(
        halflife=config.portfolio_vol_halflife, min_periods=config.portfolio_vol_halflife, adjust=False
    ).std() * np.sqrt(TRADING_DAYS)
    portfolio_scale = (
        (config.portfolio_vol_target / trailing_vol.replace(0.0, np.nan))
        .clip(upper=config.max_portfolio_leverage)
        .shift(config.execution_lag)
    )

    positions = held.mul(portfolio_scale, axis=0).fillna(0.0)

    gross = (positions.shift(config.execution_lag) * panel).sum(axis=1, min_count=1)

    position_change = positions.diff().abs().fillna(0.0)
    cost_rates = pd.Series(
        {
            instrument: COST_BPS_BY_ASSET_CLASS.get(asset_class_by_instrument.get(instrument, ""), 5.0)
            / 10_000.0
            * config.cost_multiplier
            for instrument in panel.columns
        }
    )
    missing_cost = [c for c in panel.columns if asset_class_by_instrument.get(c) not in COST_BPS_BY_ASSET_CLASS]
    if missing_cost:
        warnings.append(f"default 5bps cost applied to unclassified instruments: {sorted(missing_cost)}")

    costs = position_change.mul(cost_rates, axis=1).sum(axis=1)
    net = gross - costs
    turnover = position_change.sum(axis=1)

    valid = gross.notna()
    net = net.where(valid)
    gross = gross.where(valid)

    return StudyResult(
        net_returns=net,
        gross_returns=gross,
        costs=costs.where(valid),
        positions=positions,
        turnover=turnover.where(valid),
        metrics=compute_metrics(net, gross, turnover.where(valid)),
        instruments=tuple(panel.columns),
        warnings=tuple(warnings),
    )


def run_with_costs(
    returns: pd.DataFrame,
    asset_class_by_instrument: dict[str, str],
    config: StudyConfig,
    multiplier: float,
) -> StudyResult:
    return run_tsmom(returns, asset_class_by_instrument, replace(config, cost_multiplier=multiplier))
