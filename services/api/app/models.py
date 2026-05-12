import uuid
from sqlalchemy import (
    Column, String, DateTime, Date, ForeignKey, Text, BigInteger, Float, UniqueConstraint, Index, Integer, Boolean, text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from .db import Base

# ---------------------------------------------------------------------------
# Signal Engine Persistence — new tables added 2026-04-20
# ---------------------------------------------------------------------------



class Dataset(Base):
    __tablename__ = "dataset"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String, nullable=False)      # e.g. "BMCE_CSV", "Yahoo"
    symbol = Column(String, nullable=False)
    timeframe = Column(String, nullable=False)   # e.g. "1D"
    data_hash = Column(String, nullable=False)

    filename = Column(String, nullable=True)
    content_type = Column(String, nullable=True)
    object_key = Column(String, nullable=True)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    meta_json = Column(JSONB, nullable=False, default=dict)

    start_ts = Column(DateTime(timezone=True), nullable=True)
    end_ts = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class MarketDataStore(Base):
    __tablename__ = "market_data_store"
    symbol = Column(String, primary_key=True)
    timeframe = Column(String, primary_key=True, default="1d")  # optional composite PK
    object_key = Column(String, nullable=False)
    start_ts = Column(DateTime(timezone=True))
    end_ts = Column(DateTime(timezone=True))
    row_count = Column(Integer)
    last_dataset_id = Column(ForeignKey("dataset.id"))
    source_provider = Column(String, nullable=True)   # "bourse_direct"|"yahoo"|"bmce_excel"|"casablanca_bourse"
    data_as_of = Column(Date, nullable=True)           # last bar date (denormalized for freshness display)
    asset_class = Column(String(16), nullable=False, default="equity")  # "equity"|"index"|"factor"
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Run(Base):
    __tablename__ = "run"

    id = Column(UUID(as_uuid=True), primary_key=True)
    status = Column(String, nullable=False)            # created/queued/running/succeeded/failed
    run_type = Column(String, nullable=False, default="backtest")  # backtest/optimization

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    engine_version = Column(String, nullable=True)
    git_commit = Column(String, nullable=True)

    dataset_id = Column(UUID(as_uuid=True), ForeignKey("dataset.id"), nullable=True)

    spec_json = Column(JSONB, nullable=False)
    spec_hash = Column(String, nullable=False)         # stable hash from your run_spec
    error_message = Column(Text, nullable=True)

    mode = Column(String, nullable=False, server_default="single")
    seed = Column(Integer, nullable=True)
    dataset_hash = Column(String, nullable=True)
    code_version = Column(String, nullable=True)
    integrity_status = Column(String, nullable=True)

    rq_job_id = Column(String, nullable=True)
    progress_pct = Column(Float, nullable=True)
    progress_stage = Column(String, nullable=True)
    progress_message = Column(Text, nullable=True)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)

    leaderboard_json = Column(JSONB, nullable=True)


class Artifact(Base):
    __tablename__ = "artifact"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False, index=True)
    symbol = Column(String, nullable=True, index=True)

    artifact_type = Column(String, nullable=False)   # plotly_json, table_csv, manifest_json, etc.
    name = Column(String, nullable=False)            # e.g. equity_curve, price_trades

    object_key = Column(String, nullable=False)      # path in MinIO bucket
    bucket = Column(String, nullable=False, default="quant-artifacts")

    content_type = Column(String, nullable=False)    # application/json, text/csv
    size_bytes = Column(BigInteger, nullable=False, default=0)
    sha256 = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RunMetric(Base):
    __tablename__ = "run_metric"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    symbol = Column(String, nullable=False)
    metric_name = Column(String, nullable=False)
    metric_value = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "symbol", "metric_name", name="uq_run_metric_run_id_symbol_metric_name"),
    )


class Fill(Base):
    __tablename__ = "fill"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    qty = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fees = Column(Float, nullable=False, default=0.0)
    notional = Column(Float, nullable=False)
    meta = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_fill_run_id_timestamp", "run_id", "timestamp"),
        Index("ix_fill_run_id_symbol_timestamp", "run_id", "symbol", "timestamp"),
    )


class PositionLedger(Base):
    __tablename__ = "position_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    symbol = Column(String, nullable=False)
    available_qty = Column(Float, nullable=False)
    cmp = Column(Float, nullable=False)
    position_value_cost = Column(Float, nullable=False)
    pnl_realise = Column(Float, nullable=False)
    pnl_latent = Column(Float, nullable=False)
    mark_price = Column(Float, nullable=False)

    __table_args__ = (
        Index("ix_position_ledger_run_id_timestamp", "run_id", "timestamp"),
        Index("ix_position_ledger_run_id_symbol_timestamp", "run_id", "symbol", "timestamp"),
    )


