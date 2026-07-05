from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from quant_core.fundamentals.scoring import _accrual_quality, _dupont, _piotroski_lite


@dataclass(frozen=True)
class PillarConfig:
    pmom_months: int = 6
    skip_months: int = 1
    mad_clip: float = 3.0
    min_bucket: int = 8


def _clean(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _ratio(value: Any) -> float | None:
    out = _clean(value)
    if out is None:
        return None
    return out / 100.0 if abs(out) > 2.0 else out


def _metric(metrics: dict[str, Any], *names: str) -> float | None:
    for name in names:
        val = _clean(metrics.get(name))
        if val is not None:
            return val
    return None


def _mean(values: list[float | None]) -> float | None:
    finite = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return float(np.mean(finite)) if finite else None


def _value_raw(metrics: dict[str, Any], is_financial: bool) -> float | None:
    per = _metric(metrics, "PER", "P_E", "Price_to_Earnings")
    pb = _metric(metrics, "Price_to_Book", "P_B")
    cfo = _metric(metrics, "Operating_Cash_Flow", "Cash_Flow_Operations", "CFO")
    mcap = _metric(metrics, "MarketCap_Calc", "Market_Cap")
    ev_ebitda = _metric(metrics, "EV_to_EBITDA")
    parts = [
        (1.0 / per) if per and per > 0 else None,
        (1.0 / pb) if pb and pb > 0 else None,
    ]
    if not is_financial:
        parts.extend([
            (cfo / mcap) if cfo is not None and mcap and mcap > 0 else _metric(metrics, "CFO_Yield", "Operating_CF_Yield"),
            (1.0 / ev_ebitda) if ev_ebitda and ev_ebitda > 0 else None,
        ])
    return _mean(parts)


def _dividend_sustainability(metrics: dict[str, Any], history: list[Any], is_financial: bool) -> float | None:
    dividends = [_clean(getattr(row, "metric_value", None)) for row in history if getattr(row, "metric_name", "") in {"Dividendes", "Dividends_Paid", "Dividend"}]
    dividends = [v for v in dividends if v is not None]
    latest_div = dividends[-1] if dividends else _metric(metrics, "Dividendes", "Dividends_Paid")
    if latest_div is None:
        return None
    denominator = _metric(metrics, "NetIncome", "Resultat_net", "Clean_Resultat_net") if is_financial else _metric(metrics, "Free_Cash_Flow", "FCF")
    covered = denominator is not None and denominator > 0 and latest_div <= denominator
    non_cut = len(dividends) >= 3 and all(dividends[i] >= dividends[i - 1] * 0.98 for i in range(1, len(dividends)))
    return float(int(covered) + int(non_cut)) / 2.0


def _quality_raw(snapshot: Any, history: list[Any], is_financial: bool) -> float | None:
    piotroski = _clean(_piotroski_lite(snapshot, history).get("score"))
    dupont = _dupont(snapshot)
    dupont_score = _clean(dupont.get("score"))
    reported_roe = _ratio(dupont.get("reported_roe"))
    accrual = _clean(_accrual_quality(snapshot, history).get("score"))
    div = _dividend_sustainability(snapshot.metrics, history, is_financial)
    parts = [
        piotroski / 100.0 if piotroski is not None else None,
        dupont_score / 100.0 if dupont_score is not None else reported_roe,
        accrual / 100.0 if accrual is not None else None,
        div,
    ]
    return _mean(parts)


def _fundamental_momentum_raw(metrics: dict[str, Any]) -> float | None:
    revenue_growth = _ratio(_metric(metrics, "Revenue_Growth", "Chiffre_daffaires_Growth"))
    ni_growth = _ratio(_metric(metrics, "NetIncome_Growth", "Resultat_net_Growth"))
    acceleration = _ratio(_metric(metrics, "Revenue_Growth_Acceleration", "Revenue_Acceleration"))
    revisions = []
    for key, value in metrics.items():
        if key.startswith("Consensus_") and key.endswith(str(dt.date.today().year)):
            revisions.append(_clean(value))
    consensus_level = _mean(revisions)
    return _mean([revenue_growth, ni_growth, acceleration, consensus_level])


def _momentum_return(prices: pd.Series | None, as_of_date: dt.date, *, formation_months: int, skip_months: int) -> float | None:
    if prices is None or prices.empty:
        return None
    series = prices.sort_index().dropna()
    end_date = pd.Timestamp(as_of_date) - pd.DateOffset(months=skip_months)
    start_date = pd.Timestamp(as_of_date) - pd.DateOffset(months=formation_months)
    past = series[series.index <= start_date]
    end = series[series.index <= end_date]
    if past.empty or end.empty:
        return None
    start_px = float(past.iloc[-1])
    end_px = float(end.iloc[-1])
    if start_px <= 0 or not math.isfinite(start_px) or not math.isfinite(end_px):
        return None
    return end_px / start_px - 1.0


def mad_winsorized_z(values: pd.Series, *, clip: float = 3.0) -> pd.Series:
    vals = pd.to_numeric(values, errors="coerce")
    median = float(vals.median())
    mad = float((vals - median).abs().median())
    if not math.isfinite(median) or mad <= 0 or not math.isfinite(mad):
        std = float(vals.std(ddof=0))
        if std <= 0 or not math.isfinite(std):
            return pd.Series(0.0, index=values.index)
        return (vals - float(vals.mean())) / std
    robust_z = (vals - median) / (1.4826 * mad)
    clipped = median + robust_z.clip(-clip, clip) * 1.4826 * mad
    std = float(clipped.std(ddof=0))
    if std <= 0 or not math.isfinite(std):
        return pd.Series(0.0, index=values.index)
    return (clipped - float(clipped.mean())) / std


def _neutralized_z(frame: pd.DataFrame, raw_col: str, *, config: PillarConfig) -> pd.Series:
    out = pd.Series(np.nan, index=frame.index, dtype=float)
    for (_, is_financial), sub in frame.groupby(["as_of_date", "is_financial"], dropna=False):
        vals = pd.to_numeric(sub[raw_col], errors="coerce").dropna()
        if len(vals) < config.min_bucket:
            continue
        out.loc[vals.index] = mad_winsorized_z(vals, clip=config.mad_clip)
    return out


def compute_pillar_scores(
    panel: pd.DataFrame,
    *,
    price_by_symbol: dict[str, pd.Series | None] | None = None,
    config: PillarConfig | None = None,
) -> pd.DataFrame:
    cfg = config or PillarConfig()
    if panel.empty:
        return panel.copy()
    rows = []
    price_map = price_by_symbol or {}
    for idx, row in panel.iterrows():
        metrics = dict(row["metrics"])
        snapshot = row["snapshot"]
        history = list(row["history"])
        is_financial = bool(row.get("is_financial", False))
        prices = price_map.get(str(row["symbol"]))
        as_of = row["as_of_date"]
        rows.append(
            {
                "_idx": idx,
                "pillar_val_raw": _value_raw(metrics, is_financial),
                "pillar_qual_raw": _quality_raw(snapshot, history, is_financial),
                "pillar_fmom_raw": _fundamental_momentum_raw(metrics),
                "pillar_pmom_raw": _momentum_return(
                    prices,
                    as_of,
                    formation_months=cfg.pmom_months,
                    skip_months=cfg.skip_months,
                ),
            }
        )
    out = panel.copy()
    raw = pd.DataFrame(rows).set_index("_idx")
    for col in raw.columns:
        out[col] = raw[col]
    for pillar in ("val", "qual", "fmom", "pmom"):
        out[f"pillar_{pillar}"] = _neutralized_z(out, f"pillar_{pillar}_raw", config=cfg)
    return out
