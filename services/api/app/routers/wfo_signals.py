"""WFO signal layer API endpoints.

GET  /strategy/wfo/summary  — return cached WFO results for symbol × horizon
GET  /strategy/wfo/detail   — return detailed WFO results for one category
GET  /strategy/wfo/config   — return static WFO configuration (horizons, families, scoring)
POST /strategy/wfo/trigger  — enqueue on-demand WFO computation
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.quant_core.signal_engine.modes import (
    ALL_SIGNAL_MODE_NAMES,
    resolve_signal_mode,
    signal_mode_read_names,
    signal_mode_storage_name,
)

from ..auth import rate_limit_trigger, require_admin
from ..db import get_db
from ..models import WfoGlobalSignal, WfoSignalSummary
from ..services.market_universe import list_signal_universe_symbols

router = APIRouter(prefix="/strategy/wfo", tags=["wfo-signals"])

CanonicalHorizon = Literal["weekly", "monthly", "quarterly"]


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class WfoRepresentativeOut(BaseModel):
    family: str
    archetype: str
    variant_id: str
    params: dict[str, Any]
    signal: float
    signal_label: str
    normalized_weight: float
    contribution: float
    description: str
    current_close: float | None = None
    indicator_value: float | None = None
    explanation: str = ""
    wfo_prom: float | None = None


class WfoCategorySummaryOut(BaseModel):
    category: str
    status: str
    score_pct: float | None = None
    signal_label: str | None = None
    representatives: list[WfoRepresentativeOut] = []
    wfe_pct: float | None = None
    robustness_ratio: float | None = None
    total_folds: int | None = None
    profitable_folds: int | None = None
    mean_oos_sharpe: float | None = None
    total_oos_pnl: float | None = None
    worst_fold_drawdown: float | None = None
    composite_score: float | None = None
    robustness_grade: str | None = None
    computed_at: str | None = None
    data_as_of: date | None = None
    compute_seconds: float | None = None
    config: dict[str, Any] | None = None


class WfoCategoryDetailOut(WfoCategorySummaryOut):
    """Extended schema with fold-by-fold details for drill-down."""
    folds: list[dict[str, Any]] | None = None
    config: dict[str, Any] | None = None
    fragility: dict[str, Any] | None = None
    error_message: str | None = None


class WfoGlobalSignalOut(BaseModel):
    status: str
    global_score_pct: float | None = None
    raw_score_pct: float | None = None
    signal_label: str | None = None
    recommendation: str | None = None
    weight_tendance: float | None = None
    weight_momentum: float | None = None
    weight_oscillation: float | None = None
    weight_volume: float | None = None
    sr_modifier: float | None = None
    sr_support_level: float | None = None
    sr_resistance_level: float | None = None
    sr_support_method: str | None = None
    sr_resistance_method: str | None = None
    best_category: str | None = None
    best_category_score: float | None = None
    categories_viable: int | None = None
    consensus_wfe_pct: float | None = None
    consensus_robustness: float | None = None
    computed_at: str | None = None
    data_as_of: date | None = None


class WfoSummaryResponse(BaseModel):
    symbol: str
    horizon: str
    categories: dict[str, WfoCategorySummaryOut]
    global_signal: WfoGlobalSignalOut | None = None


class WfoTriggerRequest(BaseModel):
    symbol: str
    horizon: CanonicalHorizon
    variant: str = "expanded"
    categories: list[str] | None = None    # None = all 4
    # Optional parameter overrides (None = use defaults)
    train_bars: int | None = None
    oos_bars: int | None = None
    step_bars: int | None = None
    window_policy: str | None = None
    top_k_folds: int | None = None
    min_walk_forwards: int | None = None
    strict_fallback_enabled: bool | None = None
    strict_fallback_floor: int | None = None
    cost_bps: float | None = None
    max_reps: int | None = None
    max_corr: float | None = None


class WfoTriggerResponse(BaseModel):
    triggered: list[str]
    job_id: str | None = None


class WfoTriggerAllRequest(BaseModel):
    variants: list[str] = list(ALL_SIGNAL_MODE_NAMES)
    train_bars: int | None = None
    oos_bars: int | None = None
    step_bars: int | None = None
    window_policy: str | None = None
    top_k_folds: int | None = None
    min_walk_forwards: int | None = None
    strict_fallback_enabled: bool | None = None
    strict_fallback_floor: int | None = None
    cost_bps: float | None = None
    max_reps: int | None = None
    max_corr: float | None = None


class WfoTriggerAllResponse(BaseModel):
    total_jobs: int
    symbols: int
    horizons: list[str]
    variants: list[str]


class WfoBatchStatusResponse(BaseModel):
    total: int
    succeeded: int
    running: int
    failed: int
    pending: int
    insufficient_data: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_summary(row: WfoSignalSummary) -> WfoCategorySummaryOut:
    """Map a WfoSignalSummary row to the summary output schema."""
    rep_data = row.representatives_json or []
    representatives = []
    for r in rep_data:
        try:
            representatives.append(WfoRepresentativeOut(**r))
        except Exception:
            pass

    return WfoCategorySummaryOut(
        category=row.category,
        status=row.status,
        score_pct=row.score_pct,
        signal_label=row.signal_label,
        representatives=representatives,
        wfe_pct=row.wfe_pct,
        robustness_ratio=row.robustness_ratio,
        total_folds=row.total_folds,
        profitable_folds=row.profitable_folds,
        mean_oos_sharpe=row.mean_oos_sharpe,
        total_oos_pnl=row.total_oos_pnl,
        worst_fold_drawdown=row.worst_fold_drawdown,
        composite_score=row.composite_score,
        robustness_grade=row.robustness_grade,
        computed_at=str(row.computed_at) if row.computed_at else None,
        data_as_of=row.data_as_of,
        compute_seconds=row.compute_seconds,
        config=row.config_json,
    )


def _row_to_detail(row: WfoSignalSummary) -> WfoCategoryDetailOut:
    """Map a WfoSignalSummary row to the detail output schema (with folds)."""
    rep_data = row.representatives_json or []
    representatives = []
    for r in rep_data:
        try:
            representatives.append(WfoRepresentativeOut(**r))
        except Exception:
            pass

    return WfoCategoryDetailOut(
        category=row.category,
        status=row.status,
        score_pct=row.score_pct,
        signal_label=row.signal_label,
        representatives=representatives,
        wfe_pct=row.wfe_pct,
        robustness_ratio=row.robustness_ratio,
        total_folds=row.total_folds,
        profitable_folds=row.profitable_folds,
        mean_oos_sharpe=row.mean_oos_sharpe,
        total_oos_pnl=row.total_oos_pnl,
        worst_fold_drawdown=row.worst_fold_drawdown,
        composite_score=row.composite_score,
        robustness_grade=row.robustness_grade,
        computed_at=str(row.computed_at) if row.computed_at else None,
        data_as_of=row.data_as_of,
        compute_seconds=row.compute_seconds,
        folds=row.folds_json,
        config=row.config_json,
        fragility=row.fragility_json,
        error_message=row.error_message,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=WfoSummaryResponse)
def get_wfo_summary(
    symbol: str = Query(...),
    horizon: CanonicalHorizon = Query(...),
    variant: str = Query("expanded"),
    db: Session = Depends(get_db),
) -> WfoSummaryResponse:
    """Return cached WFO signal results for a symbol × horizon × variant.

    Fast DB read — no computation. Returns whatever is stored,
    including "pending" placeholders for categories not yet computed.
    """
    variant = signal_mode_storage_name(variant)
    read_variants = signal_mode_read_names(variant)
    rows = []
    for read_variant in read_variants:
        rows.extend(
            db.query(WfoSignalSummary)
            .filter_by(symbol=symbol, horizon=horizon, variant=read_variant)
            .all()
        )

    categories: dict[str, WfoCategorySummaryOut] = {}
    for row in rows:
        if row.category not in categories:
            categories[row.category] = _row_to_summary(row)

    # Ensure all 5 categories are present (pending placeholders for missing ones)
    for cat in ("tendance", "momentum", "oscillation", "volume", "support_resistance"):
        if cat not in categories:
            categories[cat] = WfoCategorySummaryOut(category=cat, status="pending")

    # Global signal
    global_row = None
    for read_variant in read_variants:
        global_row = (
            db.query(WfoGlobalSignal)
            .filter_by(symbol=symbol, horizon=horizon, variant=read_variant)
            .first()
        )
        if global_row is not None:
            break
    global_out = None
    if global_row:
        global_out = WfoGlobalSignalOut(
            status=global_row.status,
            global_score_pct=global_row.global_score_pct,
            raw_score_pct=global_row.raw_score_pct,
            signal_label=global_row.signal_label,
            recommendation=global_row.recommendation,
            weight_tendance=global_row.weight_tendance,
            weight_momentum=global_row.weight_momentum,
            weight_oscillation=global_row.weight_oscillation,
            weight_volume=global_row.weight_volume,
            sr_modifier=global_row.sr_modifier,
            sr_support_level=global_row.sr_support_level,
            sr_resistance_level=global_row.sr_resistance_level,
            sr_support_method=global_row.sr_support_method,
            sr_resistance_method=global_row.sr_resistance_method,
            best_category=global_row.best_category,
            best_category_score=global_row.best_category_score,
            categories_viable=global_row.categories_viable,
            consensus_wfe_pct=global_row.consensus_wfe_pct,
            consensus_robustness=global_row.consensus_robustness,
            computed_at=str(global_row.computed_at) if global_row.computed_at else None,
            data_as_of=global_row.data_as_of,
        )

    return WfoSummaryResponse(
        symbol=symbol,
        horizon=horizon,
        categories=categories,
        global_signal=global_out,
    )


@router.get("/detail", response_model=WfoCategoryDetailOut)
def get_wfo_detail(
    symbol: str = Query(...),
    horizon: CanonicalHorizon = Query(...),
    category: str = Query(...),
    variant: str = Query("expanded"),
    db: Session = Depends(get_db),
) -> WfoCategoryDetailOut:
    """Return detailed WFO results for one category including fold data."""
    variant = signal_mode_storage_name(variant)
    row = None
    for read_variant in signal_mode_read_names(variant):
        row = (
            db.query(WfoSignalSummary)
            .filter_by(symbol=symbol, horizon=horizon, category=category, variant=read_variant)
            .first()
        )
        if row is not None:
            break
    if row is None:
        raise HTTPException(status_code=404, detail=f"No WFO data for {symbol}/{horizon}/{category}/{variant}")
    return _row_to_detail(row)


@router.get("/config")
def get_wfo_config() -> dict[str, Any]:
    """Return static WFO configuration (horizons, families, scoring, pipeline)."""
    from core.quant_core.signal_engine.domain import (
        CATEGORY_FAMILIES,
        FAMILY_SIGNAL_TYPE,
        HORIZON_PARAMS,
    )
    from core.quant_core.signal_engine.wfo_signal import (
        DEFAULT_MIN_WALK_FORWARDS,
        DEFAULT_STRICT_FALLBACK_ENABLED,
        DEFAULT_STRICT_FALLBACK_FLOOR,
        DEFAULT_TOP_K_FOLDS,
        HORIZON_TRAIN_BANDS,
        STRICT_RATIO_ANCHORS,
        STRICT_WINDOW_POLICY,
    )

    family_descriptions: dict[str, dict[str, str]] = {
        "sma": {"label": "SMA", "archetype": "price_vs_sma", "signal_type": "trend",
                "description": "Prix > SMA(window) — signal haussier quand le prix est au-dessus de la moyenne mobile simple"},
        "ema": {"label": "EMA", "archetype": "price_vs_ema", "signal_type": "trend",
                "description": "Prix > EMA(window) — moyenne mobile exponentielle, plus reactive aux prix recents"},
        "ema_cross": {"label": "EMA Cross", "archetype": "ema_cross", "signal_type": "trend",
                      "description": "EMA(rapide) > EMA(lente) — croisement de moyennes mobiles exponentielles"},
        "ichimoku": {"label": "Ichimoku", "archetype": "ichi_cloud", "signal_type": "trend",
                     "description": "Prix au-dessus du nuage ET Tenkan > Kijun — systeme de tendance multi-composants"},
        "psar": {"label": "Parabolic SAR", "archetype": "psar_trend", "signal_type": "trend",
                 "description": "Prix > SAR — indicateur de retournement parabolique"},
        "macd": {"label": "MACD", "archetype": "macd_cross", "signal_type": "momentum",
                 "description": "MACD > Signal — convergence/divergence de moyennes mobiles"},
        "roc": {"label": "ROC", "archetype": "roc_zero", "signal_type": "momentum",
                "description": "Rate of Change > 0 — taux de variation du prix"},
        "trix": {"label": "TRIX", "archetype": "trix_zero", "signal_type": "momentum",
                 "description": "TRIX > 0 — triple lissage exponentiel du taux de variation"},
        "adx": {"label": "ADX", "archetype": "adx_trend", "signal_type": "momentum",
                "description": "ADX > seuil — mesure de la force de la tendance (directionless)"},
        "tsi": {"label": "TSI", "archetype": "tsi_zero", "signal_type": "momentum",
                "description": "True Strength Index > 0 — momentum double-lisse"},
        "rsi": {"label": "RSI", "archetype": "rsi_level", "signal_type": "oscillator",
                "description": "RSI < survente ou RSI > surachat — oscillateur de force relative"},
        "stochastic": {"label": "Stochastique", "archetype": "stoch_level", "signal_type": "oscillator",
                       "description": "%K < 20 (survente) ou %K > 80 (surachat) — oscillateur stochastique"},
        "cci": {"label": "CCI", "archetype": "cci_level", "signal_type": "oscillator",
                "description": "CCI > seuil — indice de canal de commodites"},
        "mfi": {"label": "MFI", "archetype": "mfi_level", "signal_type": "oscillator",
                "description": "Money Flow Index — RSI pondere par le volume"},
        "uo": {"label": "Ultimate Oscillator", "archetype": "uo_level", "signal_type": "oscillator",
               "description": "Oscillateur ultime multi-periodes"},
        "obv": {"label": "OBV", "archetype": "obv_trend", "signal_type": "volume",
                "description": "OBV EMA > precedent — volume cumule en balance"},
        "cmf": {"label": "CMF", "archetype": "cmf_flow", "signal_type": "volume",
                "description": "Chaikin Money Flow > 0 — flux monetaire sur la periode"},
        "ad": {"label": "A/D Line", "archetype": "ad_trend", "signal_type": "volume",
               "description": "A/D EMA > precedent — ligne d'accumulation/distribution"},
        "vwap": {"label": "VWAP", "archetype": "vwap_dev", "signal_type": "volume",
                 "description": "Deviation du prix par rapport au VWAP"},
        "fi": {"label": "Force Index", "archetype": "fi_trend", "signal_type": "volume",
               "description": "Force Index > 0 — prix × volume directionnel"},
    }

    pipeline_steps = [
        {
            "id": "grid",
            "label": "Construction de la grille",
            "description": "Generation de l'univers de candidats pour chaque famille de la categorie. "
                           "Chaque famille produit des variantes avec differents parametres "
                           "(periodes, seuils) adaptes a l'horizon choisi.",
            "detail": "Pour chaque famille (ex: SMA, EMA, RSI...), on genere ~30 variantes "
                      "couvrant une gamme de parametres. Le nombre total de variantes par categorie "
                      "est typiquement 100-200. Chaque variante definit une strategie simplifiee "
                      "(ex: 'acheter quand Prix > SMA(50), vendre sinon').",
        },
        {
            "id": "wfo",
            "label": "Walk-Forward Analysis",
            "description": "Decoupage des donnees en fenetres train/test successives. "
                           "Pour chaque fenetre, evaluation de toutes les variantes via PROM "
                           "(Profit Risk Objective Measure) sur la partie in-sample.",
            "detail": "Les donnees sont decoupees en fenetres glissantes: chaque fenetre a une "
                      "partie d'entrainement (IS) et une partie de test (OOS). La taille des "
                      "fenetres depend de l'horizon (ex: medium = 504 barres train, 126 barres test). "
                      "Pour chaque fenetre, on calcule le PROM de chaque variante sur la partie IS, "
                      "puis on valide le gagnant sur la partie OOS.",
        },
        {
            "id": "score",
            "label": "Scoring et Grade",
            "description": "Calcul des metriques de robustesse: WFE (Walk-Forward Efficiency), "
                           "ratio de robustesse, score composite, et attribution d'un grade (A-F).",
            "detail": "WFE = rendement OOS annualise / rendement IS annualise. "
                      "Ratio de robustesse = % de fenetres OOS rentables. "
                      "Score composite = 40% WFE + 30% robustesse + 20% Sharpe + 10% drawdown. "
                      "Grade: A (WFE>=0.65 ET rob>=0.75), B (>=0.55 ET >=0.60), "
                      "C (>=0.50 ET >=0.50), D (>=0.40 OU >=0.40), F sinon.",
        },
        {
            "id": "reps",
            "label": "Selection des representants",
            "description": "Choix des meilleures variantes decorrelees pour former l'ensemble "
                           "de representants. Ponderation proportionnelle au PROM lisse.",
            "detail": "On classe toutes les variantes par PROM lisse (derniere fenetre IS). "
                      "On selectionne les top K (defaut 5) en verifiant que la correlation "
                      "de Pearson avec les variantes deja selectionnees reste <= 0.85. "
                      "Les poids sont proportionnels au PROM lisse (plancher a 0.01).",
        },
        {
            "id": "consensus",
            "label": "Consensus global",
            "description": "Agregation des scores des 4 categories en un signal global, "
                           "avec modulation Support/Resistance.",
            "detail": "Score brut = moyenne ponderee des categories (poids = score composite). "
                      "Modulation S/R: si le signal est aligne avec un support/resistance proche "
                      "(< 1.5 ATR), le score est amplifie (x1.15) ou attenue (x0.85). "
                      "Score final clampe a [-100, +100]. "
                      "Recommandation: achat_fort (>50), achat (>15), neutre (>=-15), "
                      "vente (>=-50), vente_forte (<-50).",
        },
    ]

    return {
        "horizons": HORIZON_PARAMS,
        "categories": CATEGORY_FAMILIES,
        "family_signal_types": FAMILY_SIGNAL_TYPE,
        "family_descriptions": family_descriptions,
        "scoring": {
            "grade_thresholds": {
                "A": {"wfe": 0.65, "robustness": 0.75},
                "B": {"wfe": 0.55, "robustness": 0.60},
                "C": {"wfe": 0.50, "robustness": 0.50},
                "D": {"wfe": 0.40, "robustness": 0.40},
            },
            "composite_weights": {
                "wfe": 0.40,
                "robustness": 0.30,
                "sharpe": 0.20,
                "drawdown": 0.10,
            },
            "max_representatives": 1,
            "max_correlation": 0.85,
        },
        "window_policy_defaults": {
            "default_policy": STRICT_WINDOW_POLICY,
            "ratio_anchors": list(STRICT_RATIO_ANCHORS),
            "min_walk_forwards": DEFAULT_MIN_WALK_FORWARDS,
            "top_k_folds": DEFAULT_TOP_K_FOLDS,
            "strict_fallback_enabled": DEFAULT_STRICT_FALLBACK_ENABLED,
            "strict_fallback_floor": DEFAULT_STRICT_FALLBACK_FLOOR,
            "train_bands": {
                name: {"min": band[0], "max": band[1]}
                for name, band in HORIZON_TRAIN_BANDS.items()
            },
        },
        "pipeline_steps": pipeline_steps,
    }


@router.post(
    "/trigger",
    response_model=WfoTriggerResponse,
    dependencies=[Depends(rate_limit_trigger)],
)
def trigger_wfo_computation(
    body: WfoTriggerRequest,
    db: Session = Depends(get_db),
) -> WfoTriggerResponse:
    """Enqueue WFO computation for a symbol × horizon via RQ.

    Uses the "wfo_signals" RQ queue.  The worker calls
    enqueue_wfo_for_symbol_horizon() which creates its own DB session.
    """
    from redis import Redis
    from rq import Queue

    from ..config import settings

    categories = body.categories or ["tendance", "momentum", "oscillation", "volume"]
    variant = signal_mode_storage_name(body.variant)

    # Set initial "running" status so frontend sees immediate feedback
    for cat in categories:
        row = (
            db.query(WfoSignalSummary)
            .filter_by(symbol=body.symbol, category=cat, horizon=body.horizon, variant=variant)
            .first()
        )
        if row is None:
            row = WfoSignalSummary(
                symbol=body.symbol, category=cat, horizon=body.horizon, variant=variant,
            )
            db.add(row)
        row.status = "running"
        row.error_message = None
    db.commit()

    # Build overrides dict (only non-None values)
    overrides: dict[str, Any] = {}
    for key in (
        "train_bars",
        "oos_bars",
        "step_bars",
        "window_policy",
        "top_k_folds",
        "min_walk_forwards",
        "strict_fallback_enabled",
        "strict_fallback_floor",
        "cost_bps",
        "max_reps",
        "max_corr",
    ):
        val = getattr(body, key, None)
        if val is not None:
            overrides[key] = val

    redis_conn = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    q = Queue("wfo_signals", connection=redis_conn)
    job = q.enqueue(
        "services.worker.tasks.wfo_signal_batch.enqueue_wfo_for_symbol_horizon",
        body.symbol,
        body.horizon,
        overrides if overrides else None,
        body.variant,
        job_timeout=7200,
    )

    return WfoTriggerResponse(triggered=categories, job_id=str(job.id))


@router.post(
    "/trigger-all",
    response_model=WfoTriggerAllResponse,
    dependencies=[Depends(require_admin), Depends(rate_limit_trigger)],
)
def trigger_all_wfo(
    body: WfoTriggerAllRequest,
    db: Session = Depends(get_db),
) -> WfoTriggerAllResponse:
    """Fan out WFO jobs for every data-backed symbol x horizon x variant."""
    from redis import Redis
    from rq import Queue
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from services.api.app.queue import _get_macro_ingest_queue

    from ..config import settings

    horizons: list[CanonicalHorizon] = ["weekly", "monthly", "quarterly"]
    categories = ["tendance", "momentum", "oscillation", "volume"]
    symbols = list_signal_universe_symbols(db)
    variants = list(dict.fromkeys(signal_mode_storage_name(v) for v in (body.variants or list(ALL_SIGNAL_MODE_NAMES))))

    overrides: dict[str, Any] = {
        k: v
        for k in (
            "train_bars",
            "oos_bars",
            "step_bars",
            "window_policy",
            "top_k_folds",
            "min_walk_forwards",
            "strict_fallback_enabled",
            "strict_fallback_floor",
            "cost_bps",
            "max_reps",
            "max_corr",
        )
        if (v := getattr(body, k)) is not None
    }

    # Single bulk upsert — 1 query instead of 1,656 individual SELECTs
    rows_to_upsert = [
        {"symbol": s, "horizon": h, "variant": v, "category": c, "status": "running", "error_message": None}
        for s in symbols for h in horizons for v in variants for c in categories
    ]
    stmt = pg_insert(WfoSignalSummary).values(rows_to_upsert)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "category", "horizon", "variant"],
        set_={"status": "running", "error_message": None},
    )
    db.execute(stmt)
    db.commit()

    # Enqueue one RQ job per (symbol, horizon, variant)
    redis_conn = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    q = Queue("wfo_signals", connection=redis_conn)
    factor_selection_jobs: dict[str, str] = {}
    if any(resolve_signal_mode(variant).is_factor_x_ta for variant in variants):
        factor_queue = _get_macro_ingest_queue()
        for s in symbols:
            job = factor_queue.enqueue(
                "services.worker.tasks.factor_selection_full.run_factor_selection_for_symbol",
                s,
                False,
                job_timeout=3600,
            )
            factor_selection_jobs[s] = str(job.id)
    total_jobs = 0
    for s in symbols:
        for h in horizons:
            for v in variants:
                mode = resolve_signal_mode(v)
                q.enqueue(
                    "services.worker.tasks.wfo_signal_batch.enqueue_wfo_for_symbol_horizon",
                    s, h, overrides or None, v,
                    job_timeout=7200,
                    depends_on=factor_selection_jobs.get(s) if mode.is_factor_x_ta else None,
                )
                total_jobs += 1

    return WfoTriggerAllResponse(
        total_jobs=total_jobs,
        symbols=len(symbols),
        horizons=horizons,
        variants=variants,
    )


@router.get("/batch-status", response_model=WfoBatchStatusResponse)
def get_wfo_batch_status(db: Session = Depends(get_db)) -> WfoBatchStatusResponse:
    """Return aggregated status counts across all wfo_signal_summary rows."""
    from sqlalchemy import func as sa_func

    rows = (
        db.query(WfoSignalSummary.status, sa_func.count().label("cnt"))
        .group_by(WfoSignalSummary.status)
        .all()
    )
    counts: dict[str, int] = {r.status: r.cnt for r in rows}
    total = sum(counts.values())
    return WfoBatchStatusResponse(
        total=total,
        succeeded=counts.get("succeeded", 0),
        running=counts.get("running", 0),
        failed=counts.get("failed", 0),
        pending=counts.get("pending", 0),
        insufficient_data=counts.get("insufficient_data", 0),
    )