class StrategyLeaderboard(Base):
    __tablename__ = "strategy_leaderboard"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    strategy_kind = Column(String, nullable=False, index=True)
    rank = Column(Integer, nullable=False)

    pnl = Column(Float, nullable=True)
    cagr = Column(Float, nullable=True)
    efficiency = Column(Float, nullable=True)
    n_fills = Column(Integer, nullable=True)

    signal_label = Column(String, nullable=True)
    signal_today = Column(Float, nullable=True)
    signal_date = Column(DateTime(timezone=True), nullable=True)

    best_params_json = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "symbol", "strategy_kind", "rank", name="uq_strategy_leaderboard_run_symbol_kind_rank"),
        Index("ix_strategy_leaderboard_run_symbol", "run_id", "symbol"),
        Index("ix_strategy_leaderboard_symbol_created_at", "symbol", "created_at"),
    )


class RunIntegrityCheck(Base):
    __tablename__ = "run_integrity_check"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False, index=True)
    check_name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    details_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "check_name", name="uq_run_integrity_check_run_name"),
    )


class RunFold(Base):
    __tablename__ = "run_fold"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False, index=True)
    fold_index = Column(Integer, nullable=False)
    strategy_kind = Column(String(128), nullable=False, default="")
    train_start = Column(DateTime(timezone=True), nullable=True)
    train_end = Column(DateTime(timezone=True), nullable=True)
    test_start = Column(DateTime(timezone=True), nullable=True)
    test_end = Column(DateTime(timezone=True), nullable=True)
    fold_metrics_json = Column(JSONB, nullable=False, default=dict)
    fold_artifacts = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "strategy_kind", "fold_index", name="uq_run_fold_run_sk_index"),
    )


class RunWfoPeriod(Base):
    __tablename__ = "run_wfo_period"
    id               = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id           = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    symbol           = Column(String, nullable=False)
    strategy_kind    = Column(String(128), nullable=False)
    horizon          = Column(String(32), nullable=True)
    fold_no          = Column(Integer, nullable=False)
    train_start      = Column(DateTime(timezone=True), nullable=True)
    train_end        = Column(DateTime(timezone=True), nullable=True)
    test_start       = Column(DateTime(timezone=True), nullable=False)
    test_end         = Column(DateTime(timezone=True), nullable=False)
    winning_trial_id    = Column(String, nullable=False)
    optimal_params_json = Column(JSONB, nullable=False, default=dict)
    is_objective_name   = Column(String, nullable=True)
    is_objective_value  = Column(Float, nullable=True)
    oos_pnl          = Column(Float, nullable=True)
    oos_return       = Column(Float, nullable=True)
    oos_cagr         = Column(Float, nullable=True)
    oos_sharpe       = Column(Float, nullable=True)
    oos_max_drawdown = Column(Float, nullable=True)
    oos_win_pct      = Column(Float, nullable=True)
    oos_n_fills      = Column(Integer, nullable=True)
    cumulative_oos_pnl = Column(Float, nullable=True)
    is_holdout       = Column(Boolean, nullable=False, default=False)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("run_id","symbol","strategy_kind","horizon","fold_no",
                         name="uq_run_wfo_period_run_sk_horizon_fold"),
        Index("ix_run_wfo_period_run_id", "run_id"),
    )


class RunSignificance(Base):
    __tablename__ = "run_significance"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False, index=True)
    method = Column(String, nullable=False)
    pvalue = Column(Float, nullable=True)
    statistic = Column(Float, nullable=True)
    mc_null_dist_ref = Column(String, nullable=True)
    details_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "method", name="uq_run_significance_run_method"),
    )


class RunRisk(Base):
    __tablename__ = "run_risk"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    kelly_fraction = Column(Float, nullable=True)
    half_kelly = Column(Float, nullable=True)
    chosen_leverage = Column(Float, nullable=True)
    mc_drawdown_pctl = Column(Float, nullable=True)
    mc_var = Column(Float, nullable=True)
    mc_cvar = Column(Float, nullable=True)
    details_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", name="uq_run_risk_run_id"),
        Index("ix_run_risk_run_id", "run_id", unique=True),
    )


class StrategyDecision(Base):
    __tablename__ = "strategy_decision"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    symbol = Column(String, nullable=False)
    strategy_kind = Column(String, nullable=False)
    trial_id = Column(String, nullable=False)
    rank = Column(Integer, nullable=True)
    params_hash = Column(String, nullable=False)
    params_json = Column(JSONB, nullable=True)
    opportunity_score = Column(Float, nullable=False)
    confidence_score = Column(Float, nullable=False)
    opportunity_subscores = Column(JSONB, nullable=False, default=dict)
    confidence_subscores = Column(JSONB, nullable=False, default=dict)
    decision_page_json = Column(JSONB, nullable=False, default=dict)
    explain_json = Column(JSONB, nullable=False, default=dict)
    status = Column(String, nullable=False, server_default="watch")
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "symbol", "strategy_kind", "trial_id", name="uq_strategy_decision_run_symbol_kind_trial"),
        Index("ix_strategy_decision_run_symbol", "run_id", "symbol"),
        Index("ix_strategy_decision_run_symbol_kind_rank", "run_id", "symbol", "strategy_kind", "rank"),
    )


