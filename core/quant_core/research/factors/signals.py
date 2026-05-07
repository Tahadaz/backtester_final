"""Pure factor-only trading signals — Phase 1.

Six pre-registered rules evaluated via the existing evaluate_signal() harness.
All functions return pd.Series with DatetimeIndex and values in {-1, 0, +1},
NaN where insufficient data (fewer than `window` bars).

Pre-registration: docs/research/phase1_pre_registration.yaml
Rule specs:       docs/factor-layer/07-phase1-factor-strategies.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Signal functions
# ---------------------------------------------------------------------------

def vix_zscore_signal(
    vix: pd.Series,
    window: int = 20,
    z_long: float = -1.0,
    z_short: float = 2.0,
) -> pd.Series:
    """Ilmanen (2011) Ch.15 risk-on/off gate via VIX z-score.

    z < z_long  →  +1  (compressed VIX, risk-on)
    z > z_short →  -1  (spiking VIX, risk-off)
    else        →   0
    """
    roll_mean = vix.rolling(window).mean()
    roll_std = vix.rolling(window).std(ddof=1)
    z = (vix - roll_mean) / roll_std.replace(0, float("nan"))

    signal = pd.Series(0.0, index=vix.index, dtype=float)
    signal[z < z_long] = 1.0
    signal[z > z_short] = -1.0
    # NaN where z is NaN (insufficient history)
    signal[z.isna()] = float("nan")
    return signal


def dxy_momentum_signal(dxy: pd.Series, window: int = 20) -> pd.Series:
    """Hau & Rey (2006): DXY 20d return < 0 → +1 (EM tailwind), else -1."""
    mom = dxy.pct_change(window, fill_method=None)
    signal = pd.Series(np.where(mom < 0, 1.0, -1.0), index=dxy.index, dtype=float)
    signal[mom.isna()] = float("nan")
    return signal


def brent_direction_signal(brent: pd.Series, window: int = 5) -> pd.Series:
    """Brent 5d momentum direction → +1/-1. Channel-gated to materials sectors."""
    mom = brent.pct_change(window, fill_method=None)
    signal = pd.Series(np.where(mom > 0, 1.0, -1.0), index=brent.index, dtype=float)
    signal[mom.isna()] = float("nan")
    return signal


def sp500_vix_confirmation_signal(
    sp500: pd.Series,
    vix: pd.Series,
    sp500_window: int = 5,
    vix_window: int = 20,
    vix_z_cap: float = 1.0,
) -> pd.Series:
    """Ilmanen (2011): SP500 5d mom > 0 AND VIX z < vix_z_cap → +1; else 0."""
    sp500_mom = sp500.pct_change(sp500_window, fill_method=None)

    roll_mean = vix.rolling(vix_window).mean()
    roll_std = vix.rolling(vix_window).std(ddof=1)
    vix_z = (vix - roll_mean) / roll_std.replace(0, float("nan"))

    common = sp500_mom.index.intersection(vix_z.index)
    sp_m = sp500_mom.reindex(common)
    v_z = vix_z.reindex(common)

    cond = (sp_m > 0) & (v_z < vix_z_cap)
    signal = pd.Series(0.0, index=common, dtype=float)
    signal[cond] = 1.0
    signal[sp_m.isna() | v_z.isna()] = float("nan")
    return signal


def us10y_shock_signal(
    us10y: pd.Series,
    window: int = 5,
    shock_threshold_bp: float = 20.0,
) -> pd.Series:
    """Campbell & Shiller (1988): 5d yield rise > 20 bp → -1 (tightening shock), else 0.

    US10Y series is in percent (e.g. 4.5 = 4.5%), so 20 bp = 0.20.
    """
    threshold_pct = shock_threshold_bp / 100.0
    delta = us10y.diff(window)
    signal = pd.Series(0.0, index=us10y.index, dtype=float)
    signal[delta > threshold_pct] = -1.0
    signal[delta.isna()] = float("nan")
    return signal


def eurusd_momentum_signal(eurusd: pd.Series, window: int = 20) -> pd.Series:
    """MAD peg channel: 20d momentum direction → +1/-1.

    MAD peg is ~60% EUR, 40% USD. EUR strength → MAD appreciation.
    """
    mom = eurusd.pct_change(window, fill_method=None)
    signal = pd.Series(np.where(mom > 0, 1.0, -1.0), index=eurusd.index, dtype=float)
    signal[mom.isna()] = float("nan")
    return signal


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FactorSignalSpec:
    factor_id: str           # canonical macro ID; matches MacroSeriesSpec.canonical_id
    signal_name: str         # unique key: "vix_zscore", "dxy_momentum", ...
    fn: Callable | None      # None for multi-factor signals (handled by dispatcher)
    default_params: dict     # frozen at pre-registration; must not be mutated
    channel_filter: tuple    # empty → all sectors; non-empty → sector must be in tuple
    citation: str
    requires: tuple          # factor_ids needed; defaults to (factor_id,)


REGISTERED_FACTOR_SIGNALS: list[FactorSignalSpec] = [
    FactorSignalSpec(
        factor_id="VIX",
        signal_name="vix_zscore",
        fn=vix_zscore_signal,
        default_params={"window": 20, "z_long": -1.0, "z_short": 2.0},
        channel_filter=(),
        citation="Ilmanen (2011), Expected Returns, Ch.15",
        requires=("VIX",),
    ),
    FactorSignalSpec(
        factor_id="DXY",
        signal_name="dxy_momentum",
        fn=dxy_momentum_signal,
        default_params={"window": 20},
        channel_filter=(),
        citation="Hau & Rey (2006), JF",
        requires=("DXY",),
    ),
    FactorSignalSpec(
        factor_id="BRENT",
        signal_name="brent_direction",
        fn=brent_direction_signal,
        default_params={"window": 5},
        channel_filter=("materials", "mining", "chemicals"),
        citation="economic channel (BRENT→extractive)",
        requires=("BRENT",),
    ),
    FactorSignalSpec(
        factor_id="SP500",
        signal_name="sp500_vix_confirmation",
        fn=None,  # multi-factor: handled in compute_factor_signal dispatcher
        default_params={"sp500_window": 5, "vix_window": 20, "vix_z_cap": 1.0},
        channel_filter=(),
        citation="Ilmanen (2011), Expected Returns, Ch.15",
        requires=("SP500", "VIX"),
    ),
    FactorSignalSpec(
        factor_id="US10Y",
        signal_name="us10y_shock",
        fn=us10y_shock_signal,
        default_params={"window": 5, "shock_threshold_bp": 20.0},
        channel_filter=("banks", "insurance", "real_estate"),
        citation="Campbell & Shiller (1988), JF",
        requires=("US10Y",),
    ),
    FactorSignalSpec(
        factor_id="EURUSD",
        signal_name="eurusd_momentum",
        fn=eurusd_momentum_signal,
        default_params={"window": 20},
        channel_filter=(),
        citation="MAD peg channel (~60% EUR, 40% USD)",
        requires=("EURUSD",),
    ),
]

# fast lookup by signal_name
_SPEC_BY_NAME: dict[str, FactorSignalSpec] = {
    s.signal_name: s for s in REGISTERED_FACTOR_SIGNALS
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_applicable(spec: FactorSignalSpec, sector: str) -> bool:
    """Return True if this signal applies to the given sector.

    Empty channel_filter means all sectors are applicable.
    Special token sector="all" bypasses the gate (for callers that want every signal).
    """
    if not spec.channel_filter:
        return True
    if sector == "all":
        return True
    return sector.lower() in spec.channel_filter


def compute_factor_signal(
    spec: FactorSignalSpec,
    aligned_factors: dict[str, pd.Series],
) -> pd.Series:
    """Compute one signal. Handles the SP500+VIX multi-factor case."""
    # Verify all required factors are present
    for req in spec.requires:
        if req not in aligned_factors:
            raise KeyError(f"Required factor {req!r} missing from aligned_factors")

    if spec.signal_name == "sp500_vix_confirmation":
        return sp500_vix_confirmation_signal(
            sp500=aligned_factors["SP500"],
            vix=aligned_factors["VIX"],
            **spec.default_params,
        )

    # Single-factor signals
    primary = aligned_factors[spec.factor_id]
    return spec.fn(primary, **spec.default_params)  # type: ignore[misc]


def compute_all_factor_signals(
    aligned_factors: dict[str, pd.Series],
    sector: str = "all",
) -> dict[str, pd.Series]:
    """Compute all registered signals whose `requires` are present and channel passes.

    Args:
        aligned_factors: {canonical_id: pd.Series} — already aligned to target calendar.
        sector: stock sector string, or "all" to bypass channel gate.

    Returns:
        {signal_name: pd.Series} for every applicable, computable signal.
    """
    result: dict[str, pd.Series] = {}
    for spec in REGISTERED_FACTOR_SIGNALS:
        # Check channel applicability
        if not is_applicable(spec, sector):
            continue
        # Check all required factors are available
        if not all(req in aligned_factors for req in spec.requires):
            continue
        try:
            result[spec.signal_name] = compute_factor_signal(spec, aligned_factors)
        except Exception:
            pass  # silently skip if compute fails (data gaps, etc.)
    return result
