"""Strategy plan API — universe filtering, S/R levels, execution, sizing."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..market_data_loader import load_ohlcv_for_symbol
from ..masi_tickers import get_masi_info
from ..schemas.strategy import (
    ExecutionPlanOut,
    ExecutionRequest,
    FamilyScoreOut,
    FocusedKellyOut,
    LevelsOut,
    LevelsRequest,
    PivotPoints,
    SRLevel,
    SavedStrategyCreate,
    StrategyAllocationOut,
    StrategyAllocationRequest,
    StrategyAllocationRowOut,
    SavedStrategyListItem,
    SavedStrategyOut,
    SavedStrategyUpdate,
    SignalConsensusOut,
    SignalConsensusRequest,
    StrategyBacktestRequest,
    StrategyBacktestResponse,
    SizingOut,
    SizingRequest,
    StockSizingRow,
    UniverseFilterRequest,
    UniverseStockOut,
)
import pandas as pd
from .strategy_signals import _get_or_compute, _score_to_label

from core.quant_core.strategy_plan.allocation import compute_strategy_allocation
from core.quant_core.strategy_plan.backtest import run_strategy_plan_backtest
from core.quant_core.signal_engine.domain import (
    CATEGORY_FAMILIES,
    FAMILY_SIGNAL_TYPE,
    HORIZON_PARAMS,
    signal_type_label,
)
from core.quant_core.strategy_plan.execution import compute_execution_plan
from core.quant_core.strategy_plan.execution_policy import build_execution_horizon_policy
from core.quant_core.strategy_plan.signal_policy import compute_consensus
from core.quant_core.strategy_plan.sizing import (
    compute_kelly_ceiling,
    compute_portfolio_allocation,
)
from core.quant_core.strategy_plan.universe import filter_universe
from core.quant_core.strategy_plan.levels import (
    compute_atr,
    compute_pivot_points,
    detect_swing_levels,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategy/plan", tags=["strategy-plan"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate_for_horizon(ohlcv, horizon: str):
    max_bars = HORIZON_PARAMS[horizon]["max_years"] * 252
    if len(ohlcv) > max_bars:
        return ohlcv.iloc[-max_bars:]
    return ohlcv


def _clean_ohlcv(ohlcv):
    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in ohlcv.columns]
    if cols:
        ohlcv = ohlcv.dropna(subset=cols)
    return ohlcv


def _resolve_execution_policy(
    horizon: str,
    timeframe: str,
    *,
    execution_holding_bars: int | None = None,
):
    return build_execution_horizon_policy(
        horizon,
        timeframe=timeframe,
        holding_bars=execution_holding_bars,
    )


def _compute_batch_scores(
    db: Session,
    symbols: list[str],
    horizon: str,
    timeframe: str,
    cost_bps: float,
    cooldown_bars: int,
) -> dict[str, dict[str, Any]]:
    """Compute signal scores for multiple symbols, identical to batch_scores endpoint logic."""
    result: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        family_scores: dict[str, float] = {}
        family_labels: dict[str, str] = {}
        for family in ("sma", "rsi", "macd", "obv"):
            try:
                detail = _get_or_compute(
                    db, family, symbol, horizon, timeframe, cost_bps, cooldown_bars,
                )
                family_scores[family] = detail.signal.family_score_pct
                family_labels[family] = detail.signal.family_signal_label
            except HTTPException:
                pass

        categories: dict[str, dict[str, Any]] = {}
        for cat_name, cat_fams in CATEGORY_FAMILIES.items():
            cat_scores = [family_scores[f] for f in cat_fams if f in family_scores]
            if cat_scores:
                cat_avg = sum(cat_scores) / len(cat_scores)
                st = FAMILY_SIGNAL_TYPE.get(cat_fams[0], "trend")
                categories[cat_name] = {
                    "score_pct": round(cat_avg, 2),
                    "label": signal_type_label(st, cat_avg),
                    "families": cat_fams,
                }

        all_scores = list(family_scores.values())
        if all_scores:
            agg = sum(all_scores) / len(all_scores)
            result[symbol] = {
                "aggregate_score_pct": round(agg, 2),
                "aggregate_signal_label": _score_to_label(agg),
                "categories": categories,
                "per_family": {
                    f: {"score_pct": round(s, 2), "label": family_labels.get(f, "N/A")}
                    for f, s in family_scores.items()
                },
            }
        else:
            result[symbol] = {
                "aggregate_score_pct": None,
                "aggregate_signal_label": None,
                "categories": {},
                "per_family": {},
            }
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/universe")
def get_universe(
    body: UniverseFilterRequest,
    db: Session = Depends(get_db),
) -> list[UniverseStockOut]:
    """Filter stock universe by data availability, signal strength, and sector."""

    # 1. Load all active stocks from StockMaster + MarketDataStore
    stocks_raw = (
        db.query(models.StockMaster)
        .filter(models.StockMaster.is_active.is_(True))
        .order_by(models.StockMaster.symbol.asc())
        .all()
    )

    stock_dicts: list[dict[str, Any]] = []
    symbols: list[str] = []
    for stock in stocks_raw:
        store = (
            db.query(models.MarketDataStore)
            .filter(
                models.MarketDataStore.symbol == stock.symbol,
                models.MarketDataStore.timeframe == body.timeframe,
            )
            .one_or_none()
        )
        adv20 = None
        try:
            ohlcv = load_ohlcv_for_symbol(db, stock.symbol, body.timeframe)
            ohlcv = _clean_ohlcv(ohlcv)
            if not ohlcv.empty and "Volume" in ohlcv.columns:
                adv20 = float(ohlcv["Volume"].tail(20).mean())
        except Exception:
            logger.debug("ADV20 unavailable for %s", stock.symbol, exc_info=True)
        stock_dicts.append({
            "symbol": stock.symbol,
            "display_name": stock.display_name,
            "sector": stock.sector or ((get_masi_info(stock.symbol) or {}).get("sector")),
            "market_cap_class": stock.market_cap_class,
            "row_count": store.row_count if store else 0,
            "data_as_of": str(store.data_as_of)[:10] if store and store.data_as_of else None,
            "adv20": adv20,
        })
        symbols.append(stock.symbol)

    # 2. Compute signal scores for all symbols
    signal_scores = _compute_batch_scores(
        db, symbols, body.horizon, body.timeframe,
        body.cost_bps, body.cooldown_bars,
    )

    # 3. Filter universe
    enriched = filter_universe(
        stock_dicts,
        signal_scores,
        min_bars=body.min_bars,
        min_abs_signal=body.min_abs_signal,
        min_adv20=body.min_adv20,
        sector_filter=body.sector_filter,
        sort_by=body.sort_by,
        sort_dir=body.sort_dir,
    )

    return [UniverseStockOut(**item) for item in enriched]


@router.post("/allocation")
def get_strategy_allocation(
    body: StrategyAllocationRequest,
    db: Session = Depends(get_db),
) -> StrategyAllocationOut:
    """Compute HRP-based stock allocation with optional manual overrides."""

    price_history: dict[str, pd.Series] = {}
    for symbol in body.symbols:
        try:
            ohlcv = load_ohlcv_for_symbol(db, symbol, body.timeframe)
            ohlcv = _clean_ohlcv(ohlcv)
            if not ohlcv.empty and "Close" in ohlcv.columns:
                price_history[symbol] = ohlcv["Close"].astype(float)
        except Exception:
            logger.debug("Allocation history unavailable for %s", symbol, exc_info=True)

    allocation = compute_strategy_allocation(
        symbols=body.symbols,
        total_capital_mad=body.total_capital_mad,
        price_history=price_history,
        manual_overrides_by_symbol=body.manual_overrides_by_symbol,
        lookback_bars=body.lookback_bars,
    )

    return StrategyAllocationOut(
        rows=[StrategyAllocationRowOut(**row) for row in allocation["rows"]],
        total_capital_mad=allocation["total_capital_mad"],
        allocated_capital_mad=allocation["allocated_capital_mad"],
        remaining_capital_mad=allocation["remaining_capital_mad"],
        explain=allocation["explain"],
    )


@router.post("/levels")
def get_levels(
    body: LevelsRequest,
    db: Session = Depends(get_db),
) -> LevelsOut:
    """Compute swing-based support/resistance, ATR, and pivot points for a symbol."""

    try:
        ohlcv = load_ohlcv_for_symbol(db, body.symbol, body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    ohlcv = _truncate_for_horizon(ohlcv, body.horizon)
    ohlcv = _clean_ohlcv(ohlcv)

    if ohlcv.empty or len(ohlcv) < 3:
        raise HTTPException(
            status_code=422,
            detail=f"Insufficient data for {body.symbol}: {len(ohlcv)} bars after cleaning.",
        )

    high = ohlcv["High"].values.astype("float64")
    low = ohlcv["Low"].values.astype("float64")
    close = ohlcv["Close"].values.astype("float64")
    idx = ohlcv.index
    policy = _resolve_execution_policy(
        body.horizon,
        body.timeframe,
        execution_holding_bars=body.execution_holding_bars,
    )
    left_bars = body.left_bars if body.left_bars is not None else policy.swing_left_bars
    right_bars = body.right_bars if body.right_bars is not None else policy.swing_right_bars
    max_levels = body.max_levels if body.max_levels is not None else policy.max_levels
    lookback = body.lookback if body.lookback is not None else policy.structural_lookback
    body.left_bars = left_bars
    body.right_bars = right_bars
    body.max_levels = max_levels
    body.lookback = lookback

    # S/R detection
    sr = detect_swing_levels(
        high, low, close,
        left_bars=left_bars,
        right_bars=right_bars,
        max_levels=max_levels,
        lookback=lookback,
        max_distance_atr=policy.max_level_distance_atr,
    )

    # Enrich with dates
    def _enrich_level(level: dict) -> SRLevel:
        bi = level["bar_index"]
        date_str = str(idx[bi])[:10] if 0 <= bi < len(idx) else None
        return SRLevel(
            price=level["price"],
            bar_index=bi,
            date=date_str,
            strength=level.get("strength", 0),
        )

    supports = [_enrich_level(s) for s in sr["supports"]]
    resistances = [_enrich_level(r) for r in sr["resistances"]]

    # ATR
    atr_abs, atr_ratio = compute_atr(high, low, close, window=14)

    # Pivot points from previous session (second-to-last bar)
    pivot = None
    if len(ohlcv) >= 2:
        prev = ohlcv.iloc[-2]
        pivot = PivotPoints(**compute_pivot_points(
            prev_high=float(prev["High"]),
            prev_low=float(prev["Low"]),
            prev_close=float(prev["Close"]),
        ))

    n_sup = len(supports)
    n_res = len(resistances)
    explain = (
        f"{n_sup} support(s) et {n_res} résistance(s) détectés "
        f"sur les {body.lookback} dernières barres "
        f"(pivot {body.left_bars}L/{body.right_bars}R). "
        f"ATR(14) = {atr_abs:.2f} ({atr_ratio*100:.2f}%)."
    )

    return LevelsOut(
        symbol=body.symbol,
        current_close=sr["current_close"],
        atr_14=round(atr_abs, 4),
        atr_pct=round(atr_ratio, 6),
        supports=supports,
        resistances=resistances,
        nearest_support=sr["nearest_support"],
        nearest_resistance=sr["nearest_resistance"],
        pivot=pivot,
        explain=explain,
    )


# ---------------------------------------------------------------------------
# Signal Consensus
# ---------------------------------------------------------------------------

@router.post("/signal-consensus")
def get_signal_consensus(
    body: SignalConsensusRequest,
    db: Session = Depends(get_db),
) -> SignalConsensusOut:
    """Compute weighted consensus across enabled signal families for a symbol."""

    if not body.enabled_families:
        return SignalConsensusOut(
            symbol=body.symbol,
            final_consensus=None,
            final_consensus_label=None,
            enabled_families=[],
            explain="Aucune famille active.",
        )

    # Compute per-family scores (reuses 5-min TTL cache)
    per_family_scores: dict[str, float] = {}
    per_family_labels: dict[str, str] = {}
    for family in body.enabled_families:
        try:
            detail = _get_or_compute(
                db, family, body.symbol, body.horizon,
                body.timeframe, body.cost_bps, body.cooldown_bars,
            )
            per_family_scores[family] = detail.signal.family_score_pct
            per_family_labels[family] = detail.signal.family_signal_label
        except HTTPException:
            logger.warning("Signal computation failed for %s/%s", family, body.symbol)

    # Compute consensus
    result = compute_consensus(per_family_scores, body.enabled_families)

    # Build per-family output with labels
    per_family_out: dict[str, FamilyScoreOut] = {}
    for f, info in result["per_family"].items():
        per_family_out[f] = FamilyScoreOut(
            score_pct=info["score_pct"],
            label=per_family_labels.get(f, "N/A"),
            weight=info["weight"],
        )

    consensus = result["final_consensus"]
    consensus_label = _score_to_label(consensus) if consensus is not None else None

    n_active = len(result["family_weights"])
    n_enabled = len(body.enabled_families)
    explain = (
        f"Consensus calculé sur {n_active}/{n_enabled} famille(s) active(s) "
        f"avec pondération égale."
    )

    return SignalConsensusOut(
        symbol=body.symbol,
        final_consensus=consensus,
        final_consensus_label=consensus_label,
        enabled_families=body.enabled_families,
        family_weights=result["family_weights"],
        per_family=per_family_out,
        explain=explain,
    )


# ---------------------------------------------------------------------------
# Execution Plan
# ---------------------------------------------------------------------------

@router.post("/execution")
def get_execution_plan(
    body: ExecutionRequest,
    db: Session = Depends(get_db),
) -> ExecutionPlanOut:
    """Compute execution plan (entry zone, stop, targets, R:R) for a symbol."""

    # 1. Consensus — use override or compute
    if body.consensus_override is not None:
        consensus = body.consensus_override
    else:
        per_family_scores: dict[str, float] = {}
        for family in body.enabled_families:
            try:
                detail = _get_or_compute(
                    db, family, body.symbol, body.horizon,
                    body.timeframe, body.cost_bps, body.cooldown_bars,
                )
                per_family_scores[family] = detail.signal.family_score_pct
            except HTTPException:
                logger.warning("Signal failed for %s/%s", family, body.symbol)

        from core.quant_core.strategy_plan.signal_policy import compute_consensus as _cc
        result = _cc(per_family_scores, body.enabled_families)
        consensus = result["final_consensus"]

    # 2. Levels — reuse existing logic
    try:
        ohlcv = load_ohlcv_for_symbol(db, body.symbol, body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    ohlcv = _truncate_for_horizon(ohlcv, body.horizon)
    ohlcv = _clean_ohlcv(ohlcv)

    if ohlcv.empty or len(ohlcv) < 3:
        raise HTTPException(
            status_code=422,
            detail=f"Insufficient data for {body.symbol}: {len(ohlcv)} bars.",
        )

    high = ohlcv["High"].values.astype("float64")
    low = ohlcv["Low"].values.astype("float64")
    close = ohlcv["Close"].values.astype("float64")
    policy = _resolve_execution_policy(
        body.horizon,
        body.timeframe,
        execution_holding_bars=body.execution_holding_bars,
    )

    sr = detect_swing_levels(
        high,
        low,
        close,
        left_bars=policy.swing_left_bars,
        right_bars=policy.swing_right_bars,
        max_levels=policy.max_levels,
        lookback=policy.structural_lookback,
        max_distance_atr=policy.max_level_distance_atr,
    )
    atr_abs, _ = compute_atr(high, low, close, window=14)

    # 3. Compute execution plan
    plan = compute_execution_plan(
        consensus=consensus,
        side_policy=body.side_policy,
        nearest_support=sr["nearest_support"],
        nearest_resistance=sr["nearest_resistance"],
        supports=sr["supports"],
        resistances=sr["resistances"],
        atr=atr_abs,
        current_close=sr["current_close"],
        entry_threshold=body.entry_threshold,
        atr_multiplier=body.atr_multiplier,
        buffer_pct=body.buffer_pct,
        min_rr=body.min_rr,
        holding_bars=policy.holding_bars,
    )

    return ExecutionPlanOut(symbol=body.symbol, **plan)


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------

@router.post("/sizing")
def get_sizing(body: SizingRequest) -> SizingOut:
    """Compute Kelly ceiling + portfolio allocation across basket stocks."""

    stock_dicts = [s.model_dump() for s in body.stocks]

    # Portfolio allocation
    alloc = compute_portfolio_allocation(
        stocks=stock_dicts,
        method=body.allocation_method,
        max_position_pct=body.max_position_pct,
        max_sector_pct=body.max_sector_pct,
        account_equity=body.account_equity,
        kelly_modifier=body.kelly_modifier,
        win_rate=body.win_rate,
        avg_wl_ratio=body.avg_wl_ratio,
    )

    # Focused Kelly (for the selected stock)
    focused_kelly = None
    if body.focused_symbol:
        for s in stock_dicts:
            if s["symbol"] == body.focused_symbol and s.get("entry_price") and s.get("stop_price"):
                kelly = compute_kelly_ceiling(
                    win_rate=body.win_rate,
                    avg_wl_ratio=body.avg_wl_ratio,
                    modifier=body.kelly_modifier,
                    entry_price=s["entry_price"],
                    stop_price=s["stop_price"],
                    account_equity=body.account_equity,
                )
                focused_kelly = FocusedKellyOut(**kelly)
                break

    return SizingOut(
        focused_kelly=focused_kelly,
        portfolio_table=[StockSizingRow(**row) for row in alloc["portfolio_table"]],
        total_exposure_pct=alloc["total_exposure_pct"],
        total_risk_pct=alloc["total_risk_pct"],
        capital_deployed=alloc["capital_deployed"],
        explain=alloc["explain"],
    )


# ---------------------------------------------------------------------------
# Saved Strategy CRUD
# ---------------------------------------------------------------------------

def _strategy_to_list_item(row: models.SavedStrategy) -> SavedStrategyListItem:
    basket = (row.config_json or {}).get("universe", {}).get("basket", [])
    return SavedStrategyListItem(
        id=str(row.id),
        name=row.name,
        status=row.status,
        side_policy=row.side_policy,
        horizon=row.horizon,
        basket_count=len(basket),
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


def _strategy_to_out(row: models.SavedStrategy) -> SavedStrategyOut:
    return SavedStrategyOut(
        id=str(row.id),
        name=row.name,
        note=row.note,
        status=row.status,
        side_policy=row.side_policy,
        horizon=row.horizon,
        config_json=row.config_json or {},
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


@router.get("/strategies")
def list_strategies(
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[SavedStrategyListItem]:
    """List saved strategies, optionally filtered by status."""
    q = db.query(models.SavedStrategy)
    if status:
        q = q.filter(models.SavedStrategy.status == status)
    else:
        q = q.filter(models.SavedStrategy.status != "archived")
    rows = q.order_by(models.SavedStrategy.updated_at.desc()).all()
    return [_strategy_to_list_item(r) for r in rows]


@router.get("/strategies/{strategy_id}")
def get_strategy(
    strategy_id: str,
    db: Session = Depends(get_db),
) -> SavedStrategyOut:
    """Get a single saved strategy with full config."""
    row = db.query(models.SavedStrategy).filter(
        models.SavedStrategy.id == strategy_id,
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return _strategy_to_out(row)


@router.post("/backtest")
def backtest_strategy(
    body: StrategyBacktestRequest,
    db: Session = Depends(get_db),
) -> StrategyBacktestResponse:
    """Run a direct backtest for one saved strategy over a fixed date range."""
    row = db.query(models.SavedStrategy).filter(
        models.SavedStrategy.id == body.strategy_id,
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")

    config_json = row.config_json or {}
    universe = config_json.get("universe") if isinstance(config_json.get("universe"), dict) else {}
    basket = [str(symbol).strip().upper() for symbol in list(universe.get("basket") or []) if str(symbol).strip()]
    if not basket:
        raise HTTPException(status_code=422, detail="Saved strategy has an empty basket.")

    bars_by_symbol: dict[str, pd.DataFrame] = {}
    missing_symbols: list[str] = []
    for symbol in basket:
        try:
            ohlcv = load_ohlcv_for_symbol(db, symbol, body.timeframe)
        except ValueError:
            missing_symbols.append(symbol)
            continue
        ohlcv = _clean_ohlcv(ohlcv)
        if ohlcv.empty:
            missing_symbols.append(symbol)
            continue
        bars_by_symbol[symbol] = ohlcv

    if not bars_by_symbol:
        raise HTTPException(
            status_code=422,
            detail="No basket symbols have usable market data for this backtest.",
        )

    try:
        result = run_strategy_plan_backtest(
            strategy_id=str(row.id),
            strategy_name=row.name,
            side_policy=row.side_policy,
            horizon=row.horizon,
            timeframe=body.timeframe,
            config_json=config_json,
            bars_by_symbol=bars_by_symbol,
            start_date=body.start_date,
            end_date=body.end_date,
            cost_model_raw=body.cost_model.model_dump(),
            volume_gate=body.volume_gate.model_dump(),
            cooldown_bars=body.cooldown_bars,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception(
            "strategy backtest failed during response build",
            extra={
                "strategy_id": body.strategy_id,
                "start_date": body.start_date,
                "end_date": body.end_date,
            },
        )
        raise HTTPException(status_code=500, detail="Strategy backtest failed unexpectedly.") from exc

    assumptions = dict(result.get("assumptions") or {})
    existing_missing = list(assumptions.get("skipped_symbols") or [])
    assumptions["missing_symbols"] = sorted(set(existing_missing + missing_symbols))
    result["assumptions"] = assumptions
    try:
        return StrategyBacktestResponse(**result)
    except Exception as exc:
        logger.exception(
            "strategy backtest response serialization failed",
            extra={
                "strategy_id": body.strategy_id,
                "start_date": body.start_date,
                "end_date": body.end_date,
            },
        )
        raise HTTPException(status_code=500, detail="Strategy backtest response could not be serialized.") from exc


@router.post("/strategies", status_code=201)
def create_strategy(
    body: SavedStrategyCreate,
    db: Session = Depends(get_db),
) -> SavedStrategyOut:
    """Create a new strategy."""
    row = models.SavedStrategy(
        name=body.name,
        note=body.note,
        side_policy=body.side_policy,
        horizon=body.horizon,
        status="draft",
        config_json={},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _strategy_to_out(row)


@router.put("/strategies/{strategy_id}")
def update_strategy(
    strategy_id: str,
    body: SavedStrategyUpdate,
    db: Session = Depends(get_db),
) -> SavedStrategyOut:
    """Update a strategy's config or metadata."""
    row = db.query(models.SavedStrategy).filter(
        models.SavedStrategy.id == strategy_id,
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(row, key, value)

    db.commit()
    db.refresh(row)
    return _strategy_to_out(row)


@router.post("/strategies/{strategy_id}/duplicate", status_code=201)
def duplicate_strategy(
    strategy_id: str,
    db: Session = Depends(get_db),
) -> SavedStrategyOut:
    """Duplicate a strategy."""
    original = db.query(models.SavedStrategy).filter(
        models.SavedStrategy.id == strategy_id,
    ).one_or_none()
    if not original:
        raise HTTPException(status_code=404, detail="Strategy not found")

    copy = models.SavedStrategy(
        name=f"{original.name} (copie)",
        note=original.note,
        side_policy=original.side_policy,
        horizon=original.horizon,
        status="draft",
        config_json=dict(original.config_json or {}),
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return _strategy_to_out(copy)


@router.patch("/strategies/{strategy_id}/archive")
def archive_strategy(
    strategy_id: str,
    db: Session = Depends(get_db),
) -> SavedStrategyOut:
    """Toggle archive status on a strategy."""
    row = db.query(models.SavedStrategy).filter(
        models.SavedStrategy.id == strategy_id,
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")

    if row.status == "archived":
        row.status = "draft"
        row.archived_at = None
    else:
        row.status = "archived"
        from sqlalchemy.sql import func as sqlfunc
        row.archived_at = sqlfunc.now()

    db.commit()
    db.refresh(row)
    return _strategy_to_out(row)