class DefaultsDiscoveryRun(Base):
    __tablename__ = "defaults_discovery_run"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_name = Column(String, nullable=False, server_default="sma_price")
    status = Column(String, nullable=False, server_default="queued")
    ticker = Column(String, nullable=True)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("dataset.id"), nullable=True)
    params_json = Column(JSONB, nullable=False, default=dict)
    results_json = Column(JSONB, nullable=True)
    artifacts_json = Column(JSONB, nullable=False, default=dict)
    rq_job_id = Column(String, nullable=True)
    progress_pct = Column(Float, nullable=True)
    progress_stage = Column(String, nullable=True)
    progress_message = Column(Text, nullable=True)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)


class StrategyDefaultSet(Base):
    __tablename__ = "strategy_default_set"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    strategy_name = Column(String, nullable=False)
    source_run_id = Column(UUID(as_uuid=True), ForeignKey("defaults_discovery_run.id"), nullable=True)
    defaults_json = Column(JSONB, nullable=False, default=dict)
    meta_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OptTask(Base):
    __tablename__ = "opt_task"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False, index=True)
    fold_id = Column(String, nullable=False)
    chunk_id = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="queued") # queued|running|succeeded|failed|canceled
    worker_job_id = Column(String, nullable=True, index=True)
    params_count = Column(Integer, nullable=False, default=0)
    spec_hash = Column(String, nullable=True)
    attempt = Column(Integer, nullable=False, default=1)
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_opt_task_run_fold_status", "run_id", "fold_id", "status"),
    )


class OptResult(Base):
    __tablename__ = "opt_result"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    fold_id = Column(String, nullable=False)
    chunk_id = Column(Integer, nullable=False)

    topk_json = Column(JSONB, nullable=False, default=list) # array length <= K
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "fold_id", "chunk_id", name="uq_opt_result_run_fold_chunk"),
    )


class StockMaster(Base):
    """Canonical registry of tracked Moroccan stocks."""
    __tablename__ = "stock_master"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String, nullable=False, unique=True)       # e.g. "ATW"
    display_name = Column(String, nullable=True)               # e.g. "Attijariwafa Bank"
    isin = Column(String, nullable=True)                       # e.g. "MA0000011926"
    sector = Column(String, nullable=True)                     # e.g. "Banques"
    market_cap_class = Column(String, nullable=True)           # "large"|"mid"|"small"
    asset_type = Column(String, nullable=False, default="equity")    # "equity"|"commodity"|"forex"|"bond"
    market_region = Column(String, nullable=True)              # "masi"|"us"|"european"|"asian"|null
    is_active = Column(Boolean, nullable=False, default=True)
    track_source = Column(String, nullable=False, default="bourse_direct")
    bourse_url = Column(String, nullable=True)              # direct link to Bourse de Casablanca stock page
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_stock_master_is_active", "is_active"),
    )


class IndexMaster(Base):
    """Canonical registry of tracked Moroccan market indices (MASI, MASI 20, MADEX, etc.)."""
    __tablename__ = "index_master"

    symbol = Column(String, primary_key=True)           # e.g. "MASI", "MASI_20"
    display_name = Column(String, nullable=False)        # original French libellé
    family = Column(String, nullable=True)               # "all_share"|"blue_chip"|"esg"|"sector"
    market_region = Column(String, nullable=True)        # "masi"|"us"|"european"|"asian" — always 'masi' for current rows
    is_active = Column(Boolean, nullable=False, default=True)
    source = Column(String, nullable=False, default="casablanca_bourse")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_index_master_is_active", "is_active"),
    )


class MacroFactorMeta(Base):
    """DB-backed registry of macro factor series (replaces static MACRO_SERIES list in macro.py).

    asset_type maps to Data-page tabs: 'equity' | 'commodity' | 'forex' | 'bond' | 'crypto'.
    market_region maps to Data-page subtabs (equity only): 'us' | 'european' | 'asian' | None.
    """
    __tablename__ = "macro_factor_meta"

    canonical_id  = Column(String, primary_key=True)          # e.g. "VIX"
    yahoo_ticker  = Column(String, nullable=False, unique=True)  # e.g. "^VIX"
    display_name  = Column(String, nullable=False)
    asset_type    = Column(String, nullable=False)             # 'equity'|'commodity'|'forex'|'bond'|'crypto'
    market_region = Column(String, nullable=True)             # 'us'|'european'|'asian'|'masi'|NULL
    active        = Column(Boolean, nullable=False, default=True)
    added_via     = Column(String, nullable=False, default="system")  # 'system'|'user'
    created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    notes         = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_macro_factor_meta_active", "active"),
        Index("ix_macro_factor_meta_asset_type", "asset_type"),
    )


