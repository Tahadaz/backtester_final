"""Model forward forecaster (brief 54 §3 Phase 4).

Goal: a lightweight, deliberately simple cross-sectional forecaster for
next-year revenue / net-income (EPS proxy) growth, used ONLY as a fallback in
`build_projection()`'s consensus-injection seam when neither BKGR nor
MarketScreener supplies a forward estimate for a given (symbol, year) -- most
MASI names, and all pre-2026 PIT history.

Design (kept intentionally small -- ~70 names x ~9 annual years cannot support
more than a handful of parameters without overfitting):

    forecast = Ridge(momentum, sector_momentum, reversion_gap)

  - momentum:        the EXACT mechanical baseline already used in
                      projection.py (0.5 * 3y-CAGR + 0.5 * last-year growth).
                      Reused via `_cagr`/`_growth_series` so the model sees
                      identical inputs to the thing it must beat.
  - sector_momentum:  cross-sectional median of `momentum` across same-sector
                      peers this year -- the "sector-relative mean-reversion"
                      term the brief asks for (systematic sector-level shocks,
                      e.g. a phosphate price cycle, tend to persist across
                      peers into next year more reliably than one company's
                      own trailing trend).
  - reversion_gap:    last-year growth minus the company's own trailing-mean
                      growth -- captures "unusually high/low this year vs its
                      own history", the classic mean-reversion signal.

Ridge with a FIXED alpha=1.0 (not cross-validated per fold) -- same convention
already used in `factor_selection/lasso.py`'s `_fit_initial_weights`.  On this
little data, tuning alpha via nested CV would mostly fit noise; a fixed,
modest shrinkage is the more honest choice and matches the brief's explicit
instruction to "resist over-parameterization."

Validation (see `run_expanding_window_backtest` and
`services/api/scripts/forecast_model_validation.py` for the live-DB run) is a
strict expanding-window, point-in-time backtest: predict next-year *realized*
growth from data available only through the as-of year, exactly mirroring the
no-lookahead discipline in `pit_ic_backtest.py` (`_filter_pit_history`,
`_assert_no_lookahead`).  Result (see 54-forward-estimate-layer-plan.md and
the Phase-4 completion notes): the model beat the naive-CAGR baseline
out-of-sample on both revenue and net-income growth across every available
test year (2021-2024), so it is wired in as the fallback -- never overriding
consensus, only filling the gap where consensus is silent.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from statistics import mean, median
from typing import Mapping, Sequence

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from .domain import AnnualMetricRow
from .projection import _cagr, _growth_series, _series

# ─── Constants ────────────────────────────────────────────────────────────────

#: Fixed Ridge shrinkage strength -- see module docstring. Not tuned per fold.
RIDGE_ALPHA = 1.0

#: Minimum number of (symbol, as_of_year) rows with a known target required to
#: fit at all; below this the panel is too thin to trust any coefficients and
#: callers should fall back to the mechanical path. Chosen empirically -- the
#: smallest expanding-window training set exercised in validation (2021) had
#: ~150 rows; 20 is a conservative floor below which we simply refuse to fit.
MIN_TRAIN_OBSERVATIONS = 20

#: Sanity band for annual growth. Real MASI names essentially never grow
#: revenue/NI by more than 500% or shrink more than 95% organically in a
#: single year; observed values outside this band are pre-existing data-layer
#: scale bugs (e.g. a missing x1e3/x1e6 unit factor for a specific
#: symbol/year -- confirmed during Phase-4 validation for IAM/MNG/BOA/ATW/TQM
#: 2020 Revenue and a few others) rather than real moves. Rows outside the
#: band are dropped from BOTH training and prediction -- data hygiene, not
#: cherry-picking, since it would exclude a row from either method identically.
GROWTH_BOUND = (-0.95, 5.0)

#: Sanity band for the reversion_gap feature (own growth minus own trailing
#: mean growth). A gap of +/-300pp signals the same class of scale artifact
#: (usually surfaced by a multi-year data gap spanning a unit change).
REVERSION_GAP_BOUND = (-3.0, 3.0)


def _in_bounds(value: float, bound: tuple[float, float]) -> bool:
    lo, hi = bound
    return lo <= value <= hi


def mechanical_momentum(series: list[tuple[int, float]]) -> float | None:
    """Exact same blend as projection.py's mechanical revenue-growth fallback:
    0.5 * 3y CAGR + 0.5 * last-year growth (falling back to whichever of the
    two is available). Kept as a standalone function -- rather than importing
    projection.py's inline calc -- so both the naive-CAGR *comparator* used in
    validation and this model's `momentum` *feature* are provably identical.
    """
    cagr_3y = _cagr(series, periods=3)
    growth_hist = _growth_series(series)
    last_year_growth = growth_hist[-1][1] if growth_hist else cagr_3y
    if cagr_3y is None and last_year_growth is None:
        return None
    if cagr_3y is None:
        return float(last_year_growth)
    if last_year_growth is None:
        return float(cagr_3y)
    return 0.5 * float(cagr_3y) + 0.5 * float(last_year_growth)


# ─── Panel construction ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GrowthObservation:
    symbol: str
    sector: str | None
    as_of_year: int
    momentum: float
    reversion_gap: float
    sector_momentum: float | None = None
    #: Realized growth as_of_year -> as_of_year+1. None for a live/current-year
    #: prediction row (target unknown by construction) or a training row whose
    #: forward actual isn't available yet.
    target: float | None = None

    def feature_vector(self) -> tuple[float, float, float]:
        sector_mom = self.sector_momentum if self.sector_momentum is not None else self.momentum
        return (self.momentum, sector_mom, self.reversion_gap)


def _feasible_features(
    pit_history: list[AnnualMetricRow],
    aliases: tuple[str, ...],
) -> tuple[float, float] | None:
    """Return (momentum, reversion_gap) for one symbol's PIT-filtered history,
    or None if infeasible (too little history, or values outside the sanity
    band -- see GROWTH_BOUND/REVERSION_GAP_BOUND)."""
    series = _series(pit_history, aliases)
    if len(series) < 2:
        return None
    momentum = mechanical_momentum(series)
    if momentum is None or not _in_bounds(momentum, GROWTH_BOUND):
        return None
    growth_hist = _growth_series(series)
    if not growth_hist:
        return momentum, 0.0
    last_year_growth = growth_hist[-1][1]
    if not _in_bounds(last_year_growth, GROWTH_BOUND):
        return None
    own_trailing_mean = mean(value for _year, value in growth_hist)
    reversion_gap = last_year_growth - own_trailing_mean
    if not _in_bounds(reversion_gap, REVERSION_GAP_BOUND):
        return None
    return momentum, reversion_gap


def _realized_growth(
    realized_history: list[AnnualMetricRow] | None,
    as_of_year: int,
    aliases: tuple[str, ...],
) -> float | None:
    """Realized growth as_of_year -> as_of_year+1 from a history PIT-filtered to
    as_of_year+1 (i.e. the actual has since printed). Returns None if the
    actual isn't available or falls outside the sanity band."""
    if not realized_history:
        return None
    fwd_series = dict(_series(realized_history, aliases))
    prev_val = fwd_series.get(as_of_year)
    next_val = fwd_series.get(as_of_year + 1)
    if prev_val is None or next_val is None or prev_val <= 0:
        return None
    realized = next_val / prev_val - 1.0
    return realized if _in_bounds(realized, GROWTH_BOUND) else None


