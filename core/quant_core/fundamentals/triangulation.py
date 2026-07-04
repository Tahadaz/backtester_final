"""Triangulated fair-value reference band (brief 48 off-ramp).

Publishes the headline valuation as a *reference band* built from independent
anchor classes instead of a single blended fair value:

  - intrinsic  median of usable intrinsic-class model values
               (fcff_dcf, fcfe_dcf, ddm, residual_income)
  - market     median of usable market-class model values
               (justified_multiples, relative_multiples)
  - broker     external consensus target price (e.g. BKGR), when available

Rationale: the PIT IC backtest found no valuation model with reliable
12-month predictive IC on MASI, so the IC-weighted ensemble collapses onto
relative_multiples for most names. Rather than presenting that collapse as a
point forecast, the band states where price sits relative to anchors that
answer different questions (what the models say / what the market pays for
peers / what the street believes). Position in the band plus the quality
verdict drives the recommendation — the band itself is a reference, not a
return prediction.

Pure and DB-free: callers (service layer) load model rows and the broker
target, this module only arranges them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median, pstdev
from typing import Any, Iterable, Mapping

from core.quant_core.fundamentals.valuation import (
    ENSEMBLE_INTRINSIC_METHOD_MODELS,
    ENSEMBLE_MARKET_METHOD_MODELS,
)

INTRINSIC_FAMILY = "intrinsic"
MARKET_FAMILY = "market"
DIAGNOSTIC_FAMILY = "diagnostic"

# Persisted `family` values drifted across vintages ("valuation", "intrinsic",
# "relative"), so classification keys on the model name via the engine's
# canonical method classes; family is only a fallback for unknown models.
_DIAGNOSTIC_MODELS = {"reverse_dcf"}
_FAMILY_FALLBACK = {
    "relative": MARKET_FAMILY,
    "market": MARKET_FAMILY,
    "intrinsic": INTRINSIC_FAMILY,
    "valuation": INTRINSIC_FAMILY,
    "diagnostic": DIAGNOSTIC_FAMILY,
}


def _model_class(model: str, family: str) -> str | None:
    if model in _DIAGNOSTIC_MODELS:
        return DIAGNOSTIC_FAMILY
    if model in ENSEMBLE_MARKET_METHOD_MODELS:
        return MARKET_FAMILY
    if model in ENSEMBLE_INTRINSIC_METHOD_MODELS:
        return INTRINSIC_FAMILY
    return _FAMILY_FALLBACK.get(family)

ANCHOR_INTRINSIC = "intrinsic_median"
ANCHOR_MARKET = "market_median"
ANCHOR_BROKER = "broker_target"

VERDICT_BELOW = "below_band"
VERDICT_LOWER = "in_band_lower"
VERDICT_UPPER = "in_band_upper"
VERDICT_ABOVE = "above_band"
VERDICT_INSUFFICIENT = "insufficient_anchors"
VERDICT_NO_PRICE = "no_price"


@dataclass(frozen=True)
class AnchorValue:
    """One triangulation anchor: a class-level value, not a model value."""

    name: str
    kind: str
    value: float
    n_models: int
    models: tuple[str, ...] = ()


@dataclass(frozen=True)
class TriangulationResult:
    current_price: float | None
    anchors: tuple[AnchorValue, ...]
    band_low: float | None
    band_mid: float | None
    band_high: float | None
    price_position: float | None
    verdict: str
    agreement: float | None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_price": self.current_price,
            "anchors": [
                {
                    "name": a.name,
                    "kind": a.kind,
                    "value": a.value,
                    "n_models": a.n_models,
                    "models": list(a.models),
                }
                for a in self.anchors
            ],
            "band_low": self.band_low,
            "band_mid": self.band_mid,
            "band_high": self.band_high,
            "price_position": self.price_position,
            "verdict": self.verdict,
            "agreement": self.agreement,
            "warnings": list(self.warnings),
        }


def _positive(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def _class_anchor(
    name: str,
    kind: str,
    rows: list[tuple[str, float]],
) -> AnchorValue | None:
    if not rows:
        return None
    values = [value for _model, value in rows]
    return AnchorValue(
        name=name,
        kind=kind,
        value=float(median(values)),
        n_models=len(rows),
        models=tuple(model for model, _value in rows),
    )


def compute_triangulation(
    model_values: Iterable[Mapping[str, Any]],
    current_price: float | None,
    *,
    broker_target: float | None = None,
    min_anchors: int = 2,
) -> TriangulationResult:
    """Build the triangulated reference band.

    Parameters
    ----------
    model_values:
        Mappings with at least ``model``, ``family``, ``fair_value``. Rows with
        missing/non-positive fair values or ``family == "diagnostic"`` are
        ignored (reverse DCF answers a different question).
    current_price:
        Latest price; band verdict is relative to it.
    broker_target:
        External consensus target price (already currency-consistent).
    min_anchors:
        Minimum distinct anchors required to publish a band.
    """
    warnings: list[str] = []
    intrinsic_rows: list[tuple[str, float]] = []
    market_rows: list[tuple[str, float]] = []
    for row in model_values:
        value = _positive(row.get("fair_value"))
        if value is None:
            continue
        model = str(row.get("model") or "unknown")
        klass = _model_class(model, str(row.get("family") or ""))
        if klass == INTRINSIC_FAMILY:
            intrinsic_rows.append((model, value))
        elif klass == MARKET_FAMILY:
            market_rows.append((model, value))

    anchors: list[AnchorValue] = []
    intrinsic = _class_anchor(ANCHOR_INTRINSIC, INTRINSIC_FAMILY, intrinsic_rows)
    if intrinsic is not None:
        anchors.append(intrinsic)
        if intrinsic.n_models == 1:
            warnings.append("single_model_intrinsic_anchor")
    else:
        warnings.append("no_intrinsic_anchor")

    # No single-model warning for the market anchor: the market method class
    # contains exactly one model (relative_multiples) by construction.
    market = _class_anchor(ANCHOR_MARKET, MARKET_FAMILY, market_rows)
    if market is not None:
        anchors.append(market)
    else:
        warnings.append("no_market_anchor")

    broker = _positive(broker_target)
    if broker is not None:
        anchors.append(AnchorValue(name=ANCHOR_BROKER, kind="broker", value=broker, n_models=0))
    else:
        warnings.append("no_broker_anchor")

    price = _positive(current_price)

    if len(anchors) < min_anchors:
        return TriangulationResult(
            current_price=price,
            anchors=tuple(anchors),
            band_low=None,
            band_mid=None,
            band_high=None,
            price_position=None,
            verdict=VERDICT_INSUFFICIENT,
            agreement=None,
            warnings=tuple(warnings),
        )

    values = [a.value for a in anchors]
    band_low = min(values)
    band_high = max(values)
    band_mid = float(median(values))

    # Anchor agreement: 1 - coefficient of variation across anchors, floored at 0.
    # Population stdev is deliberate — the anchors are the whole population here.
    mean_value = sum(values) / len(values)
    agreement = max(0.0, 1.0 - (pstdev(values) / mean_value)) if mean_value > 0 else None

    if price is None:
        verdict = VERDICT_NO_PRICE
        position = None
    elif price < band_low:
        verdict = VERDICT_BELOW
        position = 0.0
    elif price > band_high:
        verdict = VERDICT_ABOVE
        position = 1.0
    else:
        width = band_high - band_low
        position = (price - band_low) / width if width > 0 else 0.5
        verdict = VERDICT_LOWER if position <= 0.5 else VERDICT_UPPER

    return TriangulationResult(
        current_price=price,
        anchors=tuple(anchors),
        band_low=band_low,
        band_mid=band_mid,
        band_high=band_high,
        price_position=position,
        verdict=verdict,
        agreement=agreement,
        warnings=tuple(warnings),
    )