class StockFactorRelevance(Base):
    """Stores the active factors selected for a specific stock by the Phase 3 econometric pipeline.
    
    A composite primary key on (symbol, horizon, factor_canonical_id) links a stock
    to its selected macro factor for a specific forecast horizon.
    """
    __tablename__ = "stock_factor_relevance"

    symbol = Column(String, primary_key=True)               # e.g. "ATW"
    horizon = Column(String, primary_key=True)              # 'short' | 'mid' | 'long'
    factor_canonical_id = Column(String, primary_key=True)  # e.g. "SP500", "VIX"
    rank = Column(Integer, nullable=True)
    ic = Column(Float, nullable=True)
    spearman_ic = Column(Float, nullable=True)
    pearson_corr = Column(Float, nullable=True)
    ic_t_stat = Column(Float, nullable=True)
    bh_p_adj = Column(Float, nullable=True)
    lasso_coef = Column(Float, nullable=True)
    relevance_score = Column(Float, nullable=False)         # compatibility mirror of lasso_coef
    n_obs = Column(Integer, nullable=True)
    selected_reason = Column(String(32), nullable=True)
    last_calibrated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    cusum_drift_score = Column(Float, nullable=True)        # CUSUM metric tracking parameter drift
    cusum_alarm = Column(Boolean, nullable=False, default=False)  # legacy compatibility
    cusum_status = Column(String, nullable=False, default="valid")
    regime_start = Column(Date, nullable=True)
    low_confidence = Column(Boolean, nullable=False, default=False)
    next_forced_recal = Column(DateTime(timezone=True), nullable=True)
    history_n_days = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_stock_factor_relevance_symbol", "symbol"),
        Index("idx_sfr_active", "symbol", "horizon", postgresql_where=text("cusum_status = 'valid'")),
    )


class StockFactorStage1Cache(Base):
    """Internal cache for Phase 3 Stage 1 (BH-FDR NW IC) screening.
    
    Stores the pre-LASSO Information Coefficient metrics to avoid re-computing NW t-stats
    daily unless the factor/stock series have shifted.
    """
    __tablename__ = "stock_factor_stage1_cache"

    symbol = Column(String, primary_key=True)
    horizon = Column(String, primary_key=True)
    factor_canonical_id = Column(String, primary_key=True)
    ic_mean = Column(Float, nullable=False)
    spearman_ic = Column(Float, nullable=True)
    pearson_corr = Column(Float, nullable=True)
    ic_tstat = Column(Float, nullable=False)
    bh_p_adj = Column(Float, nullable=True)
    relevance_score = Column(Float, nullable=True)
    n_obs = Column(Integer, nullable=True)
    selected_reason = Column(String(32), nullable=True)
    passed_fdr = Column(Boolean, nullable=False)
    regime_start = Column(Date, nullable=True)
    low_confidence = Column(Boolean, nullable=False, default=False)
    history_n_days = Column(Integer, nullable=True)
    calculated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_stage1_cache_symbol_horizon", "symbol", "horizon"),
    )


class ProviderSymbolMap(Base):
    """Maps internal canonical symbol to provider-specific ticker."""
    __tablename__ = "provider_symbol_map"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String, ForeignKey("stock_master.symbol"), nullable=False)
    provider = Column(String, nullable=False)                  # "yahoo"|"bourse_direct"|"bmce_excel"
    provider_symbol = Column(String, nullable=False)           # e.g. "ATW.CS" for Yahoo
    confidence = Column(Float, nullable=False, default=1.0)   # 0.0–1.0
    is_verified = Column(Boolean, nullable=False, default=False)
    override_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "provider", name="uq_provider_symbol_map_symbol_provider"),
    )


class MarketRefreshRun(Base):
    """Tracks each bulk or single-symbol market data refresh job."""
    __tablename__ = "market_refresh_run"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trigger_source = Column(String, nullable=False, default="manual")  # "manual"|"scheduled"|"api"
    scope = Column(String, nullable=False, default="all")              # "all"|"single"
    symbol = Column(String, nullable=True)                             # NULL if scope="all"
    timeframe = Column(String, nullable=False, default="1D")
    status = Column(String, nullable=False, default="queued")          # "queued"|"running"|"succeeded"|"partial"|"failed"
    rq_job_id = Column(String, nullable=True)
    symbols_total = Column(Integer, nullable=True)
    symbols_done = Column(Integer, nullable=True)
    symbols_failed = Column(Integer, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    error_message = Column(Text, nullable=True)
    meta_json = Column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_market_refresh_run_status", "status"),
        Index("ix_market_refresh_run_created_at", "created_at"),
    )


class SavedStrategy(Base):
    """Persisted trading strategy with configuration and snapshot."""
    __tablename__ = "saved_strategy"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    note = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="draft")          # draft/modified/saved/archived
    side_policy = Column(String(20), nullable=False, default="long_only") # long_only/long_short
    horizon = Column(String(20), nullable=False, default="medium")        # short/medium/long
    config_json = Column(JSONB, nullable=False, default=dict)             # all layer configs
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_saved_strategy_status", "status"),
        Index("ix_saved_strategy_updated_at", "updated_at"),
    )


class DashboardCustomIndex(Base):
    """Persisted custom dashboard index definition (shared/global)."""
    __tablename__ = "dashboard_custom_index"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(120), nullable=False)
    symbols = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_dashboard_custom_index_updated_at", "updated_at"),
    )