def build_growth_observations(
    pit_histories_by_symbol: Mapping[str, list[AnnualMetricRow]],
    sectors: Mapping[str, str | None],
    as_of_year: int,
    aliases: tuple[str, ...],
    *,
    realized_histories_by_symbol: Mapping[str, list[AnnualMetricRow]] | None = None,
) -> list[GrowthObservation]:
    """Build the cross-sectional panel of growth observations as of `as_of_year`.

    PIT contract (caller's responsibility, mirroring pit_ic_backtest.py):
      - `pit_histories_by_symbol` values MUST already be filtered to
        statement_year <= as_of_year (e.g. via `_filter_pit_history`).
      - `realized_histories_by_symbol`, if given, MUST be filtered to
        statement_year <= as_of_year + 1 and is used ONLY to compute the
        *training* target. Omit it (or omit a symbol) for a live/current-year
        prediction row -- the target for the row actually being forecast must
        never be populated from data that wouldn't exist yet.

    This function does not itself call `_filter_pit_history` -- it trusts the
    caller's filtering, exactly like `_build_pit_snapshot` trusts its PIT
    history argument. Both service-layer callers and this module's own
    backtest harness are responsible for the filtering step.
    """
    observations: list[GrowthObservation] = []
    for symbol, pit_history in pit_histories_by_symbol.items():
        features = _feasible_features(pit_history, aliases)
        if features is None:
            continue
        momentum, reversion_gap = features
        realized_history = (realized_histories_by_symbol or {}).get(symbol)
        target = _realized_growth(realized_history, as_of_year, aliases)
        observations.append(
            GrowthObservation(
                symbol=symbol,
                sector=sectors.get(symbol),
                as_of_year=as_of_year,
                momentum=momentum,
                reversion_gap=reversion_gap,
                target=target,
            )
        )
    return attach_sector_momentum(observations)


