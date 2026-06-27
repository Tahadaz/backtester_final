from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Callable

import pandas as pd
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.quant_core.fundamentals.valuation import DEFAULT_ASSUMPTIONS

from .. import models
from ..market_data_loader import load_ohlcv_for_symbol


DEFAULT_TREASURY_CURVE = {"1Y": 0.030, "5Y": 0.033, "10Y": 0.035}
DEFAULT_MACRO_CONFIG = {
    "scope_key": "GLOBAL",
    "version_label": "base",
    "risk_free_mode": "tenor",
    "treasury_tenor": "10Y",
    "treasury_curve_json": DEFAULT_TREASURY_CURVE,
    "manual_risk_free_rate": None,
    "erp_mode": "manual",
    "erp_index_symbol": "MASI",
    "erp_index_asset_class": "index",
    "erp_lookback_years": 10.0,
    "erp_mean_method": "geometric",
    "manual_equity_risk_premium": DEFAULT_ASSUMPTIONS["equity_risk_premium"],
    "country_risk_mode": "auto",
    "morocco_country_risk_premium": DEFAULT_ASSUMPTIONS["country_risk_premium"],
    "manual_country_risk_premium": None,
    "source": "structural_default",
}
MOROCCO_INDEX_SYMBOLS = {"MASI", "MASI_20", "MASI20", "MASI20_FLOAT"}


CloseSeriesLoader = Callable[[Session, str, str], pd.Series | pd.DataFrame]


@dataclass(frozen=True)
class ResolvedMacroConfig:
    risk_free_rate: float
    equity_risk_premium: float
    country_risk_premium: float
    inputs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def assumption_updates(self) -> dict[str, float]:
        return {
            "risk_free_rate": self.risk_free_rate,
            "equity_risk_premium": self.equity_risk_premium,
            "country_risk_premium": self.country_risk_premium,
        }

    def to_build_up_inputs(self) -> dict[str, Any]:
        return {
            "macro_config": {
                **self.inputs,
                "risk_free_rate": self.risk_free_rate,
                "equity_risk_premium": self.equity_risk_premium,
                "country_risk_premium": self.country_risk_premium,
                "warnings": list(self.warnings),
            }
        }


def _finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _table_exists(db: Session, model: Any) -> bool:
    try:
        return bool(sa_inspect(db.connection()).has_table(model.__tablename__))
    except SQLAlchemyError:
        db.rollback()
        return False


def _active_row(db: Session) -> models.FundamentalMacroConfig | None:
    if not _table_exists(db, models.FundamentalMacroConfig):
        return None
    try:
        return (
            db.query(models.FundamentalMacroConfig)
            .filter(
                models.FundamentalMacroConfig.scope_key == "GLOBAL",
                models.FundamentalMacroConfig.is_active.is_(True),
            )
            .order_by(
                models.FundamentalMacroConfig.updated_at.desc().nullslast(),
                models.FundamentalMacroConfig.created_at.desc(),
                models.FundamentalMacroConfig.id.desc(),
            )
            .first()
        )
    except SQLAlchemyError:
        db.rollback()
        return None


def _config_value(row: models.FundamentalMacroConfig | None, key: str) -> Any:
    if row is None:
        return DEFAULT_MACRO_CONFIG[key]
    return getattr(row, key, DEFAULT_MACRO_CONFIG.get(key))


def _config_dict(row: models.FundamentalMacroConfig | None) -> dict[str, Any]:
    return {key: _config_value(row, key) for key in DEFAULT_MACRO_CONFIG}


def _normalize_close(data: pd.Series | pd.DataFrame) -> pd.Series:
    if isinstance(data, pd.DataFrame):
        close_col = "Close" if "Close" in data.columns else "close" if "close" in data.columns else None
        if close_col is None:
            raise ValueError("index frame is missing Close column")
        series = data[close_col]
    else:
        series = data
    close = pd.to_numeric(series, errors="coerce").where(lambda item: item > 0).dropna()
    close = close.sort_index()
    close = close[~close.index.duplicated(keep="last")]
    if close.empty:
        raise ValueError("index close series is empty")
    return close


def geometric_mean_annual_return(close: pd.Series | pd.DataFrame, *, lookback_years: float) -> float:
    series = _normalize_close(close)
    lookback = max(0.25, float(lookback_years or 10.0))
    last_ts = pd.Timestamp(series.index.max())
    cutoff = last_ts - pd.DateOffset(days=int(round(lookback * 365.25)))
    window = series.loc[series.index >= cutoff]
    if len(window) < 2:
        window = series
    if len(window) < 2:
        raise ValueError("need at least two index prices for geometric return")
    start = float(window.iloc[0])
    end = float(window.iloc[-1])
    if start <= 0.0 or end <= 0.0:
        raise ValueError("index prices must be positive")
    first_ts = pd.Timestamp(window.index.min())
    years = max((last_ts - first_ts).days / 365.25, 1.0 / 365.25)
    return (end / start) ** (1.0 / years) - 1.0