class DeskPortfolioPosition(Base):
    """Manual current-position state used by the daily dashboard blotter."""
    __tablename__ = "desk_portfolio_position"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String, nullable=False)
    side = Column(String(16), nullable=False, default="long")
    quantity = Column(Float, nullable=False, default=0.0)
    average_price_mad = Column(Float, nullable=True)
    opened_at = Column(Date, nullable=True)
    planned_holding_bars = Column(Integer, nullable=True)
    stop_loss = Column(Float, nullable=True)
    target_1 = Column(Float, nullable=True)
    status = Column(String(16), nullable=False, default="active")
    notes = Column(Text, nullable=True)
    meta_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "side", name="uq_desk_portfolio_position_symbol_side"),
        Index("ix_desk_portfolio_position_status", "status"),
        Index("ix_desk_portfolio_position_symbol", "symbol"),
    )


class DeskPortfolioFill(Base):
    """Manual fill audit trail for desk portfolio reconciliation."""
    __tablename__ = "desk_portfolio_fill"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    symbol = Column(String, nullable=False)
    side = Column(String(16), nullable=False)
    quantity = Column(Float, nullable=False)
    price_mad = Column(Float, nullable=False)
    fees_mad = Column(Float, nullable=False, default=0.0)
    notes = Column(Text, nullable=True)
    meta_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_desk_portfolio_fill_timestamp", "timestamp"),
        Index("ix_desk_portfolio_fill_symbol_timestamp", "symbol", "timestamp"),
    )


class StrategyBacktestRun(Base):
    __tablename__ = "strategy_backtest_run"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id = Column(UUID(as_uuid=True), ForeignKey("saved_strategy.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False, default="")
    mode = Column(String(20), nullable=False, default="direct")
    status = Column(String(20), nullable=False, default="queued")
    horizon = Column(String(20), nullable=False, default="medium")
    execution_fingerprint = Column(String(64), nullable=False, default="")
    strategy_snapshot_json = Column(JSONB, nullable=False, default=dict)
    data_snapshot_json = Column(JSONB, nullable=False, default=dict)
    request_json = Column(JSONB, nullable=False, default=dict)
    summary_json = Column(JSONB, nullable=False, default=dict)
    result_json = Column(JSONB, nullable=False, default=dict)
    progress_json = Column(JSONB, nullable=False, default=dict)
    error_text = Column(Text, nullable=True)
    rq_job_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_strategy_backtest_run_status", "status"),
        Index("ix_strategy_backtest_run_created_at", "created_at"),
        Index("ix_strategy_backtest_run_execution_fingerprint", "execution_fingerprint"),
    )


class StrategyBacktestStock(Base):
    __tablename__ = "strategy_backtest_stock"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("strategy_backtest_run.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    status = Column(String(20), nullable=False, default="queued")
    summary_json = Column(JSONB, nullable=False, default=dict)
    result_json = Column(JSONB, nullable=False, default=dict)
    error_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "symbol", name="uq_strategy_backtest_stock_run_symbol"),
        Index("ix_strategy_backtest_stock_run", "run_id"),
    )


class StrategyBacktestWindow(Base):
    __tablename__ = "strategy_backtest_window"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("strategy_backtest_run.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    window_index = Column(Integer, nullable=False)
    summary_json = Column(JSONB, nullable=False, default=dict)
    detail_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "symbol", "window_index", name="uq_strategy_backtest_window_run_symbol_index"),
        Index("ix_strategy_backtest_window_run", "run_id"),
    )


class WfoSignalSummary(Base):
    """Cached WFO signal result for one (symbol, category, horizon) tuple."""
    __tablename__ = "wfo_signal_summary"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    category = Column(String(32), nullable=False)       # "tendance" | "momentum" | "oscillation" | "volume"
    horizon = Column(String(16), nullable=False)         # "short" | "medium" | "long"
    variant = Column(String(64), nullable=False, server_default="expanded")
    status = Column(String(20), nullable=False, default="pending")  # "pending" | "running" | "succeeded" | "failed"

    # --- WFO results ---
    score_pct = Column(Float, nullable=True)             # -100.0 to +100.0  (ensemble score)
    signal_label = Column(String(60), nullable=True)     # French label from signal_type_label()
    representatives_json = Column(JSONB, nullable=False, default=list)
    folds_json = Column(JSONB, nullable=True)             # per-fold details (IS/OOS returns, winner, profile)
    config_json = Column(JSONB, nullable=True)            # WFO config used (train/test/step, grid_size, etc.)
    fragility_json = Column(JSONB, nullable=True)          # C.1 local-neighborhood fragility cache

    # --- WFO quality metrics ---
    wfe_pct = Column(Float, nullable=True)
    robustness_ratio = Column(Float, nullable=True)      # 0.0 to 1.0
    total_folds = Column(Integer, nullable=True)
    profitable_folds = Column(Integer, nullable=True)
    mean_oos_sharpe = Column(Float, nullable=True)
    total_oos_pnl = Column(Float, nullable=True)
    worst_fold_drawdown = Column(Float, nullable=True)
    composite_score = Column(Float, nullable=True)       # pre-computed ranking score (0-100)
    robustness_grade = Column(String(2), nullable=True)  # "A" | "B" | "C" | "D" | "F"

    # --- Metadata ---
    computed_at = Column(DateTime(timezone=True), nullable=True)
    data_as_of = Column(Date, nullable=True)             # last bar date in OHLCV when computed
    compute_seconds = Column(Float, nullable=True)       # wall-clock time for this family WFO
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "category", "horizon", "variant", name="uq_wfo_signal_summary_sym_cat_hz_var"),
        Index("ix_wfo_signal_summary_symbol_horizon", "symbol", "horizon"),
        Index("ix_wfo_signal_summary_status", "status"),
    )