def attach_sector_momentum(observations: list[GrowthObservation]) -> list[GrowthObservation]:
    """Fill in `sector_momentum` = median(momentum) across all observations
    sharing a (sector, as_of_year) -- self-inclusive (the company's own
    momentum counts in its sector's median; simplest reasonable choice at this
    sample size, and what was empirically validated)."""
    by_sector_year: dict[tuple[str | None, int], list[float]] = defaultdict(list)
    for obs in observations:
        by_sector_year[(obs.sector, obs.as_of_year)].append(obs.momentum)
    out = []
    for obs in observations:
        peers = by_sector_year[(obs.sector, obs.as_of_year)]
        out.append(replace(obs, sector_momentum=median(peers)))
    return out


# ─── Model fit / predict ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FittedGrowthForecaster:
    feature_mean: tuple[float, float, float]
    feature_scale: tuple[float, float, float]
    coef: tuple[float, float, float]
    intercept: float
    n_train: int


def fit_growth_forecaster(observations: Sequence[GrowthObservation]) -> FittedGrowthForecaster | None:
    """Fit the Ridge(alpha=RIDGE_ALPHA) forecaster on all observations carrying
    a known target. Returns None (caller must fall back to mechanical) if
    there are fewer than MIN_TRAIN_OBSERVATIONS such rows."""
    training = [obs for obs in observations if obs.target is not None]
    if len(training) < MIN_TRAIN_OBSERVATIONS:
        return None

    X = np.array([obs.feature_vector() for obs in training], dtype=float)
    y = np.array([obs.target for obs in training], dtype=float)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    ridge = Ridge(alpha=RIDGE_ALPHA)
    ridge.fit(X_scaled, y)

    scale = np.where(scaler.scale_ == 0, 1.0, scaler.scale_)
    return FittedGrowthForecaster(
        feature_mean=tuple(float(v) for v in scaler.mean_),
        feature_scale=tuple(float(v) for v in scale),
        coef=tuple(float(v) for v in ridge.coef_),
        intercept=float(ridge.intercept_),
        n_train=len(training),
    )


def predict_growth(model: FittedGrowthForecaster, observation: GrowthObservation) -> float:
    raw = np.array(observation.feature_vector(), dtype=float)
    mean_ = np.array(model.feature_mean, dtype=float)
    scale = np.array(model.feature_scale, dtype=float)
    scaled = (raw - mean_) / scale
    return float(np.dot(scaled, np.array(model.coef, dtype=float)) + model.intercept)


