"""Cross-asset carry: FX interest differentials and rates curve carry.

Method fixed by `docs/global-desk/03-carry-preregistration.md`. Portfolio
construction is deliberately *not* implemented here -- it is shared with TSMOM
via :func:`quant_core.cross_asset.tsmom_study.run_signal_portfolio`, so the two
sleeves are measured identically and their Sharpes are comparable.

Commodity curve carry is absent by design: it needs the futures term structure,
and free sources serve only the front contract. See the pre-registration §1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .tsmom_study import TRADING_DAYS


# Curve points available from FRED, in years. Used to interpolate the yield one
# year down the curve for the roll-down term.
CURVE_TENORS: dict[str, float] = {"DGS3MO": 0.25, "DGS1": 1.0, "DGS2": 2.0, "DGS5": 5.0, "DGS10": 10.0, "DGS30": 30.0}

# Instrument -> (tenor in years, modified duration).
RATES_TENOR: dict[str, tuple[float, float]] = {
    "TU": (2.0, 1.9),
    "FV": (5.0, 4.6),
    "TY": (10.0, 8.3),
    "US": (30.0, 17.5),
}

# Monthly OECD/FRED rate series are published with a lag and later revised.
# Using month M's observation during month M is look-ahead.
RATE_PUBLICATION_LAG_MONTHS = 2


def lag_monthly_rates(rates: pd.Series, months: int = RATE_PUBLICATION_LAG_MONTHS) -> pd.Series:
    """Shift a monthly series by its publication lag before it may be used."""
    if months < 0:
        raise ValueError("months must be non-negative")
    clean = pd.to_numeric(rates, errors="coerce").dropna().sort_index()
    if clean.empty:
        return clean
    shifted = clean.copy()
    shifted.index = shifted.index + pd.DateOffset(months=months)
    return shifted


def to_daily_rate(rates: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    """Step a lagged monthly rate onto a daily calendar.

    Forward-fill only: a rate is known from its (lagged) publication date until
    the next one arrives. Never interpolated, because interpolating would imply
    knowledge of the next observation before it exists.
    """
    clean = pd.to_numeric(rates, errors="coerce").dropna().sort_index()
    if clean.empty:
        return pd.Series(np.nan, index=calendar, dtype=float)
    return clean.reindex(clean.index.union(calendar)).ffill().reindex(calendar)


def fx_carry(
    rate_by_currency: dict[str, pd.Series],
    pairs: dict[str, tuple[str, str]],
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Annualized carry of a long position in each pair.

    ``pairs`` maps instrument -> (base_ccy, quote_ccy). A long position owns the
    base and funds in the quote, so it earns ``r_base - r_quote``.
    """
    daily = {ccy: to_daily_rate(series, calendar) for ccy, series in rate_by_currency.items()}
    columns: dict[str, pd.Series] = {}
    for instrument, (base, quote) in pairs.items():
        if base not in daily or quote not in daily:
            continue
        columns[instrument] = daily[base] - daily[quote]
    return pd.DataFrame(columns, index=calendar)


def interpolate_curve(curve: pd.DataFrame, target_tenor: float) -> pd.Series:
    """Linearly interpolate the yield at ``target_tenor`` from available points.

    ``curve`` columns are FRED ids present in :data:`CURVE_TENORS`.
    """
    points = sorted(
        ((CURVE_TENORS[c], c) for c in curve.columns if c in CURVE_TENORS), key=lambda item: item[0]
    )
    if not points:
        raise ValueError("no recognised curve columns")
    tenors = np.array([t for t, _ in points], dtype=float)
    values = curve[[c for _, c in points]].to_numpy(dtype=float)

    target = float(np.clip(target_tenor, tenors.min(), tenors.max()))
    out = np.full(len(curve), np.nan)
    for row in range(values.shape[0]):
        row_values = values[row]
        mask = np.isfinite(row_values)
        if mask.sum() < 2:
            continue
        out[row] = np.interp(target, tenors[mask], row_values[mask])
    return pd.Series(out, index=curve.index)


def rates_curve_carry(
    curve: pd.DataFrame,
    financing_column: str = "DGS3MO",
    tenor_map: dict[str, tuple[float, float]] | None = None,
) -> pd.DataFrame:
    """Carry plus roll-down for each constant-maturity bond position.

    ``expected = (y_T - financing) + D_T * (y_T - y_{T-1y})``

    The first term is the yield pickup over funding; the second is the capital
    gain from the bond aging one year down a sloped curve, which is the part a
    pure yield-spread signal misses.
    """
    tenor_map = tenor_map or RATES_TENOR
    if financing_column not in curve.columns:
        raise KeyError(f"financing column {financing_column!r} missing from curve")

    financing = pd.to_numeric(curve[financing_column], errors="coerce")
    columns: dict[str, pd.Series] = {}
    for instrument, (tenor, duration) in tenor_map.items():
        yield_now = interpolate_curve(curve, tenor)
        yield_rolled = interpolate_curve(curve, max(tenor - 1.0, min(CURVE_TENORS.values())))
        carry = yield_now - financing
        roll_down = duration * (yield_now - yield_rolled)
        columns[instrument] = carry + roll_down
    return pd.DataFrame(columns, index=curve.index)


# ---------------------------------------------------------------------------
# Signal variants -- exactly the three declared in the pre-registration
# ---------------------------------------------------------------------------


def carry_signal_sign(carry: pd.DataFrame, lag: int = 1) -> pd.DataFrame:
    """sign(carry), lagged."""
    if lag < 1:
        raise ValueError("lag must be at least one bar")
    return np.sign(carry.astype(float)).shift(lag)


def carry_signal_smoothed(carry: pd.DataFrame, window: int = 21, lag: int = 1) -> pd.DataFrame:
    """sign(smoothed carry), lagged -- damps month-boundary rate steps."""
    if lag < 1:
        raise ValueError("lag must be at least one bar")
    smoothed = carry.astype(float).rolling(window, min_periods=max(1, window // 2)).mean()
    return np.sign(smoothed).shift(lag)


def carry_signal_ranked(carry: pd.DataFrame, lag: int = 1) -> pd.DataFrame:
    """Cross-sectionally demeaned carry, lagged.

    Long the instruments yielding more than the cross-section average and short
    the rest, so the sleeve is closer to dollar-neutral and strips out the level
    of global rates -- which is a macro exposure, not carry.
    """
    if lag < 1:
        raise ValueError("lag must be at least one bar")
    values = carry.astype(float)
    demeaned = values.sub(values.mean(axis=1), axis=0)
    return np.sign(demeaned).shift(lag)


CARRY_VARIANTS = {
    "sign": carry_signal_sign,
    "smoothed": carry_signal_smoothed,
    "ranked": carry_signal_ranked,
}


def annualize_carry_to_daily(carry: pd.DataFrame) -> pd.DataFrame:
    """Convert an annualized carry rate to a per-bar expected accrual."""
    return carry.astype(float) / TRADING_DAYS