class WfoGlobalSignal(Base):
    """Cached WFO global consensus signal for one (symbol, horizon) tuple."""
    __tablename__ = "wfo_global_signal"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    horizon = Column(String(16), nullable=False)
    variant = Column(String(64), nullable=False, server_default="expanded")
    status = Column(String(20), nullable=False, default="pending")

    # --- Consensus signal ---
    global_score_pct = Column(Float, nullable=True)      # -100 to +100 (after S/R modulation)
    raw_score_pct = Column(Float, nullable=True)          # -100 to +100 (before S/R modulation)
    signal_label = Column(String(60), nullable=True)
    recommendation = Column(String(32), nullable=True)    # "achat_fort" | "achat" | "neutre" | "vente" | "vente_forte"

    # --- Family weights (WFO-optimized, sum to 1.0) ---
    weight_tendance = Column(Float, nullable=True)
    weight_momentum = Column(Float, nullable=True)
    weight_oscillation = Column(Float, nullable=True)
    weight_volume = Column(Float, nullable=True)

    # --- S/R modulation ---
    sr_modifier = Column(Float, nullable=True)            # multiplier applied (e.g., 1.12 or 0.88)
    sr_support_level = Column(Float, nullable=True)
    sr_resistance_level = Column(Float, nullable=True)
    sr_support_method = Column(String(40), nullable=True)
    sr_resistance_method = Column(String(40), nullable=True)
    sr_distance_support_atr = Column(Float, nullable=True)
    sr_distance_resistance_atr = Column(Float, nullable=True)

    # --- Cross-family ranking ---
    best_category = Column(String(32), nullable=True)     # "tendance" | "momentum" | ...
    best_category_score = Column(Float, nullable=True)
    categories_viable = Column(Integer, nullable=True)    # how many categories have grade >= C

    # --- WFO quality for the consensus pass ---
    consensus_wfe_pct = Column(Float, nullable=True)
    consensus_robustness = Column(Float, nullable=True)

    # --- Metadata ---
    computed_at = Column(DateTime(timezone=True), nullable=True)
    data_as_of = Column(Date, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "horizon", "variant", name="uq_wfo_global_signal_sym_hz_var"),
        Index("ix_wfo_global_signal_symbol", "symbol"),
    )


class SignalEngineFamilyResult(Base):
    """Persisted A→G signal engine output for one (symbol, family, horizon, variant).

    Mirrors WfoSignalSummary in structure. Enables export-scores.py to read
    from DB instead of recomputing the full pipeline on every run.
    """
    __tablename__ = "signal_engine_family_result"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Natural key
    symbol = Column(String, nullable=False)
    family = Column(String(64), nullable=False)        # "sma" | "macd" | "rsi" | …
    category = Column(String(32), nullable=False)      # denormalized from CATEGORY_FAMILIES
    horizon = Column(String(16), nullable=False)       # "short" | "medium" | "long"
    variant = Column(String(64), nullable=False, server_default="expanded")
    status = Column(String(20), nullable=False, server_default="pending")

    # Signal output
    family_score_pct = Column(Float, nullable=True)
    signal_label = Column(String(60), nullable=True)

    # Committed representative variants + weights (consumed by backtest)
    representatives_json = Column(JSONB, nullable=False, default=list)

    # Full family snapshot — verbatim _build_family_snapshot() output for export-scores.py
    family_detail_json = Column(JSONB, nullable=True)

    # Quality / selection counts
    tested_count = Column(Integer, nullable=True)
    viable_count = Column(Integer, nullable=True)
    competitive_count = Column(Integer, nullable=True)
    representative_count = Column(Integer, nullable=True)
    is_provisional = Column(Boolean, nullable=False, server_default="false")
    warning_message = Column(Text, nullable=True)

    # Staleness marker — SHA-256 of (data_as_of + cost_bps + cooldown_bars)
    input_hash = Column(String(64), nullable=True)

    computed_at = Column(DateTime(timezone=True), nullable=True)
    data_as_of = Column(Date, nullable=True)
    compute_seconds = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "family", "horizon", "variant", name="uq_sefr_sym_fam_hz_var"),
        Index("ix_sefr_symbol_horizon", "symbol", "horizon"),
        Index("ix_sefr_category_horizon", "category", "horizon"),
        Index("ix_sefr_status", "status"),
    )