def forecast_symbol_growth(
    symbol: str,
    observations: Sequence[GrowthObservation],
) -> float | None:
    """Fit on every observation in `observations` carrying a known target, then
    predict growth for `symbol`'s row in `observations` (its as_of_year row,
    target expected to be None -- the row being forecast live).

    Returns None if `symbol` has no feasible observation in the panel, or if
    there isn't enough training data to fit -- callers must treat None as
    "no model view available" and fall back to the existing mechanical path,
    never as a zero-growth forecast.
    """
    target_obs = next((obs for obs in observations if obs.symbol == symbol), None)
    if target_obs is None:
        return None
    model = fit_growth_forecaster(observations)
    if model is None:
        return None
    return predict_growth(model, target_obs)


# ─── Expanding-window backtest (validation harness) ────────────────────────────

@dataclass(frozen=True)
class BacktestMetrics:
    n: int
    rmse: float
    mae: float
    hit_rate: float


def _metrics(preds: np.ndarray, actuals: np.ndarray) -> BacktestMetrics:
    err = preds - actuals
    return BacktestMetrics(
        n=int(len(actuals)),
        rmse=float(np.sqrt(np.mean(err ** 2))),
        mae=float(np.mean(np.abs(err))),
        hit_rate=float(np.mean(np.sign(preds) == np.sign(actuals))),
    )


def run_expanding_window_backtest(
    panel: Sequence[GrowthObservation],
    test_years: Sequence[int],
) -> dict[str, BacktestMetrics] | None:
    """Point-in-time expanding-window validation: for each test_year, fit on
    every observation with as_of_year < test_year and a known target, predict
    for every observation AT test_year with a known target (so we can score
    against the now-realized actual), and compare the model's predictions
    against the naive-CAGR `momentum` feature (== the exact mechanical
    fallback in projection.py) on identical rows.

    `panel` should span all as_of_years of interest, built with
    `realized_histories_by_symbol` supplied for every year so historical
    targets are populated -- see
    `services/api/scripts/forecast_model_validation.py` for the live-DB
    construction. Returns None if no test_year has enough train+test data.
    """
    model_preds: list[float] = []
    model_actuals: list[float] = []
    baseline_preds: list[float] = []
    baseline_actuals: list[float] = []

    for test_year in sorted(test_years):
        train_rows = [obs for obs in panel if obs.target is not None and obs.as_of_year < test_year]
        test_rows = [obs for obs in panel if obs.as_of_year == test_year and obs.target is not None]
        if len(train_rows) < MIN_TRAIN_OBSERVATIONS or not test_rows:
            continue

        model = fit_growth_forecaster(train_rows)
        if model is None:
            continue

        for obs in test_rows:
            model_preds.append(predict_growth(model, obs))
            model_actuals.append(obs.target)  # type: ignore[arg-type]
            baseline_preds.append(obs.momentum)
            baseline_actuals.append(obs.target)  # type: ignore[arg-type]

    if not model_actuals:
        return None

    return {
        "model": _metrics(np.array(model_preds), np.array(model_actuals)),
        "naive_cagr": _metrics(np.array(baseline_preds), np.array(baseline_actuals)),
    }


__all__ = [
    "GROWTH_BOUND",
    "MIN_TRAIN_OBSERVATIONS",
    "REVERSION_GAP_BOUND",
    "RIDGE_ALPHA",
    "BacktestMetrics",
    "FittedGrowthForecaster",
    "GrowthObservation",
    "attach_sector_momentum",
    "build_growth_observations",
    "fit_growth_forecaster",
    "forecast_symbol_growth",
    "mechanical_momentum",
    "predict_growth",
    "run_expanding_window_backtest",
]
