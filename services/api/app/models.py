import uuid
from sqlalchemy import (
    Column, String, DateTime, Date, ForeignKey, Text, BigInteger, Float, UniqueConstraint, Index, Integer, Boolean
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from .db import Base



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
    source_provider = Column(String, nullable=True)   # "bourse_direct"|"yahoo"|"bmce_excel"
    data_as_of = Column(Date, nullable=True)           # last bar date (denormalized for freshness display)
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
    is_active = Column(Boolean, nullable=False, default=True)
    track_source = Column(String, nullable=False, default="bourse_direct")
    bourse_url = Column(String, nullable=True)              # direct link to Bourse de Casablanca stock page
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_stock_master_is_active", "is_active"),
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