class SignalEngineGlobalResult(Base):
    """Persisted A→G global aggregate for one (symbol, horizon, variant).

    Stores both legacy (1 family/category) and expanded (up to 5 families/category)
    aggregate scores plus per-category breakdowns. Mirrors WfoGlobalSignal.
    """
    __tablename__ = "signal_engine_global_result"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    symbol = Column(String, nullable=False)
    horizon = Column(String(16), nullable=False)
    variant = Column(String(64), nullable=False, server_default="expanded")
    status = Column(String(20), nullable=False, server_default="pending")

    # Aggregate scores
    aggregate_score_pct = Column(Float, nullable=True)           # legacy: 1 family per category
    expanded_aggregate_score_pct = Column(Float, nullable=True)  # expanded: up to 5 families per category
    signal_label = Column(String(60), nullable=True)

    # Per-category and per-family breakdowns
    per_category_json = Column(JSONB, nullable=True)    # {category: {score_pct, label, family_scores: {family: score}}}
    per_family_json = Column(JSONB, nullable=True)      # {family: {score_pct, label}}

    # Technical levels + S/R stored verbatim for export-scores.py backward compat
    technical_levels_json = Column(JSONB, nullable=True)
    support_resistance_json = Column(JSONB, nullable=True)

    computed_at = Column(DateTime(timezone=True), nullable=True)
    data_as_of = Column(Date, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "horizon", "variant", name="uq_segr_sym_hz_var"),
        Index("ix_segr_symbol", "symbol"),
        Index("ix_segr_horizon_status", "horizon", "status"),
    )


class SignalScoreHistory(Base):
    """Per-bar category-aggregated signal score, used for predictive-ability analytics.

    One row per (date, symbol, source, category, horizon). `source` distinguishes
    engine_legacy / engine_expanded / wfo. `score_pct` is in [-100, +100] — for
    WFO it's discretized to {-100, 0, +100} (binary signal mapped from {-1,0,+1}).
    """
    __tablename__ = "signal_score_history"

    date = Column(Date, primary_key=True, nullable=False)
    symbol = Column(String, primary_key=True, nullable=False)
    source = Column(String(64), primary_key=True, nullable=False)
    category = Column(String(32), primary_key=True, nullable=False)
    horizon = Column(String(16), primary_key=True, nullable=False)
    score_pct = Column(Float, nullable=True)
    is_oos = Column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        Index("ix_ssh_symbol_source_horizon", "symbol", "source", "horizon"),
        Index("ix_ssh_symbol_date", "symbol", "date"),
    )


class ScoreHistoryJob(Base):
    """Tracks score-history population jobs (one per symbol)."""
    __tablename__ = "score_history_job"

    symbol = Column(String, primary_key=True, nullable=False)
    status = Column(String(20), nullable=False, server_default="pending")
    rq_job_id = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_shj_status", "status"),
    )


class SignalBacktestRun(Base):
    """Persisted signal-based backtest result with Monte Carlo equity-fan data.

    One row per (symbol, horizon, source, scope, scope_key, variant, window_start, window_end, cooldown_bars).
    Equity curve and MC envelope are stored in JSONB (small arrays — ~80 daily bars max).
    """
    __tablename__ = "signal_backtest_run"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Natural key
    symbol = Column(String, nullable=False)
    horizon = Column(String(16), nullable=False)
    source = Column(String(10), nullable=False)        # "engine" | "wfo"
    scope = Column(String(20), nullable=False)         # "per_category" | "global" | "combination"
    scope_key = Column(String(64), nullable=False)     # "tendance" | "global" | "tendance+momentum"
    variant = Column(String(64), nullable=False, server_default="expanded")
    window_start = Column(Date, nullable=False)
    window_end = Column(Date, nullable=False)

    # Config (not part of unique key — overwrites on change)
    status = Column(String(20), nullable=False, server_default="pending")
    cost_bps = Column(Float, nullable=False, server_default="5.0")
    slippage_bps = Column(Float, nullable=False, server_default="5.0")
    side_policy = Column(String(16), nullable=False, server_default="long_only")
    cooldown_bars = Column(Integer, nullable=False, server_default="0")
    n_paths = Column(Integer, nullable=False, server_default="2000")
    mc_method = Column(String(20), nullable=False, server_default="block_bootstrap")
    block_mean = Column(Integer, nullable=True)        # null = auto ceil(T^(1/3))

    # Realized backtest outputs
    n_bars = Column(Integer, nullable=True)
    n_trades = Column(Integer, nullable=True)
    equity_json = Column(JSONB, nullable=True)         # float[n_bars], normalized start=1.0
    dates_json = Column(JSONB, nullable=True)          # "YYYY-MM-DD"[n_bars]

    # Denormalized metrics for fast sorting / filtering
    total_return = Column(Float, nullable=True)
    cagr = Column(Float, nullable=True)
    sharpe = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)
    win_rate = Column(Float, nullable=True)

    # Monte Carlo outputs
    # {p05, p25, p50, p75, p95} — each is float[n_bars]
    mc_envelope_json = Column(JSONB, nullable=True)
    # {total_return/cagr/sharpe/max_drawdown: {p05,p50,p95}, var95, cvar95, prob_positive_terminal}
    mc_stats_json = Column(JSONB, nullable=True)

    # Trade-level detail (added 2026-04-21)
    trades_json = Column(JSONB, nullable=True)           # list of {open_date,close_date,open_price,close_price,direction,pnl_return,bars_held}
    close_series_json = Column(JSONB, nullable=True)     # OHLCV close aligned to dates_json
    position_series_json = Column(JSONB, nullable=True)  # executed_position per bar
    signal_diagnostics_json = Column(JSONB, nullable=True)  # {flat_executed, target_nonzero_bars, ...}
    warning_code = Column(String(32), nullable=True)     # "flat_signal" | "few_trades" | null
    shuffle_stats_json = Column(JSONB, nullable=True)    # shuffled-trade bootstrap result

    # Staleness: SHA-256 of (representatives_json + data_as_of + cost/slippage/side/cooldown)
    input_hash = Column(String(64), nullable=True)

    computed_at = Column(DateTime(timezone=True), nullable=True)
    data_as_of = Column(Date, nullable=True)
    compute_seconds = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "symbol", "horizon", "source", "scope", "scope_key", "variant",
            "window_start", "window_end", "cooldown_bars",
            name="uq_sbr_natural_key",
        ),
        Index("ix_sbr_symbol_horizon", "symbol", "horizon"),
        Index("ix_sbr_source_scope", "source", "scope"),
        Index("ix_sbr_status", "status"),
        Index("ix_sbr_data_as_of", "data_as_of"),
    )


