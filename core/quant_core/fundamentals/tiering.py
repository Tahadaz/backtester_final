"""Fundamental tiering: bridge between the fundamentals layer and the strategy/
technical layer (brief 57).

Design rationale (see docs/fundamentals-layer/55-perfect-foresight-ic-study.md):
fundamentals on MASI carry no reliable 12-month return-predictive IC, so they
must not be used as a timing signal. Their role here is narrower and more
durable: decide WHAT is ownable and at what conviction, while the technical
signal engine keeps deciding WHEN. `compute_fundamental_tier` is a pure,
DB-free function that turns pillar scores + accounting-quality diagnostics +
the triangulated valuation band (see triangulation.py) into one of five
conviction/risk-budget tiers.

This is deliberately a *soft* tiering, never a hard trade veto — a desk that
gets told "never buy X" will route around the system; a desk that gets told
"X is in the avoid tier because data is unverified and two independent
accounting red flags fired" can make an informed override. Every tier
decision therefore carries machine-readable `reasons`.

Thresholds are calibrated against the live MASI universe (72 active equities,
2026-07-02 snapshot; see docs/fundamentals-layer/57-fundamental-tiering.md
for the full distribution dump) rather than assumed — pillar scores and the
`screens.altman_z`/`piotroski_lite`/`accrual_quality` diagnostics are all on
a 0-100 scale (cross-sectional percentile or an explicitly 0-100-normalized
screen score), never a 0-1 ratio.

Pure and DB-free: the service layer (fundamental_tiers.py) loads snapshot
rows, ensemble warnings, and the triangulation result; this module only
classifies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from core.quant_core.fundamentals.triangulation import (
    TriangulationResult,
    VERDICT_BELOW,
    VERDICT_LOWER,
)

# --- Tier enum (string constants; ordered highest to lowest conviction) ----

TIER_QUALITY_UNDERVALUED = "quality_undervalued"
TIER_QUALITY = "quality"
TIER_NEUTRAL = "neutral"
TIER_CAUTION = "caution"
TIER_AVOID = "avoid"

TIER_ORDER: tuple[str, ...] = (
    TIER_QUALITY_UNDERVALUED,
    TIER_QUALITY,
    TIER_NEUTRAL,
    TIER_CAUTION,
    TIER_AVOID,
)

# --- Thresholds (all on the 0-100 scale scoring.py / screens.py emit) ------
#
# Verified empirically against the live DB (72 active MASI equities,
# `fundamental_latest_snapshot.scores_json` / `diagnostics_json`, canonical
# snapshots, 2026-07-02) — see docs/fundamentals-layer/57-fundamental-tiering.md
# for the full percentile dump this file's constants were read off.

# scores.quality (adjusted quality: mean of raw percentile, accounting
# discipline, accrual quality) distribution: min=18.3 p25=47.1 median=63.5
# p75=74.4 p90=80.7 max=96.8 (n=71). 70.0 is a round top-quartile-ish cutoff,
# just under the empirical p75.
QUALITY_UPPER_BAND_MIN = 70.0

# scores.health (Current_Ratio/Cash_Ratio/Interest_Coverage percentile)
# distribution: min=0.0 p25=30.6 median=47.3 p75=76.2 p90=88.9 max=100.0
# (n=42 of 71 scored symbols — health is frequently unscored, including for
# all four smoke symbols IAM/ATW/LES/AFM). 70.0 mirrors the quality cutoff
# and sits just under the empirical p75.
HEALTH_UPPER_BAND_MIN = 70.0

# scores.health distribution p25=30.6 (n=42). A health pillar in the bottom
# quartile is a genuine liquidity/coverage weakness (Current_Ratio,
# Cash_Ratio, Interest_Coverage all trail peers), not noise from a thin
# cohort — cohorts under 3 already return None upstream (scoring.py).
HEALTH_WEAK_MAX = 30.0

# diagnostics.piotroski_lite.score (100 x passed/available of 9 trend
# checks) distribution: min=12.5 p10=40.0 p25=57.1 median=62.5 p75=75.0
# p90=87.5 max=100.0 (n=71). p10 is used verbatim as the bottom-band cutoff:
# only the worst decile of accounting-quality trend scores counts as a red
# flag, not merely "below average".
PIOTROSKI_BOTTOM_BAND_MAX = 40.0

# diagnostics.accrual_quality.score (50 + 35 x cash_conversion, clipped to
# [0,100]; 50 = cash_conversion 0, i.e. break-even) distribution: min=0.0
# p10=0.0 p25=48.6 median=72.3 p75=95.6 p90=100.0 (n=66) — heavily
# left-skewed with a mass of symbols pinned at the 0 floor. 40.0 sits
# between p10 and p25 and corresponds to cash_conversion <= -0.29, i.e. net
# income has meaningfully and persistently exceeded free cash flow — a real
# earnings-quality flag, not sampling noise.
ACCRUAL_POOR_MAX = 40.0

# diagnostics.screens.altman_z.zone in {"safe","grey","distress"} (or None
# when not applicable — financials are excluded from Altman Z entirely, see
# screens.py:altman_not_applicable_financials, and both AFM and ATW score
# None for this reason). "grey" is already a distress *watch list* per
# 16-institutional-screens.md, so it is treated as a caution-level red flag
# alongside "distress"; only "distress" alone, when paired with a second
# independent red flag, escalates to avoid (see below).
ALTMAN_CAUTION_ZONES = frozenset({"distress", "grey"})
ALTMAN_DISTRESS_ZONE = "distress"

# Triangulation agreement gate for quality_undervalued, per brief 57 spec.
TRIANGULATION_AGREEMENT_MIN = 0.6

_UNDERVALUED_VERDICTS = frozenset({VERDICT_BELOW, VERDICT_LOWER})


@dataclass(frozen=True)
class FundamentalTier:
    tier: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    inputs_used: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "reasons": list(self.reasons),
            "inputs_used": dict(self.inputs_used),
        }


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # filter NaN


def _quality(scores: Mapping[str, Any]) -> float | None:
    return _num(scores.get("quality"))


def _health(scores: Mapping[str, Any]) -> float | None:
    return _num(scores.get("health"))


def _piotroski_score(diagnostics: Mapping[str, Any]) -> float | None:
    block = diagnostics.get("piotroski_lite")
    if not isinstance(block, Mapping):
        return None
    return _num(block.get("score"))


def _accrual_score(diagnostics: Mapping[str, Any]) -> float | None:
    block = diagnostics.get("accrual_quality")
    if not isinstance(block, Mapping):
        return None
    return _num(block.get("score"))


def _altman_zone(diagnostics: Mapping[str, Any]) -> str | None:
    screens = diagnostics.get("screens")
    if not isinstance(screens, Mapping):
        return None
    altman = screens.get("altman_z")
    if not isinstance(altman, Mapping):
        return None
    zone = altman.get("zone")
    return str(zone) if zone else None


def compute_fundamental_tier(
    scores: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    triangulation: TriangulationResult | None,
    data_unverified: bool,
) -> FundamentalTier:
    """Classify one symbol into a soft conviction/risk-budget tier.

    Absence of evidence (missing pillar scores, unscored Altman Z for
    financials, no triangulation band) degrades the result toward `neutral`,
    never toward `avoid` — the sole exception is `data_unverified`, which is
    itself evidence of a data problem, not an absence of it.
    """
    quality = _quality(scores)
    health = _health(scores)
    piotroski = _piotroski_score(diagnostics)
    accrual = _accrual_score(diagnostics)
    altman_zone = _altman_zone(diagnostics)

    verdict = triangulation.verdict if triangulation is not None else None
    agreement = triangulation.agreement if triangulation is not None else None

    inputs_used: dict[str, Any] = {
        "quality": quality,
        "health": health,
        "piotroski_lite_score": piotroski,
        "accrual_quality_score": accrual,
        "altman_zone": altman_zone,
        "triangulation_verdict": verdict,
        "triangulation_agreement": agreement,
        "data_unverified": bool(data_unverified),
    }

    # --- avoid: data_unverified is itself decisive -------------------------
    if data_unverified:
        return FundamentalTier(tier=TIER_AVOID, reasons=("data_unverified",), inputs_used=inputs_used)

    # --- avoid: the one named multi-red-flag combo from the brief ----------
    # (Altman distress zone AND Piotroski bottom band) — two independent
    # accounting-quality probes agreeing the name is structurally weak.
    altman_distress = altman_zone == ALTMAN_DISTRESS_ZONE
    piotroski_bottom = piotroski is not None and piotroski < PIOTROSKI_BOTTOM_BAND_MAX
    if altman_distress and piotroski_bottom:
        return FundamentalTier(
            tier=TIER_AVOID,
            reasons=("altman_zone_distress", "piotroski_bottom_band"),
            inputs_used=inputs_used,
        )

    # --- caution: any single independent red flag ---------------------------
    health_weak = health is not None and health < HEALTH_WEAK_MAX
    altman_flag = altman_zone in ALTMAN_CAUTION_ZONES
    accrual_poor = accrual is not None and accrual < ACCRUAL_POOR_MAX

    caution_reasons: list[str] = []
    if health_weak:
        caution_reasons.append("health_pillar_weak")
    if altman_flag:
        caution_reasons.append(f"altman_zone_{altman_zone}")
    if piotroski_bottom:
        caution_reasons.append("piotroski_bottom_band")
    if accrual_poor:
        caution_reasons.append("accrual_quality_poor")

    if caution_reasons:
        return FundamentalTier(tier=TIER_CAUTION, reasons=tuple(caution_reasons), inputs_used=inputs_used)

    # --- quality / quality_undervalued: zero red flags, strong pillars -----
    quality_upper = quality is not None and quality >= QUALITY_UPPER_BAND_MIN
    health_upper = health is not None and health >= HEALTH_UPPER_BAND_MIN

    if quality_upper and health_upper:
        undervalued = (
            verdict in _UNDERVALUED_VERDICTS
            and agreement is not None
            and agreement >= TRIANGULATION_AGREEMENT_MIN
        )
        if undervalued:
            return FundamentalTier(
                tier=TIER_QUALITY_UNDERVALUED,
                reasons=(
                    "quality_pillar_upper_band",
                    "health_pillar_upper_band",
                    f"triangulation_{verdict}",
                    "triangulation_agreement_high",
                ),
                inputs_used=inputs_used,
            )
        band_reason = (
            f"triangulation_{verdict}" if verdict is not None else "triangulation_band_unavailable"
        )
        return FundamentalTier(
            tier=TIER_QUALITY,
            reasons=("quality_pillar_upper_band", "health_pillar_upper_band", band_reason),
            inputs_used=inputs_used,
        )

    # --- neutral: everything else, including missing scores ----------------
    neutral_reasons: list[str] = []
    if quality is None:
        neutral_reasons.append("quality_score_missing")
    elif not quality_upper:
        neutral_reasons.append("quality_pillar_below_upper_band")
    if health is None:
        neutral_reasons.append("health_score_missing")
    elif not health_upper:
        neutral_reasons.append("health_pillar_below_upper_band")
    if not neutral_reasons:
        neutral_reasons.append("no_qualifying_signal")

    return FundamentalTier(tier=TIER_NEUTRAL, reasons=tuple(neutral_reasons), inputs_used=inputs_used)