def _load_index_close(db: Session, symbol: str, asset_class: str) -> pd.Series:
    # market_data_store is already keyed by canonical symbol; asset_class is
    # retained in the macro config for CRP coupling and UI display.
    frame = load_ohlcv_for_symbol(db, symbol, "1D")
    return _normalize_close(frame)


def _is_morocco_index(db: Session, symbol: str, asset_class: str) -> bool:
    normalized = str(symbol or "").strip().upper()
    if normalized in MOROCCO_INDEX_SYMBOLS or normalized.startswith("MASI"):
        return True
    if str(asset_class or "").strip().lower() != "index":
        return False
    if not _table_exists(db, models.IndexMaster):
        return False
    try:
        row = db.query(models.IndexMaster).filter(models.IndexMaster.symbol == normalized).first()
    except SQLAlchemyError:
        db.rollback()
        return False
    return str(getattr(row, "market_region", "") or "").strip().lower() == "masi"


def resolve_macro_config(
    db: Session,
    *,
    close_loader: CloseSeriesLoader | None = None,
    as_of: dt.date | None = None,
) -> ResolvedMacroConfig:
    row = _active_row(db)
    config = _config_dict(row)
    warnings: list[str] = []

    curve = config.get("treasury_curve_json") if isinstance(config.get("treasury_curve_json"), dict) else {}
    curve = {str(key).upper(): value for key, value in {**DEFAULT_TREASURY_CURVE, **curve}.items()}
    tenor = str(config.get("treasury_tenor") or "10Y").strip().upper()
    risk_free_mode = str(config.get("risk_free_mode") or "tenor").strip().lower()
    manual_rf = _finite_float(config.get("manual_risk_free_rate"))
    if risk_free_mode == "manual" and manual_rf is not None:
        risk_free = manual_rf
        risk_free_source = "manual"
    else:
        risk_free = _finite_float(curve.get(tenor)) or DEFAULT_TREASURY_CURVE["10Y"]
        risk_free_source = f"treasury_curve:{tenor}"

    erp_mode = str(config.get("erp_mode") or "manual").strip().lower()
    index_symbol = str(config.get("erp_index_symbol") or "MASI").strip().upper()
    index_asset_class = str(config.get("erp_index_asset_class") or "index").strip().lower()
    lookback_years = _finite_float(config.get("erp_lookback_years")) or 10.0
    expected_index_return: float | None = None
    manual_erp = _finite_float(config.get("manual_equity_risk_premium"))
    if erp_mode == "index":
        loader = close_loader or (lambda session, symbol, asset_class: _load_index_close(session, symbol, asset_class))
        try:
            index_close = loader(db, index_symbol, index_asset_class)
            if as_of is not None:
                series = _normalize_close(index_close)
                index_close = series.loc[series.index <= pd.Timestamp(as_of)]
            expected_index_return = geometric_mean_annual_return(index_close, lookback_years=lookback_years)
            equity_risk_premium = expected_index_return - risk_free
            erp_source = f"index:{index_symbol}:geometric_{lookback_years:g}y"
        except Exception as exc:
            equity_risk_premium = manual_erp if manual_erp is not None else DEFAULT_ASSUMPTIONS["equity_risk_premium"]
            erp_source = "manual_fallback" if manual_erp is not None else "default_fallback"
            warnings.append(f"erp_index_return_unavailable:{type(exc).__name__}")
    else:
        equity_risk_premium = manual_erp if manual_erp is not None else DEFAULT_ASSUMPTIONS["equity_risk_premium"]
        erp_source = "manual"

    country_risk_mode = str(config.get("country_risk_mode") or "auto").strip().lower()
    manual_crp = _finite_float(config.get("manual_country_risk_premium"))
    if country_risk_mode == "manual" and manual_crp is not None:
        country_risk_premium = manual_crp
        crp_source = "manual"
    else:
        is_morocco = _is_morocco_index(db, index_symbol, index_asset_class)
        country_risk_premium = 0.0 if is_morocco else (_finite_float(config.get("morocco_country_risk_premium")) or 0.0)
        crp_source = "auto:masi_embedded" if is_morocco else "auto:morocco_crp_for_global_index"

    inputs = {
        "scope_key": config.get("scope_key") or "GLOBAL",
        "version_label": config.get("version_label") or "base",
        "source": config.get("source") or ("db" if row is not None else "structural_default"),
        "risk_free_mode": risk_free_mode,
        "risk_free_source": risk_free_source,
        "treasury_tenor": tenor,
        "treasury_curve": curve,
        "erp_mode": erp_mode,
        "erp_source": erp_source,
        "erp_index_symbol": index_symbol,
        "erp_index_asset_class": index_asset_class,
        "erp_lookback_years": lookback_years,
        "erp_mean_method": config.get("erp_mean_method") or "geometric",
        "expected_index_return": expected_index_return,
        "country_risk_mode": country_risk_mode,
        "country_risk_source": crp_source,
    }
    return ResolvedMacroConfig(
        risk_free_rate=float(risk_free),
        equity_risk_premium=float(equity_risk_premium),
        country_risk_premium=float(country_risk_premium),
        inputs=inputs,
        warnings=warnings,
    )