class SignalEngineBatchJob(Base):
    """Tracks batch computation jobs for signal engine or backtest for a (symbol, horizon).

    Used for progress reporting and preventing concurrent duplicate runs.
    UUID PK consistent with Run / StrategyBacktestRun convention.
    """
    __tablename__ = "signal_engine_batch_job"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    symbol = Column(String, nullable=False)
    horizon = Column(String(16), nullable=False)
    variant = Column(String(64), nullable=False, server_default="expanded")
    job_type = Column(String(20), nullable=False)      # "signal_engine" | "signal_backtest"
    status = Column(String(20), nullable=False, server_default="pending")
    rq_job_id = Column(String, nullable=True)
    triggered_by = Column(String(32), nullable=True)   # "manual" | "market_refresh" | "scheduler"
    batch_id = Column(String(64), nullable=True)       # manual global launch grouping id

    total_units = Column(Integer, nullable=True)       # families (engine) or scopes (backtest)
    completed_units = Column(Integer, nullable=False, server_default="0")
    failed_units = Column(Integer, nullable=False, server_default="0")

    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_sebj_symbol_horizon_type", "symbol", "horizon", "job_type"),
        Index("ix_sebj_status", "status"),
        Index("ix_sebj_created_at", "created_at"),
        Index("ix_sebj_batch_id", "batch_id"),
    )


class MarketRefreshError(Base):
    """Per-symbol error log within a refresh run."""
    __tablename__ = "market_refresh_error"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    refresh_run_id = Column(UUID(as_uuid=True), ForeignKey("market_refresh_run.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    provider = Column(String, nullable=False, default="bourse_direct")
    error_type = Column(String, nullable=True)    # "not_found"|"parse_error"|"network_error"|"validation_error"
    error_message = Column(Text, nullable=True)
    raw_response = Column(Text, nullable=True)    # first 2000 chars of raw response for debugging
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_market_refresh_error_run", "refresh_run_id"),
        Index("ix_market_refresh_error_symbol", "symbol"),
    )


# ---------------------------------------------------------------------------
# Phase 0 — Pipeline lineage scaffolding
# ---------------------------------------------------------------------------


class PipelineRevision(Base):
    """One row per successful pipeline-stage output.

    Used to thread `upstream_rev` lineage through the snapshot/cache tables
    introduced in Phase 1+ (`dashboard_snapshot`, `signal_evaluation_cache`,
    `factor_relevance_cache`, etc.). Workers append a row before flipping
    a downstream snapshot to the new revision.
    """

    __tablename__ = "pipeline_revision"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    stage = Column(String(64), nullable=False)
    upstream_rev = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    content_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_pipeline_revision_stage_created", "stage", "created_at"),
        UniqueConstraint("stage", "content_hash", name="uq_pipeline_revision_stage_content"),
    )


class DashboardSnapshot(Base):
    """Pre-computed dashboard payload for one (horizon, as_of_date).

    Written by the worker via CAS upsert. The API in snapshot/shadow mode
    reads ``payload_jsonb`` instead of running the live aggregation.
    """

    __tablename__ = "dashboard_snapshot"

    horizon = Column(String(16), primary_key=True)
    as_of_date = Column(Date, primary_key=True)
    payload_jsonb = Column(JSONB, nullable=False)
    upstream_rev = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_dashboard_snapshot_horizon_computed", "horizon", "computed_at"),
    )


class SnapshotColumns:
    """Mixin: every Phase 1+ snapshot/cache table inherits these columns.

    `upstream_rev` is the JSON tuple of producer revisions consumed
    (e.g. ``{"data_as_of": "...", "engine_run_id": "...", ...}``).
    `computed_at` is when the row was written.
    `as_of_date` is the point-in-time the row represents (immutable per date).
    """

    upstream_rev = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    as_of_date = Column(Date, nullable=True)
